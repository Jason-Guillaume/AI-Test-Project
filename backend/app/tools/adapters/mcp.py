"""MCP 工具快照到 Planner 函数工具的固定适配。

函数名仍使用原 ``mcp_<server_id>_<digest>`` 规则，映射只基于运行快照中的已审批条目；
实际调用的凭据、当前审批复核与审计回执继续由 MCP 服务及任务 Worker 持有。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any


def build_mcp_function_tools(
    mcp_tools: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], list[dict[str, Any]]]:
    """构造 MCP Planner 工具定义和稳定函数名到快照记录的映射。"""
    by_function: dict[str, Mapping[str, Any]] = {}
    definitions: list[dict[str, Any]] = []
    for item in mcp_tools:
        digest = hashlib.sha256(str(item["key"]).encode("utf-8")).hexdigest()[:12]
        function_name = f"mcp_{int(item['server_id'])}_{digest}"
        by_function[function_name] = item
        definitions.append({
            "type": "function",
            "function": {
                "name": function_name,
                "description": f"{str(item.get('server_name') or 'MCP')} · {str(item.get('tool_name') or '')}：{str(item.get('description') or '')}"[:900],
                "parameters": item.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return by_function, definitions
