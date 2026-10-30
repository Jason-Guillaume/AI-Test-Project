"""任务服务的窄调用契约；回调只代表单项能力，不暴露服务实例。"""

from __future__ import annotations

from typing import Any, Protocol
from sqlalchemy.orm import Session
from app.core.models.identity import User
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskEvent, TaskRun, TaskWorkItem


class RunCreator(Protocol):
    """创建运行及冻结快照，事务仍由调用方持有。"""

    def __call__(self, db: Session, task: Task, actor: User, *, run_number: int,
                 target_type: str, agent_bundle: dict[str, Any] | None = None) -> TaskRun: ...


class WorkEnqueuer(Protocol):
    """按运行内工作键幂等登记一项工作。"""

    def __call__(self, db: Session, run: TaskRun, agent: TaskAgentInstance | None, *,
                 work_key: str, kind: str, input_json: dict[str, Any], sequence: int) -> TaskWorkItem: ...


class EventAppender(Protocol):
    """在调用方事务内追加事件及通知。"""

    def __call__(self, db: Session, run: TaskRun, event_type: str, payload: dict[str, Any], *,
                 actor_user_id: int | None = None, agent_instance_id: int | None = None) -> TaskEvent: ...
