"""Fixture、数据池、被测库连接和云效配置的可恢复删除。"""

from uuid import uuid4

from tests.conftest import unique


def _project(api, admin):
    response = api.post("/projects", username=admin, json={"name": unique("lifecycle-project")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _fixture(api, admin, project_id, key):
    response = api.post(
        f"/projects/{project_id}/fixtures", username=admin,
        json={
            "name": key, "fixture_key": key, "entity_type": "USER", "scope": "PROJECT",
            "status": "ACTIVE", "steps": [], "outputs": [], "dependencies": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _trash(api, admin, project_id, resource_type, resource_id):
    response = api.get(
        "/recycle-bin", username=admin,
        params={"project_id": project_id, "resource_type": resource_type},
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["resource_id"] == str(resource_id))


def test_fixture_delete_hides_list_and_restore_keeps_id(api, admin):
    """单条删除后列表和详情都看不到，恢复后原 ID 回到列表。"""
    project_id = _project(api, admin)
    created = _fixture(api, admin, project_id, f"KEEP_{uuid4().hex[:8].upper()}")
    assert api.delete(f"/fixtures/{created['id']}", username=admin).status_code == 204
    assert api.delete(f"/fixtures/{created['id']}", username=admin).status_code == 204
    assert api.get(f"/fixtures/{created['id']}", username=admin).status_code == 404
    assert api.patch(f"/fixtures/{created['id']}", username=admin, json={"name": "改名"}).status_code == 404
    listed = api.get(f"/projects/{project_id}/fixtures", username=admin).json()
    assert all(item["id"] != created["id"] for item in listed["items"])

    item = _trash(api, admin, project_id, "fixture", created["id"])
    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert api.get(f"/fixtures/{created['id']}", username=admin).status_code == 200


def test_fixture_batch_is_partial_and_scoped(api, admin):
    """批量删除逐条提交：不存在、跨项目和空集合都不会破坏成功项。"""
    project_id = _project(api, admin)
    other_id = _project(api, admin)
    first = _fixture(api, admin, project_id, f"BATCH_A_{uuid4().hex[:6].upper()}")
    second = _fixture(api, admin, other_id, f"BATCH_B_{uuid4().hex[:6].upper()}")
    empty = api.post(
        "/resources/fixture/batch-delete", username=admin,
        json={"project_id": project_id, "ids": []},
    )
    assert empty.status_code == 422

    receipt = api.post(
        "/resources/fixture/batch-delete", username=admin,
        json={"project_id": project_id, "ids": [first["id"], 999999999, second["id"]]},
    )
    assert receipt.status_code == 200, receipt.text
    body = receipt.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 2
    assert api.get(f"/fixtures/{first['id']}", username=admin).status_code == 404
    assert api.get(f"/fixtures/{second['id']}", username=admin).status_code == 200

    repeated = api.post(
        "/resources/fixture/batch-delete", username=admin,
        json={"project_id": project_id, "ids": [first["id"]]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["items"][0]["succeeded"] is True
    assert repeated.json()["items"][0]["already_done"] is True


def test_fixture_restore_reports_key_conflict_without_overwrite(api, admin):
    """恢复时同键冲突返回明确错误，不覆盖新记录。"""
    project_id = _project(api, admin)
    key = f"CONFLICT_{uuid4().hex[:6].upper()}"
    original = _fixture(api, admin, project_id, key)
    assert api.delete(f"/fixtures/{original['id']}", username=admin).status_code == 204
    replacement = _fixture(api, admin, project_id, key)
    item = _trash(api, admin, project_id, "fixture", original["id"])
    blocked = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert blocked.status_code == 409
    assert "冲突" in blocked.json()["message"]
    assert api.get(f"/fixtures/{replacement['id']}", username=admin).status_code == 200
    assert api.delete(f"/fixtures/{replacement['id']}", username=admin).status_code == 204
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 200


def test_pool_child_blocks_parent_and_restore_order(api, admin):
    """有条目时不能删池；先恢复池再恢复条目。"""
    project_id = _project(api, admin)
    pool = api.post(
        f"/projects/{project_id}/data-pools", username=admin,
        json={"name": unique("pool"), "pool_key": f"POOL_{uuid4().hex[:6].upper()}", "status": "ACTIVE"},
    )
    assert pool.status_code == 201, pool.text
    pool_id = pool.json()["id"]
    item = api.post(
        f"/data-pools/{pool_id}/items", username=admin,
        json={"payload_json": {"token": "secret"}, "status": "AVAILABLE"},
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]
    blocked = api.delete(f"/data-pools/{pool_id}", username=admin)
    assert blocked.status_code == 409
    assert api.delete(f"/data-pool-items/{item_id}", username=admin).status_code == 204
    assert api.get(f"/data-pools/{pool_id}/items", username=admin).json()["total"] == 0
    assert api.delete(f"/data-pools/{pool_id}", username=admin).status_code == 204

    item_trash = _trash(api, admin, project_id, "data_pool_item", item_id)
    parent_missing = api.post(f"/recycle-bin/{item_trash['id']}/restore", username=admin)
    assert parent_missing.status_code == 409
    pool_trash = _trash(api, admin, project_id, "data_pool", pool_id)
    batch = api.post(
        "/recycle-bin/batch-restore", username=admin,
        json={"item_ids": [pool_trash["id"], item_trash["id"]]},
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()["succeeded"] == 2
    assert api.get(f"/data-pools/{pool_id}", username=admin).status_code == 200
    listed = api.get(f"/data-pools/{pool_id}/items", username=admin).json()
    assert listed["total"] == 1
    assert listed["items"][0]["payload_json"]["token"] == "******"


def test_connection_soft_delete_redacts_password_and_rejects_repeat_restore(api, admin, db):
    """连接删除后密码不出现在回收站，重复恢复是幂等成功。"""
    from app.core.models.configuration import Environment
    from app.core.models.identity import User

    project_id = _project(api, admin)
    admin_id = db.query(User).filter(User.username == "platform_admin").first().id
    env = db.query(Environment).filter(Environment.name == "dev").first()
    if env is None:
        env = Environment(
            name="dev", display_name="dev", base_url="https://example.com",
            gateway_prefix="", default_headers={}, is_active=True, created_by=admin_id,
        )
        db.add(env)
        db.commit()
        db.refresh(env)
    created = api.post(
        f"/projects/{project_id}/target-databases", username=admin,
        json={
            "environment_id": env.id, "name": unique("conn"), "host": "127.0.0.1",
            "port": 5432, "database_name": "demo", "username": "reader",
            "password": "test-only-not-a-real-secret", "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    bob = unique("viewer")
    registered = api.register(bob)
    assert registered.status_code == 201, registered.text
    api.login(bob, "Init-Password-123")
    member = api.put(
        f"/projects/{project_id}/members/{registered.json()['user']['id']}", username=admin,
        json={"user_id": registered.json()["user"]["id"], "role": "viewer"},
    )
    assert member.status_code == 200, member.text
    denied = api.delete(f"/target-databases/{connection_id}", username=bob)
    assert denied.status_code in {403, 404}
    assert api.delete(f"/target-databases/{connection_id}", username=admin).status_code == 204
    assert api.get(f"/target-databases/{connection_id}", username=admin).status_code == 404
    item = _trash(api, admin, project_id, "target_database_connection", connection_id)
    detail = api.get(f"/recycle-bin/{item['id']}", username=admin)
    assert detail.status_code == 200
    assert detail.json()["resource_data"]["password_encrypted"] is None
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 200
    again = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert again.status_code == 200
    assert again.json()["already_done"] is True
    assert api.get(f"/target-databases/{connection_id}", username=admin).status_code == 200


def test_automation_integration_delete_keeps_secret_out_of_trash_detail(api, admin):
    """接入配置软删除后列表消失，回收站不回传令牌密文。"""
    project_id = _project(api, admin)
    created = api.post(
        f"/projects/{project_id}/automation-integrations", username=admin,
        json={
            "name": unique("yunxiao"), "organization_id": "org-demo",
            "access_token": "token-demo-value", "callback_secret": "callback-demo",
        },
    )
    assert created.status_code == 201, created.text
    config_id = created.json()["id"]
    assert api.delete(f"/automation-integrations/{config_id}", username=admin).status_code == 204
    listed = api.get(f"/projects/{project_id}/automation-integrations", username=admin)
    assert listed.status_code == 200
    assert all(item["id"] != config_id for item in listed.json()["items"])
    item = _trash(api, admin, project_id, "automation_integration", config_id)
    detail = api.get(f"/recycle-bin/{item['id']}", username=admin).json()
    assert detail["resource_data"]["access_token_encrypted"] is None
    assert detail["resource_data"]["callback_secret_encrypted"] is None
    missing = api.delete("/automation-integrations/999999999", username=admin)
    assert missing.status_code == 404
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 200
