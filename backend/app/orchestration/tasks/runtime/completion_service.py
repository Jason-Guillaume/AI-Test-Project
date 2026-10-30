"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.orchestration.tasks.services import state_service
import logging
from datetime import datetime, timedelta
from typing import Callable
from sqlalchemy.orm import Session
from app.llm import LLMError
from app.core.security.sanitizer import sanitize_text
from app.orchestration.tasks.models import (
    Task,
    TaskAgentInstance,
    TaskAttempt,
    TaskMessage,
    TaskRun,
    TaskToolInvocation,
    TaskWorkItem,
)
from app.orchestration.tasks.runtime.contracts import ClaimedWork


log = logging.getLogger(__name__)


def complete_work(db: Session, task: Task, run: TaskRun, work: TaskWorkItem, attempt: TaskAttempt, agent: TaskAgentInstance | None) -> None:
    """在工作项安全边界应用暂停/取消，并按实际待办决定是否继续派发。"""
    now = datetime.now()
    # 禁止旧代次在失去租约后刷新/提交新尝试的状态。先锁定权威行，再落收敛结果。
    with db.no_autoflush:
        current_owner = db.query(TaskRun.lease_owner).filter(TaskRun.id == run.id).with_for_update().scalar()
        current_generation = db.query(TaskWorkItem.attempt_count).filter(TaskWorkItem.id == work.id).scalar()
    if current_owner != attempt.owner or current_generation != attempt.lease_generation:
        db.rollback()
        return
    db.flush()
    db.refresh(run, with_for_update=True)
    if work.status == "RUNNING":
        work.status = "SUCCEEDED"
        work.finished_at = now
        attempt.status = "SUCCEEDED"
        attempt.finished_at = now
    if run.status == "CANCEL_REQUESTED":
        run.status = "CANCELLED"
        run.finished_at = now
        db.query(TaskWorkItem).filter(TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "PENDING").update(
            {TaskWorkItem.status: "CANCELLED"}, synchronize_session=False,
        )
        if agent is not None:
            agent.status = "CANCELLED"
        state_service.append_event(db, run, "run.cancelled", {"safe_boundary_reached": True})
    elif run.status == "PAUSE_REQUESTED":
        run.status = "PAUSED"
        if agent is not None:
            agent.status = "PAUSED"
        state_service.append_event(db, run, "run.paused", {"safe_boundary_reached": True})
    elif run.status == "RUNNING":
        if work.kind == "CHAT":
            prior_status = attempt.checkpoint_json.get("run_status_before_claim")
            run.status = prior_status if prior_status not in {None, "QUEUED", "RUNNING"} else "QUEUED"
        elif work.kind in {"EXECUTE_API", "EXECUTE_WEB", "EXECUTE_SECURITY", "SECURITY_SCAN", "REPORT", "REVIEW"}:
            run.status = "QUEUED"
    model_attempts = (attempt.checkpoint_json or {}).get("model_attempts", [])
    if model_attempts:
        event_type = "llm.fallback_succeeded" if any(item.get("candidate_index", 0) > 0 for item in model_attempts) else "llm.primary_succeeded"
        state_service.append_event(
            db, run, event_type,
            {"work_item_id": work.id, "model_attempts": model_attempts},
            agent_instance_id=agent.id if agent else None,
        )
    run.lease_owner = None
    run.lease_expires_at = None
    state_service.sync_task_status(db, task, run)
    db.commit()


def defer_at_control_boundary(db: Session, run: TaskRun, work: TaskWorkItem, attempt: TaskAttempt, agent: TaskAgentInstance | None, *, messages: list[TaskMessage] | None=None) -> bool:
    """模型调用后若收到暂停或取消，保留工作项以便安全恢复且不越过控制命令。"""
    if run.status not in {"PAUSE_REQUESTED", "CANCEL_REQUESTED"}:
        return False
    now = datetime.now()
    work.status = "PENDING"
    work.claimed_at = None
    attempt.status = "INTERRUPTED"
    attempt.error_code = "CONTROL_REQUESTED"
    attempt.error_message = "用户控制命令在模型调用期间到达，未执行后续操作"
    attempt.finished_at = now
    if messages:
        for message in messages:
            message.status = "RECEIVED"
    if agent is not None:
        agent.status = "PAUSED" if run.status == "PAUSE_REQUESTED" else "CANCEL_REQUESTED"
    return True


def fail_work(claim: ClaimedWork, error: Exception, *, db_factory: Callable[[], Session]) -> None:
    """落失败尝试；API 副作用回执不明时阻止重放并转待核对。"""
    db = db_factory()
    try:
        run = db.query(TaskRun).filter(TaskRun.id == claim.run_id).with_for_update().first()
        work = db.query(TaskWorkItem).filter(TaskWorkItem.id == claim.work_item_id).with_for_update().first()
        attempt = db.get(TaskAttempt, claim.attempt_id)
        if work is None or run is None or attempt is None:
            return
        if (run.lease_owner != claim.owner or attempt.owner != claim.owner
                or work.attempt_count != attempt.lease_generation):
            # 旧线程的迟到异常不得覆盖恢复后重新领取的工作与运行。
            db.rollback()
            return
        now = datetime.now()
        code = getattr(error, "code", "TASK_WORK_FAILED")
        message = sanitize_text(str(error))[:2000]
        work.status = "FAILED"
        work.error_code = str(code)[:80]
        work.error_message = message
        work.finished_at = now
        attempt.status = "FAILED"
        attempt.error_code = str(code)[:80]
        attempt.error_message = message
        attempt.finished_at = now
        agent = db.get(TaskAgentInstance, work.agent_instance_id) if work.agent_instance_id else None
        task = db.get(Task, run.task_id)
        invocation = None
        if work.kind in {"EXECUTE_API", "EXECUTE_WEB", "EXECUTE_SECURITY"}:
            invocation = db.query(TaskToolInvocation).filter(TaskToolInvocation.work_item_id == work.id).with_for_update().first()
        # 只有纯模型调用且尚未开始业务副作用时才能自动重试，避免重复创建 TestRun。
        can_retry_model = isinstance(error, LLMError) and error.retryable and (
            work.kind not in {"EXECUTE_API", "EXECUTE_WEB", "EXECUTE_SECURITY"} or invocation is None
        )
        if can_retry_model:
            attempts = list(getattr(error, "attempts", []) or [])
            attempt.checkpoint_json = {**(attempt.checkpoint_json or {}), "model_attempts": attempts}
            work.status = "PENDING"
            work.finished_at = None
            work.error_code = str(code)[:80]
            attempt.status = "FAILED"
            attempt.error_code = str(code)[:80]
            attempt.error_message = message
            attempt.finished_at = now
            if work.attempt_count < work.max_attempts:
                delay = min(30 * (2 ** max(0, work.attempt_count - 1)), 300)
                work.available_at = now + timedelta(seconds=delay)
                run.status = "QUEUED"
                run.stage = "MODEL_RETRY"
                run.error_code = "LLM_FALLBACK_EXHAUSTED"
                run.error_message = f"本轮模型路由不可用，任务将在 {delay} 秒后自动重试。"
                event_type = "llm.retry_scheduled"
                if agent is not None:
                    agent.status = "READY"
            else:
                work.available_at = None
                run.status = "PAUSED"
                run.stage = "WAITING_MODEL"
                run.error_code = "LLM_FALLBACK_EXHAUSTED"
                run.error_message = "主模型及备用模型多次不可用，任务已暂停；修复模型路由后可恢复。"
                event_type = "llm.fallback_exhausted"
                if agent is not None:
                    agent.status = "PAUSED"
            state_service.append_event(
                db, run, event_type,
                {"work_item_id": work.id, "attempt": work.attempt_count, "model_attempts": attempts},
                agent_instance_id=agent.id if agent else None,
            )
            db.query(TaskMessage).filter(
                TaskMessage.task_run_id == run.id,
                TaskMessage.agent_instance_id == (agent.id if agent else -1),
                TaskMessage.status == "PROCESSING",
            ).update({TaskMessage.status: "RECEIVED"}, synchronize_session=False)
            run.lease_owner = None
            run.lease_expires_at = None
            if task is not None:
                state_service.sync_task_status(db, task, run)
            db.commit()
            return
        if invocation is not None and invocation.status == "STARTED":
            invocation.status = "NEEDS_RECONCILIATION"
            invocation.error_code = str(code)[:80]
            invocation.error_message = message
            invocation.finished_at = now
            work.error_code = "SIDE_EFFECT_REQUIRES_RECONCILIATION"
            run.status = "RECONCILIATION_REQUIRED"
            run.stage = "RECONCILIATION_REQUIRED"
            run.error_code = "SIDE_EFFECT_REQUIRES_RECONCILIATION"
            run.error_message = "API 执行中断，业务回执状态不明；系统未自动重放，请先核对执行中心。"
            attempt.status = "NEEDS_RECONCILIATION"
            if agent is not None:
                agent.status = "NEEDS_RECONCILIATION"
            state_service.append_event(db, run, "run.reconciliation_required", {"work_item_id": work.id})
        elif work.kind == "CHAT":
            previous = attempt.checkpoint_json.get("run_status_before_claim")
            run.status = previous if previous not in {None, "RUNNING", "QUEUED"} else "QUEUED"
            if agent is not None:
                agent.status = "READY"
        elif work.kind == "FINALIZE":
            run.status = "SUCCEEDED_WITH_ISSUES"
            run.stage = "COMPLETED_WITH_ISSUES"
            run.finished_at = now
            run.error_code = str(code)[:80]
            run.error_message = "API 测试和正式报告已完成，但任务主 Agent 汇总失败。"
            if agent is not None:
                agent.status = "FAILED"
            state_service.append_event(db, run, "run.completed_with_issues", {"reason": "主 Agent 汇总失败"})
        else:
            if work.kind == "EXECUTE_WEB_AUTHORING":
                from app.features.web_testing.models import WebAgentSession
                from app.execution.browser.session_manager import registry

                for browser_session in db.query(WebAgentSession).filter(
                    WebAgentSession.task_run_id == run.id,
                    WebAgentSession.status == "ACTIVE",
                ).all():
                    registry.close_session(browser_session.id)
                    browser_session.status = "FAILED"
                    browser_session.closed_at = now
            run.status = "FAILED"
            run.stage = "FAILED"
            run.finished_at = now
            run.error_code = str(code)[:80]
            run.error_message = message
            if agent is not None:
                agent.status = "FAILED"
            state_service.append_event(db, run, "work_item.failed", {"work_item_id": work.id, "error_code": str(code)[:80]})
        if work.kind in {"EXECUTE_API", "EXECUTE_WEB", "EXECUTE_SECURITY"} and invocation is None:
            # Worker 尚未写副作用回执，失败可以按调用边界安全重试。
            if agent is not None:
                agent.status = "FAILED"
        # 若 LLM 在筛选阶段中断，重新派发时再次消费这些消息；未知业务副作用不会重放。
        db.query(TaskMessage).filter(
            TaskMessage.task_run_id == run.id,
            TaskMessage.agent_instance_id == (agent.id if agent else -1),
            TaskMessage.status == "PROCESSING",
        ).update({TaskMessage.status: "RECEIVED"}, synchronize_session=False)
        run.lease_owner = None
        run.lease_expires_at = None
        if task is not None:
            state_service.sync_task_status(db, task, run)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("记录任务工作项失败状态时发生异常 run_id=%s", claim.run_id)
    finally:
        db.close()
