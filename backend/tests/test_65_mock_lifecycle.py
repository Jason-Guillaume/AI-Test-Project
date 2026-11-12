"""Mock assets retain their identifiers, runtime secrets and immutable call evidence."""

from tests.conftest import unique


def _project(api, admin):
    response = api.post("/projects", username=admin, json={"name": unique("mock-trash")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _mock_tree(api, admin, project_id):
    service_response = api.post(
        f"/projects/{project_id}/mock-services", username=admin,
        json={"name": unique("mock-service"), "service_key": f"TRASH_{unique('key').replace('-', '_').upper()}"},
    )
    assert service_response.status_code == 201, service_response.text
    service = service_response.json()["service"]
    endpoint_response = api.post(
        f"/mock-services/{service['id']}/endpoints", username=admin,
        json={"name": unique("mock-endpoint"), "method": "GET", "path": f"/{unique('path')}"},
    )
    assert endpoint_response.status_code == 201, endpoint_response.text
    endpoint = endpoint_response.json()
    key = f"CASE_{unique('scenario').replace('-', '_').upper()}"
    scenario_response = api.post(
        f"/mock-endpoints/{endpoint['id']}/scenarios", username=admin,
        json={"name": key, "scenario_key": key, "behavior_type": "STATIC_RESPONSE", "status_code": 200},
    )
    assert scenario_response.status_code == 201, scenario_response.text
    return service, endpoint, scenario_response.json()


def _trash_item(api, admin, project_id, resource_type, resource_id):
    response = api.get(
        "/recycle-bin", username=admin,
        params={"project_id": project_id, "resource_type": resource_type},
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["resource_id"] == str(resource_id))


def test_mock_assets_soft_delete_restore_conflicts_and_protect_execution_history(api, admin, db):
    from app.features.mocking.models import MockExecution

    project_id = _project(api, admin)
    service, endpoint, scenario = _mock_tree(api, admin, project_id)
    db.add(MockExecution(
        project_id=project_id, mock_service_id=service["id"], mock_endpoint_id=endpoint["id"],
        mock_scenario_id=scenario["id"], method="GET", path=endpoint["path"], matched=True,
    ))
    db.commit()

    assert api.delete(f"/mock-services/{service['id']}", username=admin).status_code == 409
    assert api.delete(f"/mock-endpoints/{endpoint['id']}", username=admin).status_code == 409
    deleted = api.delete(f"/mock-scenarios/{scenario['id']}", username=admin)
    assert deleted.status_code == 204, deleted.text
    assert api.get(f"/mock-scenarios/{scenario['id']}", username=admin).status_code == 404
    assert api.get(f"/mock-endpoints/{endpoint['id']}/scenarios", username=admin).json()["total"] == 0

    original_item = _trash_item(api, admin, project_id, "mock_scenario", scenario["id"])
    detail = api.get(f"/recycle-bin/{original_item['id']}", username=admin)
    assert detail.status_code == 200
    assert detail.json()["resource_data"]["id"] == scenario["id"]
    preview = api.get(f"/recycle-bin/{original_item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200 and preview.json()["allowed"] is False
    assert any("调用历史" in text for text in preview.json()["dependencies"])

    replacement = api.post(
        f"/mock-endpoints/{endpoint['id']}/scenarios", username=admin,
        json={"name": scenario["name"], "scenario_key": scenario["scenario_key"],
              "behavior_type": "STATIC_RESPONSE", "status_code": 201},
    )
    assert replacement.status_code == 201, replacement.text
    conflict = api.post(f"/recycle-bin/{original_item['id']}/restore", username=admin)
    assert conflict.status_code == 409
    assert conflict.json()["meta"]["conflicting_resource"]["id"] == replacement.json()["id"]

    assert api.delete(f"/mock-scenarios/{replacement.json()['id']}", username=admin).status_code == 204
    replacement_item = _trash_item(api, admin, project_id, "mock_scenario", replacement.json()["id"])
    purged = api.client.request(
        "DELETE", f"/api/v1/recycle-bin/{replacement_item['id']}/permanent",
        headers=api.headers(admin),
        json={"confirmation": "PERMANENTLY_DELETE", "reason": "无执行历史的重复配置"},
    )
    assert purged.status_code == 200, purged.text
    restored = api.post(f"/recycle-bin/{original_item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert api.get(f"/mock-scenarios/{scenario['id']}", username=admin).status_code == 200


def test_mock_service_recycle_detail_does_not_expose_runtime_token_hash(api, admin):
    project_id = _project(api, admin)
    service_response = api.post(
        f"/projects/{project_id}/mock-services", username=admin,
        json={"name": unique("mock-secret"), "service_key": f"SECRET_{unique('key').replace('-', '_').upper()}",
              "runtime_token": "one-time-runtime-token"},
    )
    assert service_response.status_code == 201, service_response.text
    service_id = service_response.json()["service"]["id"]
    assert api.delete(f"/mock-services/{service_id}", username=admin).status_code == 204
    item = _trash_item(api, admin, project_id, "mock_service", service_id)
    detail = api.get(f"/recycle-bin/{item['id']}", username=admin)
    assert detail.status_code == 200
    assert detail.json()["resource_data"]["id"] == service_id
    assert detail.json()["resource_data"]["runtime_token_hash"] is None
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 200
