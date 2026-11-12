"""Recoverable deletion of Agent definitions with immutable runtime history."""

from tests.conftest import unique


def _agent_payload(name: str, *, children: list[int] | None = None) -> dict:
    return {
        "name": name,
        "description": "Agent lifecycle test",
        "workflow_template": "api_test",
        "instruction": "保留可恢复的 Agent 配置。",
        "skill_keys": [],
        "tool_keys": [],
        "child_agent_ids": children or [],
        "is_enabled": False,
    }


def _create_agent(api, admin, name: str, *, children: list[int] | None = None) -> dict:
    response = api.post(
        "/agent-governance/agents", username=admin,
        json=_agent_payload(name, children=children),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_agent_delete_restore_preserves_original_id_and_revisions(api, admin, db):
    from app.agents.models import AgentDefinition, AgentDefinitionRevision

    agent = _create_agent(api, admin, unique("agent-trash"))
    deleted = api.delete(f"/agent-governance/agents/{agent['id']}", username=admin)
    assert deleted.status_code == 204, deleted.text
    assert all(row["id"] != agent["id"] for row in api.get("/agent-governance/agents", username=admin).json())

    items = api.get("/recycle-bin?resource_type=agent_definition", username=admin).json()["items"]
    item = next(row for row in items if row["resource_id"] == str(agent["id"]))
    assert item["can_restore"] is True
    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200
    assert preview.json()["allowed"] is False
    assert any("修订记录" in value for value in preview.json()["dependencies"])

    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    visible = api.get("/agent-governance/agents", username=admin).json()
    assert next(row for row in visible if row["id"] == agent["id"])
    assert db.query(AgentDefinitionRevision).filter_by(agent_definition_id=agent["id"]).count() == 1
    assert db.query(AgentDefinition).filter_by(id=agent["id"]).one().deleted_at is None


def test_agent_batch_delete_returns_partial_parent_reference_receipt(api, admin):
    child = _create_agent(api, admin, unique("agent-child"))
    parent = _create_agent(api, admin, unique("agent-parent"), children=[child["id"]])

    response = api.post(
        "/resources/agent_definition/batch-delete", username=admin,
        json={"project_id": None, "ids": [child["id"], parent["id"]]},
    )
    assert response.status_code == 200, response.text
    receipt = {item["id"]: item for item in response.json()["items"]}
    assert response.json()["succeeded"] == 1
    assert response.json()["failed"] == 1
    assert receipt[child["id"]]["succeeded"] is False
    assert "父 Agent" in receipt[child["id"]]["error"]
    assert receipt[parent["id"]]["succeeded"] is True


def test_agent_delete_waits_for_active_run_and_restores_parent_dependency(api, admin, db):
    from app.agents.models import AgentDefinition
    from app.core.models.identity import User
    from app.orchestration.tasks.models import Task, TaskRun

    child = _create_agent(api, admin, unique("agent-run-child"))
    parent = _create_agent(api, admin, unique("agent-run-parent"), children=[child["id"]])
    project = api.post(
        "/projects", username=admin,
        json={"name": unique("agent-run-project"), "description": "Agent lifecycle"},
    )
    assert project.status_code == 201, project.text
    actor = db.query(User).filter_by(username=admin).one()
    task = Task(
        project_id=project.json()["id"], created_by=actor.id,
        agent_definition_id=parent["id"], title="Agent lifecycle guard", goal="test lifecycle",
    )
    db.add(task)
    db.flush()
    run = TaskRun(
        task_id=task.id, run_number=1, status="RUNNING", goal_snapshot="test lifecycle",
        input_snapshot={"agent_definition": {"id": parent["id"], "child_agents": [{"id": child["id"]}]}},
    )
    db.add(run)
    db.commit()

    active_delete = api.delete(f"/agent-governance/agents/{child['id']}", username=admin)
    assert active_delete.status_code == 409
    run.status = "COMPLETED"
    task.status = "COMPLETED"
    db.commit()

    assert api.delete(f"/agent-governance/agents/{parent['id']}", username=admin).status_code == 204
    assert api.delete(f"/agent-governance/agents/{child['id']}", username=admin).status_code == 204
    items = api.get("/recycle-bin?resource_type=agent_definition", username=admin).json()["items"]
    by_resource = {item["resource_id"]: item for item in items}

    parent_restore = api.post(f"/recycle-bin/{by_resource[str(parent['id'])]['id']}/restore", username=admin)
    assert parent_restore.status_code == 409
    assert "子 Agent" in parent_restore.text
    child_restore = api.post(f"/recycle-bin/{by_resource[str(child['id'])]['id']}/restore", username=admin)
    assert child_restore.status_code == 200, child_restore.text
    parent_restore = api.post(f"/recycle-bin/{by_resource[str(parent['id'])]['id']}/restore", username=admin)
    assert parent_restore.status_code == 200, parent_restore.text
    assert db.query(AgentDefinition).filter_by(id=parent["id"]).one().deleted_at is None
