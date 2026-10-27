"""Agent 治理配置 CRUD、引用校验与 MCP 只读工具发现。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.agent_governance.catalog import BUILTIN_TOOLS, TOOL_BY_KEY
from app.features.agent_governance.schemas import (
    AgentDefinitionCreate,
    AgentDefinitionUpdate,
    MCPApprovalUpdate,
    MCPServerCreate,
    MCPServerUpdate,
    SkillCreate,
    SkillUpdate,
)
from app.features.agent_governance.models import (
    AgentDefinition,
    AgentDefinitionRevision,
    MCPServer,
    SkillDefinition,
    SkillDefinitionRevision,
)
from app.models.configuration import ModelConfiguration
from app.shared.crypto import decrypt_secret, encrypt_secret
from app.shared.errors import bad_request, conflict, not_found


def _validate_agent_links(
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


def _agent_snapshot(row: AgentDefinition) -> dict[str, Any]:
    """生成智能体定义的版本快照。"""
    return {
        "name": row.name,
        "description": row.description,
        "workflow_template": row.workflow_template,
        "instruction": row.instruction,
        "model_config_id": row.model_config_id,
        "skill_keys": row.skill_keys or [],
        "tool_keys": row.tool_keys or [],
        "child_agent_ids": row.child_agent_ids or [],
        "is_enabled": row.is_enabled,
    }


def _skill_snapshot(row: SkillDefinition) -> dict[str, Any]:
    """生成技能定义的版本快照。"""
    return {
        "name": row.name,
        "description": row.description,
        "content": row.content,
        "is_enabled": row.is_enabled,
    }


def list_agents(db: Session) -> list[AgentDefinition]:
    """列出`agents`。"""
    return db.query(AgentDefinition).order_by(AgentDefinition.updated_at.desc(), AgentDefinition.id.desc()).all()


def create_agent(db: Session, body: AgentDefinitionCreate, actor_id: int) -> AgentDefinition:
    """创建智能体。"""
    _validate_agent_links(
        db, body.skill_keys, body.tool_keys, body.model_config_id,
        agent_enabled=body.is_enabled, child_agent_ids=body.child_agent_ids,
    )
    row = AgentDefinition(
        key=str(uuid.uuid4()),
        **body.model_dump(),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(row)
    db.flush()
    db.add(AgentDefinitionRevision(
        agent_definition_id=row.id,
        version=row.version,
        snapshot_json=_agent_snapshot(row),
        created_by=actor_id,
    ))
    db.commit()
    db.refresh(row)
    return row


def update_agent(db: Session, agent_id: int, body: AgentDefinitionUpdate, actor_id: int) -> AgentDefinition:
    """更新智能体。"""
    row = db.get(AgentDefinition, agent_id)
    if row is None:
        raise not_found("Agent 配置不存在")
    changes = body.model_dump(exclude_unset=True)
    changes = {
        key: value for key, value in changes.items()
        if value is not None or key in {"model_config_id", "skill_keys", "tool_keys"}
    }
    if changes.get("is_enabled") is False and any(
        row.id in (parent.child_agent_ids or []) and parent.is_enabled
        for parent in db.query(AgentDefinition).filter(AgentDefinition.id != row.id).all()
    ):
        raise conflict("该 Agent 正被启用中的父 Agent 使用，请先停用父 Agent 或移除引用")
    for key in ("skill_keys", "tool_keys"):
        if key in changes and changes[key] is None:
            changes[key] = []
    _validate_agent_links(
        db,
        changes.get("skill_keys", row.skill_keys or []) or [],
        changes.get("tool_keys", row.tool_keys or []) or [],
        changes.get("model_config_id", row.model_config_id),
        agent_enabled=changes.get("is_enabled", row.is_enabled),
        child_agent_ids=changes.get("child_agent_ids", row.child_agent_ids or []) or [],
        agent_id=row.id,
    )
    if changes:
        for key, value in changes.items():
            setattr(row, key, value)
        row.version += 1
        row.updated_by = actor_id
        db.add(AgentDefinitionRevision(
            agent_definition_id=row.id,
            version=row.version,
            snapshot_json=_agent_snapshot(row),
            created_by=actor_id,
        ))
        db.commit()
        db.refresh(row)
    return row


def agent_versions(db: Session, agent_id: int) -> list[AgentDefinitionRevision]:
    """列出智能体定义的历史版本。"""
    if db.get(AgentDefinition, agent_id) is None:
        raise not_found("Agent 配置不存在")
    return db.query(AgentDefinitionRevision).filter(
        AgentDefinitionRevision.agent_definition_id == agent_id
    ).order_by(AgentDefinitionRevision.version.desc()).all()


def delete_agent(db: Session, agent_id: int) -> None:
    """删除智能体。"""
    row = db.get(AgentDefinition, agent_id)
    if row is None:
        raise not_found("Agent 配置不存在")
    if any(agent_id in (item.child_agent_ids or []) for item in db.query(AgentDefinition).filter(AgentDefinition.id != agent_id).all()):
        raise conflict("该 Agent 已被其他 Agent 配置为子节点，请先移除引用")
    db.delete(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("已有任务绑定此 Agent，请停用配置而不是删除") from exc


def list_skills(db: Session) -> list[SkillDefinition]:
    """列出`skills`。"""
    return db.query(SkillDefinition).order_by(SkillDefinition.updated_at.desc(), SkillDefinition.id.desc()).all()


def create_skill(db: Session, body: SkillCreate, actor_id: int) -> SkillDefinition:
    """创建`skill`。"""
    row = SkillDefinition(key=str(uuid.uuid4()), **body.model_dump(), created_by=actor_id, updated_by=actor_id)
    db.add(row)
    db.flush()
    db.add(SkillDefinitionRevision(
        skill_definition_id=row.id,
        version=row.version,
        snapshot_json=_skill_snapshot(row),
        created_by=actor_id,
    ))
    db.commit()
    db.refresh(row)
    return row


def update_skill(db: Session, skill_id: int, body: SkillUpdate, actor_id: int) -> SkillDefinition:
    """更新`skill`。"""
    row = db.get(SkillDefinition, skill_id)
    if row is None:
        raise not_found("Skill 不存在")
    changes = {key: value for key, value in body.model_dump(exclude_unset=True).items() if value is not None}
    if changes.get("is_enabled") is False:
        if any(row.is_enabled and skill.key in (row.skill_keys or []) for row in db.query(AgentDefinition).all()):
            raise conflict("该 Skill 正被启用中的 Agent 使用，请先停用 Agent 或移除引用")
    if changes:
        for key, value in changes.items():
            setattr(row, key, value)
        row.version += 1
        row.updated_by = actor_id
        db.add(SkillDefinitionRevision(
            skill_definition_id=row.id,
            version=row.version,
            snapshot_json=_skill_snapshot(row),
            created_by=actor_id,
        ))
        db.commit()
        db.refresh(row)
    return row


def skill_versions(db: Session, skill_id: int) -> list[SkillDefinitionRevision]:
    """列出技能定义的历史版本。"""
    if db.get(SkillDefinition, skill_id) is None:
        raise not_found("Skill 不存在")
    return db.query(SkillDefinitionRevision).filter(
        SkillDefinitionRevision.skill_definition_id == skill_id
    ).order_by(SkillDefinitionRevision.version.desc()).all()


def delete_skill(db: Session, skill_id: int) -> None:
    """删除`skill`。"""
    row = db.get(SkillDefinition, skill_id)
    if row is None:
        raise not_found("Skill 不存在")
    if any(row.key in (agent.skill_keys or []) for agent in db.query(AgentDefinition).all()):
        raise conflict("该 Skill 已被 Agent 引用，请先从 Agent 配置中移除")
    db.delete(row)
    db.commit()


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


def delete_mcp_server(db: Session, server_id: int) -> None:
    """删除MCP服务端。"""
    row = db.get(MCPServer, server_id)
    if row is None:
        raise not_found("MCP 服务不存在")
    prefix = f"mcp:{server_id}:"
    if any(
        any(str(key).startswith(prefix) for key in (agent.tool_keys or []))
        for agent in db.query(AgentDefinition).all()
    ):
        raise conflict("该 MCP 服务仍被 Agent 引用，请先移除 Agent 工具授权；紧急停用可直接关闭服务")
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
    from app.features.agent.providers.sanitizer import sanitize_context

    return sanitize_context(safe_result)


def list_builtin_tools() -> list[dict[str, str]]:
    """列出内置`tools`。"""
    return BUILTIN_TOOLS
