"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import uuid
from typing import Any
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.agents.schemas import AgentDefinitionCreate, AgentDefinitionUpdate, AgentRuntimeSettings
from app.agents.models import AgentDefinition, AgentDefinitionRevision
from app.core.http.errors import bad_request, conflict, not_found
from app.agents.services.link_validation import validate_agent_links


def agent_snapshot(row: AgentDefinition) -> dict[str, Any]:
    """生成智能体定义的版本快照。"""
    return {
        "name": row.name,
        "description": row.description,
        "workflow_template": row.workflow_template,
        "instruction": row.instruction,
        "model_config_id": row.model_config_id,
        "skill_keys": row.skill_keys or [],
        "tool_keys": row.tool_keys or [],
        "child_agent_ids": row.child_agent_ids or [],
        "is_enabled": row.is_enabled,
        "settings_json": row.settings_json or AgentRuntimeSettings().model_dump(mode="json"),
        "triggers_json": row.triggers_json or [],
    }


def list_agents(db: Session) -> list[AgentDefinition]:
    """列出`agents`。"""
    return db.query(AgentDefinition).order_by(AgentDefinition.updated_at.desc(), AgentDefinition.id.desc()).all()


def create_agent(db: Session, body: AgentDefinitionCreate, actor_id: int) -> AgentDefinition:
    """创建智能体。"""
    validate_agent_links(
        db, body.skill_keys, body.tool_keys, body.model_config_id,
        agent_enabled=body.is_enabled, child_agent_ids=body.child_agent_ids,
    )
    row = AgentDefinition(
        key=str(uuid.uuid4()),
        **body.model_dump(mode="json"),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(row)
    db.flush()
    db.add(AgentDefinitionRevision(
        agent_definition_id=row.id,
        version=row.version,
        snapshot_json=agent_snapshot(row),
        created_by=actor_id,
    ))
    db.commit()
    db.refresh(row)
    return row


def update_agent(db: Session, agent_id: int, body: AgentDefinitionUpdate, actor_id: int) -> AgentDefinition:
    """更新智能体。"""
    row = db.get(AgentDefinition, agent_id)
    if row is None:
        raise not_found("Agent 配置不存在")
    changes = body.model_dump(exclude_unset=True, mode="json")
    changes = {
        key: value for key, value in changes.items()
        if value is not None or key in {"model_config_id", "skill_keys", "tool_keys"}
    }
    if "settings_json" not in changes and "model_config_id" in changes:
        legacy_settings = dict(row.settings_json or AgentRuntimeSettings().model_dump(mode="json"))
        legacy_settings["model_binding"] = "agent" if changes["model_config_id"] is not None else "task_or_global"
        changes["settings_json"] = AgentRuntimeSettings.model_validate(legacy_settings).model_dump(mode="json")
    if changes:
        effective_settings = changes.get("settings_json", row.settings_json or {})
        binding = effective_settings.get("model_binding", "task_or_global")
        effective_model_id = changes.get("model_config_id", row.model_config_id)
        if binding == "task_or_global":
            changes["model_config_id"] = None
        elif effective_model_id is None:
            raise bad_request("选择 Agent 固定模型时必须指定模型配置")
    if changes.get("is_enabled") is False and any(
        row.id in (parent.child_agent_ids or []) and parent.is_enabled
        for parent in db.query(AgentDefinition).filter(AgentDefinition.id != row.id).all()
    ):
        raise conflict("该 Agent 正被启用中的父 Agent 使用，请先停用父 Agent 或移除引用")
    for key in ("skill_keys", "tool_keys"):
        if key in changes and changes[key] is None:
            changes[key] = []
    validate_agent_links(
        db,
        changes.get("skill_keys", row.skill_keys or []) or [],
        changes.get("tool_keys", row.tool_keys or []) or [],
        changes.get("model_config_id", row.model_config_id),
        agent_enabled=changes.get("is_enabled", row.is_enabled),
        child_agent_ids=changes.get("child_agent_ids", row.child_agent_ids or []) or [],
        agent_id=row.id,
    )
    if changes:
        for key, value in changes.items():
            setattr(row, key, value)
        row.version += 1
        row.updated_by = actor_id
        db.add(AgentDefinitionRevision(
            agent_definition_id=row.id,
            version=row.version,
            snapshot_json=agent_snapshot(row),
            created_by=actor_id,
        ))
        db.commit()
        db.refresh(row)
    return row


def agent_versions(db: Session, agent_id: int) -> list[AgentDefinitionRevision]:
    """列出智能体定义的历史版本。"""
    if db.get(AgentDefinition, agent_id) is None:
        raise not_found("Agent 配置不存在")
    return db.query(AgentDefinitionRevision).filter(
        AgentDefinitionRevision.agent_definition_id == agent_id
    ).order_by(AgentDefinitionRevision.version.desc()).all()


def delete_agent(db: Session, agent_id: int) -> None:
    """删除智能体。"""
    row = db.get(AgentDefinition, agent_id)
    if row is None:
        raise not_found("Agent 配置不存在")
    if any(agent_id in (item.child_agent_ids or []) for item in db.query(AgentDefinition).filter(AgentDefinition.id != agent_id).all()):
        raise conflict("该 Agent 已被其他 Agent 配置为子节点，请先移除引用")
    db.delete(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("已有任务绑定此 Agent，请停用配置而不是删除") from exc


def restore_agent_version(db: Session, agent_id: int, version: int, actor_id: int) -> AgentDefinition:
    """将历史快照恢复为当前配置，并作为新的版本保存。"""
    revision = db.query(AgentDefinitionRevision).filter_by(agent_definition_id=agent_id, version=version).first()
    if revision is None:
        raise not_found("Agent 历史版本不存在")
    allowed = {
        "name", "description", "workflow_template", "instruction", "model_config_id",
        "skill_keys", "tool_keys", "child_agent_ids", "is_enabled", "settings_json", "triggers_json",
    }
    body = AgentDefinitionUpdate.model_validate({key: value for key, value in revision.snapshot_json.items() if key in allowed})
    return update_agent(db, agent_id, body, actor_id)


def agent_revision_snapshot(row: AgentDefinition) -> dict[str, Any]:
    """返回供同一事务创建 Agent 修订记录使用的公开快照。"""
    return agent_snapshot(row)
