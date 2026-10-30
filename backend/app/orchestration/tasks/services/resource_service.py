"""任务资源引用查询与写入。

本服务只管理任务运行到业务资源的去重回链，不复制业务实体；查询按资源类型批量加载名称，
TaskService 与 Worker 的写入入口保留各自已有的元数据语义和事务归属。
"""

from sqlalchemy.orm import Session

from app.core.models.identity import User
from app.core.security.roles import accessible_project_ids
from app.core.security.sanitizer import sanitize_context
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.reports.models.report import TestReport
from app.orchestration.tasks.models import Task, TaskResourceRef, TaskRun
from app.orchestration.tasks.services.access import TaskAccessService
from app.features.test_management.models.test_case import TestCase


class TaskResourceService:
    """任务资源引用的批量查询、来源反查和幂等写入。"""

    @staticmethod
    def list_resources(db: Session, run_id: int, user: User) -> list[dict]:
        """读取可见运行的资源引用，附加业务名称与任务来源。"""
        run, task = TaskAccessService.get_run_for_read(db, run_id, user)
        refs = db.query(TaskResourceRef).filter(
            TaskResourceRef.task_run_id == run.id,
        ).order_by(TaskResourceRef.id.asc()).all()
        names = TaskResourceService.resource_display_names(db, refs)
        return [
            TaskResourceService.resource_response(
                ref,
                display_name=names.get((ref.resource_type, ref.resource_id)),
                task_id=task.id,
                task_title=task.title,
                run_number=run.run_number,
            )
            for ref in refs
        ]

    @staticmethod
    def find_tasks_for_resource(
        db: Session, user: User, *, resource_type: str, resource_id: str,
        project_id: int | None = None,
    ) -> list[dict]:
        """按原业务资源反查可见来源任务，最多返回最近 50 条引用。"""
        visible_ids = accessible_project_ids(db, user)
        query = (
            db.query(TaskResourceRef)
            .join(TaskRun, TaskRun.id == TaskResourceRef.task_run_id)
            .join(Task, Task.id == TaskRun.task_id)
            .filter(TaskResourceRef.resource_type == resource_type, TaskResourceRef.resource_id == resource_id)
        )
        if project_id is not None:
            TaskAccessService.get_project_for_read(db, project_id, user)
            query = query.filter(Task.project_id == project_id)
        elif visible_ids is not None:
            query = query.filter(Task.project_id.in_(visible_ids or [-1]))
        rows = query.add_columns(Task.id, Task.title, TaskRun.run_number).order_by(
            TaskResourceRef.created_at.desc(), TaskResourceRef.id.desc(),
        ).limit(50).all()
        refs = [row[0] for row in rows]
        names = TaskResourceService.resource_display_names(db, refs)
        return [
            TaskResourceService.resource_response(
                ref,
                display_name=names.get((ref.resource_type, ref.resource_id)),
                task_id=task_id,
                task_title=task_title,
                run_number=run_number,
            )
            for ref, task_id, task_title, run_number in rows
        ]

    @staticmethod
    def resource_response(
        ref: TaskResourceRef, *, display_name: str | None,
        task_id: int, task_title: str, run_number: int,
    ) -> dict:
        """保留原资源引用字段并补充任务来源与可读名称。"""
        result = {column.name: getattr(ref, column.name) for column in ref.__table__.columns}
        result.update({
            "display_name": display_name,
            "task_id": task_id,
            "task_title": task_title,
            "run_number": run_number,
        })
        return result

    @staticmethod
    def resource_display_names(db: Session, refs: list[TaskResourceRef]) -> dict[tuple[str, str], str]:
        """按资源类型批量查询名称，避免资源列表产生 N+1 查询。"""
        ids_by_type: dict[str, set[int]] = {}
        for ref in refs:
            try:
                ids_by_type.setdefault(ref.resource_type, set()).add(int(ref.resource_id))
            except (TypeError, ValueError):
                continue
        names: dict[tuple[str, str], str] = {}
        if ids := ids_by_type.get("TEST_CASE"):
            rows = db.query(TestCase.id, TestCase.name).filter(TestCase.id.in_(ids)).all()
            names.update({("TEST_CASE", str(row.id)): row.name for row in rows})
        if ids := ids_by_type.get("TEST_RUN"):
            from app.features.test_management.models.execution import TestRun

            rows = db.query(TestRun.id, TestRun.status).filter(TestRun.id.in_(ids)).all()
            names.update({("TEST_RUN", str(row.id)): f"测试运行 #{row.id} · {row.status}" for row in rows})
        if ids := ids_by_type.get("REPORT"):
            rows = db.query(TestReport.id, TestReport.report_no).filter(TestReport.id.in_(ids)).all()
            names.update({("REPORT", str(row.id)): row.report_no or f"测试报告 #{row.id}" for row in rows})
        if ids := ids_by_type.get("SECURITY_FINDING"):
            from app.features.security_testing.models import SecurityFinding

            rows = db.query(SecurityFinding.id, SecurityFinding.title).filter(SecurityFinding.id.in_(ids)).all()
            names.update({("SECURITY_FINDING", str(row.id)): f"疑似问题：{row.title}" for row in rows})
        if ids := ids_by_type.get("API"):
            rows = db.query(ApiInterface.id, ApiInterface.name, ApiInterface.method, ApiInterface.path).filter(ApiInterface.id.in_(ids)).all()
            names.update({("API", str(row.id)): f"{row.method} {row.path} · {row.name}" for row in rows})
        if ids := ids_by_type.get("SECURITY_STRATEGY"):
            from app.features.security_testing.models import SecurityStrategy

            rows = db.query(SecurityStrategy.id, SecurityStrategy.name).filter(SecurityStrategy.id.in_(ids)).all()
            names.update({("SECURITY_STRATEGY", str(row.id)): row.name for row in rows})
        if ids := ids_by_type.get("WEB_AGENT_SESSION"):
            from app.features.web_testing.models import WebAgentSession

            rows = db.query(WebAgentSession.id).filter(WebAgentSession.id.in_(ids)).all()
            names.update({
                ("WEB_AGENT_SESSION", str(row.id)): f"受控浏览器会话 #{row.id}"
                for row in rows
            })
        return names

    @staticmethod
    def add_resource_ref(
        db: Session, run: TaskRun, direction: str, resource_type: str, resource_id: str,
        *, agent_instance_id: int | None = None, version: str | None = None,
        metadata: dict | None = None,
    ) -> TaskResourceRef:
        """按运行和资源去重写入服务层引用，并保留 TaskService 的 task_id 元数据。"""
        return TaskResourceService._add_resource_ref(
            db, run, direction, resource_type, resource_id,
            agent_instance_id=agent_instance_id, version=version,
            metadata={**(metadata or {}), "task_id": run.task_id},
        )

    @staticmethod
    def add_worker_resource_ref(
        db: Session, run: TaskRun, direction: str, resource_type: str, resource_id: str,
        *, agent_instance_id: int | None = None, metadata: dict | None = None,
    ) -> TaskResourceRef:
        """按运行和资源去重写入 Worker 引用，保留原 Worker 元数据形状。"""
        return TaskResourceService._add_resource_ref(
            db, run, direction, resource_type, resource_id,
            agent_instance_id=agent_instance_id, version=None, metadata=metadata or {},
        )

    @staticmethod
    def _add_resource_ref(
        db: Session, run: TaskRun, direction: str, resource_type: str, resource_id: str,
        *, agent_instance_id: int | None, version: str | None, metadata: dict,
    ) -> TaskResourceRef:
        """复用唯一键命中的资源引用，未提交时仅加入当前会话。"""
        existing = db.query(TaskResourceRef).filter(
            TaskResourceRef.task_run_id == run.id,
            TaskResourceRef.direction == direction,
            TaskResourceRef.resource_type == resource_type,
            TaskResourceRef.resource_id == resource_id,
        ).first()
        if existing is not None:
            return existing
        ref = TaskResourceRef(
            task_run_id=run.id,
            agent_instance_id=agent_instance_id,
            direction=direction,
            resource_type=resource_type,
            resource_id=resource_id,
            version=version,
            metadata_json=sanitize_context(metadata),
        )
        db.add(ref)
        return ref
