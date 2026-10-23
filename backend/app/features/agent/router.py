"""接口测试 Agent 路由。

单 APIRouter（无自身前缀），挂在 /api/v1 下。端点：
- POST /projects/{project_id}/agent/sessions        — 建会话
- GET  /projects/{project_id}/agent/sessions        — 会话列表
- GET  /agent/sessions/{session_id}                 — 会话详情 + 消息历史（刷新恢复 §15）
- POST /agent/sessions/{session_id}/messages        — 发消息 / action 推进 Agent
- GET  /agent/sessions/{session_id}/workspace       — 工作区快照
- DELETE /agent/sessions/{session_id}               — 删会话

鉴权：读 viewer+（get_session_or_404）、写 member+（get_session_for_write /
require_writable_project），跨项目统一 404（§33）。service owns commit；路由不 commit。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.features.agent.graph import run_agent
from app.features.agent.providers.llm_provider import ProductionLLMProvider
from app.features.agent.schemas import (
    AgentMessageResponse,
    AgentSessionCreate,
    AgentSessionDetailResponse,
    AgentSessionResponse,
    AgentTurnResponse,
    AgentWorkspace,
    SendMessageRequest,
)
from app.features.agent.services import session_service
from app.features.agent.state import AgentState
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.errors import bad_request, conflict, not_found

router = APIRouter(tags=["接口测试 Agent"])


# --------------------------------------------------------------------------- 会话 CRUD


@router.post(
    "/projects/{project_id}/agent/sessions",
    response_model=AgentSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建 Agent 会话",
)
def create_session(
    project_id: int,
    body: AgentSessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentSessionResponse:
    session = session_service.create_session(db, project_id, user, title=body.title)
    return AgentSessionResponse.model_validate(session)


@router.get(
    "/projects/{project_id}/agent/sessions",
    response_model=list[AgentSessionResponse],
    summary="会话列表",
)
def list_sessions(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    sessions = session_service.list_sessions(db, project_id, user)
    return [AgentSessionResponse.model_validate(s) for s in sessions]


@router.get(
    "/agent/sessions/{session_id}",
    response_model=AgentSessionDetailResponse,
    summary="会话详情 + 消息历史",
)
def get_session_detail(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """返回会话 + 全部消息，供浏览器刷新后无损恢复（§15）。"""
    session = session_service.get_session_or_404(db, session_id, user)
    messages = session_service.list_messages(db, session_id)
    return {
        "session": AgentSessionResponse.model_validate(session),
        "messages": [AgentMessageResponse.model_validate(m) for m in messages],
    }


@router.delete(
    "/agent/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除会话",
)
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    session_service.delete_session(db, session_id, user)
    return None


# --------------------------------------------------------------------------- 工作区


@router.get(
    "/agent/sessions/{session_id}/workspace",
    response_model=AgentWorkspace,
    summary="工作区快照（plan/points/cases/result）",
)
def get_workspace(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentWorkspace:
    session = session_service.get_session_or_404(db, session_id, user)
    state = session_service.load_state(db, session)
    return _build_workspace(state, session)


# --------------------------------------------------------------------------- 消息推进


@router.post(
    "/agent/sessions/{session_id}/messages",
    response_model=AgentTurnResponse,
    summary="发送消息 / action 推进 Agent",
)
def send_message(
    session_id: int,
    body: SendMessageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if not body.content and not body.action:
        raise bad_request("请提供 content（自然语言消息）或 action（快捷操作）")

    session = session_service.get_session_for_write(db, session_id, user)

    # Web 智能体会话必须属于本 Agent 会话所在项目（跨项目统一 404，§33）；
    # 只校验归属，是否 ACTIVE 由节点/运行时刻判定。
    if body.web_session_id:
        from app.features.web_ui.models import WebAgentSession
        web_row = db.get(WebAgentSession, body.web_session_id)
        if web_row is None or web_row.project_id != session.project_id:
            raise not_found("Web 智能体会话不存在或不属于当前项目")
        if body.action in ("confirm_web_step", "reject_web_step"):
            previous = session_service.load_state(db, session).get("web_agent_session_id")
            if previous and previous != body.web_session_id:
                raise conflict("浏览器会话已更换，请先发送新的自然语言目标")

    provider = ProductionLLMProvider(db)

    final_state, emitted = run_agent(
        db, session, user, provider,
        content=body.content,
        action=body.action,
        point_ids=body.point_ids,
        case_ids=body.case_ids,
        environment_id=body.environment_id,
        channel_id=body.channel_id,
        security_item_indexes=body.security_item_indexes,
        security_case_ids=body.security_case_ids,
        zap_scan_target_id=body.zap_scan_target_id,
        zap_scan_profile_id=body.zap_scan_profile_id,
        approval_note=body.approval_note,
        web_session_id=body.web_session_id,
    )

    return {
        "session": AgentSessionResponse.model_validate(session),
        "messages": emitted,
        "workspace": _build_workspace(final_state, session),
    }


# --------------------------------------------------------------------------- 辅助


# stage → 前端应展示的快捷操作按钮。
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
    # Phase 2：ZAP 扫描计划已生成但未确认（任务还没创建，§二十三）。
    "ZAP_SCAN_REVIEW": ["confirm_security_scan"],
    # Web 智能体二轮：步骤提案待确认。只给确认执行与驳回两个出口——
    # 提升入口在前端提案面板上，直接调 /web-agent/sessions/{id}/promote。
    "WEB_STEP_REVIEW": ["confirm_web_step", "reject_web_step"],
}


def _build_workspace(state: AgentState, session) -> AgentWorkspace:
    """从最终 state 组装工作区快照（按 stage 决定 suggested_actions）。"""
    stage = state.get("current_stage") or session.current_stage
    actions = list(_STAGE_ACTIONS.get(stage, []))
    # AgentState 保留可执行原值；API 工作区只回脱敏步骤，避免填写值和断言页面内容外泄。
    web_steps = session_service.redact_web_steps(state.get("web_proposed_steps") or [])
    current_step = state.get("web_current_step")
    safe_current_step = (
        session_service.redact_web_steps([current_step])[0]
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
