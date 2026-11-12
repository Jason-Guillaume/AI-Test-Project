"""接口测试 Agent 路由。

单 APIRouter（无自身前缀），挂在 /api/v1 下。端点：
- POST /projects/{project_id}/agent/sessions        — 建会话
- GET  /projects/{project_id}/agent/sessions        — 会话列表
- GET  /agent/sessions/{session_id}                 — 会话详情 + 消息历史（刷新恢复 §15）
- POST /agent/sessions/{session_id}/messages        — 发消息 / action 推进 Agent
- GET  /agent/sessions/{session_id}/workspace       — 工作区快照
- DELETE /agent/sessions/{session_id}               — 删会话

鉴权：读 viewer+（get_session_or_404）、写 member+（get_session_for_write /
require_writable_project），跨项目统一 404（§33）。service owns commit；路由不 commit。"""

from __future__ import annotations

from datetime import datetime

from app.agents.services.workspace_response import build_workspace
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.agents.workflows.legacy.graph import run_agent
from app.llm.providers import ProductionLLMProvider
from app.agents.session_schemas import (
    AgentMessageResponse,
    AgentSessionCreate,
    AgentSessionDetailResponse,
    AgentSessionResponse,
    AgentTurnResponse,
    AgentWorkspace,
    SendMessageRequest,
)
from app.agents.services import session_service
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.errors import bad_request, conflict, not_found


class AgentMemoryInput(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    source_message_ids: list[int] = Field(default_factory=list, max_length=10)
    expected_version: int = Field(default=0, ge=0)
    expires_at: datetime | None = None


class AgentMemoryExpireInput(BaseModel):
    expected_version: int = Field(gt=0)


def _memory_response(row) -> dict:
    return {
        "id": row.id, "project_id": row.project_id,
        "agent_definition_id": row.agent_definition_id,
        "memory_key": row.memory_key, "version": row.version,
        "content": row.content, "source_refs": row.source_refs,
        "source_digest": row.source_digest, "status": row.status,
        "expires_at": row.expires_at, "created_at": row.created_at,
    }


router = APIRouter(tags=["接口测试 Agent"])


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
    """创建会话。"""
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
    """列出`sessions`。"""
    sessions = session_service.list_sessions(db, project_id, user)
    return [AgentSessionResponse.model_validate(s) for s in sessions]


@router.get(
    "/projects/{project_id}/agents/{agent_id}/memories",
    summary="读取 Agent 长期记忆",
)
def list_agent_memories(
    project_id: int,
    agent_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    from app.agents.services.long_term_memory import list_agent_memories as list_memories

    return {"items": [
        _memory_response(row) for row in list_memories(db, project_id, agent_id, user)
    ]}


@router.put(
    "/projects/{project_id}/agents/{agent_id}/memories/{memory_key}",
    summary="新增或版本化更新 Agent 长期记忆",
)
def put_agent_memory(
    project_id: int,
    agent_id: int,
    memory_key: str,
    body: AgentMemoryInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    from app.agents.services.long_term_memory import save_agent_memory

    row = save_agent_memory(
        db, project_id, agent_id, user, memory_key=memory_key,
        content=body.content, source_message_ids=body.source_message_ids,
        expected_version=body.expected_version, expires_at=body.expires_at,
    )
    return _memory_response(row)


@router.post(
    "/projects/{project_id}/agents/{agent_id}/memories/{memory_key}/expire",
    summary="使 Agent 长期记忆版本失效",
)
def expire_agent_memory(
    project_id: int,
    agent_id: int,
    memory_key: str,
    body: AgentMemoryExpireInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    from app.agents.services.long_term_memory import expire_agent_memory as expire_memory

    row = expire_memory(
        db, project_id, agent_id, user, memory_key, expected_version=body.expected_version,
    )
    return _memory_response(row)


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
    """删除会话。"""
    session_service.delete_session(db, session_id, user)
    return None


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
    """获取`workspace`。"""
    session = session_service.get_session_or_404(db, session_id, user)
    state = session_service.load_state(db, session)
    return build_workspace(state, session)


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
    """发送消息。"""
    if not body.content and not body.action:
        raise bad_request("请提供 content（自然语言消息）或 action（快捷操作）")

    session = session_service.get_session_for_write(db, session_id, user)

    # Web 智能体会话必须属于本 Agent 会话所在项目（跨项目统一 404，§33）；
    # 只校验归属，是否 ACTIVE 由节点/运行时刻判定。
    if body.web_session_id:
        from app.features.web_testing.models import WebAgentSession
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
        web_session_id=body.web_session_id,
        zap_scan_target_id=body.zap_scan_target_id,
        zap_scan_profile_id=body.zap_scan_profile_id,
        approval_note=body.approval_note,
    )

    return {
        "session": AgentSessionResponse.model_validate(session),
        "messages": emitted,
        "workspace": build_workspace(final_state, session),
    }
