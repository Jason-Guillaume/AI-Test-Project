"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
import re
from sqlalchemy import func, or_
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


def list_latest_state_messages(db: Session, session_id: int) -> list[AgentMessage]:
    """每种消息类型只取最新一条，供工作流状态恢复，避免扫描完整会话正文。"""
    latest_ids = db.query(func.max(AgentMessage.id).label("id")).filter(
        AgentMessage.session_id == session_id,
    ).group_by(AgentMessage.message_type).subquery()
    return db.query(AgentMessage).join(
        latest_ids, latest_ids.c.id == AgentMessage.id,
    ).order_by(AgentMessage.id.asc()).all()


def list_context_candidates(
    db: Session,
    session_id: int,
    *,
    query: str | None,
    recent_limit: int = 32,
    related_limit: int = 96,
) -> tuple[list[AgentMessage], int]:
    """取最近消息和同一会话内的关键词相关旧消息，并返回总消息数。"""
    base = db.query(AgentMessage).filter(AgentMessage.session_id == session_id)
    total = int(base.with_entities(func.count(AgentMessage.id)).scalar() or 0)
    recent = base.order_by(AgentMessage.id.desc()).limit(max(1, recent_limit)).all()
    if len(recent) < recent_limit or not query:
        return list(reversed(recent)), total

    oldest_recent_id = min(row.id for row in recent)
    terms = []
    for token in re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]+", query.lower()):
        if token[0].isascii():
            terms.append(token)
        elif len(token) > 1:
            terms.extend(token[index:index + 2] for index in range(len(token) - 1))
        else:
            terms.append(token)
    predicates = []
    for term in list(dict.fromkeys(terms))[:64]:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        predicates.append(AgentMessage.content.ilike(f"%{escaped}%", escape="\\"))
    related = []
    if predicates:
        related = base.filter(
            AgentMessage.id < oldest_recent_id,
            AgentMessage.content.isnot(None),
            or_(*predicates),
        ).order_by(AgentMessage.id.desc()).limit(max(0, related_limit)).all()
    by_id = {row.id: row for row in (*recent, *related)}
    return [by_id[ident] for ident in sorted(by_id)], total


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
