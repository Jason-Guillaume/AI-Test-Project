"""Agent 会话公开入口；状态恢复、轮次写入和人工提案均使用唯一实现。"""

from __future__ import annotations

from app.agents.services.message_store import append_message
from app.agents.services.proposal_service import claim_web_proposal
from app.agents.services.session_access import create_session
from app.agents.services.session_access import delete_session
from app.agents.services.proposal_service import discard_web_proposal
from app.agents.services.proposal_service import finish_web_proposal
from app.agents.services.session_access import get_session_for_write
from app.agents.services.session_access import get_session_or_404
from app.agents.services.message_store import list_messages
from app.agents.services.session_access import list_sessions
from app.agents.services.session_state import load_state
from app.agents.services.message_store import next_generation_version
from app.agents.services.session_turn import persist_turn
from app.agents.services.session_response import redact_web_steps
from app.agents.services.proposal_service import reject_web_proposal


__all__ = [
    'create_session',
    'list_sessions',
    'get_session_or_404',
    'get_session_for_write',
    'delete_session',
    'append_message',
    'list_messages',
    'claim_web_proposal',
    'finish_web_proposal',
    'reject_web_proposal',
    'discard_web_proposal',
    'next_generation_version',
    'load_state',
    'redact_web_steps',
    'persist_turn',
]
