"""项目与 Agent 隔离的长期记忆写入、来源验证和召回。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.agents.models import AgentDefinition, AgentLongTermMemory, AgentSession
from app.agents.models.message import AgentMessage
from app.core.http.errors import bad_request, conflict, forbidden, not_found
from app.core.models.identity import User
from app.core.security.roles import PROJECT_ROLE_EDITOR, has_project_role, project_role_for
from app.core.security.sanitizer import sanitize_text
from app.orchestration.tasks.models import TaskAgentInstance
from app.platform.projects.services.access_service import get_project_or_404


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _authorize(db: Session, project_id: int, agent_id: int, actor: User, *, write: bool = False) -> None:
    project = get_project_or_404(db, project_id, actor)
    if write and not has_project_role(project_role_for(db, project, actor), PROJECT_ROLE_EDITOR):
        raise forbidden("需要项目编辑者权限")
    if db.get(AgentDefinition, agent_id) is None:
        raise not_found("Agent 不存在")


def _validated_sources(
    db: Session, project_id: int, agent_id: int, source_message_ids: list[int],
) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(int(value) for value in source_message_ids))
    if len(ids) > 10:
        raise bad_request("长期记忆最多引用 10 条来源消息")
    if not ids:
        return []
    rows = db.query(
        AgentMessage.id, AgentMessage.session_id, AgentMessage.content,
        AgentSession.task_agent_instance_id,
    ).join(AgentSession, AgentSession.id == AgentMessage.session_id).filter(
        AgentMessage.id.in_(ids),
        AgentSession.project_id == project_id,
        AgentSession.task_agent_instance_id.isnot(None),
    ).all()
    if len(rows) != len(ids):
        raise bad_request("来源消息不存在或不属于当前项目")
    instance_ids = {row.task_agent_instance_id for row in rows}
    instances = db.query(TaskAgentInstance).filter(TaskAgentInstance.id.in_(instance_ids)).all()
    instance_agents = {
        item.id: (item.config_snapshot or {}).get("agent_definition_id")
        for item in instances
    }
    if any(instance_agents.get(row.task_agent_instance_id) != agent_id for row in rows):
        raise forbidden("来源消息不属于当前 Agent")
    by_id = {row.id: row for row in rows}
    return [{
        "kind": "AGENT_MESSAGE",
        "message_id": ident,
        "session_id": by_id[ident].session_id,
        "content_sha256": hashlib.sha256((by_id[ident].content or "").encode("utf-8")).hexdigest(),
    } for ident in ids]


def list_agent_memories(db: Session, project_id: int, agent_id: int, actor: User) -> list[AgentLongTermMemory]:
    _authorize(db, project_id, agent_id, actor)
    latest_versions = db.query(
        AgentLongTermMemory.memory_key,
        func.max(AgentLongTermMemory.version).label("version"),
    ).filter(
        AgentLongTermMemory.project_id == project_id,
        AgentLongTermMemory.agent_definition_id == agent_id,
    ).group_by(AgentLongTermMemory.memory_key).subquery()
    return db.query(AgentLongTermMemory).join(
        latest_versions,
        and_(
            latest_versions.c.memory_key == AgentLongTermMemory.memory_key,
            latest_versions.c.version == AgentLongTermMemory.version,
        ),
    ).order_by(AgentLongTermMemory.memory_key).all()


def save_agent_memory(
    db: Session,
    project_id: int,
    agent_id: int,
    actor: User,
    *,
    memory_key: str,
    content: str,
    source_message_ids: list[int] | None = None,
    expected_version: int = 0,
    expires_at: datetime | None = None,
) -> AgentLongTermMemory:
    _authorize(db, project_id, agent_id, actor, write=True)
    normalized_key = memory_key.strip()
    normalized_content = sanitize_text(content).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", normalized_key) or not normalized_content:
        raise bad_request("记忆键和内容不能为空")
    if len(normalized_content) > 12000:
        raise bad_request("长期记忆内容不得超过 12000 个字符")
    now = datetime.now()
    if expires_at is not None and expires_at.tzinfo is not None:
        expires_at = expires_at.astimezone().replace(tzinfo=None)
    if expires_at is not None and expires_at <= now:
        raise bad_request("记忆到期时间必须晚于当前时间")

    # 锁定定义行也覆盖首次写入时尚无记忆行的并发竞态；Agent 版本写入不跨模型请求。
    db.query(AgentDefinition.id).filter(AgentDefinition.id == agent_id).with_for_update().one()
    latest = db.query(AgentLongTermMemory).filter_by(
        project_id=project_id, agent_definition_id=agent_id, memory_key=normalized_key,
    ).order_by(AgentLongTermMemory.version.desc()).with_for_update().first()
    current_version = latest.version if latest else 0
    if int(expected_version) != current_version:
        raise conflict("记忆已被其他请求更新，请刷新后重试")

    source_refs = _validated_sources(db, project_id, agent_id, source_message_ids or [])
    if source_refs:
        source_contents = db.query(AgentMessage.content).filter(
            AgentMessage.id.in_([item["message_id"] for item in source_refs]),
        ).all()
        if normalized_content not in {row[0] for row in source_contents}:
            raise bad_request("引用会话来源时，记忆内容必须与某条原始消息一致")
    else:
        source_refs = [{
            "kind": "USER_PROVIDED",
            "created_by": actor.id,
            "content_sha256": hashlib.sha256(normalized_content.encode("utf-8")).hexdigest(),
        }]
    source_digest = _digest(source_refs)
    if latest is not None and latest.status == "ACTIVE":
        latest.status = "SUPERSEDED"
    row = AgentLongTermMemory(
        project_id=project_id,
        agent_definition_id=agent_id,
        memory_key=normalized_key,
        version=current_version + 1,
        content=normalized_content,
        source_refs=source_refs,
        source_digest=source_digest,
        status="ACTIVE",
        supersedes_id=latest.id if latest else None,
        created_by=actor.id,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def expire_agent_memory(
    db: Session, project_id: int, agent_id: int, actor: User, memory_key: str, *, expected_version: int,
) -> AgentLongTermMemory:
    _authorize(db, project_id, agent_id, actor, write=True)
    row = db.query(AgentLongTermMemory).filter_by(
        project_id=project_id, agent_definition_id=agent_id,
        memory_key=memory_key, version=expected_version,
    ).with_for_update().one_or_none()
    if row is None or row.status != "ACTIVE":
        raise not_found("当前记忆版本不存在")
    row.status = "EXPIRED"
    row.expires_at = datetime.now()
    db.commit()
    db.refresh(row)
    return row


def retrieve_agent_memories(
    db: Session, project_id: int, agent_id: int, query: str | None, *, limit: int = 6,
) -> list[dict[str, Any]]:
    """只召回同项目同 Agent 且来源仍有效的记忆，忽略其他 Agent 的内容。"""
    now = datetime.now()
    query_builder = db.query(AgentLongTermMemory).filter(
        AgentLongTermMemory.project_id == project_id,
        AgentLongTermMemory.agent_definition_id == agent_id,
        AgentLongTermMemory.status == "ACTIVE",
        (AgentLongTermMemory.expires_at.is_(None) | (AgentLongTermMemory.expires_at > now)),
    )
    if query:
        terms = []
        import re
        for token in re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]+", query.lower()):
            terms.extend([token] if token[0].isascii() or len(token) == 1 else
                         [token[index:index + 2] for index in range(len(token) - 1)])
        if terms:
            from sqlalchemy import or_
            query_builder = query_builder.filter(or_(*[
                AgentLongTermMemory.content.ilike(f"%{term}%") for term in list(dict.fromkeys(terms))[:64]
            ]))
    rows = query_builder.order_by(
        AgentLongTermMemory.created_at.desc(), AgentLongTermMemory.id.desc(),
    ).limit(max(1, min(limit, 20))).all()
    output = []
    for row in rows:
        refs = row.source_refs or []
        if _digest(refs) != row.source_digest:
            continue
        message_refs = [ref for ref in refs if ref.get("kind") == "AGENT_MESSAGE"]
        if message_refs:
            valid_refs = _validated_sources(
                db, project_id, agent_id, [ref["message_id"] for ref in message_refs],
            )
            if valid_refs != message_refs:
                continue
        else:
            if not refs or any(ref.get("kind") != "USER_PROVIDED" for ref in refs):
                continue
            content_digest = hashlib.sha256(row.content.encode("utf-8")).hexdigest()
            if any(ref.get("content_sha256") != content_digest for ref in refs):
                continue
        output.append({
            "id": row.id, "memory_key": row.memory_key, "version": row.version,
            "content": row.content, "source_digest": row.source_digest,
            "source_refs": refs, "expires_at": row.expires_at,
        })
    return output
