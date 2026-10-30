"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import re
from sqlalchemy.orm import Session
from app.agents.models import AgentDefinition
from app.mcp.models import MCPServer
from app.skills.models import SkillDefinition
from app.tools.catalog import TOOL_BY_KEY
from app.tools.models import ToolDefinitionOverride
from app.core.models.configuration import ModelConfiguration
from app.core.http.errors import bad_request


def validate_agent_links(
    db: Session,
    skill_keys: list[str],
    tool_keys: list[str],
    model_config_id: int | None,
    *,
    agent_enabled: bool,
    child_agent_ids: list[int],
    agent_id: int | None = None,
) -> None:
    """校验 Agent 关联的 Skill、内置/MCP 工具和最多一层的叶子子 Agent。"""
    if len(set(skill_keys)) != len(skill_keys) or len(set(tool_keys)) != len(tool_keys):
        raise bad_request("Skill 和工具不能重复关联")
    skills = db.query(SkillDefinition).filter(SkillDefinition.key.in_(skill_keys)).all() if skill_keys else []
    if len({row.key for row in skills}) != len(set(skill_keys)):
        raise bad_request("Agent 关联的 Skill 不存在")
    if agent_enabled and any(not row.is_enabled for row in skills):
        raise bad_request("启用 Agent 前，请先启用其关联的 Skill")
    mcp_refs: list[tuple[int, str]] = []
    unknown_tools = set()
    for key in set(tool_keys):
        if key in TOOL_BY_KEY:
            override = db.get(ToolDefinitionOverride, key)
            if override is not None and not override.is_enabled:
                raise bad_request(f"工具「{TOOL_BY_KEY[key]['name']}」已停用")
            continue
        match = re.fullmatch(r"mcp:(\d+):(.+)", key)
        if match:
            mcp_refs.append((int(match.group(1)), match.group(2)))
        else:
            unknown_tools.add(key)
    if unknown_tools:
        raise bad_request("Agent 包含平台未注册的工具")
    for server_id, tool_name in mcp_refs:
        server = db.get(MCPServer, server_id)
        if server is None:
            raise bad_request("Agent 关联的 MCP 服务不存在")
        discovered = {item.get("name"): item for item in (server.discovered_tools_json or [])}
        tool = discovered.get(tool_name)
        if tool is None:
            raise bad_request("Agent 关联的 MCP 工具未在最近发现结果中")
        if agent_enabled:
            if not server.is_enabled or server.connection_status != "connected" or tool_name not in (server.approved_tools_json or []):
                raise bad_request("启用 Agent 前，请确保 MCP 服务已启用、连接且工具获批")
            if (tool.get("annotations") or {}).get("readOnlyHint") is not True:
                raise bad_request("只有明确标注为只读的 MCP 工具可以由任务 Agent 自动调用")
    child_ids = list(dict.fromkeys(int(item) for item in child_agent_ids))
    if len(child_ids) != len(child_agent_ids) or len(child_ids) > 8:
        raise bad_request("子 Agent 不能重复，且最多选择 8 个")
    if agent_id is not None and agent_id in child_ids:
        raise bad_request("Agent 不能将自身配置为子 Agent")
    if child_ids:
        children = db.query(AgentDefinition).filter(AgentDefinition.id.in_(child_ids)).all()
        child_by_id = {item.id: item for item in children}
        if len(child_by_id) != len(child_ids):
            raise bad_request("所选子 Agent 不存在")
        if any(item.child_agent_ids for item in children):
            raise bad_request("子 Agent 目前只支持叶子节点，不能继续嵌套")
        if any(item.tool_keys for item in children):
            raise bad_request("子 Agent 当前只承担分析职责，请移除其工具授权后再关联")
        if agent_enabled and any(not item.is_enabled for item in children):
            raise bad_request("启用父 Agent 前，请先启用全部子 Agent")
    if agent_id is not None and child_agent_ids and any(
        agent_id in (item.child_agent_ids or [])
        for item in db.query(AgentDefinition).filter(AgentDefinition.id != agent_id).all()
    ):
        raise bad_request("已被其他 Agent 作为子节点引用的配置不能再嵌套子 Agent")
    if agent_id is not None and tool_keys and any(
        agent_id in (item.child_agent_ids or [])
        for item in db.query(AgentDefinition).filter(AgentDefinition.id != agent_id).all()
    ):
        raise bad_request("作为子 Agent 的配置只承担分析职责，不能授权工具")
    if model_config_id is not None:
        model = db.get(ModelConfiguration, model_config_id)
        if model is None:
            raise bad_request("所选模型配置不存在")
        if agent_enabled and not model.is_enabled:
            raise bad_request("启用 Agent 前，请先启用其关联的模型配置")
