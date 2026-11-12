"""Project root soft deletion preserves child assets and protects active work."""

from tests.conftest import unique


def _create_project(api, admin):
    response = api.post(
        "/projects", username=admin,
        json={"name": unique("project-lifecycle"), "description": "recoverable root"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_project_delete_restore_preserves_project_id_and_children(api, admin, db):
    from app.core.models.project import Project
    from app.features.test_management.models.test_case import TestCase

    project = _create_project(api, admin)
    case_response = api.post(
        f"/projects/{project['id']}/test-cases", username=admin,
        json={"name": unique("project-child-case")},
    )
    assert case_response.status_code == 201, case_response.text
    case_id = case_response.json()["id"]

    deleted = api.delete(f"/projects/{project['id']}", username=admin)
    assert deleted.status_code == 204, deleted.text
    assert all(row["id"] != project["id"] for row in api.get("/projects", username=admin).json()["items"])
    assert api.get(f"/projects/{project['id']}", username=admin).status_code == 404

    items = api.get(
        f"/recycle-bin?resource_type=project&project_id={project['id']}", username=admin,
    ).json()["items"]
    item = next(row for row in items if row["resource_id"] == str(project["id"]))
    assert item["project_id"] == project["id"]
    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert api.get(f"/projects/{project['id']}", username=admin).status_code == 200
    assert db.query(Project).filter_by(id=project["id"]).one().deleted_at is None
    assert db.query(TestCase).filter_by(id=case_id).one().deleted_at is None


def test_project_delete_blocks_running_task_and_batch_is_partial(api, admin, db):
    from app.core.models.identity import User
    from app.orchestration.tasks.models import Task

    blocked_project = _create_project(api, admin)
    free_project = _create_project(api, admin)
    actor = db.query(User).filter_by(username=admin).one()
    db.add(Task(
        project_id=blocked_project["id"], created_by=actor.id,
        title="active lifecycle guard", goal="keep project active", status="RUNNING",
    ))
    db.commit()

    receipt = api.post(
        "/resources/project/batch-delete", username=admin,
        json={"project_id": None, "ids": [blocked_project["id"], free_project["id"]]},
    )
    assert receipt.status_code == 200, receipt.text
    result = {row["id"]: row for row in receipt.json()["items"]}
    assert receipt.json()["succeeded"] == 1
    assert receipt.json()["failed"] == 1
    assert result[blocked_project["id"]]["succeeded"] is False
    assert "活跃或排队记录" in result[blocked_project["id"]]["error"]
    assert result[free_project["id"]]["succeeded"] is True


def test_project_delete_rejects_non_owner_and_permanent_purge_protects_children(api, admin, db):
    from app.core.models.identity import User
    from app.core.models.project import ProjectMember

    project = _create_project(api, admin)
    username = unique("project-viewer")
    registered = api.register(username)
    assert registered.status_code == 201, registered.text
    api.login(username)
    actor_id = db.query(User).filter_by(username=username).one().id
    member = api.put(
        f"/projects/{project['id']}/members/{actor_id}", username=admin,
        json={"user_id": actor_id, "role": "member"},
    )
    assert member.status_code in (200, 201), member.text
    denied = api.delete(f"/projects/{project['id']}", username=username)
    assert denied.status_code == 403
    assert db.query(ProjectMember).filter_by(project_id=project["id"], user_id=actor_id).one()

    assert api.delete(f"/projects/{project['id']}", username=admin).status_code == 204
    item = next(
        row for row in api.get("/recycle-bin?resource_type=project", username=admin).json()["items"]
        if row["resource_id"] == str(project["id"])
    )
    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200
    assert preview.json()["allowed"] is False
    assert any("外键资源" in dependency for dependency in preview.json()["dependencies"])
    assert db.query(ProjectMember).filter_by(project_id=project["id"]).count() == 1

