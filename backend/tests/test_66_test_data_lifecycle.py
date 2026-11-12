"""Data catalog/provider assets use recoverable lifecycle without exposing secrets."""

from tests.conftest import unique


def _project(api, admin):
    response = api.post("/projects", username=admin, json={"name": unique("factory-trash")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _trash_item(api, admin, project_id, resource_type, resource_id):
    response = api.get(
        "/recycle-bin", username=admin,
        params={"project_id": project_id, "resource_type": resource_type},
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["resource_id"] == str(resource_id))


def test_test_data_asset_soft_delete_restore_conflict_and_sensitive_redaction(api, admin):
    project_id = _project(api, admin)
    name = unique("asset")
    created = api.post(
        f"/projects/{project_id}/test-data-assets", username=admin,
        json={"name": name, "entity_type": "USER", "value_json": {"password": "secret", "token": "abc"}},
    )
    assert created.status_code == 201, created.text
    asset_id = created.json()["id"]
    assert api.delete(f"/test-data-assets/{asset_id}", username=admin).status_code == 204
    assert api.get(f"/test-data-assets/{asset_id}", username=admin).status_code == 404

    item = _trash_item(api, admin, project_id, "test_data_asset", asset_id)
    detail = api.get(f"/recycle-bin/{item['id']}", username=admin)
    assert detail.status_code == 200
    assert detail.json()["resource_data"]["id"] == asset_id
    assert detail.json()["resource_data"]["value_json"] == {"password": "******", "token": "******"}

    replacement = api.post(
        f"/projects/{project_id}/test-data-assets", username=admin,
        json={"name": name, "entity_type": "USER"},
    )
    assert replacement.status_code == 201, replacement.text
    conflict = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert conflict.status_code == 409
    assert conflict.json()["meta"]["conflicting_resource"]["id"] == replacement.json()["id"]

    assert api.delete(f"/test-data-assets/{replacement.json()['id']}", username=admin).status_code == 204
    replacement_item = _trash_item(api, admin, project_id, "test_data_asset", replacement.json()["id"])
    purged = api.client.request(
        "DELETE", f"/api/v1/recycle-bin/{replacement_item['id']}/permanent",
        headers=api.headers(admin),
        json={"confirmation": "PERMANENTLY_DELETE", "reason": "释放测试名称"},
    )
    assert purged.status_code == 200, purged.text
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 200
    assert api.get(f"/test-data-assets/{asset_id}", username=admin).json()["id"] == asset_id


def test_data_provider_soft_delete_blocks_fixture_reference_and_preserves_execution_evidence(api, admin, db):
    from app.features.test_data.models import Fixture, FixtureStep, ProviderExecution

    project_id = _project(api, admin)
    created = api.post(
        f"/projects/{project_id}/data-providers", username=admin,
        json={"name": unique("provider"), "provider_type": "STATIC", "config_json": {"values": {"x": 1}}},
    )
    assert created.status_code == 201, created.text
    provider = created.json()

    fixture = Fixture(
        project_id=project_id, name=unique("fixture"), fixture_key=f"FACTORY_{unique('key').replace('-', '_').upper()}",
        entity_type="USER", scope="CASE", status="DRAFT",
    )
    db.add(fixture)
    db.flush()
    db.add(FixtureStep(
        fixture_id=fixture.id, phase="GENERATE", step_type="STATIC", name="Provider 依赖",
        sort=0, provider_id=provider["id"], config_json={"values": {}},
    ))
    db.commit()
    assert api.delete(f"/data-providers/{provider['id']}", username=admin).status_code == 409

    db.query(FixtureStep).filter(FixtureStep.provider_id == provider["id"]).delete(synchronize_session=False)
    db.add(ProviderExecution(
        project_id=project_id, provider_id=provider["id"], provider_type="STATIC", status="SUCCESS",
    ))
    db.commit()
    assert api.delete(f"/data-providers/{provider['id']}", username=admin).status_code == 204
    assert api.get(f"/data-providers/{provider['id']}", username=admin).status_code == 404

    item = _trash_item(api, admin, project_id, "data_provider", provider["id"])
    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200 and preview.json()["allowed"] is False
    assert any("Provider 执行历史" in text for text in preview.json()["dependencies"])
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 200
    assert api.get(f"/data-providers/{provider['id']}", username=admin).status_code == 200
