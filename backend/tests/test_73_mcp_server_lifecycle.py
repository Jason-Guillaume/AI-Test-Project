"""MCP server deletion preserves approved configuration and execution history."""

from tests.conftest import unique


def _create_mcp(api, admin, name: str) -> dict:
    response = api.post(
        "/agent-governance/mcp-servers", username=admin,
        json={
            "name": name, "endpoint": "https://mcp.example.test/mcp",
            "auth_type": "bearer", "auth_token": "test-only-secret", "is_enabled": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_mcp_delete_restore_preserves_id_and_redacts_encrypted_credential(api, admin):
    server = _create_mcp(api, admin, unique("mcp-trash"))
    deleted = api.delete(f"/agent-governance/mcp-servers/{server['id']}", username=admin)
    assert deleted.status_code == 204, deleted.text
    assert all(row["id"] != server["id"] for row in api.get("/agent-governance/mcp-servers", username=admin).json())

    items = api.get("/recycle-bin?resource_type=mcp_server", username=admin).json()["items"]
    item = next(row for row in items if row["resource_id"] == str(server["id"]))
    detail = api.get(f"/recycle-bin/{item['id']}", username=admin).json()
    assert detail["resource_data"]["auth_secret_encrypted"] is None
    assert "test-only-secret" not in str(detail)

    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    visible = api.get("/agent-governance/mcp-servers", username=admin).json()
    assert any(row["id"] == server["id"] and row["has_auth"] for row in visible)


def test_mcp_delete_blocks_agent_reference_and_purge_protects_revision(api, admin):
    from app.core.database.session import SessionLocal
    from app.mcp.models import MCPServer

    server = _create_mcp(api, admin, unique("mcp-referenced"))
    with SessionLocal() as session:
        row = session.query(MCPServer).filter_by(id=server["id"]).one()
        row.discovered_tools_json = [{
            "name": "readonly_lookup", "annotations": {"readOnlyHint": True},
        }]
        session.commit()

    agent_name = unique("mcp-reference-agent")
    created = api.post(
        "/agent-governance/agents", username=admin,
        json={
            "name": agent_name, "description": "MCP lifecycle reference",
            "workflow_template": "api_test", "instruction": "Use the approved read-only MCP tool.",
            "skill_keys": [], "tool_keys": [f"mcp:{server['id']}:readonly_lookup"],
            "child_agent_ids": [], "is_enabled": False,
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    blocked = api.delete(f"/agent-governance/mcp-servers/{server['id']}", username=admin)
    assert blocked.status_code == 409
    assert "Agent 工具授权引用" in blocked.text

    removed = api.patch(
        f"/agent-governance/agents/{agent_id}", username=admin,
        json={"tool_keys": []},
    )
    assert removed.status_code == 200, removed.text
    assert api.delete(f"/agent-governance/mcp-servers/{server['id']}", username=admin).status_code == 204

    item = next(
        row for row in api.get("/recycle-bin?resource_type=mcp_server", username=admin).json()["items"]
        if row["resource_id"] == str(server["id"])
    )
    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200
    assert preview.json()["allowed"] is False
    assert any("Agent 历史修订" in dependency for dependency in preview.json()["dependencies"])
