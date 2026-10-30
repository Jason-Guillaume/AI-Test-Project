"""任务运行处理器的可信上下文和窄协作接口。

Worker 从数据库装配任务身份、运行、工作项与执行尝试；处理器只取得本阶段需要的模型、
入队、资源、事件和控制边界能力，不接收整个 Worker 或 TaskService。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from app.llm import LLMProvider
from app.orchestration.tasks.services.contracts import WorkEnqueuer, EventAppender
from sqlalchemy.orm import Session
from app.core.models.identity import User
from app.orchestration.tasks.models import (
    Task,
    TaskAgentInstance,
    TaskAttempt,
    TaskMessage,
    TaskResourceRef,
    TaskRun,
    TaskWorkItem,
)


@dataclass(frozen=True)
class TaskHandlerContext:
    """由 Worker 可信装配的单次处理上下文，不接受模型输入覆盖。"""

    db: Session
    task: Task
    run: TaskRun
    work: TaskWorkItem
    attempt: TaskAttempt
    agent: TaskAgentInstance | None
    actor: User


class ProviderFactory(Protocol):
    """只装配当前工作项获授权的模型路由。"""

    def __call__(self, db: Session, task: Task, run: TaskRun, work: TaskWorkItem,
                 attempt: TaskAttempt, agent: TaskAgentInstance, actor: User) -> LLMProvider: ...


class WorkerResourceAppender(Protocol):
    """以唯一资源键登记 Worker 回执。"""

    def __call__(self, db: Session, run: TaskRun, direction: str, resource_type: str,
                 resource_id: str, *, agent_instance_id: int | None = None,
                 metadata: dict[str, Any] | None = None) -> TaskResourceRef: ...


class ControlBoundary(Protocol):
    """模型调用后复核暂停和取消，不执行后续副作用。"""

    def __call__(self, db: Session, run: TaskRun, work: TaskWorkItem, attempt: TaskAttempt,
                 agent: TaskAgentInstance | None, *, messages: list[TaskMessage] | None = None) -> bool: ...


@dataclass(frozen=True)
class TaskHandlerServices:
    """报告和审阅处理器需要的有限运行时协作能力。"""

    provider_for_agent: ProviderFactory
    enqueue_work: WorkEnqueuer
    add_worker_resource: WorkerResourceAppender
    append_event: EventAppender
    defer_at_control_boundary: ControlBoundary


def require_agent_tool(run: TaskRun, agent: TaskAgentInstance, tool_name: str) -> None:
    """验证运行快照绑定 Agent 的工具白名单；旧流程保持原有默认能力。"""
    if (run.input_snapshot or {}).get("agent_definition") and tool_name not in (agent.tool_allowlist_json or []):
        raise RuntimeError(f"当前 Agent 未获授权使用工具：{tool_name}")


@dataclass(frozen=True)
class ClaimedWork:
    """已领取工作项、运行和执行尝试的稳定 ID。"""

    work_item_id: int
    run_id: int
    attempt_id: int
    owner: str
