"""治理页的只读配置投影，复用运行时工具路径和知识权限解析。"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agents.assembly.builder import available_mcp_tool, configured_tool_paths
from app.agents import services as agent_services
from app.agents.models import AgentDefinition
from app.core.http.errors import not_found
from app.knowledge.service import access, freeze
from app.mcp.models import MCPServer
from app.orchestration.tasks.services.assembly_service import agent_workflow_matches, required_agent_tools, resolve_authorized_model
from app.skills.loader import load_skill_files
from app.skills.models import SkillDefinition
from app.tools.builtin.case_generation.contracts import allowed_generation_tools


def _skill_ref(skill):
    """返回可公开的 Skill 标识、版本和状态。"""
    return {'key': skill.key, 'name': skill.name, 'version': skill.version, 'is_enabled': skill.is_enabled}


def _path_allows_tool(agent, key, parent):
    if parent is not None:
        return (parent.is_enabled and parent.workflow_template == 'case_generation'
                and agent.workflow_template == 'case_generation' and key in (agent.tool_keys or [])
                and allowed_generation_tools(agent.tool_keys or []))
    if key.startswith('mcp:'):
        return any(agent_workflow_matches(agent.workflow_template, target)
                   and required_agent_tools(target).issubset(agent.tool_keys or [])
                   for target in ('API', 'WEB', 'SECURITY'))
    return True


def _tool_paths(agent, skills, servers, builtins, *, parent=None, parent_options=()):
    """为每个去重工具键附加依赖链与当前配置可用状态。"""
    skill_keys = list(dict.fromkeys(agent.skill_keys or []))
    linked = [skills[key] for key in skill_keys if key in skills]
    refs = [dict(key=skill.key, mcp_tool_keys_json=skill.mcp_tool_keys_json) for skill in linked]
    skills_ready = len(linked) == len(skill_keys) and all(skill.is_enabled for skill in linked)
    rows = []
    for path in configured_tool_paths(agent.tool_keys or [], refs).values():
        key = path['key']
        server_id = None
        is_mcp = key.startswith('mcp:')
        if is_mcp:
            parts = key.split(':', 2)
            server_id = int(parts[1]) if len(parts) == 3 and parts[1].isdecimal() else None
            tool_ready = server_id is not None and available_mcp_tool(servers.get(server_id), parts[2]) is not None
        else:
            tool = builtins.get(key) or {}
            tool_ready = bool(tool.get('is_enabled') and (tool.get('runtime_details') or {}).get('executor_registered'))
        ready = bool(agent.is_enabled and skills_ready and tool_ready)
        row = {
            'key': key, 'server_id': server_id, 'direct': path['direct'],
            'skills': [_skill_ref(skills[skill_key]) for skill_key in path['skill_keys']],
            'available': ready and _path_allows_tool(agent, key, parent),
        }
        if parent_options:
            row['parent_paths'] = [{'id': item.id, 'name': item.name,
                                    'available': ready and _path_allows_tool(agent, key, item)}
                                   for item in parent_options]
        rows.append(row)
    return rows


def tool_dependencies(db: Session) -> list[dict]:
    """返回 MCP 和工具详情使用的 Agent 配置路径。"""
    skills = {skill.key: skill for skill in db.query(SkillDefinition).all()}
    servers = {server.id: server for server in db.query(MCPServer).all()}
    builtins = {tool['key']: tool for tool in agent_services.list_builtin_tools(db)}
    agents = db.query(AgentDefinition).order_by(AgentDefinition.id).all()
    parents = {}
    for agent in agents:
        for child_id in agent.child_agent_ids or []:
            parents.setdefault(child_id, []).append(agent)
    return [{'id': agent.id, 'name': agent.name,
             'tools': _tool_paths(agent, skills, servers, builtins, parent_options=parents.get(agent.id, []))}
            for agent in agents]


def effective_configuration(db: Session, agent_id: int, actor, project_id: int, parent_id: int | None) -> dict:
    """预览当前项目采用的模型、知识快照、Skill 文件及工具来源。"""
    access(db, project_id, actor)
    agent = db.get(AgentDefinition, agent_id)
    if agent is None:
        raise not_found('Agent 不存在')
    parent = db.get(AgentDefinition, parent_id) if parent_id is not None else None
    if parent_id is not None and (parent is None or agent.id not in (parent.child_agent_ids or [])):
        raise not_found('此主 Agent 未配置该子 Agent')
    skills = {row.key: row for row in db.query(SkillDefinition).filter(SkillDefinition.key.in_(agent.skill_keys or [])).all()}
    servers = {row.id: row for row in db.query(MCPServer).all()}
    builtins = {tool['key']: tool for tool in agent_services.list_builtin_tools(db)}
    warnings = []
    if not agent.is_enabled:
        warnings.append('Agent 已停用')
    if parent is not None and not parent.is_enabled:
        warnings.append('主 Agent 已停用')
    for key in agent.skill_keys or []:
        if key not in skills or not skills[key].is_enabled:
            warnings.append(f'Skill {key} 不存在或已停用')

    def fixed_model(definition):
        """读取通用路径或用例生成路径采用的显式模型绑定。"""
        binding = (definition.settings_json or {}).get('model_binding')
        if parent is not None and definition is agent and parent.workflow_template != 'case_generation':
            return definition.model_config_id
        if binding == 'agent' or (binding is None and definition.workflow_template != 'case_generation'):
            return definition.model_config_id
        return None

    model = None
    try:
        chosen = fixed_model(agent)
        inherited = parent is not None and chosen is None
        result = resolve_authorized_model(db, project_id, actor,
            requested_model_id=(fixed_model(parent) if inherited else chosen))
        model = {'id': result.id, 'label': result.label, 'name': result.model_name,
                 'source': 'parent' if inherited else 'agent' if chosen is not None else 'default'}
    except HTTPException as exc:
        warnings.append(str(exc.detail))
    knowledge = None
    try:
        knowledge = freeze(db, project_id, agent_id, actor)
    except HTTPException as exc:
        warnings.append(str(exc.detail))
    return {
        'agent_id': agent.id, 'version': agent.version, 'model': model, 'knowledge': knowledge, 'warnings': warnings,
        'skills': [{**_skill_ref(skills[key]), 'files': sorted(load_skill_files(skills[key]))}
                   for key in dict.fromkeys(agent.skill_keys or []) if key in skills],
        'tools': _tool_paths(agent, skills, servers, builtins, parent=parent),
    }
