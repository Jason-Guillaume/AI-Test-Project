"""内置工具目录配置服务。

本服务维护工具说明、参数说明覆写和启停状态；Agent 授权变更由 Agent 服务负责，避免工具域反向依赖 Agent。
"""
from __future__ import annotations
from typing import Any
from sqlalchemy.orm import Session
from app.tools.catalog import TOOL_BY_KEY
from app.tools.models import ToolDefinitionOverride
from app.tools.schemas import ToolDefinitionUpdate
from app.core.http.errors import bad_request, not_found


def apply_tool_override(db: Session, tool_key: str, body: ToolDefinitionUpdate, actor_id: int) -> ToolDefinitionOverride:
    """在调用方事务内更新单个工具目录覆写，不单独提交数据库事务。"""
    catalog_tool = TOOL_BY_KEY.get(tool_key)
    if catalog_tool is None:
        raise not_found("平台工具不存在")
    parameter_names = {item["name"] for item in catalog_tool.get("parameters", [])}
    context_names = {item["name"] for item in catalog_tool.get("runtime_details", {}).get("input_context", [])}
    unknown_names = set(body.parameter_overrides_json) - parameter_names - context_names
    if unknown_names:
        raise bad_request("只能覆写已登记参数或运行上下文字段说明")
    if any("default" in override for name, override in body.parameter_overrides_json.items() if name in context_names):
        raise bad_request("运行时上下文字段由平台注入，不能配置默认值")
    row = db.get(ToolDefinitionOverride, tool_key)
    if row is None:
        row = ToolDefinitionOverride(
            tool_key=tool_key,
            description=body.description,
            parameter_overrides_json=body.parameter_overrides_json,
            is_enabled=body.is_enabled,
            updated_by=actor_id,
        )
        db.add(row)
    else:
        row.description = body.description
        row.parameter_overrides_json = body.parameter_overrides_json
        row.is_enabled = body.is_enabled
        row.updated_by = actor_id
    return row


def restore_tool_override(db: Session, tool_key: str, actor_id: int) -> ToolDefinitionOverride | None:
    """恢复工具目录的代码默认值，不改变 Agent 授权，也不提交调用方事务。"""
    catalog_tool = TOOL_BY_KEY.get(tool_key)
    if catalog_tool is None:
        raise not_found("平台工具不存在")
    row = db.get(ToolDefinitionOverride, tool_key)
    if row is not None:
        row.description = catalog_tool["description"]
        row.parameter_overrides_json = {}
        row.is_enabled = True
        row.updated_by = actor_id
    return row
