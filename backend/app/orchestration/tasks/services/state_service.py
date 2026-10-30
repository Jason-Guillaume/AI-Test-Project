"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskEvent, TaskRun, TaskWorkItem
from app.core.http.errors import not_found
from app.core.security.sanitizer import sanitize_context


def enqueue_work(
    db: Session, run: TaskRun, agent: TaskAgentInstance | None, *, work_key: str,
    kind: str, input_json: dict[str, Any], sequence: int,
) -> TaskWorkItem:
    """按运行内键去重登记工作项，重复 HTTP 命令不会复制任务副作用。"""
    existing = db.query(TaskWorkItem).filter(
        TaskWorkItem.task_run_id == run.id, TaskWorkItem.work_key == work_key,
    ).first()
    if existing is not None:
        return existing
    work = TaskWorkItem(
        task_run_id=run.id,
        agent_instance_id=agent.id if agent else None,
        work_key=work_key,
        kind=kind,
        sequence=sequence,
        status="PENDING",
        input_json=sanitize_context(input_json),
        idempotency_key=f"run:{run.id}:{work_key}",
    )
    db.add(work)
    db.flush()
    return work


def agent_by_role(db: Session, run_id: int, role: str) -> TaskAgentInstance:
    """取运行内固定角色实例；不存在时按数据完整性错误处理。"""
    agent = db.query(TaskAgentInstance).filter(
        TaskAgentInstance.task_run_id == run_id, TaskAgentInstance.role == role,
    ).first()
    if agent is None:
        raise not_found("任务参与者不存在")
    return agent


def append_event(
    db: Session, run: TaskRun, event_type: str, payload: dict[str, Any], *,
    actor_user_id: int | None = None, agent_instance_id: int | None = None,
) -> TaskEvent:
    """同事务递增运行游标并记录实际状态变化。"""
    run.event_seq += 1
    event = TaskEvent(
        task_run_id=run.id,
        event_seq=run.event_seq,
        event_type=event_type,
        actor_user_id=actor_user_id,
        agent_instance_id=agent_instance_id,
        payload=sanitize_context(payload),
    )
    db.add(event)
    notification = TASK_NOTIFICATION_EVENTS.get(event_type)
    if notification:
        task = db.get(Task, run.task_id)
        if task is not None and task.created_by is not None:
            from app.core.models.notification import Notification

            notification_type, title = notification
            db.add(Notification(
                user_id=task.created_by,
                project_id=task.project_id,
                event_type=notification_type,
                title=title,
                body=task.title,
                payload={"actor": actor_user_id, "detail": {"task_id": task.id, "run_id": run.id}},
                is_read=False,
            ))
    return event


def sync_task_status(db: Session, task: Task, run: TaskRun) -> None:
    """只让最新 run 更新任务列表状态，旧运行收尾不覆盖新目标。"""
    latest_id = db.query(TaskRun.id).filter(TaskRun.task_id == task.id).order_by(TaskRun.run_number.desc()).limit(1).scalar()
    if latest_id == run.id:
        task.status = run.status


RUN_TERMINAL_STATUSES = frozenset({"SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED", "SUPERSEDED"})


RUN_PAUSE_STATUSES = frozenset({"PAUSED", "PAUSE_REQUESTED"})


TASK_NOTIFICATION_EVENTS = {
    "plan.proposed": ("task.plan_ready", "任务方案待确认"),
    "run.completed": ("task.completed", "任务已完成"),
    "run.completed_with_issues": ("task.completed_with_issues", "任务完成但有问题"),
    "work_item.failed": ("task.failed", "任务执行失败"),
    "llm.fallback_exhausted": ("task.waiting_model", "任务等待模型配置恢复"),
    "run.reconciliation_required": ("task.reconciliation_required", "任务执行结果待核对"),
}
