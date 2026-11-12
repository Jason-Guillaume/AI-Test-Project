"""Business management assets participate in the shared recoverable lifecycle."""

from tests.conftest import unique


def _project(api, admin):
    response = api.post("/projects", username=admin, json={"name": unique("business-lifecycle")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _domain(api, admin, project_id, name=None):
    response = api.post(
        f"/projects/{project_id}/business-domains", username=admin,
        json={"name": name or unique("domain"), "status": "ACTIVE", "sort": 0},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _flow(api, admin, project_id, domain_id, name=None):
    response = api.post(
        f"/projects/{project_id}/business-flows", username=admin,
        json={"name": name or unique("flow"), "domain_id": domain_id, "status": "DRAFT"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _action(api, admin, flow_id, key=None):
    response = api.post(
        f"/business-flows/{flow_id}/actions", username=admin,
        json={"name": unique("action"), "action_key": key or unique("key"), "action_type": "NORMAL"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _trash_item(api, admin, project_id, resource_type, resource_id):
    response = api.get(
        "/recycle-bin", username=admin,
        params={"project_id": project_id, "resource_type": resource_type},
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["resource_id"] == str(resource_id))


def test_business_parent_delete_requires_explicit_child_handling_and_restores_original_ids(api, admin):
    project_id = _project(api, admin)
    domain_id = _domain(api, admin, project_id)
    flow_id = _flow(api, admin, project_id, domain_id)
    action_id = _action(api, admin, flow_id)

    blocked = api.delete(f"/business-flows/{flow_id}", username=admin)
    assert blocked.status_code == 409, blocked.text
    assert api.get(f"/business-flows/{flow_id}", username=admin).status_code == 200

    assert api.delete(f"/business-actions/{action_id}", username=admin).status_code == 204
    assert api.delete(f"/business-flows/{flow_id}", username=admin).status_code == 204
    assert api.delete(f"/business-domains/{domain_id}", username=admin).status_code == 204
    assert api.get(f"/business-domains/{domain_id}", username=admin).status_code == 404

    domain_item = _trash_item(api, admin, project_id, "business_domain", domain_id)
    flow_item = _trash_item(api, admin, project_id, "business_flow", flow_id)
    action_item = _trash_item(api, admin, project_id, "business_action", action_id)
    assert api.post(f"/recycle-bin/{flow_item['id']}/restore", username=admin).status_code == 409
    assert api.post(f"/recycle-bin/{domain_item['id']}/restore", username=admin).status_code == 200
    assert api.post(f"/recycle-bin/{flow_item['id']}/restore", username=admin).status_code == 200
    assert api.post(f"/recycle-bin/{action_item['id']}/restore", username=admin).status_code == 200
    restored_actions = api.get(f"/business-flows/{flow_id}/actions", username=admin)
    assert restored_actions.status_code == 200, restored_actions.text
    assert any(action["id"] == action_id for action in restored_actions.json())


def test_business_batch_delete_returns_per_resource_dependency_results(api, admin):
    project_id = _project(api, admin)
    domain_id = _domain(api, admin, project_id)
    blocked_flow = _flow(api, admin, project_id, domain_id)
    free_flow = _flow(api, admin, project_id, domain_id)
    _action(api, admin, blocked_flow)

    response = api.post(
        "/resources/business_flow/batch-delete", username=admin,
        json={"project_id": project_id, "ids": [blocked_flow, free_flow], "reason": "清理无用流程"},
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert (receipt["succeeded"], receipt["failed"]) == (1, 1)
    by_id = {item["id"]: item for item in receipt["items"]}
    assert "业务流程下仍有动作" in by_id[blocked_flow]["error"]
    assert by_id[free_flow]["succeeded"] is True
    assert api.get(f"/business-flows/{blocked_flow}", username=admin).status_code == 200
    assert api.get(f"/business-flows/{free_flow}", username=admin).status_code == 404
    _trash_item(api, admin, project_id, "business_flow", free_flow)


def test_business_name_can_be_reused_but_restore_reports_conflict(api, admin):
    project_id = _project(api, admin)
    domain_name = unique("same-domain")
    original_id = _domain(api, admin, project_id, domain_name)
    assert api.delete(f"/business-domains/{original_id}", username=admin).status_code == 204
    item = _trash_item(api, admin, project_id, "business_domain", original_id)

    replacement_id = _domain(api, admin, project_id, domain_name)
    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 409, restored.text
    assert restored.json()["meta"]["conflicting_resource"]["id"] == replacement_id
    assert api.get(f"/business-domains/{replacement_id}", username=admin).status_code == 200


def test_suite_plan_trash_preserves_links_and_restores_dependencies_in_order(api, admin):
    project_id = _project(api, admin)
    suite_response = api.post(
        f"/projects/{project_id}/test-suites", username=admin,
        json={"name": unique("suite"), "suite_type": "REGRESSION", "enabled": True},
    )
    assert suite_response.status_code == 201, suite_response.text
    suite_id = suite_response.json()["id"]
    plan_response = api.post(
        f"/projects/{project_id}/test-plans", username=admin,
        json={"name": unique("plan"), "status": "DRAFT", "execution_mode": "MANUAL"},
    )
    assert plan_response.status_code == 201, plan_response.text
    plan_id = plan_response.json()["id"]
    link_response = api.post(
        f"/test-plans/{plan_id}/suites", username=admin,
        json={"suite_id": suite_id, "sort": 0},
    )
    assert link_response.status_code == 201, link_response.text
    link_id = link_response.json()["id"]

    assert api.delete(f"/test-suites/{suite_id}", username=admin).status_code == 204
    assert api.delete(f"/test-plans/{plan_id}", username=admin).status_code == 204
    assert api.get(f"/test-suites/{suite_id}", username=admin).status_code == 404
    assert api.get(f"/test-plans/{plan_id}", username=admin).status_code == 404

    suite_item = _trash_item(api, admin, project_id, "test_suite", suite_id)
    plan_item = _trash_item(api, admin, project_id, "test_plan", plan_id)
    assert api.post(f"/recycle-bin/{plan_item['id']}/restore", username=admin).status_code == 409
    assert api.post(f"/recycle-bin/{suite_item['id']}/restore", username=admin).status_code == 200
    assert api.post(f"/recycle-bin/{plan_item['id']}/restore", username=admin).status_code == 200
    restored_links = api.get(f"/test-plans/{plan_id}/suites", username=admin)
    assert restored_links.status_code == 200, restored_links.text
    assert any(link["id"] == link_id and link["suite_id"] == suite_id for link in restored_links.json())


def test_running_test_plan_cannot_be_deleted(api, admin, db):
    from app.features.test_management.models.execution import TestRun

    project_id = _project(api, admin)
    plan_response = api.post(
        f"/projects/{project_id}/test-plans", username=admin,
        json={"name": unique("running-plan"), "status": "DRAFT", "execution_mode": "MANUAL"},
    )
    assert plan_response.status_code == 201, plan_response.text
    plan_id = plan_response.json()["id"]
    db.add(TestRun(project_id=project_id, plan_id=plan_id, status="RUNNING"))
    db.commit()

    deleted = api.delete(f"/test-plans/{plan_id}", username=admin)
    assert deleted.status_code == 409, deleted.text
    assert api.get(f"/test-plans/{plan_id}", username=admin).status_code == 200

