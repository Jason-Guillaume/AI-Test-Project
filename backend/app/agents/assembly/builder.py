"""Agent 运行配置组装器。

按当前数据库配置、项目授权和模型解析回调构造与历史任务格式兼容的 Agent/Skill/MCP 快照；
运行图、任务状态和租约仍由各自上层服务维护。
"""
from __future__ import annotations
from typing import Any, Callable
from sqlalchemy.orm import Session
from app.agents.models import AgentDefinition, AgentDefinitionRevision
from app.mcp.models import MCPServer
from app.skills.loader import load_skill_files
from app.skills.models import SkillDefinition
from app.core.http.errors import bad_request, not_found


def configured_tool_paths(tool_keys: list[str], skills: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """合并直接工具与 Skill 引入路径，按运行时顺序为每个工具保留一项。"""
    paths = {key: {'key': key, 'direct': True, 'skill_keys': []} for key in tool_keys}
    for skill in skills:
        for key in dict.fromkeys(skill.get('mcp_tool_keys_json') or []):
            path = paths.setdefault(key, {'key': key, 'direct': False, 'skill_keys': []})
            if skill['key'] not in path['skill_keys']:
                path['skill_keys'].append(skill['key'])
    return paths


def available_mcp_tool(server: MCPServer | None, name: str) -> dict[str, Any] | None:
    """按启用、连接、审批及只读状态解析当前可用的 MCP 定义。"""
    if (server is None or not server.is_enabled or server.connection_status != 'connected'
            or name not in (server.approved_tools_json or [])):
        return None
    return next((tool for tool in (server.discovered_tools_json or [])
                 if tool.get('name') == name and (tool.get('annotations') or {}).get('readOnlyHint') is True), None)


def snapshot_agent_skills(db: Session, agents: list[AgentDefinition]) -> dict[int, list[dict[str, Any]]]:
    """所有主子节点按相同顺序一次锁定 Skill，避免交错引用时互相等待。"""
    keys = {key for agent in agents for key in (agent.skill_keys or [])}
    rows = db.query(SkillDefinition).filter(SkillDefinition.key.in_(keys)).order_by(
        SkillDefinition.id,
    ).populate_existing().with_for_update().all() if keys else []
    by_key = {row.key: row for row in rows if row.is_enabled}
    return {agent.id: _snapshot_skills(agent, by_key) for agent in agents}


def _snapshot_skills(agent, by_key) -> list[dict[str, Any]]:
    """按 Agent 配置顺序冻结 Skill 版本和文件，并校验内容上限。"""
    keys = list(dict.fromkeys(agent.skill_keys or []))
    if not set(keys).issubset(by_key):
        raise bad_request(f"Agent「{agent.name}」关联的 Skill 不存在或已停用")
    snapshots = []
    for key in keys:
        skill = by_key[key]
        files = load_skill_files(skill)
        snapshots.append({
            "key": key, "name": skill.name, "version": skill.version,
            "content": files.get("SKILL.md", ""), "files_json": files,
            "mcp_tool_keys_json": list(skill.mcp_tool_keys_json or []),
        })
    if sum(len(text) for skill in snapshots for text in skill["files_json"].values()) > 100_000:
        raise bad_request("Agent 的 Skill 内容过大，请减少关联 Skill")
    return snapshots


def build_agent_profile(
    db: Session, *, project_id: int, agent_definition_id: int | None, actor: Any, target_type: str,
    workflow_matches: Callable[[str, str], bool],
    required_tool_keys: Callable[[str], set[str]],
    resolve_authorized_model: Callable[..., Any],
    model_snapshot: Callable[[Any], dict[str, Any]],
) -> dict[str, Any] | None:
    """解析已启用 Agent 及依赖，并构建不含模型凭据的运行快照。"""
    from app.knowledge.service import freeze
    if agent_definition_id is None:
        return None
    # Lock the selected definition while its runtime snapshot and task run are created.
    # Lifecycle deletion takes the same row lock, so a delete cannot pass its active-run
    # check between this read and the transaction that stores the snapshot.
    definition = db.query(AgentDefinition).filter(
        AgentDefinition.id == agent_definition_id,
    ).with_for_update().first()
    if definition is None:
        raise not_found("Agent 配置不存在")
    if not definition.is_enabled:
        raise bad_request("所选 Agent 已停用")
    definition_revision = db.query(AgentDefinitionRevision).filter_by(
        agent_definition_id=definition.id, version=definition.version,
    ).first()
    if not workflow_matches(definition.workflow_template, target_type):
        raise bad_request("所选 Agent 工作流与任务执行类型不匹配")
    required_tools = required_tool_keys(target_type)
    missing_tools = required_tools - set(definition.tool_keys or [])
    if missing_tools:
        raise bad_request("所选 Agent 缺少当前任务所需的工具授权，请在 Agent 治理中心补齐权限")

    settings = dict(definition.settings_json or {})
    binding = settings.get("model_binding")
    requested_model_id = definition.model_config_id if binding in {None, "agent"} else None
    model = resolve_authorized_model(
        db, project_id, actor, requested_model_id=requested_model_id,
    )
    child_rows_from_db = db.query(AgentDefinition).filter(
        AgentDefinition.id.in_(definition.child_agent_ids or []),
    ).order_by(AgentDefinition.id).with_for_update().all() if definition.child_agent_ids else []
    child_by_id = {child.id: child for child in child_rows_from_db}
    child_rows = [child_by_id[child_id] for child_id in (definition.child_agent_ids or []) if child_id in child_by_id]
    if len(child_rows) != len(definition.child_agent_ids or []) or any(
        not child.is_enabled or child.child_agent_ids or child.tool_keys for child in child_rows
    ):
        raise bad_request("所选 Agent 的子 Agent 已停用或配置不再有效")
    skills_by_agent = snapshot_agent_skills(db, [definition, *child_rows])
    skills = skills_by_agent[definition.id]
    child_snapshots = []
    for child in child_rows:
        child_skills = skills_by_agent[child.id]
        child_model = resolve_authorized_model(
            db, project_id, actor,
            requested_model_id=child.model_config_id if child.model_config_id is not None else model.id,
        )
        child_model_snapshot = model_snapshot(child_model)
        child_revision = db.query(AgentDefinitionRevision).filter_by(
            agent_definition_id=child.id, version=child.version,
        ).first()
        child_snapshots.append({
            "knowledge": freeze(db, project_id, child.id, actor),
            "id": child.id,
            "revision_id": child_revision.id if child_revision else None,
            "key": child.key,
            "name": child.name,
            "version": child.version,
            "instruction": child.instruction,
            "model_config_id": child_model.id,
            "fallback_model_config_ids": child_model_snapshot.get("fallback_model_config_ids", []),
            "settings_json": dict(child.settings_json or {}),
            "skills": child_skills,
        })
    mcp_tools_snapshot = []
    resolved_tool_keys = list(configured_tool_paths(definition.tool_keys or [], skills))
    for tool_key in resolved_tool_keys:
        if not tool_key.startswith("mcp:"):
            continue
        try:
            _, server_id_text, tool_name = tool_key.split(":", 2)
            server = db.get(MCPServer, int(server_id_text))
        except (ValueError, TypeError):
            server = None
            tool_name = ""
        discovered = available_mcp_tool(server, tool_name)
        if discovered is None:
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
            "knowledge": freeze(db, project_id, definition.id, actor),
            "id": definition.id,
            "revision_id": definition_revision.id if definition_revision else None,
            "key": definition.key,
            "name": definition.name,
            "version": definition.version,
            "workflow_template": definition.workflow_template,
            "instruction": definition.instruction,
            "tool_keys": resolved_tool_keys,
            "settings_json": settings,
            "triggers_json": list(definition.triggers_json or []),
            "child_agent_ids": list(definition.child_agent_ids or []),
            "skills": skills,
            "child_agents": child_snapshots,
            "mcp_tools": mcp_tools_snapshot,
        },
    }
