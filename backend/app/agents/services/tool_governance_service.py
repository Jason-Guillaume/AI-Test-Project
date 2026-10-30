"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.agents.models import AgentDefinition, AgentDefinitionRevision
from app.tools.catalog import BUILTIN_TOOLS, TOOL_BY_KEY
from app.tools.models import ToolDefinitionOverride
from app.core.http.errors import bad_request, not_found
from app.tools.schemas import ToolDefinitionUpdate
from app.tools.services.tool_service import apply_tool_override, restore_tool_override
from app.agents.services.definition_service import agent_snapshot
from app.agents.services.link_validation import validate_agent_links


def list_builtin_tools(db: Session) -> list[dict[str, Any]]:
    """列出内置`tools`。"""
    overrides = {row.tool_key: row for row in db.query(ToolDefinitionOverride).all()}
    agents_by_tool: dict[str, list[int]] = {key: [] for key in TOOL_BY_KEY}
    for agent in db.query(AgentDefinition).all():
        for key in agent.tool_keys or []:
            if key in agents_by_tool:
                agents_by_tool[key].append(agent.id)
    result = []
    for tool in BUILTIN_TOOLS:
        override = overrides.get(tool["key"])
        parameter_overrides = (override.parameter_overrides_json or {}) if override else {}
        runtime_details = tool.get("runtime_details", {})
        parameters = [
            {
                **parameter,
                "description": parameter_overrides.get(parameter["name"], {}).get("description", parameter["description"]),
                **({"default": parameter_overrides[parameter["name"]]["default"]} if "default" in parameter_overrides.get(parameter["name"], {}) else {}),
            }
            for parameter in tool.get("parameters", [])
        ]
        runtime_details = {
            **runtime_details,
            "input_context": [
                {
                    **field,
                    "description": parameter_overrides.get(field["name"], {}).get("description", field["description"]),
                }
                for field in runtime_details.get("input_context", [])
            ],
        }
        result.append({
            **tool,
            "description": override.description if override else tool["description"],
            "parameter_overrides_json": parameter_overrides,
            "is_enabled": override.is_enabled if override else True,
            "agent_ids": agents_by_tool[tool["key"]],
            "parameters": parameters,
            "runtime_details": runtime_details,
        })
    return result


def update_builtin_tool(
    db: Session, tool_key: str, body: ToolDefinitionUpdate, actor_id: int,
) -> dict[str, Any]:
    """更新工具说明及 Agent 授权，并记录受影响 Agent 的新版本。"""
    if tool_key not in TOOL_BY_KEY:
        raise not_found("平台工具不存在")
    agents = db.query(AgentDefinition).all()
    agents_by_id = {agent.id: agent for agent in agents}
    selected_ids = set(body.agent_ids) if body.is_enabled else set()
    if selected_ids - agents_by_id.keys():
        raise bad_request("所选 Agent 不存在")
    updates: list[tuple[AgentDefinition, list[str]]] = []
    for agent in agents:
        current_keys = list(agent.tool_keys or [])
        has_tool = tool_key in current_keys
        should_have_tool = agent.id in selected_ids
        if has_tool == should_have_tool:
            continue
        next_keys = current_keys if should_have_tool else [key for key in current_keys if key != tool_key]
        if should_have_tool:
            next_keys.append(tool_key)
            validate_agent_links(
                db, agent.skill_keys or [], next_keys, agent.model_config_id,
                agent_enabled=agent.is_enabled, child_agent_ids=agent.child_agent_ids or [],
                agent_id=agent.id,
            )
        updates.append((agent, next_keys))
    # 工具覆写与 Agent 修订共享 Session，确保授权和工具状态一并提交。
    apply_tool_override(db, tool_key, body, actor_id)
    for agent, tool_keys in updates:
        agent.tool_keys = tool_keys
        agent.version += 1
        agent.updated_by = actor_id
        db.add(AgentDefinitionRevision(
            agent_definition_id=agent.id, version=agent.version,
            snapshot_json=agent_snapshot(agent), created_by=actor_id,
        ))
    db.commit()
    return next(item for item in list_builtin_tools(db) if item["key"] == tool_key)


def restore_builtin_tool_defaults(db: Session, tool_key: str, actor_id: int) -> dict[str, Any]:
    """恢复工具目录默认值，不改变 Agent 授权列表。"""
    override = restore_tool_override(db, tool_key, actor_id)
    if override is not None:
        db.commit()
    return next(item for item in list_builtin_tools(db) if item["key"] == tool_key)
