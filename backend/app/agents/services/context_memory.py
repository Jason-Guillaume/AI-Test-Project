"""带原始消息来源校验的会话级长期历史摘要。"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.agents.models.context_summary import AgentSessionSummary
from app.agents.models.message import AgentMessage
from app.agents.models.session import AgentSession

logger = logging.getLogger(__name__)

_SHORT_TERM_MESSAGES = 32
_SUMMARY_SOURCE_LIMIT = 16
_SUMMARY_MESSAGE_CHARS = 360
_CONSTRAINT_MARKERS = ("必须", "禁止", "不允许", "不得", "约束")
_CONSTRAINT_SLOTS = 4


def _is_constraint(text: str) -> bool:
    """识别需要在压缩后仍保留的业务约束，不把普通叙述当成约束。"""
    return any(marker in text for marker in _CONSTRAINT_MARKERS)


def select_summary_sources(rows: list[Any], *, limit: int = _SUMMARY_SOURCE_LIMIT) -> list[Any]:
    """优先保留约束语句，再用较新消息填满摘要名额。"""
    ordered = [row for row in rows if getattr(row, "content", None)]
    constraints = [row for row in ordered if _is_constraint(row.content)][:_CONSTRAINT_SLOTS]
    constraint_ids = {row.id for row in constraints}
    recent_slots = max(0, limit - len(constraints))
    recent = [row for row in ordered if row.id not in constraint_ids][-recent_slots:]
    return sorted([*constraints, *recent], key=lambda row: row.id)


def _digest_refs(refs: list[dict[str, Any]]) -> str:
    body = json.dumps(refs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_valid_session_summary(db: Session, session_id: int) -> dict[str, Any] | None:
    """只返回来源消息仍存在且内容指纹一致的摘要。"""
    summary = db.get(AgentSessionSummary, session_id)
    if summary is None or (summary.expires_at and summary.expires_at <= datetime.now()):
        return None
    refs = summary.source_refs or []
    ids = [ref.get("message_id") for ref in refs if isinstance(ref, dict)]
    if not ids or len(ids) != len(refs):
        return None
    rows = db.query(AgentMessage.id, AgentMessage.content).filter(
        AgentMessage.session_id == session_id,
        AgentMessage.id.in_(ids),
    ).all()
    content_by_id = {row.id: row.content or "" for row in rows}
    if len(content_by_id) != len(ids):
        return None
    if any(
        hashlib.sha256(content_by_id[ref["message_id"]].encode("utf-8")).hexdigest()
        != ref.get("content_sha256")
        for ref in refs
    ):
        return None
    if _digest_refs(refs) != summary.source_digest:
        return None
    return {
        "session_id": summary.session_id,
        "version": summary.summary_version,
        "kind": summary.summary_kind,
        "text": summary.summary_text,
        "source_refs": refs,
        "source_digest": summary.source_digest,
        "through_message_id": summary.source_through_message_id,
        "expires_at": summary.expires_at,
    }


def refresh_session_summary(db: Session, session_id: int) -> None:
    """定期更新旧会话的提取式索引，不调用模型、不改写事实或删除原文。"""
    savepoint = db.begin_nested()
    try:
        db.query(AgentSession.id).filter(AgentSession.id == session_id).with_for_update().one_or_none()
        base = db.query(AgentMessage).filter(AgentMessage.session_id == session_id)
        total = int(base.count())
        if total <= _SHORT_TERM_MESSAGES:
            savepoint.commit()
            return

        cutoff_id = base.with_entities(AgentMessage.id).order_by(
            AgentMessage.id.desc(),
        ).offset(_SHORT_TERM_MESSAGES).limit(1).scalar()
        if cutoff_id is None:
            savepoint.commit()
            return
        candidates = base.filter(AgentMessage.id <= cutoff_id).order_by(
            AgentMessage.id.desc(),
        ).limit(_SUMMARY_SOURCE_LIMIT * 2).all()
        selected = select_summary_sources(list(reversed(candidates)))
        if not selected:
            savepoint.commit()
            return

        refs = []
        lines = []
        for row in selected:
            content = row.content or ""
            excerpt = content
            if len(excerpt) > _SUMMARY_MESSAGE_CHARS:
                head = _SUMMARY_MESSAGE_CHARS - 40
                excerpt = f"{excerpt[:head]}…[摘录省略]…{excerpt[-40:]}"
            refs.append({
                "message_id": row.id,
                "role": row.role.lower(),
                "message_type": row.message_type,
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            })
            lines.append(f"[{row.role.lower()}#{row.id}/{row.message_type}] {excerpt}")
        digest = _digest_refs(refs)
        summary = db.get(AgentSessionSummary, session_id)
        if summary is None:
            summary = AgentSessionSummary(
                session_id=session_id,
                summary_version=1,
                summary_kind="EXTRACTIVE",
            )
        else:
            summary.summary_version += 1
        summary.summary_text = "\n".join(lines)
        summary.source_refs = refs
        summary.source_digest = digest
        summary.source_through_message_id = max(ref["message_id"] for ref in refs)
        summary.expires_at = datetime.now() + timedelta(days=90)
        db.add(summary)
        db.flush()
        savepoint.commit()
    except Exception as exc:  # noqa: BLE001 — 摘要失败不改变 Agent 回合结果
        if savepoint.is_active:
            savepoint.rollback()
        logger.warning("Agent 会话摘要更新失败（忽略）：%s", type(exc).__name__)
