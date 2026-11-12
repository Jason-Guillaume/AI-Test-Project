"""运行事实写入与治理指标查询。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.agents.models import AgentDefinition
from app.core.database.session import SessionLocal
from app.core.http.errors import bad_request, not_found
from app.core.models.configuration import ModelConfiguration
from app.core.models.project import Project
from app.features.test_management.models.case_generation import CaseDraft, CaseGenerationAudit, CaseGenerationBatch
from app.orchestration.tasks.models import (
    RuntimeCallFact,
    RuntimeEventFact,
    Task,
    TaskAgentInstance,
    TaskRun,
    TaskToolInvocation,
    TaskWorkItem,
)

logger = logging.getLogger(__name__)

_SAFE_EVENT_METADATA_KEYS = frozenset({
    "tool_call_id", "channel", "input_field_names", "query_sha256", "strategy",
    "bm25_k1", "bm25_b", "tokenizer_version",
    "candidate_count", "candidate_limit", "candidate_truncated", "vector_candidate_count",
    "fusion", "result_count",
    "minimum_score", "top_k", "duration_ms", "vector_status", "reranker_status",
    "chunk_ids", "version_ids", "source_count", "context_token_budget", "estimated_tokens",
    "history_count", "compressed_history_count", "candidate_message_count",
    "unsearched_message_count", "omitted_message_count", "message_ids", "summary_message_ids",
    "summary_used", "summary_version", "summary_source_count", "memory_count", "memory_ids",
    "skill_keys", "skill_versions",
    "file_count", "model_config_id", "model_name", "model_revision", "request_count",
})


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """只保留白名单内的标量和有限长度 ID 列表。"""
    safe: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if key not in _SAFE_EVENT_METADATA_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value[:200] if isinstance(value, str) else value
        elif isinstance(value, list):
            safe[key] = [item[:200] if isinstance(item, str) else item
                         for item in value[:100]
                         if isinstance(item, (str, int, float, bool))]
    return safe


def _skill_identity(event_name: str) -> tuple[str, int | None]:
    """从受控 Skill 事件名读取稳定 Key 与 Revision。"""
    key, separator, version = event_name.rpartition("@")
    if not separator:
        return event_name, None
    try:
        return key, int(version)
    except ValueError:
        return event_name, None


def _task_run_status_metrics(statuses: dict[str, int]) -> dict[str, int | float | None]:
    """按运行质量口径计算已终态比例；核对中、排队和 superseded 不混入分母。"""
    success = int(statuses.get("SUCCEEDED", 0))
    partial = int(statuses.get("SUCCEEDED_WITH_ISSUES", 0))
    failed = int(statuses.get("FAILED", 0))
    cancelled = int(statuses.get("CANCELLED", 0))
    superseded = int(statuses.get("SUPERSEDED", 0))
    reconciliation = int(statuses.get("RECONCILIATION_REQUIRED", 0))
    terminal = success + partial + failed + cancelled
    execution_terminal = success + partial + failed
    total = sum(int(count) for count in statuses.values())
    nonterminal = max(0, total - terminal - superseded - reconciliation)
    return {
        "task_runs": total,
        "terminal_runs": terminal,
        "successful_runs": success,
        "partial_runs": partial,
        "failed_runs": failed,
        "cancelled_runs": cancelled,
        "reconciliation_required_runs": reconciliation,
        "superseded_runs": superseded,
        "nonterminal_runs": nonterminal,
        "success_rate": round(success / terminal, 4) if terminal else None,
        "partial_completion_rate": round(partial / terminal, 4) if terminal else None,
        "failure_rate": round(failed / terminal, 4) if terminal else None,
        "cancellation_rate": round(cancelled / terminal, 4) if terminal else None,
        "execution_success_rate": round(success / execution_terminal, 4) if execution_terminal else None,
    }


def _provider_health(db: Session, call_query) -> list[dict[str, Any]]:
    """按供应商汇总真实调用事实，不把未终态调用算进健康率。"""
    rows = call_query.outerjoin(
        ModelConfiguration, ModelConfiguration.id == RuntimeCallFact.model_config_id,
    ).with_entities(
        ModelConfiguration.provider,
        RuntimeCallFact.cost_currency,
        RuntimeCallFact.status,
        func.count(RuntimeCallFact.id),
        func.sum(RuntimeCallFact.total_tokens),
        func.sum(RuntimeCallFact.cost_amount),
    ).group_by(
        ModelConfiguration.provider,
        RuntimeCallFact.cost_currency,
        RuntimeCallFact.status,
    ).all()
    config_rows = db.query(
        ModelConfiguration.provider, ModelConfiguration.is_enabled, func.count(ModelConfiguration.id),
    ).group_by(ModelConfiguration.provider, ModelConfiguration.is_enabled).all()
    configs: dict[str, dict[str, int]] = {}
    for provider, enabled, count in config_rows:
        row = configs.setdefault(provider, {"enabled_configs": 0, "disabled_configs": 0})
        key = "enabled_configs" if enabled else "disabled_configs"
        row[key] += int(count)
    grouped: dict[str, dict[str, Any]] = {}
    for provider_name, currency, status, count, tokens, cost in rows:
        provider = provider_name or "UNKNOWN"
        row = grouped.setdefault(provider, {
            "provider": provider,
            "calls": 0, "succeeded": 0, "failed": 0, "unknown_calls": 0,
            "known_calls": 0, "tokens": 0, "success_rate": None, "status": "INSUFFICIENT_SAMPLE",
            "enabled_configs": configs.get(provider, {}).get("enabled_configs", 0),
            "disabled_configs": configs.get(provider, {}).get("disabled_configs", 0),
            "cost_by_currency": [],
            "_costs": {},
        })
        row["calls"] += int(count)
        row["tokens"] += int(tokens or 0)
        if status == "SUCCEEDED":
            row["succeeded"] += int(count)
            row["known_calls"] += int(count)
        elif status == "FAILED":
            row["failed"] += int(count)
            row["known_calls"] += int(count)
        else:
            row["unknown_calls"] += int(count)
        if cost is not None and currency:
            row["_costs"][currency] = row["_costs"].get(currency, 0.0) + float(cost)
    providers = []
    for row in grouped.values():
        known = row["known_calls"]
        row["success_rate"] = round(row["succeeded"] / known, 4) if known else None
        failure_rate = row["failed"] / known if known else None
        if row["enabled_configs"] == 0 and row["disabled_configs"] > 0:
            row["status"] = "DISABLED"
        elif known < 5 or failure_rate is None:
            row["status"] = "INSUFFICIENT_SAMPLE"
        elif failure_rate >= 0.5:
            row["status"] = "UNHEALTHY"
        elif failure_rate >= 0.2:
            row["status"] = "DEGRADED"
        else:
            row["status"] = "HEALTHY"
        row["cost_by_currency"] = [
            {"currency": currency, "amount": round(amount, 8)}
            for currency, amount in sorted(row.pop("_costs").items())
        ]
        providers.append(row)
    providers.sort(key=lambda item: (-item["calls"], item["provider"]))
    return providers


def _positive_token_average(query) -> tuple[int, float | None]:
    """只统计已记录的正 Token，避免用空用量冒充消耗。"""
    count, average = query.filter(RuntimeCallFact.total_tokens > 0).with_entities(
        func.count(RuntimeCallFact.id), func.avg(RuntimeCallFact.total_tokens),
    ).one()
    return int(count or 0), (float(average) if average is not None else None)


def model_revision_admitted(db: Session, model_config_id: int) -> bool:
    """有模型中心修订时，停用修订不再因为旧配置行仍启用而被调用。"""
    from app.platform.model_configuration.models import ModelLegacyBinding, ModelRevision

    binding = db.query(ModelLegacyBinding).filter(
        ModelLegacyBinding.legacy_kind == "MODEL_CONFIGURATION",
        ModelLegacyBinding.legacy_id == model_config_id,
    ).first()
    if binding is None:
        return True
    revision = db.get(ModelRevision, binding.revision_id)
    return revision is not None and bool(revision.enabled)


def assert_token_quota(db: Session, *, project_id: int, user_id: int | None) -> None:
    """按当日已落库 Token 拦截超额调用。未配置额度时不改变现有调用。"""
    from app.core.config import settings
    from app.llm.contracts import LLMError

    project_limit = int(settings.AGENT_PROJECT_DAILY_TOKEN_QUOTA)
    user_limit = int(settings.AGENT_USER_DAILY_TOKEN_QUOTA)
    if project_limit <= 0 and user_limit <= 0:
        return
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if project_limit > 0:
        used = db.query(func.coalesce(func.sum(RuntimeCallFact.total_tokens), 0)).filter(
            RuntimeCallFact.project_id == project_id,
            RuntimeCallFact.created_at >= start,
        ).scalar()
        if int(used or 0) >= project_limit:
            raise LLMError("TOKEN_QUOTA_EXCEEDED", "项目当日模型 Token 额度已用完", retryable=False)
    if user_limit > 0 and user_id is not None:
        used = db.query(func.coalesce(func.sum(RuntimeCallFact.total_tokens), 0)).join(
            Task, Task.id == RuntimeCallFact.task_id,
        ).filter(
            Task.created_by == user_id,
            RuntimeCallFact.created_at >= start,
        ).scalar()
        if int(used or 0) >= user_limit:
            raise LLMError("TOKEN_QUOTA_EXCEEDED", "当前用户当日模型 Token 额度已用完", retryable=False)


def _model_success_rate(succeeded: int, failed: int) -> float | None:
    """UNKNOWN 等非终态调用不进入模型成功率分母。"""
    known_calls = succeeded + failed
    return round(succeeded / known_calls, 4) if known_calls else None


def _execution_root_filter():
    """只统计自指协调根或未建立根关系的历史 Run，避免 Fan-out 子 Run 重复计任务。"""
    return or_(TaskRun.execution_root_run_id == TaskRun.id, TaskRun.execution_root_run_id.is_(None))


def _task_run_window_filter(start: datetime, end: datetime):
    """终态按完成时间分桶；仍在等待/执行/核对的根按创建时间分桶。"""
    terminal_statuses = ("SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED", "SUPERSEDED")
    finished_at = func.coalesce(TaskRun.finished_at, TaskRun.created_at)
    return or_(
        and_(TaskRun.status.in_(terminal_statuses), finished_at >= start, finished_at < end),
        and_(TaskRun.status.notin_(terminal_statuses), TaskRun.created_at >= start, TaskRun.created_at < end),
    )


def _manual_feedback(db: Session, project_id: int | None, start: datetime, end: datetime) -> dict[str, Any]:
    """读取已有用例草稿审核结果，只统计可追溯的接受、拒绝和编辑。"""
    reviewed = db.query(CaseDraft).join(
        CaseGenerationBatch, CaseGenerationBatch.id == CaseDraft.batch_id,
    ).filter(
        CaseDraft.reviewed_at >= start, CaseDraft.reviewed_at < end,
        CaseDraft.status.in_(("ACCEPTED", "REJECTED")),
    )
    if project_id is not None:
        reviewed = reviewed.filter(CaseGenerationBatch.project_id == project_id)
    states = {status: int(count) for status, count in reviewed.with_entities(
        CaseDraft.status, func.count(CaseDraft.id),
    ).group_by(CaseDraft.status).all()}
    reviewed_count = sum(states.values())
    edited = db.query(func.count(func.distinct(CaseGenerationAudit.draft_id))).join(
        CaseDraft, CaseDraft.id == CaseGenerationAudit.draft_id,
    ).join(CaseGenerationBatch, CaseGenerationBatch.id == CaseDraft.batch_id).filter(
        CaseGenerationAudit.action == "EDIT",
        CaseGenerationAudit.created_at >= start, CaseGenerationAudit.created_at < end,
        CaseDraft.reviewed_at >= start, CaseDraft.reviewed_at < end,
        CaseDraft.status.in_(("ACCEPTED", "REJECTED")),
    )
    if project_id is not None:
        edited = edited.filter(CaseGenerationBatch.project_id == project_id)
    edited_count = int(edited.scalar() or 0)
    rejected = states.get("REJECTED", 0)
    accepted = states.get("ACCEPTED", 0)
    return {
        "reviewed_drafts": reviewed_count,
        "accepted_drafts": accepted,
        "rejected_drafts": rejected,
        "edited_reviewed_drafts": edited_count,
        "rejection_rate": round(rejected / reviewed_count, 4) if reviewed_count else None,
        "edit_rate": round(edited_count / reviewed_count, 4) if reviewed_count else None,
    }


def record_runtime_event(
    *,
    db: Session | None = None,
    project_id: int,
    event_id: str | None = None,
    event_type: str,
    event_name: str,
    status: str,
    duration_ms: int,
    task_id: int | None = None,
    task_run_id: int | None = None,
    execution_root_run_id: int | None = None,
    work_item_id: int | None = None,
    attempt_id: int | None = None,
    agent_session_id: int | None = None,
    agent_instance_id: int | None = None,
    agent_definition_id: int | None = None,
    agent_definition_revision_id: int | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    error_code: str | None = None,
    event_metadata: dict[str, Any] | None = None,
) -> None:
    """记录无正文事实；有调用方 Session 时随该事务原子提交，避免 FK 锁自阻塞。"""
    if not project_id or event_type not in {
        "AGENT_RUN", "TOOL_CALL", "KNOWLEDGE_RETRIEVAL", "CONTEXT_ASSEMBLY", "SKILL_LOAD",
    }:
        return
    owns_session = db is None
    session = SessionLocal() if owns_session else db
    savepoint = None
    try:
        if not owns_session:
            # SAVEPOINT 隔离唯一约束等事实写入错误，不回滚调用方的业务事务。
            savepoint = session.begin_nested()
        normalized_event_id = (event_id or uuid4().hex)[:64]
        if event_id and session.query(RuntimeEventFact.id).filter(
            RuntimeEventFact.event_id == normalized_event_id,
        ).first():
            if savepoint is not None:
                savepoint.commit()
            return
        session.add(RuntimeEventFact(
            event_id=normalized_event_id,
            project_id=project_id,
            task_id=task_id,
            task_run_id=task_run_id,
            execution_root_run_id=execution_root_run_id,
            work_item_id=work_item_id,
            attempt_id=attempt_id,
            agent_session_id=agent_session_id,
            agent_instance_id=agent_instance_id,
            agent_definition_id=agent_definition_id,
            agent_definition_revision_id=agent_definition_revision_id,
            trace_id=trace_id,
            span_id=span_id,
            event_type=event_type,
            event_name=event_name[:160],
            status=status[:24],
            error_code=error_code[:80] if error_code else None,
            duration_ms=max(0, int(duration_ms)),
            event_metadata=_safe_metadata(event_metadata),
            occurred_at=datetime.now(),
        ))
        session.flush()
        from app.orchestration.tasks.services.trace_projection_service import enqueue_projection
        enqueue_projection(
            session, source_type="RUNTIME_EVENT", source_key=normalized_event_id,
            project_id=project_id, task_id=task_id or 0, task_run_id=task_run_id or 0,
            execution_root_run_id=execution_root_run_id or task_run_id or 0,
            trace_id=trace_id, span_id=span_id,
        )
        if owns_session:
            session.commit()
        elif savepoint is not None:
            savepoint.commit()
    except Exception as exc:  # noqa: BLE001 —— 指标写入不可改变业务结果
        if owns_session:
            session.rollback()
        elif savepoint is not None and savepoint.is_active:
            savepoint.rollback()
        logger.warning("运行事实写入失败（忽略）：%s", type(exc).__name__)
    finally:
        if owns_session:
            session.close()


def runtime_overview(
    db: Session,
    *,
    project_id: int | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
) -> dict[str, Any]:
    """按来源口径汇总任务、模型、工具与 Agent 修订运行数据。"""
    end = to_at or datetime.now()
    start = from_at or end - timedelta(days=30)
    if start.tzinfo is not None:
        start = start.astimezone().replace(tzinfo=None)
    if end.tzinfo is not None:
        end = end.astimezone().replace(tzinfo=None)
    if start >= end:
        raise bad_request("开始时间必须早于结束时间")
    if end - start > timedelta(days=90):
        raise bad_request("单次运行指标查询最多支持 90 天")
    if project_id is not None and db.get(Project, project_id) is None:
        raise not_found("项目不存在")

    run_query = db.query(TaskRun).join(Task, Task.id == TaskRun.task_id).filter(
        _task_run_window_filter(start, end),
        _execution_root_filter(),
    )
    call_query = db.query(RuntimeCallFact).filter(
        RuntimeCallFact.created_at >= start, RuntimeCallFact.created_at < end,
    )
    event_query = db.query(RuntimeEventFact).filter(
        RuntimeEventFact.occurred_at >= start, RuntimeEventFact.occurred_at < end,
    )
    work_query = db.query(TaskWorkItem).join(TaskRun, TaskRun.id == TaskWorkItem.task_run_id).join(
        Task, Task.id == TaskRun.task_id,
    ).filter(TaskRun.created_at >= start, TaskRun.created_at < end)
    tool_query = db.query(TaskToolInvocation).join(TaskRun, TaskRun.id == TaskToolInvocation.task_run_id).join(
        Task, Task.id == TaskRun.task_id,
    ).filter(TaskRun.created_at >= start, TaskRun.created_at < end)
    if project_id is not None:
        run_query = run_query.filter(Task.project_id == project_id)
        call_query = call_query.filter(RuntimeCallFact.project_id == project_id)
        event_query = event_query.filter(RuntimeEventFact.project_id == project_id)
        work_query = work_query.filter(Task.project_id == project_id)
        tool_query = tool_query.filter(Task.project_id == project_id)

    run_statuses = {status: int(count) for status, count in run_query.with_entities(
        TaskRun.status, func.count(TaskRun.id),
    ).group_by(TaskRun.status).all()}
    task_metrics = _task_run_status_metrics(run_statuses)
    failed = int(task_metrics["failed_runs"])
    terminal_quality = int(task_metrics["terminal_runs"])

    elapsed_ms = func.extract("epoch", TaskRun.finished_at - TaskRun.started_at) * 1000
    duration_stats = run_query.filter(
        TaskRun.started_at.isnot(None), TaskRun.finished_at.isnot(None),
        TaskRun.finished_at >= TaskRun.started_at,
        TaskRun.status.in_(("SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED")),
    ).with_entities(
        func.count(TaskRun.id), func.avg(elapsed_ms),
        func.percentile_cont(0.95).within_group(elapsed_ms),
    ).first()

    call_statuses = {status: int(count) for status, count in call_query.with_entities(
        RuntimeCallFact.status, func.count(RuntimeCallFact.id),
    ).group_by(RuntimeCallFact.status).all()}
    model_total = sum(call_statuses.values())
    model_latency_sample = call_query.filter(RuntimeCallFact.duration_ms > 0).with_entities(
        func.count(RuntimeCallFact.id), func.avg(RuntimeCallFact.duration_ms),
        func.percentile_cont(0.50).within_group(RuntimeCallFact.duration_ms),
        func.percentile_cont(0.95).within_group(RuntimeCallFact.duration_ms),
    ).first() or (0, None, None, None)
    usage_known_count = int(call_query.filter(RuntimeCallFact.usage_status == "KNOWN").count())
    token_total = call_query.with_entities(func.sum(RuntimeCallFact.total_tokens)).scalar()
    cost_rows = call_query.filter(and_(
        RuntimeCallFact.cost_amount.isnot(None), RuntimeCallFact.cost_currency.isnot(None),
    )).with_entities(
        RuntimeCallFact.cost_currency, func.sum(RuntimeCallFact.cost_amount),
        func.count(RuntimeCallFact.id),
    ).group_by(RuntimeCallFact.cost_currency).all()
    cost_by_currency = [
        {"currency": currency, "amount": float(amount), "calls": int(count)}
        for currency, amount, count in cost_rows
    ]
    cost_total = cost_by_currency[0]["amount"] if len(cost_by_currency) == 1 else None
    cost_currency = cost_by_currency[0]["currency"] if len(cost_by_currency) == 1 else None
    priced_calls = int(call_query.filter(and_(
        RuntimeCallFact.cost_amount.isnot(None), RuntimeCallFact.cost_currency.isnot(None),
    )).count())

    work_count = int(work_query.count())
    started_work_count = int(work_query.filter(TaskWorkItem.attempt_count > 0).count())
    retried_count = int(work_query.filter(TaskWorkItem.attempt_count > 1).count())
    subagent_work = work_query.join(TaskAgentInstance, TaskAgentInstance.id == TaskWorkItem.agent_instance_id).filter(
        TaskAgentInstance.role == "SUB_AGENT",
    )
    subagent_work_terminal = int(subagent_work.filter(TaskWorkItem.status.in_(
        ("SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED"),
    )).count())
    subagent_work_failed = int(subagent_work.filter(TaskWorkItem.status == "FAILED").count())
    subagent_work_reconciliation = int(subagent_work.filter(TaskWorkItem.status == "RECONCILIATION_REQUIRED").count())
    subagent_instance_query = db.query(TaskAgentInstance).join(
        TaskRun, TaskRun.id == TaskAgentInstance.task_run_id,
    ).join(Task, Task.id == TaskRun.task_id).filter(
        TaskAgentInstance.role == "SUB_AGENT",
        TaskRun.created_at >= start, TaskRun.created_at < end,
    )
    if project_id is not None:
        subagent_instance_query = subagent_instance_query.filter(Task.project_id == project_id)
    subagent_instance_statuses = {status: int(count) for status, count in subagent_instance_query.with_entities(
        TaskAgentInstance.status, func.count(TaskAgentInstance.id),
    ).group_by(TaskAgentInstance.status).all()}
    subagent_instance_terminal = sum(subagent_instance_statuses.get(status, 0) for status in (
        "SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED",
    ))
    subagent_instance_failed = subagent_instance_statuses.get("FAILED", 0)
    subagent_event_query = event_query.filter(RuntimeEventFact.event_type == "AGENT_RUN")
    subagent_event_statuses = {status: int(count) for status, count in subagent_event_query.with_entities(
        RuntimeEventFact.status, func.count(RuntimeEventFact.id),
    ).group_by(RuntimeEventFact.status).all()}
    subagent_event_terminal = subagent_event_statuses.get("SUCCEEDED", 0) + subagent_event_statuses.get("FAILED", 0)
    subagent_event_failed = subagent_event_statuses.get("FAILED", 0)

    tool_statuses = {status: int(count) for status, count in tool_query.with_entities(
        TaskToolInvocation.status, func.count(TaskToolInvocation.id),
    ).group_by(TaskToolInvocation.status).all()}
    durable_tool_total = sum(tool_statuses.values())
    durable_tool_terminal = tool_statuses.get("SUCCEEDED", 0) + tool_statuses.get("FAILED", 0)
    tool_event_query = event_query.filter(RuntimeEventFact.event_type == "TOOL_CALL")
    tool_event_count = int(tool_event_query.count())
    tool_event_statuses = {status: int(count) for status, count in tool_event_query.with_entities(
        RuntimeEventFact.status, func.count(RuntimeEventFact.id),
    ).group_by(RuntimeEventFact.status).all()}
    tool_event_terminal = tool_event_statuses.get("SUCCEEDED", 0) + tool_event_statuses.get("FAILED", 0)
    retrieval_count = int(event_query.filter(RuntimeEventFact.event_type == "KNOWLEDGE_RETRIEVAL").count())
    context_count = int(event_query.filter(RuntimeEventFact.event_type == "CONTEXT_ASSEMBLY").count())
    skill_event_query = event_query.filter(RuntimeEventFact.event_type == "SKILL_LOAD")
    skill_status_rows = skill_event_query.with_entities(
        RuntimeEventFact.event_name, RuntimeEventFact.status,
        func.count(RuntimeEventFact.id), func.avg(RuntimeEventFact.duration_ms),
    ).group_by(RuntimeEventFact.event_name, RuntimeEventFact.status).all()
    skill_events: dict[str, dict[str, Any]] = {}
    for name, status, count, average_ms in skill_status_rows:
        skill_key, skill_version = _skill_identity(name)
        row = skill_events.setdefault(name, {
            "skill_key": skill_key, "skill_version": skill_version, "_event_key": name,
            "loads": 0, "succeeded": 0, "failed": 0, "_latency_sum": 0.0,
        })
        row["loads"] += int(count)
        row["succeeded"] += int(count) if status == "SUCCEEDED" else 0
        row["failed"] += int(count) if status == "FAILED" else 0
        row["_latency_sum"] += float(average_ms or 0) * int(count)
    skills = []
    for row in skill_events.values():
        row["avg_latency_ms"] = round(row.pop("_latency_sum") / row["loads"], 2) if row["loads"] else None
        skills.append(row)
    skills.sort(key=lambda row: (-row["loads"], row["skill_key"]))

    model_rows = call_query.with_entities(
        RuntimeCallFact.model_config_id, RuntimeCallFact.model_name, RuntimeCallFact.model_revision,
        RuntimeCallFact.cost_currency,
        RuntimeCallFact.status, func.count(RuntimeCallFact.id), func.sum(RuntimeCallFact.total_tokens),
        func.sum(RuntimeCallFact.cost_amount),
    ).group_by(
        RuntimeCallFact.model_config_id, RuntimeCallFact.model_name, RuntimeCallFact.model_revision,
        RuntimeCallFact.cost_currency, RuntimeCallFact.status,
    ).all()
    models: dict[tuple[Any, ...], dict[str, Any]] = {}
    for model_id, name, revision, currency, status, count, tokens, cost in model_rows:
        key = (model_id, name, revision, currency)
        row = models.setdefault(key, {
            "model_config_id": model_id, "model_name": name, "model_revision": revision,
            "cost_currency": currency,
            "calls": 0, "succeeded": 0, "failed": 0, "known_calls": 0,
            "unknown_calls": 0, "success_rate": None, "tokens": 0, "cost": None,
            "latency_sample_count": 0, "avg_latency_ms": None,
            "p50_latency_ms": None, "p95_latency_ms": None,
            "_cost_known": False,
        })
        row["calls"] += int(count)
        row["succeeded"] += int(count) if status == "SUCCEEDED" else 0
        row["failed"] += int(count) if status == "FAILED" else 0
        row["known_calls"] += int(count) if status in {"SUCCEEDED", "FAILED"} else 0
        row["tokens"] += int(tokens or 0)
        if cost is not None and currency is not None:
            row["cost"] = float(row["cost"] or 0) + float(cost)
            row["_cost_known"] = True
    latency_by_model = {}
    for model_id, name, revision, sample_count, average_ms, p50_ms, p95_ms in call_query.filter(
        RuntimeCallFact.duration_ms > 0,
    ).with_entities(
        RuntimeCallFact.model_config_id, RuntimeCallFact.model_name, RuntimeCallFact.model_revision,
        func.count(RuntimeCallFact.id), func.avg(RuntimeCallFact.duration_ms),
        func.percentile_cont(0.50).within_group(RuntimeCallFact.duration_ms),
        func.percentile_cont(0.95).within_group(RuntimeCallFact.duration_ms),
    ).group_by(
        RuntimeCallFact.model_config_id, RuntimeCallFact.model_name, RuntimeCallFact.model_revision,
    ).all():
        latency_by_model[(model_id, name, revision)] = {
            "latency_sample_count": int(sample_count),
            "avg_latency_ms": round(float(average_ms), 2) if average_ms is not None else None,
            "p50_latency_ms": round(float(p50_ms), 2) if p50_ms is not None else None,
            "p95_latency_ms": round(float(p95_ms), 2) if p95_ms is not None else None,
        }
    model_breakdown = []
    for row in models.values():
        row["unknown_calls"] = row["calls"] - row["known_calls"]
        row["success_rate"] = _model_success_rate(row["succeeded"], row["failed"])
        row.update(latency_by_model.get(
            (row["model_config_id"], row["model_name"], row["model_revision"]),
            {"latency_sample_count": 0, "avg_latency_ms": None,
             "p50_latency_ms": None, "p95_latency_ms": None},
        ))
        row.pop("_cost_known")
        model_breakdown.append(row)
    model_breakdown.sort(key=lambda row: (-row["calls"], row["model_name"]))

    agent_rows = call_query.with_entities(
        RuntimeCallFact.agent_definition_id, RuntimeCallFact.agent_definition_revision_id,
        RuntimeCallFact.cost_currency,
        RuntimeCallFact.status, func.count(RuntimeCallFact.id), func.sum(RuntimeCallFact.total_tokens),
        func.sum(RuntimeCallFact.cost_amount), func.avg(RuntimeCallFact.duration_ms),
    ).group_by(
        RuntimeCallFact.agent_definition_id, RuntimeCallFact.agent_definition_revision_id,
        RuntimeCallFact.cost_currency, RuntimeCallFact.status,
    ).all()
    agent_ids = {agent_id for agent_id, *_ in agent_rows if agent_id is not None}
    agent_names = {row.id: row.name for row in db.query(AgentDefinition.id, AgentDefinition.name).filter(
        AgentDefinition.id.in_(agent_ids),
    ).all()} if agent_ids else {}
    agents: dict[tuple[Any, Any], dict[str, Any]] = {}
    for agent_id, revision_id, currency, status, count, tokens, cost, avg_ms in agent_rows:
        key = (agent_id, revision_id, currency)
        row = agents.setdefault(key, {
            "agent_definition_id": agent_id, "agent_name": agent_names.get(agent_id, "已删除 Agent"),
            "revision_id": revision_id, "cost_currency": currency, "calls": 0, "succeeded": 0, "failed": 0,
            "tokens": 0, "cost": None, "_latency_sum": 0.0,
        })
        row["calls"] += int(count)
        row["succeeded"] += int(count) if status == "SUCCEEDED" else 0
        row["failed"] += int(count) if status == "FAILED" else 0
        row["tokens"] += int(tokens or 0)
        row["_latency_sum"] += float(avg_ms or 0) * int(count)
        if cost is not None and currency is not None:
            row["cost"] = float(row["cost"] or 0) + float(cost)
    agent_breakdown = []
    for row in agents.values():
        row["avg_latency_ms"] = round(row.pop("_latency_sum") / row["calls"], 2) if row["calls"] else None
        agent_breakdown.append(row)
    agent_breakdown.sort(key=lambda row: (-row["calls"], row["agent_name"]))

    event_rows = tool_event_query.with_entities(
        RuntimeEventFact.event_name, RuntimeEventFact.status,
        func.count(RuntimeEventFact.id), func.avg(RuntimeEventFact.duration_ms),
    ).group_by(RuntimeEventFact.event_name, RuntimeEventFact.status).all()
    tool_events: dict[str, dict[str, Any]] = {}
    for name, status, count, average_ms in event_rows:
        row = tool_events.setdefault(name, {"tool_key": name, "calls": 0, "succeeded": 0, "failed": 0, "_latency_sum": 0.0})
        row["calls"] += int(count)
        row["succeeded"] += int(count) if status == "SUCCEEDED" else 0
        row["failed"] += int(count) if status == "FAILED" else 0
        row["_latency_sum"] += float(average_ms or 0) * int(count)
    tool_breakdown = []
    for row in tool_events.values():
        row["avg_latency_ms"] = round(row.pop("_latency_sum") / row["calls"], 2) if row["calls"] else None
        tool_breakdown.append(row)
    tool_breakdown.sort(key=lambda row: (-row["calls"], row["tool_key"]))

    previous_start = start - (end - start)
    previous_run_query = db.query(TaskRun).join(Task, Task.id == TaskRun.task_id).filter(
        _task_run_window_filter(previous_start, start),
        _execution_root_filter(),
    )
    previous_call_query = db.query(RuntimeCallFact).filter(
        RuntimeCallFact.created_at >= previous_start, RuntimeCallFact.created_at < start,
    )
    previous_event_query = db.query(RuntimeEventFact).filter(
        RuntimeEventFact.occurred_at >= previous_start, RuntimeEventFact.occurred_at < start,
        RuntimeEventFact.event_type == "TOOL_CALL",
    )
    previous_skill_query = db.query(RuntimeEventFact).filter(
        RuntimeEventFact.occurred_at >= previous_start, RuntimeEventFact.occurred_at < start,
        RuntimeEventFact.event_type == "SKILL_LOAD",
    )
    if project_id is not None:
        previous_run_query = previous_run_query.filter(Task.project_id == project_id)
        previous_call_query = previous_call_query.filter(RuntimeCallFact.project_id == project_id)
        previous_event_query = previous_event_query.filter(RuntimeEventFact.project_id == project_id)
        previous_skill_query = previous_skill_query.filter(RuntimeEventFact.project_id == project_id)
    feedback = _manual_feedback(db, project_id, start, end)
    previous_feedback = _manual_feedback(db, project_id, previous_start, start)
    previous_run_statuses = {status: int(count) for status, count in previous_run_query.with_entities(
        TaskRun.status, func.count(TaskRun.id),
    ).group_by(TaskRun.status).all()}
    previous_task_metrics = _task_run_status_metrics(previous_run_statuses)
    previous_terminal = int(previous_task_metrics["terminal_runs"])
    previous_failed = int(previous_task_metrics["failed_runs"])
    anomalies: list[dict[str, Any]] = []
    if terminal_quality >= 5 and previous_terminal >= 5:
        current_rate = failed / terminal_quality
        previous_rate = previous_failed / previous_terminal
        if current_rate - previous_rate >= 0.15:
            anomalies.append({
                "kind": "TASK_FAILURE_RATE_INCREASE", "severity": "WARNING",
                "current": round(current_rate, 4), "baseline": round(previous_rate, 4),
                "current_samples": terminal_quality, "baseline_samples": previous_terminal,
            })
    for metric, kind in (("rejection_rate", "MANUAL_REJECTION_RATE_INCREASE"), ("edit_rate", "MANUAL_EDIT_RATE_INCREASE")):
        current_rate = feedback[metric]
        baseline_rate = previous_feedback[metric]
        if (current_rate is not None and baseline_rate is not None
                and feedback["reviewed_drafts"] >= 5 and previous_feedback["reviewed_drafts"] >= 5
                and current_rate - baseline_rate >= 0.15):
            anomalies.append({
                "kind": kind, "severity": "INFO",
                "current": current_rate, "baseline": baseline_rate,
                "current_samples": feedback["reviewed_drafts"],
                "baseline_samples": previous_feedback["reviewed_drafts"],
            })

    previous_model_rows = previous_call_query.with_entities(
        RuntimeCallFact.model_name, RuntimeCallFact.model_revision, RuntimeCallFact.status,
        func.count(RuntimeCallFact.id), func.count(func.nullif(RuntimeCallFact.duration_ms, 0)),
        func.avg(func.nullif(RuntimeCallFact.duration_ms, 0)),
    ).group_by(RuntimeCallFact.model_name, RuntimeCallFact.model_revision, RuntimeCallFact.status).all()
    previous_models: dict[tuple[str, str | None], dict[str, float]] = {}
    for name, revision, status, count, duration_count, average_ms in previous_model_rows:
        key = (name, revision)
        row = previous_models.setdefault(key, {
            "calls": 0, "known_calls": 0, "failed": 0, "latency_sum": 0.0, "duration_count": 0,
        })
        row["calls"] += int(count)
        row["failed"] += int(count) if status == "FAILED" else 0
        row["known_calls"] += int(count) if status in {"SUCCEEDED", "FAILED"} else 0
        row["latency_sum"] += float(average_ms or 0) * int(duration_count)
        row["duration_count"] += int(duration_count)
    current_models: dict[tuple[str, str | None], dict[str, float]] = {}
    for name, revision, status, count, duration_count, average_ms in call_query.with_entities(
        RuntimeCallFact.model_name, RuntimeCallFact.model_revision, RuntimeCallFact.status,
        func.count(RuntimeCallFact.id), func.count(func.nullif(RuntimeCallFact.duration_ms, 0)),
        func.avg(func.nullif(RuntimeCallFact.duration_ms, 0)),
    ).group_by(RuntimeCallFact.model_name, RuntimeCallFact.model_revision, RuntimeCallFact.status).all():
        key = (name, revision)
        row = current_models.setdefault(key, {
            "calls": 0, "known_calls": 0, "failed": 0, "latency_sum": 0.0, "duration_count": 0,
        })
        row["calls"] += int(count)
        row["failed"] += int(count) if status == "FAILED" else 0
        row["known_calls"] += int(count) if status in {"SUCCEEDED", "FAILED"} else 0
        row["latency_sum"] += float(average_ms or 0) * int(duration_count)
        row["duration_count"] += int(duration_count)
    for key, current in current_models.items():
        baseline = previous_models.get(key)
        if not baseline:
            continue
        current_latency = current["latency_sum"] / current["duration_count"] if current["duration_count"] else None
        baseline_latency = baseline["latency_sum"] / baseline["duration_count"] if baseline["duration_count"] else None
        if (current_latency is not None and baseline_latency is not None
                and current["duration_count"] >= 5 and baseline["duration_count"] >= 5
                and current_latency >= max(baseline_latency * 2, baseline_latency + 1000)):
            anomalies.append({
                "kind": "MODEL_LATENCY_INCREASE", "severity": "WARNING",
                "model_name": key[0], "model_revision": key[1],
                "current": round(current_latency, 2), "baseline": round(baseline_latency, 2),
                "current_samples": int(current["calls"]), "baseline_samples": int(baseline["calls"]),
            })
        current_failure_rate = current["failed"] / current["known_calls"] if current["known_calls"] else None
        baseline_failure_rate = baseline["failed"] / baseline["known_calls"] if baseline["known_calls"] else None
        if (current_failure_rate is not None and baseline_failure_rate is not None
                and current["known_calls"] >= 5 and baseline["known_calls"] >= 5
                and current_failure_rate - baseline_failure_rate >= 0.15):
            anomalies.append({
                "kind": "MODEL_FAILURE_RATE_INCREASE", "severity": "WARNING",
                "model_name": key[0], "model_revision": key[1],
                "current": round(current_failure_rate, 4), "baseline": round(baseline_failure_rate, 4),
                "current_samples": int(current["calls"]), "baseline_samples": int(baseline["calls"]),
            })
    current_token_samples, current_token_average = _positive_token_average(call_query)
    previous_token_samples, previous_token_average = _positive_token_average(previous_call_query)
    if (current_token_average is not None and previous_token_average is not None
            and current_token_samples >= 5 and previous_token_samples >= 5
            and previous_token_average > 0
            and current_token_average >= previous_token_average * 2):
        anomalies.append({
            "kind": "TOKEN_USAGE_INCREASE", "severity": "WARNING",
            "current": round(current_token_average, 2),
            "baseline": round(previous_token_average, 2),
            "current_samples": current_token_samples,
            "baseline_samples": previous_token_samples,
        })

    def agent_failure_rates(query: Any) -> dict[tuple[int, int | None], dict[str, int]]:
        rows = query.with_entities(
            RuntimeCallFact.agent_definition_id, RuntimeCallFact.agent_definition_revision_id,
            RuntimeCallFact.status, func.count(RuntimeCallFact.id),
        ).filter(RuntimeCallFact.agent_definition_id.isnot(None)).group_by(
            RuntimeCallFact.agent_definition_id, RuntimeCallFact.agent_definition_revision_id,
            RuntimeCallFact.status,
        ).all()
        result: dict[tuple[int, int | None], dict[str, int]] = {}
        for agent_id, revision_id, status, count in rows:
            row = result.setdefault((agent_id, revision_id), {"known": 0, "failed": 0})
            if status in {"SUCCEEDED", "FAILED"}:
                row["known"] += int(count)
                row["failed"] += int(count) if status == "FAILED" else 0
        return result

    previous_agent_failures = agent_failure_rates(previous_call_query)
    current_agent_failures = agent_failure_rates(call_query)
    for key, current in current_agent_failures.items():
        baseline = previous_agent_failures.get(key)
        if not baseline or current["known"] < 5 or baseline["known"] < 5:
            continue
        current_rate = current["failed"] / current["known"]
        baseline_rate = baseline["failed"] / baseline["known"]
        if current_rate - baseline_rate >= 0.15:
            anomalies.append({
                "kind": "AGENT_REVISION_FAILURE_RATE_INCREASE", "severity": "WARNING",
                "agent_definition_id": key[0], "agent_name": agent_names.get(key[0], "已删除 Agent"),
                "revision_id": key[1], "current": round(current_rate, 4),
                "baseline": round(baseline_rate, 4),
                "current_samples": current["known"], "baseline_samples": baseline["known"],
            })

    previous_agent_rows = previous_call_query.filter(and_(
        RuntimeCallFact.cost_amount.isnot(None), RuntimeCallFact.cost_currency.isnot(None),
    )).with_entities(
        RuntimeCallFact.agent_definition_id, RuntimeCallFact.agent_definition_revision_id,
        RuntimeCallFact.cost_currency, func.count(RuntimeCallFact.id),
        func.sum(RuntimeCallFact.cost_amount),
    ).group_by(
        RuntimeCallFact.agent_definition_id, RuntimeCallFact.agent_definition_revision_id,
        RuntimeCallFact.cost_currency,
    ).all()
    previous_agents = {
        (agent_id, revision_id, currency): {"calls": int(count), "cost": float(cost) if cost is not None else None}
        for agent_id, revision_id, currency, count, cost in previous_agent_rows
    }
    current_agent_rows = call_query.filter(and_(
        RuntimeCallFact.cost_amount.isnot(None), RuntimeCallFact.cost_currency.isnot(None),
    )).with_entities(
        RuntimeCallFact.agent_definition_id, RuntimeCallFact.agent_definition_revision_id,
        RuntimeCallFact.cost_currency, func.count(RuntimeCallFact.id),
        func.sum(RuntimeCallFact.cost_amount),
    ).group_by(
        RuntimeCallFact.agent_definition_id, RuntimeCallFact.agent_definition_revision_id,
        RuntimeCallFact.cost_currency,
    ).all()
    for agent_id, revision_id, currency, count, current_cost in current_agent_rows:
        baseline = previous_agents.get((agent_id, revision_id, currency))
        if (agent_id is None or not baseline or int(count) < 5 or baseline["calls"] < 5
                or current_cost is None or baseline["cost"] is None):
            continue
        current_per_call = float(current_cost) / int(count)
        baseline_per_call = baseline["cost"] / baseline["calls"]
        if baseline_per_call > 0 and current_per_call >= baseline_per_call * 2:
            anomalies.append({
                "kind": "AGENT_REVISION_COST_INCREASE", "severity": "WARNING",
                "agent_definition_id": agent_id, "agent_name": agent_names.get(agent_id, "已删除 Agent"),
                "revision_id": revision_id, "currency": currency,
                "current": round(current_per_call, 8), "baseline": round(baseline_per_call, 8),
                "current_samples": int(count), "baseline_samples": baseline["calls"],
            })

    previous_tool_rows = previous_event_query.with_entities(
        RuntimeEventFact.event_name, RuntimeEventFact.status, func.count(RuntimeEventFact.id),
    ).group_by(RuntimeEventFact.event_name, RuntimeEventFact.status).all()
    previous_tools: dict[str, dict[str, int]] = {}
    for name, status, count in previous_tool_rows:
        row = previous_tools.setdefault(name, {"calls": 0, "failed": 0})
        row["calls"] += int(count)
        row["failed"] += int(count) if status == "FAILED" else 0
    for tool in tool_breakdown:
        baseline = previous_tools.get(tool["tool_key"])
        if not baseline or tool["calls"] < 5 or baseline["calls"] < 5:
            continue
        current_failure_rate = tool["failed"] / tool["calls"]
        baseline_failure_rate = baseline["failed"] / baseline["calls"]
        if current_failure_rate - baseline_failure_rate >= 0.15:
            anomalies.append({
                "kind": "TOOL_FAILURE_RATE_INCREASE", "severity": "WARNING",
                "tool_key": tool["tool_key"], "current": round(current_failure_rate, 4),
                "baseline": round(baseline_failure_rate, 4),
                "current_samples": tool["calls"], "baseline_samples": baseline["calls"],
            })

    previous_skill_rows = previous_skill_query.with_entities(
        RuntimeEventFact.event_name, RuntimeEventFact.status, func.count(RuntimeEventFact.id),
    ).group_by(RuntimeEventFact.event_name, RuntimeEventFact.status).all()
    previous_skills: dict[str, dict[str, int]] = {}
    for name, status, count in previous_skill_rows:
        row = previous_skills.setdefault(name, {"loads": 0, "failed": 0})
        row["loads"] += int(count)
        row["failed"] += int(count) if status == "FAILED" else 0
    for skill in skills:
        baseline = previous_skills.get(skill["_event_key"])
        if not baseline or skill["loads"] < 5 or baseline["loads"] < 5:
            continue
        current_failure_rate = skill["failed"] / skill["loads"]
        baseline_failure_rate = baseline["failed"] / baseline["loads"]
        if current_failure_rate - baseline_failure_rate >= 0.15:
            anomalies.append({
                "kind": "SKILL_LOAD_FAILURE_RATE_INCREASE", "severity": "WARNING",
                "skill_key": skill["skill_key"], "skill_version": skill["skill_version"],
                "current": round(current_failure_rate, 4),
                "baseline": round(baseline_failure_rate, 4),
                "current_samples": skill["loads"], "baseline_samples": baseline["loads"],
            })
    for skill in skills:
        skill.pop("_event_key")

    duration_count, average_duration, p95_duration = duration_stats or (0, None, None)
    data_watermark = {
        "task_runs": run_query.with_entities(func.max(TaskRun.updated_at)).scalar(),
        "model_calls": call_query.with_entities(func.max(RuntimeCallFact.created_at)).scalar(),
        "runtime_events": event_query.with_entities(func.max(RuntimeEventFact.occurred_at)).scalar(),
    }
    return {
        "metric_definition_version": "agent-runtime-v2",
        "window": {"from": start, "to": end, "project_id": project_id},
        "data_watermark": data_watermark,
        "summary": {
            **task_metrics,
            "average_duration_ms": round(float(average_duration), 2) if average_duration is not None else None,
            "p95_duration_ms": round(float(p95_duration), 2) if p95_duration is not None else None,
            "duration_sample_count": int(duration_count or 0),
            "average_model_latency_ms": round(float(model_latency_sample[1]), 2) if model_latency_sample[1] is not None else None,
            "p50_model_latency_ms": round(float(model_latency_sample[2]), 2) if model_latency_sample[2] is not None else None,
            "p95_model_latency_ms": round(float(model_latency_sample[3]), 2) if model_latency_sample[3] is not None else None,
            "model_latency_sample_count": int(model_latency_sample[0] or 0),
            "retried_work_items": retried_count,
            "work_items": work_count,
            "started_work_items": started_work_count,
            "retry_rate": round(retried_count / started_work_count, 4) if started_work_count else None,
            "subagent_failed_work_items": subagent_work_failed,
            "subagent_terminal_work_items": subagent_work_terminal,
            "subagent_reconciliation_required_work_items": subagent_work_reconciliation,
            "subagent_runtime_events": subagent_event_terminal,
            "subagent_runtime_failures": subagent_event_failed,
            "subagent_failed_instances": subagent_instance_failed,
            "subagent_terminal_instances": subagent_instance_terminal,
            "subagent_failure_rate": round(
                subagent_instance_failed / subagent_instance_terminal, 4,
            ) if subagent_instance_terminal else None,
            "model_calls": model_total,
            "model_success_rate": _model_success_rate(
                call_statuses.get("SUCCEEDED", 0), call_statuses.get("FAILED", 0),
            ),
            "model_failures": call_statuses.get("FAILED", 0),
            "model_tokens": int(token_total or 0),
            "known_usage_calls": usage_known_count,
            "unknown_usage_calls": model_total - usage_known_count,
            "cost_amount": float(cost_total) if cost_total is not None else None,
            "cost_currency": cost_currency,
            "cost_by_currency": cost_by_currency,
            "priced_model_calls": priced_calls,
            "unpriced_model_calls": model_total - priced_calls,
            "durable_tool_invocations": durable_tool_total,
            "durable_tool_success_rate": round(tool_statuses.get("SUCCEEDED", 0) / durable_tool_terminal, 4) if durable_tool_terminal else None,
            "durable_tool_terminal_invocations": durable_tool_terminal,
            "traced_tool_calls": tool_event_count,
            "traced_tool_success_rate": round(tool_event_statuses.get("SUCCEEDED", 0) / tool_event_terminal, 4) if tool_event_terminal else None,
            "skill_loads": sum(row["loads"] for row in skills),
            "skill_load_failures": sum(row["failed"] for row in skills),
            "skill_load_success_rate": round(
                sum(row["succeeded"] for row in skills) / (sum(row["succeeded"] + row["failed"] for row in skills)), 4,
            ) if sum(row["succeeded"] + row["failed"] for row in skills) else None,
            "knowledge_retrievals": retrieval_count,
            "context_assemblies": context_count,
            "manual_reviewed_drafts": feedback["reviewed_drafts"],
            "manual_rejection_rate": feedback["rejection_rate"],
            "manual_edit_rate": feedback["edit_rate"],
        },
        "model_statuses": call_statuses,
        "run_statuses": run_statuses,
        "providers": _provider_health(db, call_query),
        "models": model_breakdown,
        "agents_by_revision": agent_breakdown,
        "tools": tool_breakdown,
        "skills": skills,
        "anomalies": anomalies,
        "manual_feedback": feedback,
        "definitions": {
            "time_window": "TaskRun 执行根的终态按 finished_at 分桶，排队/运行/待核对等非终态按 created_at 分桶；模型调用与运行事件按事实发生时间过滤。结束时间为开区间。",
            "task_runs": "来源：TaskRun 自指协调根或 execution_root_run_id 为空的历史 Run；Fan-out 子 Run 不重复计数。旧数据无根关系时按行计数，歧义历史不会猜测合并。",
            "success_rate": "SUCCEEDED / (SUCCEEDED + SUCCEEDED_WITH_ISSUES + FAILED + CANCELLED)；RECONCILIATION_REQUIRED、排队/运行中和 SUPERSEDED 单列且不进分母。",
            "partial_completion_rate": "SUCCEEDED_WITH_ISSUES / 与 success_rate 相同的终态运行分母。",
            "failure_rate": "FAILED / 与 success_rate 相同的终态运行分母；核对中运行不按失败处理。",
            "cancellation_rate": "CANCELLED / 与 success_rate 相同的终态运行分母。",
            "execution_success_rate": "SUCCEEDED / (SUCCEEDED + SUCCEEDED_WITH_ISSUES + FAILED)；另列并排除取消。",
            "duration": "有开始和结束时间的 SUCCEEDED/SUCCEEDED_WITH_ISSUES/FAILED/CANCELLED TaskRun；P95 使用 PostgreSQL percentile_cont(0.95)。",
            "retry_rate": "attempt_count > 1 的 TaskWorkItem / attempt_count > 0 的 TaskWorkItem。",
            "subagent_failure_rate": "来源：TaskAgentInstance role=SUB_AGENT；FAILED 实例 / SUCCEEDED、SUCCEEDED_WITH_ISSUES、FAILED、CANCELLED 实例。TaskWorkItem 核对中数量及每次运行事件另列。",
            "subagent_work_items": "来源：TaskWorkItem 与 TaskAgentInstance；统计子 Agent 工作项数量、失败数及待核对数，不与实例失败率合并。",
            "subagent_runtime_events": "来源：RuntimeEventFact event_type=AGENT_RUN；按 attempt_id 记录已提交的子 Agent 成功/失败运行事件，恢复复用结果使用稳定 event_id 去重。",
            "model": "RuntimeCallFact；不包含未写入 RuntimeCallFact 的历史调用。",
            "model_status_rate": "来源：RuntimeCallFact；仅 SUCCEEDED/FAILED 为已知终态调用，UNKNOWN 不进成功率分母；模型明细同时列出已知与未知调用数。",
            "tool": "RuntimeEventFact 覆盖本版本接入 dispatcher 的工具；其成功率按成功/失败终态计算。TaskToolInvocation 业务回执成功率同样排除 STARTED/未知状态。",
            "skill": "统计 Skill 文件装载/渲染是否完成，不代表 Markdown Skill 的业务结果或正确率。",
            "cost": "仅汇总有明确价格快照的调用；未配置价格时为 null，不按 Token 猜测成本。",
            "model_latency": "来源：RuntimeCallFact.duration_ms > 0；平均值、P50 和 P95 仅使用实测正时长，单列有效样本数；零值不作为测量结果。",
            "providers": "来源：RuntimeCallFact 左连接 ModelConfiguration.provider。成功率分母仅为 SUCCEEDED+FAILED。启用配置数为当前配置，不随时间窗变化。已知终态不足 5 次为 INSUFFICIENT_SAMPLE；失败率不低于 20% 为 DEGRADED，不低于 50% 为 UNHEALTHY；该供应商配置全部停用为 DISABLED。成本按币种分开，不跨币种相加。",
            "anomalies": "与上一段等长时间窗对比；当前和基线样本均至少 5。任务/模型/工具/Skill 及用例人工反馈率增加至少 15 个百分点告警；模型平均延迟至少翻倍且增加不少于 1000ms（仅计正时长样本）告警；已记录正 Token 的单次平均用量至少翻倍告警；已计价 Agent Revision 单次成本至少翻倍才告警。",
            "manual_feedback": "仅用已有 CaseDraft/CaseGenerationAudit 统计用例生成的人工接受、拒绝和编辑；不外推为正确率，也不代表其他 Agent 类型。",
        },
    }
