"""服务端聚合当前用户发起且仍可见的待处理任务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.core.models.identity import User
from app.core.models.project import Project
from app.core.security.roles import accessible_project_ids
from app.orchestration.tasks.models import Task, TaskRun
from app.orchestration.tasks.services.access import TaskAccessService


CATEGORY = case(
    (TaskRun.status == "WAITING_CONFIRMATION", "approval"),
    (and_(TaskRun.status == "PAUSED", TaskRun.stage == "WAITING_MODEL"), "model_blocked"),
    (TaskRun.status == "RECONCILIATION_REQUIRED", "reconcile"),
    (TaskRun.status.in_(("FAILED", "SUCCEEDED_WITH_ISSUES")), "failed"),
    else_=None,
)


class TaskInboxService:
    """跨页准确汇总待办，并返回每项定位到真实最新运行的信息。"""

    @staticmethod
    def list_for_user(
        db: Session, actor: User, *, page: int, page_size: int,
        project_id: int | None = None, category: str | None = None,
    ) -> dict[str, Any]:
        visible_ids = accessible_project_ids(db, actor)
        if project_id is not None:
            TaskAccessService.get_project_for_read(db, project_id, actor)
        latest = db.query(
            TaskRun.task_id.label("task_id"), func.max(TaskRun.run_number).label("run_number"),
        ).group_by(TaskRun.task_id).subquery()
        query = db.query(Task, TaskRun, Project).join(
            latest, latest.c.task_id == Task.id,
        ).join(
            TaskRun, and_(TaskRun.task_id == Task.id, TaskRun.run_number == latest.c.run_number),
        ).join(Project, Project.id == Task.project_id).filter(
            Task.created_by == actor.id,
            Task.archived.is_(False),
            CATEGORY.isnot(None),
        )
        if project_id is not None:
            query = query.filter(Task.project_id == project_id)
        elif visible_ids is not None:
            query = query.filter(Task.project_id.in_(visible_ids or [-1]))

        counts_query = db.query(CATEGORY.label("category"), func.count(Task.id)).join(
            latest, latest.c.task_id == Task.id,
        ).join(
            TaskRun, and_(TaskRun.task_id == Task.id, TaskRun.run_number == latest.c.run_number),
        ).filter(
            Task.created_by == actor.id,
            Task.archived.is_(False),
            CATEGORY.isnot(None),
        )
        if project_id is not None:
            counts_query = counts_query.filter(Task.project_id == project_id)
        elif visible_ids is not None:
            counts_query = counts_query.filter(Task.project_id.in_(visible_ids or [-1]))
        counts = {"approval": 0, "model_blocked": 0, "failed": 0, "reconcile": 0}
        counts.update({key: int(value) for key, value in counts_query.group_by(CATEGORY).all()})
        if category:
            query = query.filter(CATEGORY == category)
        total = int(query.order_by(None).with_entities(func.count(Task.id)).scalar() or 0)
        rows = query.order_by(Task.updated_at.desc(), Task.id.desc()).offset(
            (page - 1) * page_size,
        ).limit(page_size).all()
        items = []
        for task, run, project in rows:
            category_value = "approval" if run.status == "WAITING_CONFIRMATION" else (
                "model_blocked" if run.status == "PAUSED" and run.stage == "WAITING_MODEL" else (
                    "reconcile" if run.status == "RECONCILIATION_REQUIRED" else "failed"
                )
            )
            reason = run.error_message or {
                "approval": "方案等待人工确认",
                "model_blocked": "模型配置当前不可用",
                "reconcile": "外部执行回执需要人工核对",
                "failed": "任务运行未能完整完成",
            }[category_value]
            next_action = {
                "approval": "打开方案并确认或拒绝",
                "model_blocked": "检查模型配置后恢复运行",
                "reconcile": "核对执行中心回执，避免重复执行",
                "failed": "查看失败原因并检查可重试工作项",
            }[category_value]
            items.append({
                "task_id": task.id,
                "project_id": task.project_id,
                "project_name": project.name,
                "task_title": task.title,
                "run_id": run.id,
                "run_number": run.run_number,
                "run_status": run.status,
                "stage": run.stage,
                "category": category_value,
                "reason": reason,
                "next_action": next_action,
                "updated_at": task.updated_at,
            })
        return {"items": items, "counts": counts, "total": total, "page": page, "page_size": page_size}
