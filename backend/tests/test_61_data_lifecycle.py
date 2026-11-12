"""Core lifecycle contract: scoped soft deletion, partial batches, conflict-safe restore and audit."""

from __future__ import annotations

from tests.conftest import unique


def _project(api, admin, name=None):
    response = api.post("/projects", username=admin, json={"name": name or unique("lifecycle")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _case(api, admin, project_id, name=None, *, test_point_id=None):
    body = {"name": name or unique("lifecycle-case")}
    if test_point_id is not None:
        body["test_point_id"] = test_point_id
    response = api.post(
        f"/projects/{project_id}/test-cases", username=admin,
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _point(api, admin, project_id, name=None):
    response = api.post(
        f"/projects/{project_id}/test-points", username=admin,
        json={"name": name or unique("lifecycle-point")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_test_strategy_delete_reference_guard_and_restore_conflict(api, admin):
    project_id = _project(api, admin)
    strategy = api.post(
        f"/projects/{project_id}/test-strategies", username=admin,
        json={"name": unique("lifecycle-strategy")},
    ).json()
    point = api.post(
        f"/projects/{project_id}/test-points", username=admin,
        json={"name": unique("strategy-point"), "strategy_id": strategy["id"]},
    ).json()

    blocked = api.delete(f"/test-strategies/{strategy['id']}", username=admin)
    assert blocked.status_code == 409
    detached = api.patch(f"/test-points/{point['id']}", username=admin, json={"strategy_id": None})
    assert detached.status_code == 200 and detached.json()["strategy_id"] is None
    assert api.delete(f"/test-strategies/{strategy['id']}", username=admin).status_code == 204
    item = _trash_item(api, admin, project_id, "test_strategy", strategy["id"])

    replacement = api.post(
        f"/projects/{project_id}/test-strategies", username=admin,
        json={"name": strategy["name"]},
    )
    assert replacement.status_code == 201, replacement.text
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 409
    assert api.delete(f"/test-strategies/{replacement.json()['id']}", username=admin).status_code == 204
    replacement_item = _trash_item(api, admin, project_id, "test_strategy", replacement.json()["id"])
    assert api.client.request(
        "DELETE", f"/api/v1/recycle-bin/{replacement_item['id']}/permanent",
        headers=api.headers(admin),
        json={"confirmation": "PERMANENTLY_DELETE", "reason": "回归数据清理"},
    ).status_code == 200
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 200
    restored = api.get(f"/test-strategies/{strategy['id']}", username=admin)
    assert restored.status_code == 200 and restored.json()["id"] == strategy["id"]


def _trash_item(api, actor, project_id, resource_type, resource_id):
    response = api.get(
        "/recycle-bin", username=actor,
        params={"project_id": project_id, "resource_type": resource_type},
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["resource_id"] == str(resource_id))


def test_case_delete_recycle_restore_and_association_history(api, admin):
    project_id = _project(api, admin)
    suite = api.post(
        f"/projects/{project_id}/test-suites", username=admin,
        json={"name": unique("suite")},
    ).json()
    case_id = _case(api, admin, project_id)
    link = api.post(
        f"/test-suites/{suite['id']}/cases", username=admin,
        json={"test_case_id": case_id},
    )
    assert link.status_code == 201, link.text

    deleted = api.delete(f"/test-cases/{case_id}", username=admin)
    assert deleted.status_code == 204, deleted.text
    assert api.get(f"/test-cases/{case_id}", username=admin).status_code == 404
    assert all(row["id"] != case_id for row in api.get(f"/projects/{project_id}/test-cases", username=admin).json())

    item = _trash_item(api, admin, project_id, "test_case", case_id)
    detail = api.get(f"/recycle-bin/{item['id']}", username=admin)
    assert detail.status_code == 200, detail.text
    assert detail.json()["resource_data"]["id"] == case_id
    assert detail.json()["project_id"] == project_id
    assert detail.json()["deletion_batch_id"]

    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert api.get(f"/test-cases/{case_id}", username=admin).status_code == 200
    cases = api.get(f"/test-suites/{suite['id']}/cases", username=admin)
    assert any(row["test_case_id"] == case_id for row in cases.json())
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).json()["already_done"] is True

    repeated_delete = api.delete(f"/test-cases/{case_id}", username=admin)
    assert repeated_delete.status_code == 204
    audit = api.get(f"/recycle-bin/{item['id']}/audit", username=admin)
    assert audit.status_code == 200
    assert [event["event_type"] for event in audit.json()] == ["DELETE", "RESTORE", "RESTORE"]


def test_batch_delete_returns_partial_receipts_and_blocks_running_case(api, admin, db):
    from app.features.test_management.models.execution import CaseExecution, TestRun

    project_id = _project(api, admin)
    running_case = _case(api, admin, project_id)
    free_case = _case(api, admin, project_id)
    run = TestRun(project_id=project_id, status="RUNNING")
    db.add(run)
    db.flush()
    db.add(CaseExecution(test_run_id=run.id, test_case_id=running_case, status="RUNNING"))
    db.commit()

    response = api.post(
        "/resources/test_case/batch-delete", username=admin,
        json={"project_id": project_id, "ids": [running_case, free_case], "reason": "清理重复用例"},
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert (receipt["succeeded"], receipt["failed"]) == (1, 1)
    by_id = {item["id"]: item for item in receipt["items"]}
    assert "执行中的测试计划" in by_id[running_case]["error"]
    assert by_id[free_case]["succeeded"] is True
    assert api.get(f"/test-cases/{running_case}", username=admin).status_code == 200
    assert api.get(f"/test-cases/{free_case}", username=admin).status_code == 404
    assert _trash_item(api, admin, project_id, "test_case", free_case)


def test_restore_checks_trashed_dependency_and_purge_preserves_deleted_references(api, admin):
    project_id = _project(api, admin)
    point_id = _point(api, admin, project_id)
    case_id = _case(api, admin, project_id, test_point_id=point_id)

    assert api.delete(f"/test-cases/{case_id}", username=admin).status_code == 204
    assert api.delete(f"/test-points/{point_id}", username=admin).status_code == 204
    point_item = _trash_item(api, admin, project_id, "test_point", point_id)
    case_item = _trash_item(api, admin, project_id, "test_case", case_id)

    preview = api.get(f"/recycle-bin/{point_item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200
    assert preview.json()["allowed"] is False
    assert any("已删除" in dependency for dependency in preview.json()["dependencies"])

    restore_case_first = api.post(f"/recycle-bin/{case_item['id']}/restore", username=admin)
    assert restore_case_first.status_code == 409
    assert "先恢复该依赖" in restore_case_first.json()["message"]
    assert api.post(f"/recycle-bin/{point_item['id']}/restore", username=admin).status_code == 200
    assert api.post(f"/recycle-bin/{case_item['id']}/restore", username=admin).status_code == 200


def test_restore_name_conflict_returns_409_without_overwriting(api, admin):
    project_id = _project(api, admin)
    original_name = unique("same-name")
    original_id = _case(api, admin, project_id, original_name)
    assert api.delete(f"/test-cases/{original_id}", username=admin).status_code == 204
    item = _trash_item(api, admin, project_id, "test_case", original_id)

    replacement = _case(api, admin, project_id, original_name)
    conflict = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["meta"]["conflicting_resource"]["id"] == replacement
    assert api.get(f"/test-cases/{replacement}", username=admin).status_code == 200
    assert _trash_item(api, admin, project_id, "test_case", original_id)["can_restore"] is True

    assert api.delete(f"/test-cases/{replacement}", username=admin).status_code == 204
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 200
    assert api.get(f"/test-cases/{original_id}", username=admin).status_code == 200


def test_batch_restore_reports_partial_success_and_keeps_conflict_item(api, admin):
    project_id = _project(api, admin)
    conflicted_id = _case(api, admin, project_id, unique("restore-conflict"))
    clean_id = _case(api, admin, project_id)
    assert api.delete(f"/test-cases/{conflicted_id}", username=admin).status_code == 204
    assert api.delete(f"/test-cases/{clean_id}", username=admin).status_code == 204
    conflicted_item = _trash_item(api, admin, project_id, "test_case", conflicted_id)
    clean_item = _trash_item(api, admin, project_id, "test_case", clean_id)
    replacement_id = _case(api, admin, project_id, conflicted_item["display_name"])

    response = api.post(
        "/recycle-bin/batch-restore", username=admin,
        json={"item_ids": [conflicted_item["id"], clean_item["id"]]},
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert (receipt["succeeded"], receipt["failed"]) == (1, 1)
    assert api.get(f"/test-cases/{clean_id}", username=admin).status_code == 200
    still_trashed = api.get(f"/recycle-bin/{conflicted_item['id']}", username=admin)
    assert still_trashed.status_code == 200
    assert still_trashed.json()["deletion_status"] == "ACTIVE"

    assert api.delete(f"/test-cases/{replacement_id}", username=admin).status_code == 204
    retried = api.post(f"/recycle-bin/{conflicted_item['id']}/restore", username=admin)
    assert retried.status_code == 200, retried.text


def test_permanent_purge_requires_platform_admin_and_keeps_audit(api, admin):
    project_id = _project(api, admin)
    point_id = _point(api, admin, project_id)
    assert api.delete(f"/test-points/{point_id}", username=admin).status_code == 204
    item = _trash_item(api, admin, project_id, "test_point", point_id)

    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200, preview.text
    assert preview.json()["allowed"] is True
    user_name = unique("purge-denied")
    registered = api.register(user_name)
    assert registered.status_code == 201
    api.login(user_name)
    denied = api.client.request(
        "DELETE", f"/api/v1/recycle-bin/{item['id']}/permanent",
        headers=api.headers(user_name),
        json={"confirmation": "PERMANENTLY_DELETE", "reason": "测试"},
    )
    assert denied.status_code == 403

    purged = api.client.request(
        "DELETE", f"/api/v1/recycle-bin/{item['id']}/permanent",
        headers=api.headers(admin),
        json={"confirmation": "PERMANENTLY_DELETE", "reason": "已核验无依赖"},
    )
    assert purged.status_code == 200, purged.text
    assert api.get(f"/test-points/{point_id}", username=admin).status_code == 404
    status = api.get(f"/recycle-bin/{item['id']}", username=admin)
    assert status.status_code == 200
    assert status.json()["deletion_status"] == "PURGED"
    events = api.get(f"/recycle-bin/{item['id']}/audit", username=admin).json()
    assert events[-1]["event_type"] == "PURGE"


def test_project_scope_enforced_for_batch_delete_and_restore(api, admin):
    project_a = _project(api, admin)
    project_b = _project(api, admin)
    case_b = _case(api, admin, project_b)

    cross_project_delete = api.post(
        "/resources/test_case/batch-delete", username=admin,
        json={"project_id": project_a, "ids": [case_b]},
    )
    assert cross_project_delete.status_code == 200
    assert cross_project_delete.json()["items"][0]["succeeded"] is False
    assert api.get(f"/test-cases/{case_b}", username=admin).status_code == 200

    assert api.delete(f"/test-cases/{case_b}", username=admin).status_code == 204
    item = _trash_item(api, admin, project_b, "test_case", case_b)
    username = unique("lifecycle-member")
    user = api.register(username)
    assert user.status_code == 201, user.text
    user_id = user.json()["user"]["id"]
    api.login(username)
    add = api.put(
        f"/projects/{project_a}/members/{user_id}", username=admin,
        json={"user_id": user_id, "role": "member"},
    )
    assert add.status_code == 200, add.text

    hidden_list = api.get("/recycle-bin", username=username, params={"project_id": project_b})
    assert hidden_list.status_code == 404
    hidden_restore = api.post(f"/recycle-bin/{item['id']}/restore", username=username)
    assert hidden_restore.status_code == 404
    assert api.get(f"/test-cases/{case_b}", username=admin).status_code == 404


def test_viewer_cannot_delete_or_restore_project_assets(api, admin):
    project_id = _project(api, admin)
    case_id = _case(api, admin, project_id)
    username = unique("lifecycle-viewer")
    user = api.register(username)
    assert user.status_code == 201, user.text
    user_id = user.json()["user"]["id"]
    api.login(username)
    added = api.put(
        f"/projects/{project_id}/members/{user_id}", username=admin,
        json={"user_id": user_id, "role": "viewer"},
    )
    assert added.status_code == 200, added.text

    single = api.delete(f"/test-cases/{case_id}", username=username)
    assert single.status_code == 403
    batch = api.post(
        "/resources/test_case/batch-delete", username=username,
        json={"project_id": project_id, "ids": [case_id]},
    )
    assert batch.status_code == 403
    assert api.get(f"/test-cases/{case_id}", username=admin).status_code == 200

