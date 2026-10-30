"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.agents.models.message import AgentMessage
from app.agents.models.session import AgentSession
from app.core.security.sanitizer import sanitize_context, sanitize_text


def append_message(
    db: Session,
    session_id: int,
    *,
    role: str,
    message_type: str,
    content: str | None,
    metadata: dict[str, Any] | None = None,
) -> AgentMessage:
    """追加一条消息。content / metadata 均脱敏后落库（§20/§34）。"""
    msg = AgentMessage(
        session_id=session_id,
        role=role,
        message_type=message_type,
        content=sanitize_text(content),
        metadata_json=sanitize_context(metadata) if metadata is not None else None,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def list_messages(db: Session, session_id: int) -> list[AgentMessage]:
    """按时间升序取会话全部消息。"""
    return (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.id.asc())
        .all()
    )


def next_generation_version(db: Session, session_id: int, *, message_type: str) -> int:
    """本轮生成版本号 = 该类型历史消息条数 + 1。

    写入 test_point/test_case.generation_version 用于追溯「第几轮生成」（§11）。
    使用 with_for_update 加行锁防止并发请求返回重复版本号。
    """
    # 对 session 行加行锁，确保同一 session 同时只有一个请求执行
    db.query(AgentSession).filter(AgentSession.id == session_id).with_for_update().one_or_none()
    count = (
        db.query(AgentMessage)
        .filter(AgentMessage.session_id == session_id, AgentMessage.message_type == message_type)
        .count()
    )
    return int(count) + 1
