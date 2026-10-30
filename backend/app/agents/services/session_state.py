"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import json
from typing import Any
from sqlalchemy.orm import Session
from app.agents.models.session import AgentSession
from app.agents.workflows.legacy.state import AgentState, make_initial_state
from app.core.security.crypto import decrypt_secret
from app.agents.services.message_store import list_messages


def load_state(db: Session, session: AgentSession) -> AgentState:
    """从 agent_session + agent_message 重建 AgentState（刷新 / 续轮恢复，§15）。

    重建口径：current_stage 取会话行；各产物取**该类型最新一条** ASSISTANT 消息的
    metadata_json（再生成会追加新消息，旧消息保留在历史中）。消息历史取最近 8 条
    供 prompt 使用（脱敏，已在上游 sanitize）。
    """
    msgs = list_messages(db, session.id)
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

    # prompt 消息历史：只保留 role + content（已脱敏），最近 8 条控制 token。
    state["messages"] = [
        {"role": m.role, "content": m.content}
        for m in msgs if m.content
    ][-8:]
    return state
