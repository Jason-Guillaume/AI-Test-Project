"""受控工具的中立数据契约。

本模块定义工具元数据与服务端运行上下文，供工具注册表、调度器和业务适配器共同使用；
不依赖 Agent 图、任务 Worker 或治理路由。调用来源只由服务端设定，模型输入不能提供身份或审批引用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

ToolChannel = Literal["fixed", "model"]
ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class ToolCallContext:
    """描述由服务端可信地装配的工具调用身份与任务引用。"""

    actor: Any | None = None
    project_id: int | None = None
    task_run_id: int | None = None
    attempt_id: int | None = None
    confirmation_id: int | None = None
    trusted_arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolBinding:
    """记录稳定工具键、受控处理器和允许的调用通道。"""

    key: str
    handler: ToolHandler
    risk: str
    allowed_channels: frozenset[ToolChannel]
    catalog_status: str
    input_contract: dict[str, Any] = field(default_factory=dict)
