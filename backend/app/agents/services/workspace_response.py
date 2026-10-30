"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.agents.session_schemas import AgentWorkspace
from app.agents.workflows.legacy.state import AgentState
from app.agents.services.session_response import redact_web_steps


_STAGE_ACTIONS: dict[str, list[str]] = {
    "UNDERSTANDING": [],
    "CONTEXT_LOADING": [],
    "PLANNING": [],
    "TEST_POINT_REVIEW": ["confirm_points", "regenerate_points"],
    "TEST_POINT_GENERATED": [],
    "TEST_CASE_REVIEW": ["confirm_cases", "regenerate_cases", "execute"],
    "READY_TO_EXECUTE": ["execute"],
    "EXECUTING": [],
    "ANALYZING": ["analyze"],
    "REPORT_GENERATING": [],
    "REPORT_REVIEW": ["confirm_report", "skip_notification"],
    "NOTIFYING": [],
    "COMPLETED": ["analyze"],
    "FAILED": ["regenerate_points", "regenerate_cases"],
    "CLARIFY": [],
    # Phase F：安全计划已生成但未确认（用例还没落库）。
    "SECURITY_PLAN_REVIEW": ["confirm_security_plan"],
    # ZAP 扫描计划只能人工确认，主动扫描确认时还须提交批准说明。
    "ZAP_SCAN_REVIEW": ["confirm_security_scan"],
    # Web 智能体二轮：步骤提案待确认。只给确认执行与驳回两个出口——
    # 提升入口在前端提案面板上，直接调 /web-agent/sessions/{id}/promote。
    "WEB_STEP_REVIEW": ["confirm_web_step", "reject_web_step"],
}


def build_workspace(state: AgentState, session) -> AgentWorkspace:
    """从最终 state 组装工作区快照（按 stage 决定 suggested_actions）。"""
    stage = state.get("current_stage") or session.current_stage
    actions = list(_STAGE_ACTIONS.get(stage, []))
    # AgentState 保留可执行原值；API 工作区只回脱敏步骤，避免填写值和断言页面内容外泄。
    web_steps = redact_web_steps(state.get("web_proposed_steps") or [])
    current_step = state.get("web_current_step")
    safe_current_step = (
        redact_web_steps([current_step])[0]
        if current_step else None
    )
    # 预算耗尽时也停在 WEB_STEP_REVIEW，但没有待执行提案；不要显示会触发失败的确认/驳回按钮。
    if stage == "WEB_STEP_REVIEW" and not safe_current_step:
        actions = []
    # 有待确认的高风险用例时才给「确认风险」按钮（否则点了只会提示没有待确认项）。
    pending = state.get("security_risk_pending") or {}
    if pending.get("count"):
        actions.append("confirm_security_risk")
    return AgentWorkspace(
        stage=stage,
        intent=state.get("intent"),
        test_plan=state.get("test_plan"),
        test_points=state.get("generated_test_points", []),
        test_cases=state.get("generated_test_cases", []),
        test_run_id=state.get("test_run_id"),
        execution_result=state.get("execution_result"),
        analysis=state.get("analysis"),
        report_id=state.get("report_id"),
        report_brief=state.get("report_brief"),
        notification_brief=state.get("notification_brief"),
        error=state.get("error"),
        security_plan=state.get("security_plan"),
        security_findings=state.get("security_finding_brief", []),
        zap_scan_plan=state.get("zap_scan_plan"),
        zap_scan_job_id=state.get("zap_scan_job_id"),
        zap_scan_note=state.get("zap_scan_note"),
        web_agent_session_id=state.get("web_agent_session_id"),
        web_goal=state.get("web_goal"),
        web_step_budget=state.get("web_step_budget") or 20,
        web_proposed_steps=web_steps,
        web_current_step=safe_current_step,
        web_observation=state.get("web_current_observation"),
        suggested_actions=actions,
    )
