"""Agent 运行快照与公开响应投影。

运行快照继续保存已解析的 Agent、子 Agent、Skill 与 MCP 元数据，供恢复任务使用；
对外任务响应只暴露版本与引用，不回传指令、Skill 正文或 MCP 输入 schema。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_agent_run_snapshot(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    """复制 Agent 解析结果中的运行快照，避免 ORM 对象或可变配置混入历史任务。"""
    if not bundle:
        return None
    return deepcopy(bundle["snapshot"])


def public_agent_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """生成任务详情可公开的 Agent 摘要，兼容缺少可选字段的旧运行快照。"""
    if not snapshot:
        return None
    return {
        "name": snapshot.get("name"),
        "version": snapshot.get("version"),
        "workflow_template": snapshot.get("workflow_template"),
        "tool_keys": list(snapshot.get("tool_keys") or []),
        "child_agent_ids": list(snapshot.get("child_agent_ids") or []),
        "child_agents": [
            {"id": child.get("id"), "name": child.get("name"), "version": child.get("version")}
            for child in (snapshot.get("child_agents") or [])
        ],
        "mcp_tools": [
            {"key": tool.get("key"), "server_name": tool.get("server_name"), "tool_name": tool.get("tool_name")}
            for tool in (snapshot.get("mcp_tools") or [])
        ],
        "skills": [
            {"key": skill.get("key"), "name": skill.get("name"), "version": skill.get("version")}
            for skill in (snapshot.get("skills") or [])
        ],
    }
