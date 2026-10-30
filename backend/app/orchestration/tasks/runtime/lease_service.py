"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.orchestration.tasks.services import state_service
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import (
    Task,
    TaskAgentInstance,
    TaskAttempt,
    TaskMessage,
    TaskRun,
    TaskSchedulerControl,
    TaskToolInvocation,
    TaskWorkItem,
    TaskWorkItemDependency,
)
from app.orchestration.tasks.runtime.contracts import ClaimedWork


log = logging.getLogger(__name__)


def claim_work(*, db_factory: Callable[[], Session], owner: str, lease_seconds: int) -> ClaimedWork | None:
    """在全局调度行锁保护下检查并发额度，再用 SKIP LOCKED 领取一项。"""
    db = db_factory()
    now = datetime.now()
    try:
        control = db.query(TaskSchedulerControl).filter(TaskSchedulerControl.id == 1).with_for_update().first()
        if control is None:
            log.error("任务调度控制行缺失；请先应用 Alembic 0015")
            return None
        active = db.query(TaskRun.id).filter(TaskRun.lease_expires_at > now).count()
        if active >= max(1, control.max_concurrent_runs):
            db.rollback()
            return None

        candidates = (
            db.query(TaskWorkItem, TaskRun)
            .join(TaskRun, TaskRun.id == TaskWorkItem.task_run_id)
            .filter(
                TaskWorkItem.status == "PENDING",
                or_(TaskWorkItem.available_at.is_(None), TaskWorkItem.available_at <= now),
                or_(
                    TaskRun.status == "QUEUED",
                    and_(
                        TaskWorkItem.kind == "CHAT",
                        TaskRun.status.in_(("WAITING_CONFIRMATION", "PAUSED", "SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED", "SUPERSEDED", "RECONCILIATION_REQUIRED")),
                    ),
                ),
            )
            .order_by(TaskWorkItem.sequence.asc(), TaskWorkItem.id.asc())
            # 同时锁运行行，保证事件序号与并发命令状态转换串行化。
            .with_for_update(skip_locked=True)
            .limit(20)
            .all()
        )
        selected = None
        for work, run in candidates:
            dependencies = (
                db.query(TaskWorkItem)
                .join(TaskWorkItemDependency, TaskWorkItemDependency.depends_on_id == TaskWorkItem.id)
                .filter(TaskWorkItemDependency.work_item_id == work.id)
                .all()
            )
            if all(item.status in {"SUCCEEDED", "SUCCEEDED_WITH_ISSUES"} for item in dependencies):
                selected = (work, run)
                break
        if selected is None:
            db.rollback()
            return None

        work, run = selected
        previous_status = run.status
        work.status = "RUNNING"
        work.claimed_at = now
        work.attempt_count += 1
        attempt = TaskAttempt(
            work_item_id=work.id,
            attempt_number=work.attempt_count,
            lease_generation=work.attempt_count,
            owner=owner,
            status="RUNNING",
            checkpoint_json={"run_status_before_claim": previous_status},
            heartbeat_at=now,
        )
        db.add(attempt)
        run.lease_owner = owner
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        run.started_at = run.started_at or now
        if run.status == "QUEUED":
            run.status = "RUNNING"
        agent = db.get(TaskAgentInstance, work.agent_instance_id) if work.agent_instance_id else None
        if agent is not None:
            agent.status = "RUNNING"
        state_service.append_event(
            db, run, "work_item.started",
            {"work_item_id": work.id, "kind": work.kind, "attempt": work.attempt_count},
            agent_instance_id=agent.id if agent else None,
        )
        db.flush()
        claim = ClaimedWork(work_item_id=work.id, run_id=run.id, attempt_id=attempt.id, owner=owner)
        db.commit()
        return claim
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def heartbeat_loop(claim: ClaimedWork, stop_event: threading.Event, *, db_factory: Callable[[], Session], owner: str, lease_seconds: int) -> None:
    """每隔一段时间续租 run 与 attempt；所有者不匹配时停止覆盖新租约。"""
    interval = max(5.0, min(20.0, lease_seconds / 4))
    while not stop_event.wait(interval):
        db = db_factory()
        try:
            run = db.query(TaskRun).filter(TaskRun.id == claim.run_id).with_for_update().first()
            attempt = db.get(TaskAttempt, claim.attempt_id)
            work = db.get(TaskWorkItem, claim.work_item_id)
            if (run is None or attempt is None or work is None or run.lease_owner != owner
                    or attempt.owner != owner or work.attempt_count != attempt.lease_generation):
                db.rollback()
                return
            now = datetime.now()
            run.lease_expires_at = now + timedelta(seconds=lease_seconds)
            attempt.heartbeat_at = now
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("任务心跳续租失败 run_id=%s", claim.run_id)
        finally:
            db.close()


def recover_expired(*, db_factory: Callable[[], Session]) -> int:
    """清扫租约过期执行；对可能已发生的 API 写入转待核对，不盲目重放。"""
    db = db_factory()
    now = datetime.now()
    recovered = 0
    try:
        runs = (
            db.query(TaskRun)
            .filter(TaskRun.lease_expires_at.isnot(None), TaskRun.lease_expires_at < now)
            .with_for_update(skip_locked=True)
            .all()
        )
        for run in runs:
            work = db.query(TaskWorkItem).filter(TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "RUNNING").with_for_update().first()
            if work is None:
                if (run.lease_owner or "").startswith("web-authoring:"):
                    task = db.get(Task, run.task_id)
                    agent = db.query(TaskAgentInstance).filter_by(task_run_id=run.id, role="UI_WORKER").first()
                    db.query(TaskMessage).filter(
                        TaskMessage.task_run_id == run.id,
                        TaskMessage.message_type == "WEB_TURN",
                        TaskMessage.status == "PROCESSING",
                    ).update({
                        TaskMessage.status: "FAILED",
                        TaskMessage.processed_at: now,
                    }, synchronize_session=False)
                    from app.features.web_testing.models import WebAgentSession
                    from app.execution.browser.session_manager import registry

                    for browser in db.query(WebAgentSession).filter(
                        WebAgentSession.task_run_id == run.id,
                        WebAgentSession.status == "ACTIVE",
                    ).all():
                        registry.close_session(browser.id)
                        browser.status = "FAILED"
                        browser.closed_at = now
                    if run.status == "CANCEL_REQUESTED":
                        run.status = "CANCELLED"
                        run.stage = "CANCELLED"
                        run.finished_at = now
                        if agent is not None:
                            agent.status = "CANCELLED"
                    elif run.status == "PAUSE_REQUESTED":
                        run.status = "PAUSED"
                        if agent is not None:
                            agent.status = "PAUSED"
                    elif run.status == "RUNNING":
                        run.status = "WAITING_CONFIRMATION"
                        run.stage = "WEB_AUTHORING"
                        run.error_code = "WEB_TURN_INTERRUPTED"
                        run.error_message = "Web 操作进程已中断；请重新启动浏览器并检查页面后继续。"
                        if agent is not None:
                            agent.status = "ACTIVE"
                    run.lease_owner = None
                    run.lease_expires_at = None
                    if task is not None:
                        state_service.sync_task_status(db, task, run)
                    state_service.append_event(db, run, "web.authoring.turn_interrupted", {"recovered": True})
                    recovered += 1
                    continue
                run.lease_owner = None
                run.lease_expires_at = None
                continue
            attempt = db.query(TaskAttempt).filter(TaskAttempt.work_item_id == work.id, TaskAttempt.status == "RUNNING").order_by(TaskAttempt.attempt_number.desc()).first()
            invocation = db.query(TaskToolInvocation).filter(TaskToolInvocation.work_item_id == work.id).first() if work.kind in {"EXECUTE_API", "EXECUTE_WEB", "EXECUTE_SECURITY"} else None
            task = db.get(Task, run.task_id)
            agent = db.get(TaskAgentInstance, work.agent_instance_id) if work.agent_instance_id else None
            if invocation is not None and invocation.status == "STARTED":
                invocation.status = "NEEDS_RECONCILIATION"
                invocation.error_message = "调度进程租约过期，API 执行回执未知"
                run.status = "RECONCILIATION_REQUIRED"
                run.stage = "RECONCILIATION_REQUIRED"
                run.error_code = "SIDE_EFFECT_REQUIRES_RECONCILIATION"
                run.error_message = "API 执行中断，业务回执状态不明；系统未自动重放，请先核对执行中心。"
                work.status = "FAILED"
                work.error_code = "SIDE_EFFECT_REQUIRES_RECONCILIATION"
                work.error_message = run.error_message
                if attempt is not None:
                    attempt.status = "NEEDS_RECONCILIATION"
                    attempt.error_code = run.error_code
                    attempt.error_message = run.error_message
                    attempt.finished_at = now
                if agent is not None:
                    agent.status = "NEEDS_RECONCILIATION"
                state_service.append_event(db, run, "run.reconciliation_required", {"work_item_id": work.id})
            else:
                # Planner、对话、报告均可通过检查点或业务回执幂等恢复。
                work.status = "PENDING"
                work.error_code = None
                work.error_message = None
                work.claimed_at = None
                if attempt is not None:
                    attempt.status = "INTERRUPTED"
                    attempt.error_code = "WORKER_INTERRUPTED"
                    attempt.error_message = "调度租约过期，工作项已安全重新排队"
                    attempt.finished_at = now
                if run.status == "CANCEL_REQUESTED":
                    run.status = "CANCELLED"
                    run.finished_at = now
                    work.status = "CANCELLED"
                elif run.status == "PAUSE_REQUESTED":
                    run.status = "PAUSED"
                elif work.kind == "CHAT":
                    prior_status = attempt.checkpoint_json.get("run_status_before_claim") if attempt else None
                    run.status = prior_status if prior_status not in {None, "QUEUED", "RUNNING"} else "QUEUED"
                else:
                    run.status = "QUEUED"
                # 未完成 Worker 收件箱恢复为 RECEIVED，避免中断后丢失补充要求。
                if agent is not None:
                    db.query(TaskMessage).filter(
                        TaskMessage.task_run_id == run.id,
                        TaskMessage.agent_instance_id == agent.id,
                        TaskMessage.status == "PROCESSING",
                    ).update({TaskMessage.status: "RECEIVED"}, synchronize_session=False)
                    agent.status = "QUEUED" if run.status == "QUEUED" else run.status
            run.lease_owner = None
            run.lease_expires_at = None
            if task is not None:
                state_service.sync_task_status(db, task, run)
            state_service.append_event(db, run, "run.recovered", {"work_item_id": work.id, "status": run.status})
            recovered += 1
        db.commit()
        return recovered
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
