"""统一内置工具调用入口。

本模块按稳定键查找显式注册处理器，在调用前检查工具存在与调用通道；
现有本地处理器仍负责项目权限、人工确认及业务规则，任务回执继续由任务适配器持有。
"""

from __future__ import annotations

from inspect import signature
import time
from typing import Any
from uuid import uuid4

from app.llm.tracing import runtime_call_observation, task_trace_metadata
from app.orchestration.tasks.services.runtime_fact_service import record_runtime_event
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
    tool_call_id = uuid4().hex
    event_metadata = {
        "tool_call_id": tool_call_id,
        "tool_key": key,
        "channel": channel,
        "task_run_id": context.task_run_id if context else None,
        "attempt_id": context.attempt_id if context else None,
        "input_field_names": sorted(kwargs),
    }
    started = time.monotonic()
    span_id = None
    try:
        with runtime_call_observation(name="tool.call", metadata=event_metadata) as span:
            result = handler(*args, **kwargs)
            span_id = getattr(span, "id", None)
            if span is not None:
                span.update(output={"status": "SUCCEEDED", "result_type": type(result).__name__})
    except Exception as exc:
        _record_tool_event(
            context, task_trace_metadata.get() or {}, tool_call_id, key, channel,
            sorted(kwargs), "FAILED", type(exc).__name__, int((time.monotonic() - started) * 1000), span_id,
        )
        raise
    _record_tool_event(
        context, task_trace_metadata.get() or {}, tool_call_id, key, channel,
        sorted(kwargs), "SUCCEEDED", None, int((time.monotonic() - started) * 1000), span_id,
    )
    return result


def _record_tool_event(context, trace_metadata, call_id, key, channel, field_names,
                       status, error_code, duration_ms, span_id) -> None:
    """写入可聚合的工具调用索引，不复制工具输入或输出。"""
    get_context_value = lambda field: getattr(context, field, None) if context is not None else None
    project_id = get_context_value("project_id") or trace_metadata.get("project_id")
    if project_id is None:
        return
    record_runtime_event(
        event_id=call_id,
        project_id=project_id,
        task_id=get_context_value("task_id") or trace_metadata.get("task_id"),
        task_run_id=get_context_value("task_run_id") or trace_metadata.get("task_run_id"),
        execution_root_run_id=get_context_value("execution_root_run_id") or trace_metadata.get("execution_root_run_id"),
        work_item_id=get_context_value("work_item_id") or trace_metadata.get("work_item_id"),
        attempt_id=get_context_value("attempt_id") or trace_metadata.get("attempt_id"),
        agent_session_id=get_context_value("agent_session_id") or trace_metadata.get("agent_session_id"),
        agent_instance_id=get_context_value("agent_instance_id") or trace_metadata.get("agent_run_id"),
        agent_definition_id=get_context_value("agent_definition_id") or trace_metadata.get("agent_id"),
        agent_definition_revision_id=get_context_value("agent_definition_revision_id") or trace_metadata.get("agent_revision_id"),
        trace_id=get_context_value("trace_id") or trace_metadata.get("trace_id"),
        span_id=span_id,
        event_type="TOOL_CALL",
        event_name=key,
        status=status,
        error_code=error_code,
        duration_ms=duration_ms,
        event_metadata={"tool_call_id": call_id, "channel": channel, "input_field_names": field_names},
    )
