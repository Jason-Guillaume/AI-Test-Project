"""Recoverable lifecycle behavior for knowledge catalog rows."""

from tests.conftest import unique


def _project(api, admin):
    response = api.post(
        "/projects", username=admin,
        json={"name": unique("knowledge-trash"), "description": "lifecycle"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _base(api, admin, project_id, name):
    response = api.post(
        f"/projects/{project_id}/knowledge-bases", username=admin, json={"name": name},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_knowledge_document_batch_delete_restore_keeps_versions(api, admin, db):
    from app.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion

    project_id = _project(api, admin)
    other_project_id = _project(api, admin)
    base = _base(api, admin, project_id, unique("knowledge-base"))
    ready = KnowledgeDocument(project_id=project_id, base_id=base["id"], name="ready.md", category="rules")
    queued = KnowledgeDocument(project_id=project_id, base_id=base["id"], name="queued.md", category="rules")
    db.add_all([ready, queued])
    db.flush()
    ready_version = KnowledgeVersion(
        document_id=ready.id, version=1, digest="a" * 64, filename="ready.md",
        content=b"retained source", status="READY", attempts=1,
    )
    queued_version = KnowledgeVersion(
        document_id=queued.id, version=1, digest="b" * 64, filename="queued.md",
        content=b"queued source", status="QUEUED", attempts=0,
    )
    db.add_all([ready_version, queued_version])
    db.flush()
    ready.current_version_id = ready_version.id
    db.add(KnowledgeChunk(version_id=ready_version.id, position=0, text="immutable retrieval evidence"))
    db.commit()

    wrong_project = api.post(
        "/resources/knowledge_document/batch-delete", username=admin,
        json={"project_id": other_project_id, "ids": [ready.id]},
    )
    assert wrong_project.status_code == 200
    assert wrong_project.json()["failed"] == 1
    assert wrong_project.json()["succeeded"] == 0

    deleted = api.post(
        "/resources/knowledge_document/batch-delete", username=admin,
        json={"project_id": project_id, "ids": [ready.id, queued.id]},
    )
    assert deleted.status_code == 200, deleted.text
    assert (deleted.json()["succeeded"], deleted.json()["failed"]) == (1, 1)
    assert "排队中的版本解析任务" in deleted.json()["items"][1]["error"]
    docs = api.get(
        f"/projects/{project_id}/knowledge-bases/{base['id']}/documents", username=admin,
    ).json()["items"]
    assert {item["id"] for item in docs} == {queued.id}

    recycle = api.get(
        f"/recycle-bin?project_id={project_id}&resource_type=knowledge_document", username=admin,
    )
    assert recycle.status_code == 200, recycle.text
    item = next(row for row in recycle.json()["items"] if row["resource_id"] == str(ready.id))
    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200 and not preview.json()["allowed"]
    assert any("知识版本" in text for text in preview.json()["dependencies"])

    restored = api.post("/recycle-bin/batch-restore", username=admin, json={"item_ids": [item["id"]]})
    assert restored.status_code == 200 and restored.json()["succeeded"] == 1, restored.text
    detail = api.get(
        f"/projects/{project_id}/knowledge-documents/{ready.id}/versions", username=admin,
    )
    assert detail.status_code == 200 and detail.json()["items"][0]["id"] == ready_version.id
    assert db.get(KnowledgeVersion, ready_version.id).content == b"retained source"
    assert db.query(KnowledgeChunk).filter_by(version_id=ready_version.id).count() == 1

    from app.orchestration.tasks.models import Task, TaskRun

    task = Task(project_id=project_id, title="knowledge lifecycle run", goal="use the frozen document")
    db.add(task)
    db.flush()
    run = TaskRun(
        task_id=task.id, run_number=1, status="RUNNING", stage="PLANNING",
        goal_snapshot=task.goal,
        input_snapshot={"agent_definition": {"knowledge": {"version_ids": [ready_version.id]}}},
    )
    db.add(run)
    db.flush()
    run.execution_root_run_id = run.id
    db.commit()
    while_running = api.post(
        "/resources/knowledge_document/batch-delete", username=admin,
        json={"project_id": project_id, "ids": [ready.id]},
    )
    assert while_running.status_code == 200 and while_running.json()["failed"] == 1
    assert "任务知识快照引用" in while_running.json()["items"][0]["error"]
    run.status = "SUCCEEDED"
    db.commit()
    after_run = api.post(
        "/resources/knowledge_document/batch-delete", username=admin,
        json={"project_id": project_id, "ids": [ready.id]},
    )
    assert after_run.status_code == 200 and after_run.json()["succeeded"] == 1

    blocked_parent = api.delete(
        f"/projects/{project_id}/knowledge-bases/{base['id']}", username=admin,
    )
    assert blocked_parent.status_code == 409
    assert api.get(f"/projects/{project_id}/knowledge-bases", username=admin).status_code == 200


def test_empty_knowledge_base_single_delete_and_restore_original_id(api, admin):
    project_id = _project(api, admin)
    base = _base(api, admin, project_id, unique("empty-knowledge"))
    deleted = api.delete(
        f"/projects/{project_id}/knowledge-bases/{base['id']}", username=admin,
    )
    assert deleted.status_code == 204, deleted.text
    visible = api.get(f"/projects/{project_id}/knowledge-bases", username=admin).json()["items"]
    assert all(row["id"] != base["id"] for row in visible)
    item = next(
        row for row in api.get(
            f"/recycle-bin?project_id={project_id}&resource_type=knowledge_base", username=admin,
        ).json()["items"] if row["resource_id"] == str(base["id"])
    )
    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    active = api.get(f"/projects/{project_id}/knowledge-bases", username=admin).json()["items"]
    assert any(row["id"] == base["id"] for row in active)
