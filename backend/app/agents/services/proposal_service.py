"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import json
from typing import Any
from sqlalchemy.orm import Session
from app.agents.models.message import AgentMessage
from app.core.security.crypto import decrypt_secret


def claim_web_proposal(db: Session, session_id: int) -> dict[str, Any] | None:
    """原子领取待确认步骤；真实 WebStep 只从加密消息载荷中解密，不用脱敏投影执行。"""
    message = (
        db.query(AgentMessage)
        .filter_by(session_id=session_id, message_type="WEB_AGENT_STEP")
        .order_by(AgentMessage.id.desc())
        .with_for_update()
        .populate_existing()
        .first()
    )
    if message is None:
        return None
    metadata = dict(message.metadata_json or {})
    if metadata.get("pending_status") != "PROPOSED":
        return None
    blob = metadata.get("pending_step_blob")
    if not isinstance(blob, str) or not blob:
        return None
    try:
        from app.features.web_testing.schemas import WebStep

        step = json.loads(decrypt_secret(blob))
        WebStep.model_validate(step)
    except Exception as exc:  # noqa: BLE001 — 密文损坏时不能执行占位值
        raise ValueError("待确认步骤无法安全读取，请重新提出步骤") from exc
    metadata["pending_status"] = "EXECUTING"
    metadata["pending_step_blob"] = None
    message.metadata_json = metadata
    db.commit()
    return {"message_id": message.id, "step": step}


def finish_web_proposal(db: Session, session_id: int, message_id: int, *, status: str) -> None:
    """更新已领取提案的最终状态并清除密文副本。"""
    if status not in {"ACCEPTED", "FAILED"}:
        raise ValueError("非法的 Web 提案终态")
    message = (
        db.query(AgentMessage)
        .filter_by(id=message_id, session_id=session_id, message_type="WEB_AGENT_STEP")
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if message is None:
        raise ValueError("待执行提案不存在")
    metadata = dict(message.metadata_json or {})
    if metadata.get("pending_status") != "EXECUTING":
        raise ValueError("待执行提案已被处理")
    metadata["pending_status"] = status
    metadata["pending_step_blob"] = None
    message.metadata_json = metadata
    db.commit()


def reject_web_proposal(db: Session, session_id: int) -> None:
    """驳回当前待确认提案，避免刷新后再次出现或被重复确认。"""
    message = (
        db.query(AgentMessage)
        .filter_by(session_id=session_id, message_type="WEB_AGENT_STEP")
        .order_by(AgentMessage.id.desc())
        .with_for_update()
        .populate_existing()
        .first()
    )
    if message is None:
        raise ValueError("待驳回步骤不存在")
    metadata = dict(message.metadata_json or {})
    if metadata.get("pending_status") != "PROPOSED":
        raise ValueError("待驳回步骤不存在或已处理")
    metadata["pending_status"] = "REJECTED"
    metadata["pending_step_blob"] = None
    message.metadata_json = metadata
    db.commit()


def discard_web_proposal(db: Session, session_id: int) -> bool:
    """新消息到达时作废尚未确认的旧提案，避免旧动作跨目标继续执行。

    返回是否实际作废；已领取或已处理的步骤保持其现有终态。
    """
    message = (
        db.query(AgentMessage)
        .filter_by(session_id=session_id, message_type="WEB_AGENT_STEP")
        .order_by(AgentMessage.id.desc())
        .with_for_update()
        .populate_existing()
        .first()
    )
    if message is None:
        return False
    metadata = dict(message.metadata_json or {})
    if metadata.get("pending_status") != "PROPOSED":
        return False
    metadata["pending_status"] = "REJECTED"
    metadata["pending_step_blob"] = None
    message.metadata_json = metadata
    db.commit()
    return True
