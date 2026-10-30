"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import (
    TaskAgentInstance,
    TaskCommand,
    TaskResourceRef,
    TaskRun,
    TaskToolInvocation,
    TaskWorkItem,
)
from app.orchestration.tasks.schemas import TaskCommandCreate
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import User
from app.core.http.errors import bad_request, conflict, not_found
from app.orchestration.tasks.services.access import TaskAccessService
from app.orchestration.tasks.services.query_service import RETRYABLE_RUN_STATUSES, retry_block_reason
from app.orchestration.tasks.services.state_service import RUN_PAUSE_STATUSES
from app.orchestration.tasks.services.state_service import RUN_TERMINAL_STATUSES
from app.orchestration.tasks.services.state_service import append_event
from app.orchestration.tasks.services.plan_service import approve_plan
from app.orchestration.tasks.services.assembly_service import model_snapshot
from app.orchestration.tasks.services.state_service import sync_task_status


def create_command(db: Session, run_id: int, body: TaskCommandCreate, *, actor: User,
) -> TaskCommand:
    """持久化并原子应用幂等控制命令。"""
    if body.command_type != "APPROVE_PLAN" and body.security_risk_confirmed:
        raise bad_request("高风险安全用例确认只能用于方案确认命令")
    run, task = TaskAccessService.get_run_for_write(db, run_id, actor, lock=True)
    prior = db.query(TaskCommand).filter(
        TaskCommand.task_run_id == run.id,
        TaskCommand.idempotency_key == body.idempotency_key,
    ).first()
    if prior is not None:
        expected_payload = command_payload(body)
        if prior.command_type != body.command_type or prior.payload != expected_payload:
            raise conflict("相同 idempotency_key 已用于不同命令")
        if prior.status == "COMPLETED":
            return prior
        command = prior
    else:
        command = TaskCommand(
            task_run_id=run.id,
            requested_by=actor.id,
            command_type=body.command_type,
            idempotency_key=body.idempotency_key,
            payload=command_payload(body),
        )
        db.add(command)
        db.flush()

    if body.command_type == "APPROVE_PLAN":
        approve_plan(
            db, run, actor,
            security_risk_confirmed=body.security_risk_confirmed,
        )
    elif body.command_type == "PAUSE":
        pause(db, run, actor)
    elif body.command_type == "RESUME":
        resume(db, run, actor)
    elif body.command_type == "CANCEL":
        cancel(db, run, actor)
    elif body.command_type == "RETRY":
        retry(db, run, actor, body.work_item_id)

    command.status = "COMPLETED"
    command.response_json = {"status": run.status, "stage": run.stage}
    command.processed_at = datetime.now()
    sync_task_status(db, task, run)
    db.commit()
    db.refresh(command)
    return command


def command_payload(body: TaskCommandCreate) -> dict[str, Any]:
    """构造幂等比较用的命令内容，批准说明经脱敏后写入审计载荷。"""
    payload: dict[str, Any] = {}
    if body.work_item_id:
        payload["work_item_id"] = body.work_item_id
    if body.security_risk_confirmed:
        payload["security_risk_confirmed"] = True
    return payload


def pause(db: Session, run: TaskRun, actor: User) -> None:
    """运行中的暂停在当前工作项安全边界生效，待确认状态可立即暂停。"""
    if run.status in RUN_TERMINAL_STATUSES or run.status in RUN_PAUSE_STATUSES:
        raise conflict("当前运行不能重复暂停")
    run.status = "PAUSE_REQUESTED" if run.status == "RUNNING" else "PAUSED"
    if run.input_snapshot.get("target_type") == "WEB_AUTHORING" and run.status == "PAUSED":
        worker = db.query(TaskAgentInstance).filter_by(task_run_id=run.id, role="UI_WORKER").first()
        if worker is not None:
            worker.status = "PAUSED"
    append_event(db, run, "run.pause_requested", {"effective_at": "安全边界"}, actor_user_id=actor.id)


def resume(db: Session, run: TaskRun, actor: User) -> None:
    """恢复暂停运行；方案仍待审阅时回到确认态，不越过人工确认。"""
    if run.status != "PAUSED":
        raise conflict("当前运行未暂停")
    has_pending = db.query(TaskWorkItem.id).filter(TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "PENDING").first()
    if run.stage == "PLAN_REVIEW":
        run.status = "WAITING_CONFIRMATION"
    elif has_pending:
        if run.stage == "WAITING_MODEL":
            # 管理员修复模型路由后显式恢复，才刷新冻结快照并开启新一轮有限重试额度。
            agents = db.query(TaskAgentInstance).filter(TaskAgentInstance.task_run_id == run.id).all()
            for agent in agents:
                model_id = agent.model_config_id or (agent.config_snapshot or {}).get("model_config_id")
                model = db.get(ModelConfiguration, model_id) if model_id else None
                if model is not None:
                    agent.config_snapshot = model_snapshot(model)
            pending = db.query(TaskWorkItem).filter(
                TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "PENDING",
            ).all()
            for work in pending:
                work.max_attempts = max(work.max_attempts, work.attempt_count + 3)
                work.available_at = None
                work.error_code = None
                work.error_message = None
            run.error_code = None
            run.error_message = None
            run.stage = "MODEL_RETRY"
        run.status = "QUEUED"
    elif run.input_snapshot.get("target_type") == "WEB_AUTHORING" and run.stage in {
        "WEB_AUTHORING", "WEB_STEP_REVIEW", "WEB_SESSION_CLOSED", "WEB_DRAFT_REVIEW",
    }:
        run.status = "WAITING_CONFIRMATION"
        worker = db.query(TaskAgentInstance).filter_by(task_run_id=run.id, role="UI_WORKER").first()
        if worker is not None:
            worker.status = "ACTIVE"
    else:
        raise conflict("当前运行没有可继续的工作项")
    append_event(db, run, "run.resumed", {"status": run.status}, actor_user_id=actor.id)


def cancel(db: Session, run: TaskRun, actor: User) -> None:
    """取消在途工作采用协作式标记；未领取工作立即终止。"""
    if run.status in RUN_TERMINAL_STATUSES or run.status == "CANCEL_REQUESTED":
        raise conflict("当前运行不能重复取消")
    if run.status == "RUNNING":
        run.status = "CANCEL_REQUESTED"
    else:
        run.status = "CANCELLED"
        run.finished_at = datetime.now()
        db.query(TaskWorkItem).filter(
            TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "PENDING",
        ).update({TaskWorkItem.status: "CANCELLED"}, synchronize_session=False)
    if run.input_snapshot.get("target_type") == "WEB_AUTHORING":
        from app.features.web_testing.models import WebAgentSession
        from app.execution.browser.session_manager import registry

        sessions = db.query(WebAgentSession).filter(
            WebAgentSession.task_run_id == run.id,
            WebAgentSession.status == "ACTIVE",
        ).all()
        for session in sessions:
            registry.close_session(session.id)
            session.status = "CLOSED"
            session.closed_at = datetime.now()
        worker = db.query(TaskAgentInstance).filter_by(task_run_id=run.id, role="UI_WORKER").first()
        if worker is not None and run.status == "CANCELLED":
            worker.status = "CANCELLED"
        if run.status == "CANCELLED":
            run.stage = "CANCELLED"
    # 历史 ZAP Job 可能仍在外部运行；只为旧任务登记取消请求，不再启动扫描器。
    from app.features.security_testing.zap.contracts import JOB_TERMINAL_STATUSES
    from app.features.security_testing.zap.models.job import SecurityScanJob
    from app.features.security_testing.zap.services import job_service

    scan_refs = db.query(TaskResourceRef).filter(
        TaskResourceRef.task_run_id == run.id,
        TaskResourceRef.resource_type == "SECURITY_SCAN_JOB",
    ).all()
    for ref in scan_refs:
        try:
            scan_job = db.get(SecurityScanJob, int(ref.resource_id))
        except (TypeError, ValueError):
            scan_job = None
        if scan_job is not None and scan_job.status not in JOB_TERMINAL_STATUSES:
            job_service.cancel(db, scan_job.project_id, actor, scan_job.id)
    append_event(db, run, "run.cancel_requested", {"status": run.status}, actor_user_id=actor.id)


def retry(db: Session, run: TaskRun, actor: User, work_item_id: int | None) -> None:
    """仅重试明确失败且副作用可判定的工作项；未知回执必须人工核对。"""
    if work_item_id is None:
        raise bad_request("重试必须指定失败的工作项")
    if run.status not in RETRYABLE_RUN_STATUSES:
        raise conflict("当前运行状态不支持重试")
    work = db.query(TaskWorkItem).filter(
        TaskWorkItem.id == work_item_id, TaskWorkItem.task_run_id == run.id,
    ).with_for_update().first()
    if work is None or work.status != "FAILED":
        raise not_found("可重试的失败工作项不存在")
    invocations = db.query(TaskToolInvocation).filter(
        TaskToolInvocation.work_item_id == work.id,
    ).all()
    block_reason = retry_block_reason(run, work, invocations)
    if block_reason:
        raise conflict(block_reason)
    work.status = "PENDING"
    work.available_at = None
    work.error_code = None
    work.error_message = None
    work.finished_at = None
    run.status = "QUEUED"
    if work.kind == "EXECUTE_SECURITY":
        run.stage = "SECURITY_EXECUTION"
    run.error_code = None
    run.error_message = None
    append_event(db, run, "work_item.retry_queued", {"work_item_id": work.id}, actor_user_id=actor.id)
