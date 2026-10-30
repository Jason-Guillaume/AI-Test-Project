"""节点执行上下文：db / user / llm_provider。

由 `build_graph` 注入每个节点的闭包（`functools.partial(node_fn, ctx)`），节点签名
统一为 `node_fn(ctx: NodeContext, state: AgentState) -> dict`。不在 state 里塞
db/user/provider（避免污染 langgraph 状态、避免随 state 序列化）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.llm import LLMProvider
from app.core.models.identity import User


@dataclass(frozen=True)
class NodeContext:
    """单次 invoke 期间所有节点共享的执行上下文。"""

    db: Session
    user: User
    provider: LLMProvider
    web_action_executor: Callable[..., dict[str, Any]] | None = None
