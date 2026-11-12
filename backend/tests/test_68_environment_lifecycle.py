"""Lifecycle coverage for platform environment catalog entries."""

from tests.conftest import unique


def test_global_environment_batch_delete_restore_and_secret_masking(api, admin):
    name = unique("trash-env").replace("-", "_")
    anchor_name = unique("environment-anchor").replace("-", "_")
    anchor = api.post(
        "/environments", username=admin,
        json={"name": anchor_name, "display_name": anchor_name, "base_url": "https://anchor.test"},
    )
    assert anchor.status_code == 201, anchor.text
    created = api.post(
        "/environments", username=admin,
        json={
            "name": name, "display_name": "Lifecycle Environment",
            "base_url": "https://example.test", "default_headers": {"Authorization": "Bearer do-not-return"},
            "is_default": False, "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    environment_id = created.json()["id"]

    deleted = api.post(
        "/resources/environment/batch-delete", username=admin,
        json={"ids": [environment_id], "reason": "lifecycle test"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["succeeded"] == 1, deleted.text
    assert api.get(f"/environments/{name}", username=admin).status_code != 200

    items_response = api.get("/recycle-bin?resource_type=environment", username=admin)
    assert items_response.status_code == 200, items_response.text
    item = next(item for item in items_response.json()["items"] if item["resource_id"] == str(environment_id))
    detail = api.get(f"/recycle-bin/{item['id']}", username=admin)
    assert detail.status_code == 200, detail.text
    assert "do-not-return" not in str(detail.json().get("resource_data"))
    assert "default_headers" not in str(item["metadata"])

    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert api.get(f"/environments/{name}", username=admin).status_code == 200

    # Leave the isolated migration test database clean: permanently remove this temporary test row.
    assert api.delete(f"/environments/{name}", username=admin).status_code == 204
    current = api.get("/recycle-bin?resource_type=environment", username=admin).json()["items"]
    cleanup_item = next(item for item in current if item["resource_id"] == str(environment_id))
    preview = api.get(f"/recycle-bin/{cleanup_item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200 and preview.json()["allowed"] is True, preview.text
    purge = api.client.request(
        "DELETE", f"/api/v1/recycle-bin/{cleanup_item['id']}/permanent",
        headers=api.headers(admin),
        json={"confirmation": "PERMANENTLY_DELETE", "reason": "isolated lifecycle test cleanup"},
    )
    assert purge.status_code == 200, purge.text


def test_environment_delete_keeps_default_and_project_dependencies_protected(api, admin):
    default_name = api.get("/environments", username=admin).json()["items"][0]["name"]
    default_delete = api.delete(f"/environments/{default_name}", username=admin)
    assert default_delete.status_code == 400

    project = api.post(
        "/projects", username=admin,
        json={"name": unique("environment-dependency"), "description": "lifecycle"},
    )
    assert project.status_code == 201, project.text
    envs = api.get(
        f"/projects/{project.json()['id']}/environments?include_inactive=true", username=admin,
    )
    assert envs.status_code == 200, envs.text
    project_environment = next(item for item in envs.json()["items"] if not item["is_default"])
    environment_name = project_environment["name"]
    protected_delete = api.delete(f"/environments/{environment_name}", username=admin)
    assert protected_delete.status_code == 409
