"""User-account lifecycle preserves identity, ownership, and access history."""

from tests.conftest import DEFAULT_PASSWORD, unique


def _create_user(api, admin: str, username: str) -> dict:
    response = api.post(
        "/users", username=admin,
        json={"username": username, "password": DEFAULT_PASSWORD, "role": "test"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_user_batch_delete_has_per_item_receipts_and_restore(api, admin):
    username = unique("user-lifecycle")
    user = _create_user(api, admin, username)
    original_token = api.login(username)
    admin_id = api.get("/me", username=admin).json()["id"]

    receipt = api.post(
        "/resources/user/batch-delete", username=admin,
        json={"project_id": None, "ids": [user["id"], admin_id]},
    )
    assert receipt.status_code == 200, receipt.text
    result = receipt.json()
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["items"][0]["succeeded"] is True
    assert result["items"][1]["succeeded"] is False
    assert "不能删除当前登录账号" in result["items"][1]["error"]

    assert api.get("/me", token=original_token).status_code == 401
    assert api.post(
        "/users", username=admin,
        json={"username": username, "password": DEFAULT_PASSWORD, "role": "test"},
    ).status_code == 409

    item = next(
        row for row in api.get("/recycle-bin?resource_type=user", username=admin).json()["items"]
        if row["resource_id"] == str(user["id"])
    )
    detail = api.get(f"/recycle-bin/{item['id']}", username=admin)
    assert detail.status_code == 200
    assert detail.json()["resource_data"]["id"] == user["id"]
    assert detail.json()["resource_data"]["hashed_password"] is None

    restored = api.post(
        "/recycle-bin/batch-restore", username=admin,
        json={"item_ids": [item["id"]]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["succeeded"] == 1
    assert api.get("/me", token=original_token).status_code == 401
    fresh_token = api.login(username)
    assert api.get("/me", token=fresh_token).json()["id"] == user["id"]


def test_user_purge_preview_protects_project_and_org_references(api, admin):
    user = _create_user(api, admin, unique("user-purge-guard"))
    assert api.delete(f"/users/{user['id']}", username=admin).status_code == 204
    item = next(
        row for row in api.get("/recycle-bin?resource_type=user", username=admin).json()["items"]
        if row["resource_id"] == str(user["id"])
    )
    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200
    assert preview.json()["allowed"] is False
    assert any("organization.owner_id" in dependency for dependency in preview.json()["dependencies"])
