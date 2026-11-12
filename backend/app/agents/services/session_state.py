"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import json
import time
from typing import Any
from sqlalchemy.orm import Session
from app.agents.models.session import AgentSession
from app.agents.workflows.legacy.state import AgentState, make_initial_state
from app.core.security.crypto import decrypt_secret
from app.agents.services.message_store import list_context_candidates, list_latest_state_messages
from app.agents.services.context_manager import assemble_history
from app.agents.services.context_memory import load_valid_session_summary
from app.core.config import settings


def load_state(db: Session, session: AgentSession, *, query: str | None = None) -> AgentState:
    """从 agent_session + agent_message 重建 AgentState（刷新 / 续轮恢复，§15）。

    重建口径：current_stage 取会话行；各产物取**该类型最新一条** ASSISTANT 消息的
    metadata_json（再生成会追加新消息，旧消息保留在历史中）。消息历史由 Context Manager
    按会话权限、查询相关性和预算装配（脱敏，已在上游 sanitize）。
    """
    # 结构化状态只读每种类型最新一条；对话上下文另走有界最近窗口 + 相关旧消息查询。
    msgs = list_latest_state_messages(db, session.id)
    history_limit = max(32, min(int(settings.AGENT_CONTEXT_MAX_HISTORY_MESSAGES) * 4, 128))
    context_msgs, total_message_count = list_context_candidates(
        db, session.id, query=query, recent_limit=history_limit, related_limit=96,
    )
    context_summary = load_valid_session_summary(db, session.id)
    from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskRun
    run = db.get(TaskRun, session.task_run_id) if session.task_run_id else None
    task = db.get(Task, run.task_id) if run else None
    instance = db.get(TaskAgentInstance, session.task_agent_instance_id) if session.task_agent_instance_id else None
    agent_config = (instance.config_snapshot or {}) if instance else {}
    agent_definition_id = agent_config.get("agent_definition_id") or agent_config.get("id")
    long_term_memories = []
    if agent_definition_id:
        from app.agents.services.long_term_memory import retrieve_agent_memories
        long_term_memories = retrieve_agent_memories(
            db, session.project_id, int(agent_definition_id), query,
        )
    state = make_initial_state(session.project_id, session.user_id, session.id)
    state["current_stage"] = session.current_stage

    def latest(msg_type: str) -> dict[str, Any] | None:
        """读取会话中的最新消息。"""
        for m in reversed(msgs):
            if m.message_type == msg_type and m.metadata_json:
                return m.metadata_json
        return None

    plan_meta = latest("TEST_PLAN")
    if plan_meta:
        state["test_plan"] = plan_meta.get("plan")
        state["intent"] = plan_meta.get("intent")
        state["target_type"] = plan_meta.get("target_type")
        state["target_ids"] = plan_meta.get("target_ids", [])
        # 跨轮次恢复被测上下文（confirm_points / regenerate_* 时复用）
        state["api_context"] = plan_meta.get("api_context")
        state["business_context"] = plan_meta.get("business_context")
        state["strategy_context"] = plan_meta.get("strategy_context") or []
        state["existing_test_context"] = plan_meta.get("existing_test_context")

    pts_meta = latest("TEST_POINTS")
    if pts_meta:
        state["generated_test_points"] = pts_meta.get("points", [])
        state["confirmed_point_ids"] = pts_meta.get("confirmed_point_ids", [])

    cases_meta = latest("TEST_CASES")
    if cases_meta:
        state["generated_test_cases"] = cases_meta.get("cases", [])
        state["confirmed_case_ids"] = cases_meta.get("confirmed_case_ids", [])
        # 高风险确认待办随用例一起恢复：materializer 写入，刷新后工作区仍要给出
        # confirm_security_risk 按钮，否则用户看不到「执行前需人工确认」的提示。
        state["security_risk_pending"] = cases_meta.get("security_risk_pending")

    sec_meta = latest("SECURITY_PLAN")
    if sec_meta:
        state["security_plan"] = sec_meta.get("plan")
        state["security_plan_id"] = sec_meta.get("plan_id")
        state["security_strategy_keys"] = sec_meta.get("strategy_keys") or []
        state["target_type"] = sec_meta.get("target_type")
        state["target_ids"] = sec_meta.get("target_ids") or []
        # 安全上下文跨轮次保留（confirm_security_plan 时 materializer 需要重放 preview）
        state["security_context"] = sec_meta.get("context")

    scan_meta = latest("SECURITY_SCAN_PLAN")
    if scan_meta:
        # 旧版扫描工作区字段继续读取，用于历史会话兼容；当前图不再注册扫描节点。
        state["zap_scan_plan"] = scan_meta.get("plan")
        state["zap_scan_job_id"] = scan_meta.get("job_id")

    step_meta = latest("WEB_AGENT_STEP")
    if step_meta:
        # Web 智能体二轮：会话绑定、目标与步数预算跨轮次恢复。提案列表供 promote
        # 提升为正式用例，当前待确认提案决定 web_step_review 暂停点能否执行。
        # 键名刻意不用 session_id：metadata 落库前经 sanitize_context 清洗，
        # session_id 属敏感字段名会被掩成 ******，跨轮次就丢绑定。
        state["web_agent_session_id"] = step_meta.get("browser_id")
        state["web_goal"] = step_meta.get("goal")
        state["web_step_budget"] = step_meta.get("budget") or 20  # 与会话默认一致
        state["web_proposed_steps"] = step_meta.get("steps") or []
        state["web_current_step"] = step_meta.get("current_step")
        state["web_last_decision"] = step_meta.get("last_decision")
        state["web_observe_count"] = step_meta.get("observe_count") or 0
        # 对话消息里的 current_step 是脱敏投影，不能作为执行参数。刷新恢复时只从
        # 应用层加密的载荷解密待确认步骤；旧消息或已领取提案一律不再显示为可执行。
        if step_meta.get("pending_status") == "PROPOSED" and step_meta.get("pending_step_blob"):
            try:
                state["web_current_step"] = json.loads(decrypt_secret(step_meta["pending_step_blob"]))
            except Exception:  # noqa: BLE001 — 损坏载荷关闭确认入口，不回退到脱敏占位值
                state["web_current_step"] = None
        elif state.get("web_current_step"):
            state["web_current_step"] = None

    obs_meta = latest("WEB_OBSERVATION")
    if obs_meta:
        # 只恢复语义树与元信息（不含截图）；执行下一步前会重新观测真实页面。
        state["web_current_observation"] = obs_meta.get("observation")

    result_meta = latest("RESULT")
    if result_meta:
        state["analysis"] = result_meta.get("analysis")
        # 未关闭 Finding 摘要由 result_analyzer 挂在 analysis 上，这里同步到顶层键。
        state["security_finding_brief"] = (result_meta.get("analysis") or {}).get(
            "security_findings", [],
        ) or []

    exec_meta = latest("EXECUTION")
    if exec_meta:
        state["test_run_id"] = exec_meta.get("run_id")
        state["execution_result"] = exec_meta.get("run")

    report_meta = latest("REPORT")
    if report_meta:
        state["report_id"] = report_meta.get("report_id")
        state["report_brief"] = report_meta.get("report")

    notif_meta = latest("NOTIFICATION")
    if notif_meta:
        state["notification_record_id"] = notif_meta.get("record_id")
        state["notification_brief"] = notif_meta.get("notification")

    # Prompt 只接收本 AgentSession 被 Context Manager 选中的脱敏历史消息。
    context_started = time.monotonic()
    state["messages"], state["context_manifest"] = assemble_history(
        session=session,
        messages=context_msgs,
        query=query,
        token_budget=settings.AGENT_CONTEXT_TOKEN_BUDGET,
        max_messages=settings.AGENT_CONTEXT_MAX_HISTORY_MESSAGES,
        total_message_count=total_message_count,
        summary=context_summary,
        long_term_memories=long_term_memories,
    )
    from app.orchestration.tasks.services.runtime_fact_service import record_runtime_event
    manifest = state["context_manifest"]
    record_runtime_event(
        db=db,
        project_id=session.project_id,
        task_id=task.id if task else None,
        task_run_id=run.id if run else None,
        execution_root_run_id=(run.execution_root_run_id or run.id) if run else None,
        agent_session_id=session.id,
        agent_instance_id=instance.id if instance else None,
        agent_definition_id=agent_config.get("agent_definition_id") or agent_config.get("id"),
        agent_definition_revision_id=instance.agent_definition_revision_id if instance else None,
        trace_id=run.trace_id if run else None,
        event_type="CONTEXT_ASSEMBLY", event_name=manifest["version"], status="SUCCEEDED",
        duration_ms=int((time.monotonic() - context_started) * 1000),
        event_metadata={
            "query_sha256": manifest["query_sha256"],
            "context_token_budget": manifest["token_budget"],
            "estimated_tokens": manifest["estimated_tokens"],
            "history_count": len(state["messages"]),
            "omitted_message_count": manifest["omitted_message_count"],
            "unsearched_message_count": manifest["unsearched_message_count"],
            "candidate_message_count": manifest["candidate_message_count"],
            "summary_used": manifest["summary_used"],
            "summary_version": manifest["summary_version"],
            "summary_source_count": manifest["summary_source_count"],
            "summary_message_ids": [source["id"] for source in manifest["summary_source_refs"]],
            "memory_count": manifest["memory_count"],
            "memory_ids": manifest["memory_ids"],
            "message_ids": [source["id"] for source in manifest["source_refs"]],
        },
    )
    return state
