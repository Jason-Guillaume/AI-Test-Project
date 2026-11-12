"""测试范围导航：三方向树、归属、资产关联和迁移核对。

覆盖节点增删改移、子孙用例计数、待整理、项目隔离，以及接口路径不能模糊回填。
"""

from __future__ import annotations

from sqlalchemy import text

from app.features.test_management.scope_placement import backfill_api_id, interface_index
from tests.conftest import unique


def _project(api, actor) -> int:
    """创建项目并返回 ID。"""
    response = api.post("/projects", username=actor, json={"name": unique("范围项目"), "description": "scope"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _case(api, actor, project_id: int, name: str, **overrides) -> dict:
    """创建用例。创建时会自动挂到对应方向的待整理。"""
    response = api.post(f"/projects/{project_id}/test-cases", username=actor, json={"name": name, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def _register(api, username: str) -> int:
    """注册并登录，返回用户 ID。"""
    response = api.register(username)
    assert response.status_code == 201, response.text
    api.login(username, "Init-Password-123")
    return response.json()["user"]["id"]


def test_unique_interface_backfill_rejects_ambiguous_paths():
    """归一化后命中两条接口时不回填；只有一条时才返回 ID。"""
    index = interface_index([
        (1, "GET", "/users/{id}"),
        (2, "GET", "/users/8"),
        (3, "POST", "/orders"),
    ])
    assert backfill_api_id("模块路径：GET /users/9", index) is None
    assert backfill_api_id("画布：POST /orders", index) == 3
    assert backfill_api_id("没有接口", index) is None


def test_tree_move_count_and_rehome(api, admin):
    """建子目录、挂用例、父节点递归计数、移入子孙被拒、删除后用例回到待整理。"""
    project_id = _project(api, admin)
    created = _case(api, admin, project_id, unique("范围用例"), target_type="WEB")
    tree = api.get(f"/projects/{project_id}/test-scopes", username=admin, params={"direction": "UI"})
    assert tree.status_code == 200, tree.text
    inbox = next(item for item in tree.json()["items"] if item["is_system"])
    assert inbox["name"] == "待整理"
    assert inbox["case_count"] == 1

    parent = api.post(
        f"/projects/{project_id}/test-scopes", username=admin,
        json={"direction": "UI", "node_type": "FOLDER", "name": unique("页面模块")},
    )
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["id"]
    child = api.post(
        f"/projects/{project_id}/test-scopes", username=admin,
        json={"direction": "UI", "parent_id": parent_id, "node_type": "FOLDER", "name": unique("功能区")},
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]

    moved = api.post(
        f"/projects/{project_id}/test-scope-cases/move", username=admin,
        json={"case_ids": [created["id"]], "scope_node_id": child_id},
    )
    assert moved.status_code == 200, moved.text
    detail = api.get(f"/test-scopes/{parent_id}", username=admin)
    assert detail.status_code == 200, detail.text
    assert detail.json()["case_count"] == 1
    assert detail.json()["path"][-1]["id"] == parent_id

    cycle = api.post(f"/test-scopes/{parent_id}/move", username=admin, json={"parent_id": child_id, "sort_order": 0})
    assert cycle.status_code == 400, cycle.text

    rejected = api.delete(f"/test-scopes/{child_id}", username=admin)
    assert rejected.status_code == 409, rejected.text
    moved_out = api.post(
        f"/projects/{project_id}/test-scope-cases/move", username=admin,
        json={"case_ids": [created["id"]], "scope_node_id": parent_id},
    )
    assert moved_out.status_code == 200, moved_out.text

    removed = api.delete(f"/test-scopes/{child_id}", username=admin)
    assert removed.status_code == 204, removed.text
    listing = api.get(
        f"/projects/{project_id}/test-scope-cases", username=admin,
        params={"scope_node_id": parent_id, "include_descendants": False},
    )
    assert listing.status_code == 200, listing.text
    assert [item["id"] for item in listing.json()["items"]] == [created["id"]]

    blocked = api.delete(f"/test-scopes/{inbox['id']}", username=admin)
    assert blocked.status_code == 400, blocked.text


def test_api_case_links_interface_and_ai_is_not_executable(api, admin):
    """带 api_id 的用例挂到接口节点；AI 用例详情标明执行未开放。"""
    project_id = _project(api, admin)
    module = api.post(f"/projects/{project_id}/api-modules", username=admin, json={"name": unique("订单模块")})
    assert module.status_code == 201, module.text
    interface = api.post(
        f"/projects/{project_id}/apis", username=admin,
        json={"module_id": module.json()["id"], "name": unique("下单"), "method": "POST", "path": "/orders"},
    )
    assert interface.status_code == 201, interface.text
    case = _case(api, admin, project_id, unique("下单成功"), target_type="API", api_id=interface.json()["id"])
    tree = api.get(f"/projects/{project_id}/test-scopes", username=admin, params={"direction": "API"})
    assert tree.status_code == 200, tree.text
    linked = next(item for item in tree.json()["items"] if item["asset_id"] == interface.json()["id"])
    assert linked["case_count"] == 1
    module_node = next(item for item in tree.json()["items"] if item["asset_id"] == module.json()["id"])
    assert module_node["case_count"] == 1

    ai_case = _case(api, admin, project_id, unique("模型输出"), target_type="AI")
    detail = api.get(f"/test-cases/{ai_case['id']}/detail", username=admin)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["direction"] == "AI"
    assert body["executor_ready"] is False
    assert "尚未开放" in body["executor_note"]
    assert body["scope_paths"][0]["path"][0]["name"] == "待整理"

    case_detail = api.get(f"/test-cases/{case['id']}/detail", username=admin)
    assert case_detail.status_code == 200, case_detail.text
    assert any(item["asset_type"] == "API_INTERFACE" for item in case_detail.json()["assets"])


def test_archive_isolation_and_viewer(api, admin):
    """归档改状态；项目外 404；viewer 不能建节点。"""
    project_id = _project(api, admin)
    case = _case(api, admin, project_id, unique("待归档"))
    archived = api.post(
        f"/projects/{project_id}/test-scope-cases/archive", username=admin,
        json={"case_ids": [case["id"]]},
    )
    assert archived.status_code == 200, archived.text
    loaded = api.get(f"/test-cases/{case['id']}", username=admin)
    assert loaded.json()["status"] == "DEPRECATED"

    outsider = unique("范围外用户")
    _register(api, outsider)
    hidden = api.get(f"/projects/{project_id}/test-scopes", username=outsider, params={"direction": "API"})
    assert hidden.status_code == 404, hidden.text

    viewer_name = unique("范围只读")
    viewer_id = _register(api, viewer_name)
    member = api.put(
        f"/projects/{project_id}/members/{viewer_id}", username=admin,
        json={"user_id": viewer_id, "role": "viewer"},
    )
    assert member.status_code == 200, member.text
    denied = api.post(
        f"/projects/{project_id}/test-scopes", username=viewer_name,
        json={"direction": "API", "node_type": "FOLDER", "name": unique("只读不能建")},
    )
    assert denied.status_code == 403, denied.text
    allowed = api.get(f"/projects/{project_id}/test-scopes/stats", username=viewer_name, params={"direction": "API"})
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["case_count"] >= 1


def test_migration_preserved_case_counts(db):
    """迁移核对表里，正式用例及子表的前后行数一致，且每条当时存在的用例都有归属。"""
    rows = db.execute(text("SELECT metric, before_count, after_count FROM test_scope_migration_check")).mappings().all()
    found = {row["metric"]: (row["before_count"], row["after_count"]) for row in rows}
    assert found["test_case"][0] == found["test_case"][1]
    assert found["test_point"][0] == found["test_point"][1]
    assert found["test_case_precondition"][0] == found["test_case_precondition"][1]
    assert found["test_step"][0] == found["test_step"][1]
    assert found["test_assertion"][0] == found["test_assertion"][1]
    assert found["case_execution"][0] == found["case_execution"][1]
    assert found["test_case_scoped"][1] == found["test_case"][1]
    assert found["test_case_api_id"][1] >= found["test_case_api_id"][0]
