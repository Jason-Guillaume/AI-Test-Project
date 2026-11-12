"""Agent 长期记忆按项目与 Agent 隔离、版本化更新并支持失效。"""

from tests.conftest import unique

from app.agents.models import AgentLongTermMemory
from app.agents.services.long_term_memory import retrieve_agent_memories


def _agent_payload(name: str) -> dict:
    return {
        "name": name, "description": "memory isolation test",
        "workflow_template": "api_test", "instruction": "按授权来源工作。",
        "model_config_id": None, "skill_keys": [], "tool_keys": [],
        "child_agent_ids": [], "is_enabled": False,
    }


def test_agent_memories_are_versioned_scoped_and_expirable(api, admin, db):
    project = api.post("/projects", username=admin, json={"name": unique("memory-project")})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    agent_payload = api.post(
        "/agent-governance/agents", username=admin, json=_agent_payload(unique("memory-agent")),
    )
    assert agent_payload.status_code == 201, agent_payload.text
    agent_id = agent_payload.json()["id"]
    other_payload = api.post(
        "/agent-governance/agents", username=admin, json=_agent_payload(unique("memory-agent")),
    )
    assert other_payload.status_code == 201, other_payload.text
    other_agent_id = other_payload.json()["id"]

    path = f"/projects/{project_id}/agents/{agent_id}/memories/payment-policy"
    created = api.put(path, username=admin, json={
        "content": "退款必须原路退回", "expected_version": 0,
    })
    assert created.status_code == 200, created.text
    assert created.json()["version"] == 1
    assert created.json()["source_refs"][0]["kind"] == "USER_PROVIDED"

    recalled = retrieve_agent_memories(db, project_id, agent_id, "退款")
    assert len(recalled) == 1
    assert recalled[0]["content"] == "退款必须原路退回"
    assert retrieve_agent_memories(db, project_id, other_agent_id, "退款") == []

    updated = api.put(path, username=admin, json={
        "content": "退款必须按原支付方式退回", "expected_version": 1,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert db.get(AgentLongTermMemory, created.json()["id"]).status == "SUPERSEDED"

    stale = api.put(path, username=admin, json={
        "content": "过期写入", "expected_version": 1,
    })
    assert stale.status_code == 409, stale.text

    expired = api.post(
        path + "/expire", username=admin,
        json={"expected_version": 2},
    )
    assert expired.status_code == 200, expired.text
    assert expired.json()["status"] == "EXPIRED"
    listed = api.get(path.rsplit("/", 1)[0], username=admin).json()["items"]
    assert len(listed) == 1 and listed[0]["status"] == "EXPIRED"
