"""任务、运行、消息和事件查询。

查询服务负责可见范围、稳定排序、游标分页和已加载对象的 DTO 组合；所有路径只读，
写入、命令和事务提交继续由原业务服务负责。
"""

import base64
import binascii
import json
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, literal, or_
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
    TaskAttempt,
    RuntimeCallFact,
    RuntimeEventFact,
)
from app.orchestration.tasks.schemas import TaskTraceEventResponse, TaskTracePageResponse, TaskWorkItemResponse
from app.orchestration.tasks.services.access import TaskAccessService
from app.orchestration.tasks.services.serializers import TaskSerializers
from app.core.http.errors import bad_request
from app.features.test_management.models.case_generation import CaseGenerationBatch


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
    def task_summary(db: Session, user: User) -> dict[str, Any]:
        """从所有可见任务的最新运行统计状态，避免用第一页估算全局数量。"""
        visible_ids = accessible_project_ids(db, user)
        latest = db.query(TaskRun.task_id, func.max(TaskRun.run_number).label("run_number")).group_by(TaskRun.task_id).subquery()
        query = db.query(TaskRun.status, func.count(Task.id)).select_from(TaskRun).join(
            Task, Task.id == TaskRun.task_id,
        ).join(
            latest, and_(latest.c.task_id == Task.id, latest.c.run_number == TaskRun.run_number),
        )
        if visible_ids is not None:
            query = query.filter(Task.project_id.in_(visible_ids or [-1]))
        counts = {status: int(count) for status, count in query.group_by(TaskRun.status).all()}
        active_statuses = {"QUEUED", "RUNNING", "WAITING_CONFIRMATION", "PAUSED", "PAUSE_REQUESTED", "CANCEL_REQUESTED", "RECONCILIATION_REQUIRED"}
        active_count = sum(count for status, count in counts.items() if status in active_statuses)
        inbox = db.query(TaskRun.status, func.count(Task.id)).select_from(TaskRun).join(
            Task, Task.id == TaskRun.task_id,
        ).join(
            latest, and_(latest.c.task_id == Task.id, latest.c.run_number == TaskRun.run_number),
        ).filter(
            Task.created_by == user.id,
            Task.archived.is_(False),
            (TaskRun.status == "WAITING_CONFIRMATION")
            | ((TaskRun.status == "PAUSED") & (TaskRun.stage == "WAITING_MODEL"))
            | TaskRun.status.in_(("FAILED", "SUCCEEDED_WITH_ISSUES", "RECONCILIATION_REQUIRED")),
        )
        if visible_ids is not None:
            inbox = inbox.filter(Task.project_id.in_(visible_ids or [-1]))
        attention_count = int(sum(count for _, count in inbox.group_by(TaskRun.status).all()))
        return {"active_count": active_count, "needs_attention_count": attention_count, "by_status": counts}

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
        tool_invocations = db.query(TaskToolInvocation).filter(
            TaskToolInvocation.task_run_id == run.id,
        ).order_by(TaskToolInvocation.created_at.asc(), TaskToolInvocation.id.asc()).all()
        # A worker may commit between the preceding related-record reads. Load the
        # run and its work items in one statement so status/stage and item status
        # come from the same database snapshot.
        run_and_work = (
            db.query(TaskRun, TaskWorkItem)
            .outerjoin(TaskWorkItem, TaskWorkItem.task_run_id == TaskRun.id)
            .filter(TaskRun.id == run.id)
            .order_by(TaskWorkItem.sequence.asc(), TaskWorkItem.id.asc())
            .populate_existing()
            .all()
        )
        run = run_and_work[0][0] if run_and_work else run
        work_items = [item for _, item in run_and_work if item is not None]
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
    def trace_timeline(
        db: Session, run_id: int, user: User, *, cursor: str | None = None, limit: int = 100,
    ) -> dict[str, Any]:
        """按任务权限聚合 Langfuse 关联索引与运行事实，并以 keyset 游标返回时间线。"""
        run, task = TaskAccessService.get_run_for_read(db, run_id, user)
        root_id = run.execution_root_run_id or run.id
        related_runs = db.query(TaskRun).filter(
            TaskRun.task_id == task.id,
            or_(TaskRun.id == root_id, TaskRun.execution_root_run_id == root_id),
        ).all()
        run_ids = [related.id for related in related_runs]
        if run.id not in run_ids:
            run_ids.append(run.id)
        traces_by_run = {related.id: related.trace_id for related in related_runs}
        traces_by_run.setdefault(run.id, run.trace_id)
        generation_batch_id = db.query(CaseGenerationBatch.id).filter(
            CaseGenerationBatch.project_id == task.project_id,
            CaseGenerationBatch.task_run_id == root_id,
        ).scalar()

        cursor_key: tuple[datetime, str, int] | None = None
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode() + b"=" * (-len(cursor) % 4)))
                cursor_at = datetime.fromisoformat(decoded["at"])
                if cursor_at.tzinfo is not None:
                    cursor_at = cursor_at.astimezone().replace(tzinfo=None)
                cursor_key = (cursor_at, str(decoded["kind"]), int(decoded["id"]))
            except (ValueError, TypeError, KeyError, binascii.Error, json.JSONDecodeError):
                raise bad_request("Trace 游标无效")

        def keyset_filter(time_col: Any, kind_col: Any, id_col: Any) -> Any:
            if cursor_key is None:
                return None
            at, kind, source_id = cursor_key
            return or_(
                time_col < at,
                and_(time_col == at, kind_col < kind),
                and_(time_col == at, kind_col == kind, id_col < source_id),
            )

        def apply_filter(query: Any, predicate: Any) -> Any:
            return query.filter(predicate) if predicate is not None else query

        root_filter = or_(
            RuntimeCallFact.execution_root_run_id == root_id,
            RuntimeCallFact.task_run_id.in_(run_ids),
        )
        call_time = func.coalesce(RuntimeCallFact.started_at, RuntimeCallFact.finished_at)
        calls = apply_filter(
            db.query(RuntimeCallFact).filter(RuntimeCallFact.task_id == task.id, root_filter),
            keyset_filter(call_time, literal("MODEL_CALL"), RuntimeCallFact.id),
        ).order_by(call_time.desc(), RuntimeCallFact.id.desc()).limit(limit + 1).all()

        event_root_filter = or_(
            RuntimeEventFact.execution_root_run_id == root_id,
            RuntimeEventFact.task_run_id.in_(run_ids),
        )
        events = apply_filter(
            db.query(RuntimeEventFact).filter(RuntimeEventFact.task_id == task.id, event_root_filter),
            keyset_filter(RuntimeEventFact.occurred_at, RuntimeEventFact.event_type, RuntimeEventFact.id),
        ).order_by(
            RuntimeEventFact.occurred_at.desc(), RuntimeEventFact.event_type.desc(), RuntimeEventFact.id.desc(),
        ).limit(limit + 1).all()

        attempt_time = func.coalesce(TaskAttempt.finished_at, TaskAttempt.heartbeat_at, TaskAttempt.started_at)
        attempts_query = db.query(TaskAttempt, TaskWorkItem).join(
            TaskWorkItem, TaskWorkItem.id == TaskAttempt.work_item_id,
        ).filter(TaskWorkItem.task_run_id.in_(run_ids))
        attempts_query = apply_filter(
            attempts_query,
            keyset_filter(attempt_time, literal("AGENT_ATTEMPT"), TaskAttempt.id),
        )
        attempts = attempts_query.order_by(attempt_time.desc(), TaskAttempt.id.desc()).limit(limit + 1).all()

        from app.orchestration.tasks.services.trace_projection_service import (
            projection_status,
            projection_status_by_source,
        )
        projection_sources = [("MODEL_CALL", row.call_id) for row in calls]
        projection_sources.extend(("RUNTIME_EVENT", row.event_id) for row in events)
        projection_sources.extend(("AGENT_ATTEMPT", str(attempt.id)) for attempt, _ in attempts)
        projection_by_source = projection_status_by_source(db, projection_sources)
        projection_summary = projection_status(db, run_ids)

        agent_ids = {row.agent_instance_id for row in calls if row.agent_instance_id}
        agent_ids.update(row.agent_instance_id for row in events if row.agent_instance_id)
        agent_ids.update(work.agent_instance_id for _, work in attempts if work.agent_instance_id)
        agents = {
            agent.id: agent for agent in db.query(TaskAgentInstance).filter(TaskAgentInstance.id.in_(agent_ids)).all()
        } if agent_ids else {}

        items: list[dict[str, Any]] = []
        for row in calls:
            agent = agents.get(row.agent_instance_id)
            items.append({
                "id": f"call:{row.id}", "occurred_at": row.started_at or row.finished_at,
                "event_type": "MODEL_CALL", "event_name": row.model_name, "status": row.status,
                "task_run_id": row.task_run_id, "work_item_id": row.work_item_id, "attempt_id": row.attempt_id,
                "agent_session_id": row.agent_session_id, "agent_instance_id": row.agent_instance_id,
                "parent_agent_instance_id": agent.parent_agent_instance_id if agent else None,
                "agent_definition_id": row.agent_definition_id,
                "agent_name": agent.display_name if agent else None, "agent_role": agent.role if agent else None,
                "agent_definition_revision_id": row.agent_definition_revision_id,
                "trace_id": row.trace_id, "span_id": row.span_id, "duration_ms": row.duration_ms,
                "error_code": row.error_code, "model_config_id": row.model_config_id,
                "model_name": row.model_name, "model_revision": row.model_revision,
                "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
                "total_tokens": row.total_tokens,
                "cost_amount": str(row.cost_amount) if row.cost_amount is not None else None,
                "cost_currency": row.cost_currency, "metadata": {},
                "projection_status": projection_by_source.get(("MODEL_CALL", row.call_id), "UNTRACKED"),
                "_sort_kind": "MODEL_CALL", "_sort_id": row.id,
            })
        for row in events:
            agent = agents.get(row.agent_instance_id)
            items.append({
                "id": f"event:{row.id}", "occurred_at": row.occurred_at,
                "event_type": row.event_type, "event_name": row.event_name, "status": row.status,
                "task_run_id": row.task_run_id, "work_item_id": row.work_item_id, "attempt_id": row.attempt_id,
                "agent_session_id": row.agent_session_id, "agent_instance_id": row.agent_instance_id,
                "parent_agent_instance_id": agent.parent_agent_instance_id if agent else None,
                "agent_definition_id": row.agent_definition_id,
                "agent_name": agent.display_name if agent else None, "agent_role": agent.role if agent else None,
                "agent_definition_revision_id": row.agent_definition_revision_id,
                "trace_id": row.trace_id, "span_id": row.span_id, "duration_ms": row.duration_ms,
                "error_code": row.error_code, "metadata": row.event_metadata or {},
                "projection_status": projection_by_source.get(("RUNTIME_EVENT", row.event_id), "UNTRACKED"),
                "_sort_kind": row.event_type, "_sort_id": row.id,
            })
        for attempt, work in attempts:
            agent = agents.get(work.agent_instance_id)
            checkpoint = attempt.checkpoint_json if isinstance(attempt.checkpoint_json, dict) else {}
            items.append({
                "id": f"attempt:{attempt.id}", "occurred_at": attempt.finished_at or attempt.heartbeat_at or attempt.started_at,
                "event_type": "AGENT_ATTEMPT", "event_name": work.kind, "status": attempt.status,
                "task_run_id": work.task_run_id, "work_item_id": work.id, "attempt_id": attempt.id,
                "agent_instance_id": work.agent_instance_id,
                "parent_agent_instance_id": agent.parent_agent_instance_id if agent else None,
                "agent_definition_id": agent.config_snapshot.get("agent_definition_id") if agent and isinstance(agent.config_snapshot, dict) else None,
                "agent_name": agent.display_name if agent else None, "agent_role": agent.role if agent else None,
                "agent_definition_revision_id": agent.agent_definition_revision_id if agent else None,
                "trace_id": traces_by_run.get(work.task_run_id),
                "span_id": checkpoint.get("agent_span_id"), "duration_ms": max(0, int((
                    (attempt.finished_at or attempt.heartbeat_at or attempt.started_at) - attempt.started_at
                ).total_seconds() * 1000)) if attempt.started_at else 0,
                "error_code": attempt.error_code, "metadata": {"attempt_number": attempt.attempt_number},
                "projection_status": projection_by_source.get(("AGENT_ATTEMPT", str(attempt.id)), "UNTRACKED"),
                "_sort_kind": "AGENT_ATTEMPT", "_sort_id": attempt.id,
            })

        items.sort(key=lambda item: (item["occurred_at"], item["_sort_kind"], item["_sort_id"]), reverse=True)
        has_more = len(items) > limit
        page_items = items[:limit]
        next_cursor = None
        if has_more and page_items:
            last = page_items[-1]
            payload = json.dumps({
                "at": last["occurred_at"].isoformat(), "kind": last["_sort_kind"], "id": last["_sort_id"],
            }, separators=(",", ":")).encode()
            next_cursor = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        serialized = []
        for item in page_items:
            item.pop("_sort_kind", None)
            item.pop("_sort_id", None)
            serialized.append(TaskTraceEventResponse.model_validate(item).model_dump())
        return TaskTracePageResponse(
            task_id=task.id, run_id=run.id, execution_root_run_id=root_id,
            generation_batch_id=generation_batch_id,
            trace_id=run.trace_id, projection=projection_summary,
            items=serialized, next_cursor=next_cursor,
        ).model_dump()

    @staticmethod
    def replay_trace_projections(db: Session, run_id: int, user: User) -> dict[str, Any]:
        """Requeue failed and register untracked runtime facts under the existing task write permission."""
        from app.orchestration.tasks.services.trace_projection_service import replay_run

        run, task = TaskAccessService.get_run_for_write(db, run_id, user)
        root_id = run.execution_root_run_id or run.id
        related_runs = db.query(TaskRun.id).filter(
            TaskRun.task_id == task.id,
            or_(TaskRun.id == root_id, TaskRun.execution_root_run_id == root_id),
        ).all()
        run_ids = [row[0] for row in related_runs]
        if run.id not in run_ids:
            run_ids.append(run.id)
        return replay_run(db, task_id=task.id, run_ids=run_ids, root_id=root_id)

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
