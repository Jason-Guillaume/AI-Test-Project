"""任务、运行、消息和事件查询。

查询服务负责可见范围、稳定排序、游标分页和已加载对象的 DTO 组合；所有路径只读，
写入、命令和事务提交继续由原业务服务负责。
"""

from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.core.models.identity import User
from app.core.security.roles import accessible_project_ids
from app.orchestration.tasks.models import (
    Task,
    TaskAgentInstance,
    TaskEvent,
    TaskMessage,
    TaskPlan,
    TaskRun,
    TaskToolInvocation,
    TaskWorkItem,
)
from app.orchestration.tasks.schemas import TaskWorkItemResponse
from app.orchestration.tasks.services.access import TaskAccessService
from app.orchestration.tasks.services.serializers import TaskSerializers


RETRYABLE_RUN_STATUSES = frozenset({"FAILED", "RECONCILIATION_REQUIRED", "SUCCEEDED_WITH_ISSUES"})
RETRYABLE_WORK_ITEM_KINDS = frozenset({
    "PLAN", "CHAT", "REPORT", "FINALIZE", "EXECUTE_API", "EXECUTE_WEB", "EXECUTE_WEB_AUTHORING", "EXECUTE_SECURITY",
})
UNCERTAIN_INVOCATION_STATUSES = frozenset({"STARTED", "NEEDS_RECONCILIATION"})


def retry_block_reason(
    run: TaskRun,
    work: TaskWorkItem,
    invocations: list[TaskToolInvocation],
) -> str | None:
    """返回工作项当前不能重试的原因；返回 None 表示服务端允许重试。"""
    if run.status not in RETRYABLE_RUN_STATUSES:
        return "当前运行状态不支持重试"
    if work.status != "FAILED":
        return "只有失败的工作项可以重试"
    if work.kind in {"EXECUTE_API", "EXECUTE_WEB", "EXECUTE_SECURITY"} and any(
        invocation.status in UNCERTAIN_INVOCATION_STATUSES for invocation in invocations
    ):
        return "测试执行回执状态不明，请先从执行中心核对，不能自动重放"
    if work.kind == "SECURITY_SCAN":
        return "历史 ZAP 工作项已停用，不能重试"
    if work.kind not in RETRYABLE_WORK_ITEM_KINDS:
        return "该类工作项尚未接入安全重试"
    if work.attempt_count >= work.max_attempts:
        return "工作项已达到最大重试次数"
    return None


class TaskQueryService:
    """任务只读查询服务。"""

    @staticmethod
    def list_tasks(
        db: Session, user: User, *, page: int, page_size: int,
        project_id: int | None = None, status: str | None = None,
    ) -> dict[str, Any]:
        """列出当前用户可见任务，保留原分页形状、过滤及排序。"""
        visible_ids = accessible_project_ids(db, user)
        query = db.query(Task)
        if project_id is not None:
            TaskAccessService.get_project_for_read(db, project_id, user)
            query = query.filter(Task.project_id == project_id)
        elif visible_ids is not None:
            # 空可见集合用 [-1] 占位，避免空 IN 条件在数据库间产生差异。
            query = query.filter(Task.project_id.in_(visible_ids or [-1]))
        if status:
            query = query.filter(Task.status == status)
        total = int(query.order_by(None).with_entities(func.count()).scalar() or 0)
        rows = query.order_by(Task.updated_at.desc(), Task.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        latest_by_task = TaskQueryService.latest_runs(db, [row.id for row in rows])
        items = [TaskSerializers.task_response(row, latest_by_task.get(row.id)) for row in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def get_task(db: Session, task_id: int, user: User) -> dict[str, Any]:
        """读取任务与最新运行；跨项目不可见统一返回 404。"""
        task = TaskAccessService.get_task_for_read(db, task_id, user)
        return TaskQueryService.task_detail(db, task)

    @staticmethod
    def task_detail(db: Session, task: Task) -> dict[str, Any]:
        """按运行编号降序读取最新运行并转换为任务详情 DTO。"""
        latest = db.query(TaskRun).filter(TaskRun.task_id == task.id).order_by(TaskRun.run_number.desc()).first()
        return TaskSerializers.task_response(task, latest)

    @staticmethod
    def get_run_detail(db: Session, run_id: int, user: User) -> dict[str, Any]:
        """读取运行方案、参与者、工作项及工具回执，保持响应中的状态一致性刷新。"""
        run, _ = TaskAccessService.get_run_for_read(db, run_id, user)
        # 多次只读查询可能跨过 Planner 提交；刷新权威状态以避免混合视图。
        plans = db.query(TaskPlan).filter(TaskPlan.task_run_id == run.id).order_by(TaskPlan.version.asc()).all()
        agents = db.query(TaskAgentInstance).filter(TaskAgentInstance.task_run_id == run.id).order_by(TaskAgentInstance.id.asc()).all()
        work_items = db.query(TaskWorkItem).filter(TaskWorkItem.task_run_id == run.id).order_by(TaskWorkItem.sequence.asc(), TaskWorkItem.id.asc()).all()
        tool_invocations = db.query(TaskToolInvocation).filter(
            TaskToolInvocation.task_run_id == run.id,
        ).order_by(TaskToolInvocation.created_at.asc(), TaskToolInvocation.id.asc()).all()
        db.refresh(run)
        invocations_by_work_item: dict[int, list[TaskToolInvocation]] = {}
        for invocation in tool_invocations:
            invocations_by_work_item.setdefault(invocation.work_item_id, []).append(invocation)
        work_item_responses = []
        for work_item in work_items:
            block_reason = retry_block_reason(run, work_item, invocations_by_work_item.get(work_item.id, []))
            response = TaskWorkItemResponse.model_validate(work_item).model_dump()
            response["retryable"] = block_reason is None
            response["retry_block_reason"] = block_reason
            work_item_responses.append(response)
        return {
            "run": TaskSerializers.run_response(run),
            "plans": plans,
            "agents": agents,
            "work_items": work_item_responses,
            "tool_invocations": tool_invocations,
        }

    @staticmethod
    def list_messages(db: Session, run_id: int, user: User) -> list[TaskMessage]:
        """按消息 ID 升序读取所选运行的参与者消息。"""
        run, _ = TaskAccessService.get_run_for_read(db, run_id, user)
        return db.query(TaskMessage).filter(TaskMessage.task_run_id == run.id).order_by(TaskMessage.id.asc()).all()

    @staticmethod
    def list_events(db: Session, run_id: int, user: User, *, after_seq: int, limit: int = 200) -> list[TaskEvent]:
        """按事件序号游标续读，限制单页最多 200 条。"""
        run, _ = TaskAccessService.get_run_for_read(db, run_id, user)
        return (
            db.query(TaskEvent)
            .filter(TaskEvent.task_run_id == run.id, TaskEvent.event_seq > after_seq)
            .order_by(TaskEvent.event_seq.asc()).limit(min(max(limit, 1), 200)).all()
        )

    @staticmethod
    def latest_runs(db: Session, task_ids: list[int]) -> dict[int, TaskRun]:
        """数据库侧聚合每个任务最新运行，避免遍历完整历史。"""
        if not task_ids:
            return {}
        latest = db.query(TaskRun.task_id, func.max(TaskRun.run_number).label("run_number")).filter(
            TaskRun.task_id.in_(task_ids)
        ).group_by(TaskRun.task_id).subquery()
        return {
            run.task_id: run for run in db.query(TaskRun).join(
                latest, and_(TaskRun.task_id == latest.c.task_id, TaskRun.run_number == latest.c.run_number)
            ).all()
        }
