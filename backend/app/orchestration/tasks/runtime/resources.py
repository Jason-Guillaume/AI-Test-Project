"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.orchestration.tasks.models import TaskAgentInstance, TaskResourceRef, TaskRun
from app.orchestration.tasks.services.resource_service import TaskResourceService


def add_resource(db: Session, run: TaskRun, agent: TaskAgentInstance, direction: str, resource_type: str, resource_id: str, metadata: dict) -> TaskResourceRef:
    """记录原业务资源引用；已存在引用复用，不复制业务数据。"""
    return TaskResourceService.add_resource_ref(
        db, run, direction, resource_type, resource_id,
        agent_instance_id=agent.id, metadata=metadata,
    )


def add_resource_ref(db: Session, run: TaskRun, direction: str, resource_type: str, resource_id: str, *, agent_instance_id: int | None=None, metadata: dict | None=None) -> TaskResourceRef:
    """按运行和业务资源去重创建回链。"""
    return TaskResourceService.add_worker_resource_ref(
        db, run, direction, resource_type, resource_id,
        agent_instance_id=agent_instance_id, metadata=metadata,
    )
