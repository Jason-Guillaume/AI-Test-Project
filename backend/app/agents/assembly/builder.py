"""Agent 运行配置组装器。

按当前数据库配置、项目授权和模型解析回调构造与历史任务格式兼容的 Agent/Skill/MCP 快照；
运行图、任务状态和租约仍由各自上层服务维护。
"""
from __future__ import annotations
from typing import Any, Callable
from sqlalchemy.orm import Session
from app.agents.models import AgentDefinition
from app.mcp.models import MCPServer
from app.skills.models import SkillDefinition
from app.core.http.errors import bad_request, not_found


def build_agent_profile(
    db: Session, *, project_id: int, agent_definition_id: int | None, actor: Any, target_type: str,
    workflow_matches: Callable[[str, str], bool],
    required_tool_keys: Callable[[str], set[str]],
    resolve_authorized_model: Callable[..., Any],
    model_snapshot: Callable[[Any], dict[str, Any]],
) -> dict[str, Any] | None:
    """解析已启用 Agent 及依赖，并构建不含模型凭据的运行快照。"""
    if agent_definition_id is None:
        return None
    definition = db.get(AgentDefinition, agent_definition_id)
    if definition is None:
        raise not_found("Agent 配置不存在")
    if not definition.is_enabled:
        raise bad_request("所选 Agent 已停用")
    if not workflow_matches(definition.workflow_template, target_type):
        raise bad_request("所选 Agent 工作流与任务执行类型不匹配")
    required_tools = required_tool_keys(target_type)
    missing_tools = required_tools - set(definition.tool_keys or [])
    if missing_tools:
        raise bad_request("所选 Agent 缺少当前任务所需的工具授权，请在 Agent 治理中心补齐权限")

    skill_rows = db.query(SkillDefinition).filter(
        SkillDefinition.key.in_(definition.skill_keys or []),
    ).all() if definition.skill_keys else []
    skills_by_key = {row.key: row for row in skill_rows}
    if len(skills_by_key) != len(definition.skill_keys or []) or any(
        not skills_by_key[key].is_enabled for key in (definition.skill_keys or [])
    ):
        raise bad_request("所选 Agent 关联的 Skill 不存在或已停用")
    skills = [skills_by_key[key] for key in (definition.skill_keys or [])]
    if sum(sum(len(content) for content in (skill.files_json or {"SKILL.md": skill.content}).values()) for skill in skills) > 100_000:
        raise bad_request("所选 Agent 的 Skill 内容过大，请减少关联 Skill")

    settings = dict(definition.settings_json or {})
    binding = settings.get("model_binding")
    requested_model_id = definition.model_config_id if binding in {None, "agent"} else None
    model = resolve_authorized_model(
        db, project_id, actor, requested_model_id=requested_model_id,
    )
    child_rows_from_db = db.query(AgentDefinition).filter(
        AgentDefinition.id.in_(definition.child_agent_ids or []),
    ).all() if definition.child_agent_ids else []
    child_by_id = {child.id: child for child in child_rows_from_db}
    child_rows = [child_by_id[child_id] for child_id in (definition.child_agent_ids or []) if child_id in child_by_id]
    if len(child_rows) != len(definition.child_agent_ids or []) or any(
        not child.is_enabled or child.child_agent_ids or child.tool_keys for child in child_rows
    ):
        raise bad_request("所选 Agent 的子 Agent 已停用或配置不再有效")
    child_snapshots = []
    for child in child_rows:
        child_skills_by_key = {
            skill.key: skill for skill in db.query(SkillDefinition).filter(
                SkillDefinition.key.in_(child.skill_keys or []),
            ).all()
        } if child.skill_keys else {}
        if len(child_skills_by_key) != len(child.skill_keys or []) or any(
            not child_skills_by_key[key].is_enabled for key in (child.skill_keys or [])
        ):
            raise bad_request(f"子 Agent「{child.name}」关联的 Skill 不存在或已停用")
        child_model = resolve_authorized_model(
            db, project_id, actor,
            requested_model_id=child.model_config_id if child.model_config_id is not None else model.id,
        )
        child_model_snapshot = model_snapshot(child_model)
        child_snapshots.append({
            "id": child.id,
            "key": child.key,
            "name": child.name,
            "version": child.version,
            "instruction": child.instruction,
            "model_config_id": child_model.id,
            "fallback_model_config_ids": child_model_snapshot.get("fallback_model_config_ids", []),
            "skills": [
                {
                    "key": skill.key, "name": skill.name, "version": skill.version,
                    "content": skill.content,
                }
                for skill in (child_skills_by_key[key] for key in (child.skill_keys or []))
            ],
        })
    mcp_tools_snapshot = []
    resolved_tool_keys = list(dict.fromkeys([
        *(definition.tool_keys or []),
        *(key for skill in skills for key in (skill.mcp_tool_keys_json or [])),
    ]))
    for tool_key in resolved_tool_keys:
        if not tool_key.startswith("mcp:"):
            continue
        try:
            _, server_id_text, tool_name = tool_key.split(":", 2)
            server = db.get(MCPServer, int(server_id_text))
        except (ValueError, TypeError):
            server = None
            tool_name = ""
        discovered = next(
            (item for item in (server.discovered_tools_json or []) if item.get("name") == tool_name), None,
        ) if server is not None else None
        if (
            server is None or not server.is_enabled or server.connection_status != "connected"
            or tool_name not in (server.approved_tools_json or []) or discovered is None
            or (discovered.get("annotations") or {}).get("readOnlyHint") is not True
        ):
            raise bad_request("Agent 关联的 MCP 工具当前未连接、未审批或不再标记为只读")
        mcp_tools_snapshot.append({
            "key": tool_key,
            "server_id": server.id,
            "server_name": server.name,
            "tool_name": tool_name,
            "description": discovered.get("description", "")[:1000],
            "input_schema": discovered.get("inputSchema") or {"type": "object", "properties": {}},
        })
    return {
        "definition": definition,
        "model": model,
        "snapshot": {
            "id": definition.id,
            "key": definition.key,
            "name": definition.name,
            "version": definition.version,
            "workflow_template": definition.workflow_template,
            "instruction": definition.instruction,
            "tool_keys": resolved_tool_keys,
            "settings_json": settings,
            "triggers_json": list(definition.triggers_json or []),
            "child_agent_ids": list(definition.child_agent_ids or []),
            "skills": [
                {
                    "key": skill.key,
                    "name": skill.name,
                    "version": skill.version,
                    "content": skill.content,
                    "files_json": dict(skill.files_json or {"SKILL.md": skill.content}),
                    "mcp_tool_keys_json": list(skill.mcp_tool_keys_json or []),
                }
                for skill in skills
            ],
            "child_agents": child_snapshots,
            "mcp_tools": mcp_tools_snapshot,
        },
    }
