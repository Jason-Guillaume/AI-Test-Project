"""统一内置工具调用入口。

本模块按稳定键查找显式注册处理器，在调用前检查工具存在与调用通道；
现有本地处理器仍负责项目权限、人工确认及业务规则，任务回执继续由任务适配器持有。
"""

from __future__ import annotations

from inspect import signature
from typing import Any

from app.tools.contracts import ToolCallContext, ToolChannel
from app.tools.registry import ToolDispatchError, get_binding


def dispatch_tool(
    key: str,
    /,
    *args: Any,
    channel: ToolChannel,
    context: ToolCallContext | None = None,
    **kwargs: Any,
) -> Any:
    """经注册表调用本地处理器，并注入不可由模型覆盖的可信身份参数。

    Args:
        key: 服务端选择的稳定工具键。
        channel: 由调用适配器指定的 ``fixed`` 或 ``model`` 来源。
        context: 可选可信用户、项目、运行、尝试和确认引用。
        args: 与既有本地工具签名兼容的位置参数。
        kwargs: 业务输入；与可信上下文冲突时拒绝调用。
    Returns:
        Any: 返回原处理器结果，不改变业务序列化行为。
    Raises:
        ToolDispatchError: 键未注册、来源不允许或模型参数试图覆盖可信身份时抛出。
    """
    binding = get_binding(key, channel=channel)
    handler = binding.handler
    trusted = dict(context.trusted_arguments) if context is not None else {}
    if context is not None:
        parameters = signature(handler).parameters
        if "actor" in parameters and context.actor is not None:
            trusted.setdefault("actor", context.actor)
        if "user" in parameters and context.actor is not None:
            trusted.setdefault("user", context.actor)
        if "project_id" in parameters and context.project_id is not None:
            trusted.setdefault("project_id", context.project_id)
    for name, value in trusted.items():
        if name in kwargs and kwargs[name] != value:
            raise ToolDispatchError(f"调用参数不能覆盖服务端上下文：{name}")
        kwargs[name] = value
    return handler(*args, **kwargs)
