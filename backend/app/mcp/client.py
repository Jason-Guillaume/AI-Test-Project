"""MCP Streamable HTTP 协议客户端辅助实现。

本模块仅处理当前已使用的 JSON-RPC 请求与响应解析；连接凭据、审批和工具调用范围由 ``mcp.services`` 复核。
"""
from __future__ import annotations
import json
import httpx
from app.mcp.models import MCPServer


def _json_rpc_result(response: httpx.Response) -> dict[str, Any]:
    """解析 JSON-RPC 响应结果。"""
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("MCP 响应超过 2 MB 限制")
    content_type = response.headers.get("content-type", "").lower()
    candidates: list[str] = []
    if "text/event-stream" in content_type:
        data_lines: list[str] = []
        for line in response.text.splitlines() + [""]:
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif not line and data_lines:
                candidates.append("\n".join(data_lines))
                data_lines.clear()
    else:
        candidates.append(response.text)
    for candidate in candidates:
        if not candidate or candidate == "[DONE]":
            continue
        payload = json.loads(candidate)
        if isinstance(payload, dict) and ("result" in payload or "error" in payload):
            if "error" in payload:
                raise ValueError(str(payload["error"].get("message", "MCP 返回 JSON-RPC 错误"))[:400])
            return payload.get("result") or {}
    raise ValueError("MCP 服务没有返回有效的 JSON-RPC 响应")

def _mcp_post(client: httpx.Client, row: MCPServer, payload: dict[str, Any], headers: dict[str, str]) -> tuple[httpx.Response, dict[str, Any] | None]:
    """向 MCP 服务发送 POST 请求。"""
    response = client.post(row.endpoint, json=payload, headers=headers)
    response.raise_for_status()
    if payload.get("id") is None:
        return response, None
    return response, _json_rpc_result(response)
