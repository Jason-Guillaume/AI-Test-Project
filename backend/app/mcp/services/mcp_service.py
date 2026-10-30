"""MCP 服务注册、发现、审批与只读调用服务。

保留 Streamable HTTP 实现、凭据加密和每次调用的当前审批复核；只允许明确标记为只读的已批准工具。
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Any
import httpx
from sqlalchemy.orm import Session
from app.mcp.schemas import MCPApprovalUpdate, MCPServerCreate, MCPServerUpdate
from app.mcp.client import _json_rpc_result, _mcp_post
from app.mcp.models import MCPServer
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.core.http.errors import bad_request, not_found


def _server_response(row: MCPServer) -> dict[str, Any]:
    """构造`server`响应数据。"""
    return {
        "id": row.id,
        "name": row.name,
        "endpoint": row.endpoint,
        "auth_type": row.auth_type,
        "has_auth": bool(row.auth_secret_encrypted),
        "is_enabled": row.is_enabled,
        "connection_status": row.connection_status,
        "discovered_tools_json": row.discovered_tools_json or [],
        "approved_tools_json": row.approved_tools_json or [],
        "last_checked_at": row.last_checked_at,
        "last_error": row.last_error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }

def list_mcp_servers(db: Session) -> list[dict[str, Any]]:
    """列出MCP`servers`。"""
    rows = db.query(MCPServer).order_by(MCPServer.updated_at.desc(), MCPServer.id.desc()).all()
    return [_server_response(row) for row in rows]

def create_mcp_server(db: Session, body: MCPServerCreate, actor_id: int) -> dict[str, Any]:
    """创建MCP服务端。"""
    row = MCPServer(
        name=body.name,
        endpoint=body.endpoint,
        auth_type=body.auth_type,
        auth_secret_encrypted=encrypt_secret(body.auth_token) if body.auth_type == "bearer" else None,
        is_enabled=body.is_enabled,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _server_response(row)

def update_mcp_server(db: Session, server_id: int, body: MCPServerUpdate, actor_id: int) -> dict[str, Any]:
    """更新MCP服务端。"""
    row = db.get(MCPServer, server_id)
    if row is None:
        raise not_found("MCP 服务不存在")
    changes = {key: value for key, value in body.model_dump(exclude_unset=True).items() if value is not None}
    token = changes.pop("auth_token", None)
    new_auth_type = changes.get("auth_type", row.auth_type)
    if new_auth_type == "bearer" and not (token or row.auth_secret_encrypted):
        raise bad_request("Bearer 认证需要填写访问令牌")
    credentials_changed = (
        ("endpoint" in changes and changes["endpoint"] != row.endpoint)
        or ("auth_type" in changes and changes["auth_type"] != row.auth_type)
        or bool(token)
    )
    if new_auth_type == "none":
        row.auth_secret_encrypted = None
    elif token:
        row.auth_secret_encrypted = encrypt_secret(token)
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_by = actor_id
    if credentials_changed:
        row.connection_status = "unknown"
        row.discovered_tools_json = []
        row.approved_tools_json = []
        row.last_error = None
    db.commit()
    db.refresh(row)
    return _server_response(row)

def remove_mcp_server(db: Session, server_id: int) -> None:
    """删除MCP服务端。"""
    row = db.get(MCPServer, server_id)
    if row is None:
        raise not_found("MCP 服务不存在")
    db.delete(row)
    db.commit()

def update_mcp_approvals(db: Session, server_id: int, body: MCPApprovalUpdate, actor_id: int) -> dict[str, Any]:
    """更新MCP`approvals`。"""
    row = db.get(MCPServer, server_id)
    if row is None:
        raise not_found("MCP 服务不存在")
    discovered = {item.get("name") for item in (row.discovered_tools_json or [])}
    if set(body.tool_names) - discovered:
        raise bad_request("只能批准本服务最近一次发现的工具")
    row.approved_tools_json = list(dict.fromkeys(body.tool_names))
    row.updated_by = actor_id
    db.commit()
    db.refresh(row)
    return _server_response(row)



def discover_mcp_tools(db: Session, server_id: int, actor_id: int) -> dict[str, Any]:
    """按 MCP Streamable HTTP 初始化并调用 tools/list；不会执行任何发现到的工具。"""
    row = db.get(MCPServer, server_id)
    if row is None:
        raise not_found("MCP 服务不存在")
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
        "Content-Type": "application/json",
    }
    if row.auth_type == "bearer":
        token = decrypt_secret(row.auth_secret_encrypted)
        if not token:
            raise bad_request("MCP Bearer 凭据无法解密，请重新保存凭据")
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=httpx.Timeout(12.0), follow_redirects=False) as client:
            initialize = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test-platform-admin", "version": "1.0"},
                },
            }
            init_response, init_result = _mcp_post(client, row, initialize, headers)
            session_id = init_response.headers.get("MCP-Session-Id")
            session_headers = dict(headers)
            if session_id:
                session_headers["MCP-Session-Id"] = session_id
            _mcp_post(client, row, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_headers)
            _, tools_result = _mcp_post(
                client, row,
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                session_headers,
            )
            tools = []
            for item in (tools_result or {}).get("tools", [])[:100]:
                name = item.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                tool = {"name": name[:128], "description": str(item.get("description", ""))[:1000]}
                annotations = item.get("annotations")
                if isinstance(annotations, dict):
                    tool["annotations"] = {
                        key: annotations[key]
                        for key in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
                        if isinstance(annotations.get(key), bool)
                    }
                schema = item.get("inputSchema")
                if isinstance(schema, dict) and len(json.dumps(schema, ensure_ascii=False)) <= 20000:
                    tool["inputSchema"] = schema
                tools.append(tool)
        row.discovered_tools_json = tools
        row.approved_tools_json = [name for name in (row.approved_tools_json or []) if name in {t["name"] for t in tools}]
        row.connection_status = "connected"
        row.last_error = None
        _ = init_result
    except Exception as exc:
        row.connection_status = "error"
        # 不把请求头、凭据、异常堆栈写入数据库或响应。
        row.last_error = str(exc).splitlines()[0][:500] or exc.__class__.__name__
        row.last_checked_at = datetime.utcnow()
        row.updated_by = actor_id
        db.commit()
        raise bad_request(f"MCP 连接或工具发现失败：{row.last_error}")
    row.last_checked_at = datetime.utcnow()
    row.updated_by = actor_id
    db.commit()
    db.refresh(row)
    return _server_response(row)

def invoke_approved_mcp_tool(
    db: Session, server_id: int, tool_name: str, arguments: dict[str, Any],
) -> dict[str, Any]:
    """仅调用当前已启用、已发现、已审批且明确只读的 MCP 工具。"""
    row = db.get(MCPServer, server_id)
    if row is None or not row.is_enabled or row.connection_status != "connected":
        raise RuntimeError("MCP 服务当前不可用")
    if tool_name not in (row.approved_tools_json or []):
        raise RuntimeError("MCP 工具当前未获管理员审批")
    discovered = next(
        (item for item in (row.discovered_tools_json or []) if item.get("name") == tool_name), None,
    )
    if discovered is None or (discovered.get("annotations") or {}).get("readOnlyHint") is not True:
        raise RuntimeError("MCP 自动执行仅允许明确标注为只读的工具")
    try:
        encoded_arguments = json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("MCP 工具参数不是有效 JSON") from exc
    if len(encoded_arguments.encode("utf-8")) > 64_000:
        raise RuntimeError("MCP 工具参数超过 64 KB 限制")

    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
        "Content-Type": "application/json",
    }
    if row.auth_type == "bearer":
        token = decrypt_secret(row.auth_secret_encrypted)
        if not token:
            raise RuntimeError("MCP Bearer 凭据无法解密")
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=httpx.Timeout(18.0), follow_redirects=False) as client:
            init_response, _ = _mcp_post(client, row, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "test-platform-task-agent", "version": "1.0"},
                },
            }, headers)
            if session_id := init_response.headers.get("MCP-Session-Id"):
                headers["MCP-Session-Id"] = session_id
            _mcp_post(client, row, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers)
            _, result = _mcp_post(client, row, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }, headers)
    except Exception as exc:  # noqa: BLE001 — 不将请求头或 MCP 凭据写入错误。
        raise RuntimeError(f"MCP 工具调用失败：{type(exc).__name__}") from exc
    if (result or {}).get("isError") is True:
        raise RuntimeError("MCP 工具执行返回错误")
    safe_result = result or {}
    if len(json.dumps(safe_result, ensure_ascii=False, default=str).encode("utf-8")) > 100_000:
        raise RuntimeError("MCP 工具结果超过 100 KB 限制")
    from app.core.security.sanitizer import sanitize_context

    return sanitize_context(safe_result)
