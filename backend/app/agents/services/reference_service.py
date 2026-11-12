"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.agents.models import AgentDefinition
from app.skills.models import SkillDefinition, SkillDefinitionRevision
from app.skills.schemas import SkillUpdate
from app.skills.services import skill_service
from app.core.http.errors import conflict, not_found


def update_skill(db: Session, skill_id: int, body: SkillUpdate, actor_id: int) -> SkillDefinition:
    """更新 Skill，并保护仍由启用 Agent 使用的定义。"""
    row = db.get(SkillDefinition, skill_id)
    if row is None:
        raise not_found("Skill 不存在")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("is_enabled") is False and any(
        row.is_enabled and row.key in (agent.skill_keys or [])
        for agent in db.query(AgentDefinition).all()
    ):
        raise conflict("该 Skill 正被启用中的 Agent 使用，请先停用 Agent 或移除引用")
    return skill_service.update_skill(db, skill_id, body, actor_id)


def delete_skill(db: Session, skill_id: int, actor) -> None:
    """将未被活跃 Agent 引用的 Skill 移入统一回收站。"""
    skill_service.remove_skill(db, skill_id, actor)


def delete_mcp_server(db: Session, server_id: int, actor) -> None:
    """软删除未被 Agent、Skill 或活跃任务引用的 MCP 服务。"""
    from app.lifecycle.service import delete_resource

    delete_resource(db, "mcp_server", server_id, actor=actor)


def restore_skill_version(db: Session, skill_id: int, version: int, actor_id: int) -> SkillDefinition:
    """恢复 Skill 历史版本，并沿用启用引用保护。"""
    revision = db.query(SkillDefinitionRevision).filter_by(
        skill_definition_id=skill_id, version=version,
    ).first()
    if revision is None:
        raise not_found("Skill 历史版本不存在")
    allowed = {"name", "description", "content", "is_enabled", "files_json", "mcp_tool_keys_json"}
    body = SkillUpdate.model_validate({
        key: value for key, value in revision.snapshot_json.items() if key in allowed
    })
    return update_skill(db, skill_id, body, actor_id)
