"""统一内置工具调用入口。

本模块按稳定键查找显式注册处理器，在调用前检查工具存在与调用通道；
现有本地处理器仍负责项目权限、人工确认及业务规则，任务回执继续由任务适配器持有。
"""

from __future__ import annotations

from datetime import datetime
from inspect import signature
import logging
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.core.security.sensitive import is_sensitive_key
from app.llm.tracing import runtime_call_observation, task_trace_metadata
from app.orchestration.tasks.services.runtime_fact_service import record_runtime_event
from app.tools.contracts import ToolCallContext, ToolChannel
from app.tools.registry import ToolDispatchError, get_binding

_PENDING_EVENTS = 'tool_runtime_events'
logger = logging.getLogger(__name__)


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
    tool_call_id = uuid4().hex
    started = time.monotonic()
    trace = task_trace_metadata.get() or {}
    try:
        binding = get_binding(key, channel=channel)
        _reject_disabled_tool(key, context)
        _reject_expired_deadline(context)
        handler = binding.handler
        parameters = signature(handler).parameters
        trusted = dict(context.trusted_arguments) if context is not None else {}
        if context is not None:
            for name, value in (("actor", context.actor), ("user", context.actor), ("project_id", context.project_id)):
                if name in parameters and value is not None:
                    trusted.setdefault(name, value)
        for name, value in trusted.items():
            if name in kwargs and kwargs[name] != value:
                raise ToolDispatchError(f"调用参数不能覆盖服务端上下文：{name}", code='TOOL_CONTEXT_OVERRIDE')
            kwargs[name] = value
    except ToolDispatchError as exc:
        record_tool_rejection(key, channel, context, exc.code, call_id=tool_call_id,
                              duration_ms=int((time.monotonic() - started) * 1000))
        raise
    field_names = sorted(name for name in kwargs if name in parameters and not is_sensitive_key(name))
    event_metadata = {
        "tool_call_id": tool_call_id,
        "tool_key": key,
        "channel": channel,
        "task_run_id": context.task_run_id if context else None,
        "attempt_id": context.attempt_id if context else None,
        "input_field_names": field_names,
    }
    span_id = None
    try:
        _arm_statement_timeout(context)
        with runtime_call_observation(name="tool.call", metadata=event_metadata) as span:
            span_id = getattr(span, "id", None)
            result = handler(*args, **kwargs)
            if span is not None:
                span.update(output={"status": "SUCCEEDED", "result_type": type(result).__name__})
    except Exception as exc:
        _record_tool_event(
            context, trace, tool_call_id, key, channel,
            field_names, "FAILED", type(exc).__name__, int((time.monotonic() - started) * 1000), span_id,
        )
        raise
    _record_tool_event(
        context, trace, tool_call_id, key, channel,
        field_names, "SUCCEEDED", None, int((time.monotonic() - started) * 1000), span_id,
    )
    return result


def record_tool_rejection(key: str, channel: ToolChannel, context: ToolCallContext | None, code: str,
                          *, call_id: str | None = None, duration_ms: int = 0) -> None:
    """为真实调度的服务端授权拒绝记一条无输入、无正文的工具事实。"""
    _record_tool_event(context, task_trace_metadata.get() or {}, call_id or uuid4().hex,
                       'unregistered' if code == 'TOOL_UNREGISTERED' else key, channel,
                       [], 'REJECTED', code, duration_ms, None)


def _arm_statement_timeout(context: ToolCallContext | None) -> None:
    """给当前事务里的数据库语句加上本地超时，提交或回滚后自动失效。"""
    db = getattr(context, "db", None) if context is not None else None
    get_bind = getattr(db, "get_bind", None)
    if get_bind is None:
        return
    try:
        bind = get_bind()
    except Exception:
        return
    if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return
    from sqlalchemy import text

    from app.core.config import settings

    db.execute(text("SELECT set_config('statement_timeout', :timeout, true)"), {
        "timeout": str(int(settings.TOOL_CALL_TIMEOUT_SECONDS) * 1000),
    })


def _reject_expired_deadline(context: ToolCallContext | None) -> None:
    """截止时间已过时不再开始工具调用，避免超时后继续产生副作用。"""
    db = getattr(context, "db", None) if context is not None else None
    if db is None or context is None or context.task_run_id is None:
        return
    from app.orchestration.tasks.models import TaskAttempt, TaskRun

    run = db.get(TaskRun, context.task_run_id)
    now = datetime.now()
    if run is not None and run.deadline_at is not None and run.deadline_at <= now:
        raise ToolDispatchError("任务已超过截止时间，未开始工具调用", code='TOOL_RUN_DEADLINE_EXCEEDED')
    if context.attempt_id is None:
        return
    attempt = db.get(TaskAttempt, context.attempt_id)
    if attempt is not None and attempt.deadline_at is not None and attempt.deadline_at <= now:
        raise ToolDispatchError("本次尝试已超过截止时间，未开始工具调用", code='TOOL_ATTEMPT_DEADLINE_EXCEEDED')


def _reject_disabled_tool(key: str, context: ToolCallContext | None) -> None:
    """停用后的工具即使仍留在历史授权里也不能执行。"""
    db = getattr(context, "db", None) if context is not None else None
    if db is None:
        return
    from app.tools.models import ToolDefinitionOverride

    override = db.query(ToolDefinitionOverride).filter(ToolDefinitionOverride.tool_key == key).first()
    if override is not None and override.is_enabled is False:
        raise ToolDispatchError(f"工具已停用：{key}", code='TOOL_DISABLED')


def _record_tool_event(context, trace_metadata, call_id, key, channel, field_names,
                       status, error_code, duration_ms, span_id) -> None:
    """写入可聚合的工具调用索引，不复制工具输入或输出。"""
    get_context_value = lambda field: getattr(context, field, None) if context is not None else None
    project_id = get_context_value("project_id") or trace_metadata.get("project_id")
    if project_id is None:
        return
    fact = dict(
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
        occurred_at=datetime.now(),
        event_metadata={"tool_call_id": call_id, "channel": channel, "input_field_names": field_names},
    )
    db = get_context_value('db')
    if isinstance(db, Session):
        if db.in_transaction():
            db.info.setdefault(_PENDING_EVENTS, []).append(fact)
        else:
            _write_tool_events(db, [fact])
    else:
        record_runtime_event(**fact)


def _write_tool_events(db: Session, events: list[dict]) -> None:
    """通过独立事务保存事实，工具副作用的提交结果由调用方决定。"""
    try:
        bind = db.get_bind()
        with Session(bind=bind.engine if isinstance(bind, Connection) else bind) as audit:
            for fact in events:
                record_runtime_event(db=audit, **fact)
            audit.commit()
    except Exception as exc:  # 审计持久化故障仍保留原工具返回或异常。
        logger.warning('工具运行事实提交失败 %s', type(exc).__name__)


@event.listens_for(Session, 'after_transaction_end')
def _flush_tool_events(db, transaction) -> None:
    """等外层事务释放任务、工作项和尝试的行锁，再提交工具事实。"""
    if transaction.parent is None:
        pending = db.info.pop(_PENDING_EVENTS, [])
        if pending:
            _write_tool_events(db, pending)
