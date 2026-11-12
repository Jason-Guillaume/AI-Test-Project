"""Recoverable Skill definitions while preserving config and execution history."""

from tests.conftest import unique


def _create_skill(api, admin, name: str) -> dict:
    response = api.post(
        "/agent-governance/skills", username=admin,
        json={"name": name, "content": "# Skill\nLifecycle test", "is_enabled": False},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_agent(api, admin, name: str, skill_key: str) -> dict:
    response = api.post(
        "/agent-governance/agents", username=admin,
        json={
            "name": name, "description": "Skill lifecycle test",
            "workflow_template": "api_test", "instruction": "Keep Skill association safe.",
            "skill_keys": [skill_key], "tool_keys": [], "child_agent_ids": [],
            "is_enabled": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_skill_delete_restore_preserves_original_id_and_revisions(api, admin, db):
    from app.skills.models import SkillDefinition, SkillDefinitionRevision

    skill = _create_skill(api, admin, unique("skill-trash"))
    updated = api.patch(
        f"/agent-governance/skills/{skill['id']}", username=admin,
        json={"description": "second immutable revision"},
    )
    assert updated.status_code == 200, updated.text

    deleted = api.delete(f"/agent-governance/skills/{skill['id']}", username=admin)
    assert deleted.status_code == 204, deleted.text
    assert all(row["id"] != skill["id"] for row in api.get("/agent-governance/skills", username=admin).json())

    items = api.get("/recycle-bin?resource_type=skill_definition", username=admin).json()["items"]
    item = next(row for row in items if row["resource_id"] == str(skill["id"]))
    assert item["can_restore"] is True
    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200
    assert preview.json()["allowed"] is False
    assert any("修订记录" in value for value in preview.json()["dependencies"])

    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert any(row["id"] == skill["id"] for row in api.get("/agent-governance/skills", username=admin).json())
    assert db.query(SkillDefinition).filter_by(id=skill["id"]).one().deleted_at is None
    assert db.query(SkillDefinitionRevision).filter_by(skill_definition_id=skill["id"]).count() == 2


def test_skill_batch_delete_returns_per_item_agent_reference_receipt(api, admin):
    referenced = _create_skill(api, admin, unique("skill-referenced"))
    independent = _create_skill(api, admin, unique("skill-independent"))
    agent = _create_agent(api, admin, unique("skill-reference-agent"), referenced["key"])

    response = api.post(
        "/resources/skill_definition/batch-delete", username=admin,
        json={"project_id": None, "ids": [referenced["id"], independent["id"]]},
    )
    assert response.status_code == 200, response.text
    receipt = {row["id"]: row for row in response.json()["items"]}
    assert response.json()["succeeded"] == 1
    assert response.json()["failed"] == 1
    assert receipt[referenced["id"]]["succeeded"] is False
    assert "Agent 配置引用" in receipt[referenced["id"]]["error"]
    assert receipt[independent["id"]]["succeeded"] is True

    update = api.patch(
        f"/agent-governance/agents/{agent['id']}", username=admin,
        json={"skill_keys": []},
    )
    assert update.status_code == 200, update.text
    assert api.delete(f"/agent-governance/skills/{referenced['id']}", username=admin).status_code == 204

    items = api.get("/recycle-bin?resource_type=skill_definition", username=admin).json()["items"]
    by_resource = {row["resource_id"]: row for row in items}
    restored = api.post(
        f"/recycle-bin/{by_resource[str(referenced['id'])]['id']}/restore", username=admin,
    )
    assert restored.status_code == 200, restored.text


def test_skill_delete_rejects_active_task_snapshot_and_preserves_history(api, admin, db):
    from app.core.models.identity import User
    from app.orchestration.tasks.models import Task, TaskRun

    skill = _create_skill(api, admin, unique("skill-active-run"))
    agent = _create_agent(api, admin, unique("skill-active-run-agent"), skill["key"])
    assert api.patch(
        f"/agent-governance/agents/{agent['id']}", username=admin,
        json={"skill_keys": []},
    ).status_code == 200
    project_response = api.post(
        "/projects", username=admin,
        json={"name": unique("skill-lifecycle-project"), "description": "Skill lifecycle"},
    )
    assert project_response.status_code == 201, project_response.text
    actor = db.query(User).filter_by(username=admin).one()
    task = Task(
        project_id=project_response.json()["id"], created_by=actor.id,
        title="Skill lifecycle guard", goal="preserve active snapshot",
    )
    db.add(task)
    db.flush()
    run = TaskRun(
        task_id=task.id, run_number=1, status="RUNNING", goal_snapshot="preserve active snapshot",
        input_snapshot={"agent_definition": {"skills": [{"key": skill["key"]}]}},
    )
    db.add(run)
    db.commit()

    blocked = api.delete(f"/agent-governance/skills/{skill['id']}", username=admin)
    assert blocked.status_code == 409
    assert "任务快照引用" in blocked.text

    run.status = "COMPLETED"
    task.status = "COMPLETED"
    db.commit()
    assert api.delete(f"/agent-governance/skills/{skill['id']}", username=admin).status_code == 204
    history = api.get("/agent-governance/skills", username=admin).json()
    assert all(row["id"] != skill["id"] for row in history)
