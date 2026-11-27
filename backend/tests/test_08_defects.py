"""验收项 8：缺陷管理 CRUD + 权限 + 通知（无指派人模型）。

覆盖：
- CRUD 全链路：创建、列表、详情、更新、删除
- 权限：viewer 无法写、member 可以写、跨项目越权按 404 隐藏
- 通知：defect.created / defect.status_changed 事件入库；不再产生 defect.assigned
- 字段停用：处理人与普通编辑改状态返回明确的停用提示
- 过滤：project_id / status / severity / keyword 各验证
- 校验：非法状态/严重度/标题走 422
"""

from __future__ import annotations

from tests.conftest import unique


# ---------------------------------------------------------------- 建项目辅助

def _create_project(api, actor, name=None):
    """以 actor 身份创建个人项目，返回 (project_id, project_name)。"""
    proj_name = name or unique("proj")
    response = api.post(
        "/projects",
        username=actor,
        json={"name": proj_name, "description": "test project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], proj_name


def _register_and_login(api, username):
    """注册新用户并缓存令牌，返回新用户的 user_id。"""
    response = api.register(username)
    assert response.status_code == 201, response.text
    user_id = response.json()["user"]["id"]
    api.login(username, "Init-Password-123")
    return user_id


def _add_project_member(api, actor, project_id, user_id, role="member"):
    """以 actor 身份把 user_id 加为项目成员。"""
    response = api.put(
        f"/projects/{project_id}/members/{user_id}",
        username=actor,
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- CRUD 冒烟

def test_defect_full_crud_lifecycle(api, admin):
    """完整 CRUD 生命周期：创建→列表→详情→更新→删除。"""
    project_id, _ = _create_project(api, admin)

    # 1. 创建缺陷（新缺陷自动进入待确认队列）
    create_body = {
        "project_id": project_id,
        "title": "登录页返回 500",
        "description": "使用错误密码登录时服务端异常",
        "severity": 3,
        "steps_to_reproduce": "1. 打开登录页\n2. 输入错误密码\n3. 点击登录",
        "expected_result": "提示凭据无效",
        "actual_result": "返回 500\n服务器错误",
        "environment": "dev",
    }
    r = api.post("/bugs", username=admin, json=create_body)
    assert r.status_code == 201, r.text
    bug = r.json()
    assert bug["title"] == "登录页返回 500"
    assert bug["status"] == "待确认"
    assert bug["status_display"] == "待确认"
    assert bug["severity"] == 3
    assert bug["reporter_username"] == admin
    assert bug["project_name"]
    assert bug["expected_result"] == "提示凭据无效"
    assert bug["actual_result"] == "返回 500\n服务器错误"
    # 响应不再包含任何处理人字段。
    assert "assignee_id" not in bug
    assert "assignee_username" not in bug
    bug_id = bug["id"]

    # 2. 详情
    r = api.get(f"/bugs/{bug_id}", username=admin)
    assert r.status_code == 200
    assert r.json()["id"] == bug_id

    # 3. 列表按 project_id 过滤
    r = api.get("/bugs", username=admin, params={"project_id": project_id})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == bug_id

    # 4. 按状态过滤
    r = api.get("/bugs", username=admin, params={"status": "待确认"})
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    # 5. 按严重度过滤
    r = api.get("/bugs", username=admin, params={"severity": 3})
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    # 6. 按关键字过滤（命中与不命中）
    r = api.get("/bugs", username=admin, params={"keyword": "登录页"})
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    r = api.get("/bugs", username=admin, params={"keyword": "完全不匹配"})
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # 7. 更新：普通编辑只改事实字段；改状态被契约层拒绝。
    r = api.put(f"/bugs/{bug_id}", username=admin, json={"status": "处理中"})
    assert r.status_code == 422
    assert "队列动作" in r.text
    r = api.put(f"/bugs/{bug_id}", username=admin, json={"severity": 4})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["status"] == "待确认"
    assert updated["severity"] == 4
    assert updated["expected_result"] == "提示凭据无效"
    r = api.put(f"/bugs/{bug_id}", username=admin, json={"actual_result": None})
    assert r.status_code == 200, r.text
    assert r.json()["actual_result"] is None

    # 8. 删除
    r = api.delete(f"/bugs/{bug_id}", username=admin)
    assert r.status_code == 204

    # 9. 已删除的缺陷：详情返回 404，列表 total 归零
    r = api.get(f"/bugs/{bug_id}", username=admin)
    assert r.status_code == 404
    r = api.get("/bugs", username=admin, params={"project_id": project_id})
    assert r.status_code == 200
    assert r.json()["total"] == 0


# ---------------------------------------------------------------- 通知

def test_defect_create_triggers_notification(api, admin):
    """创建缺陷后，报告人收件箱应收到 defect.created 通知。"""
    project_id, _ = _create_project(api, admin)
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "通知冒烟缺陷"},
    )
    assert r.status_code == 201
    bug_id = r.json()["id"]

    r = api.get("/notifications", username=admin, params={"page_size": 20})
    assert r.status_code == 200
    items = r.json()["items"]
    event_types = [item["event_type"] for item in items]
    assert "defect.created" in event_types
    matching = [item for item in items if item["event_type"] == "defect.created"]
    assert matching
    assert matching[0]["project_id"] == project_id
    assert matching[0]["payload"]["detail"]["bug_id"] == bug_id


def test_defect_status_action_triggers_notification(api, admin):
    """队列动作变更状态时，报告人应收到 defect.status_changed 通知。"""
    project_id, _ = _create_project(api, admin)
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "状态变更冒烟"},
    )
    bug_id = r.json()["id"]
    r = api.post(
        f"/bugs/{bug_id}/actions",
        username=admin,
        json={"action": "confirm"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["bug"]["status"] == "处理中"

    r = api.get("/notifications", username=admin, params={"page_size": 20})
    event_types = [item["event_type"] for item in r.json()["items"]]
    assert "defect.status_changed" in event_types


def test_defect_assignee_retired_no_assignment_notification(api, admin):
    """处理人字段停用：显式指派返回 422，且不再产生 defect.assigned 通知。"""
    target_name = unique("assignee")
    target_id = _register_and_login(api, target_name)
    project_id, _ = _create_project(api, admin)
    _add_project_member(api, admin, project_id, target_id, role="member")

    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "分配冒烟"},
    )
    assert r.status_code == 201
    bug_id = r.json()["id"]

    r = api.put(
        f"/bugs/{bug_id}",
        username=admin,
        json={"assignee_id": target_id},
    )
    assert r.status_code == 422
    assert "处理人字段已停用" in r.text

    r = api.get("/notifications", username=target_name, params={"page_size": 20})
    event_types = [item["event_type"] for item in r.json()["items"]]
    assert "defect.assigned" not in event_types


def test_defect_notifications_catalog_lists_defect_events(api, admin):
    """GET /notifications/events 应列出缺陷事件类型（含新增积压提醒）。"""
    r = api.get("/notifications/events", username=admin)
    assert r.status_code == 200
    values = {item["value"] for item in r.json()}
    assert "defect.created" in values
    assert "defect.status_changed" in values
    assert "defect.reminder" in values


# ---------------------------------------------------------------- 权限

def test_defect_viewer_cannot_write(api, admin):
    """viewer 只能读，写操作应返回 403。"""
    viewer_name = unique("viewer")
    viewer_id = _register_and_login(api, viewer_name)
    project_id, _ = _create_project(api, admin)
    _add_project_member(api, admin, project_id, viewer_id, role="viewer")

    # viewer 创建缺陷应被拒。
    r = api.post(
        "/bugs",
        username=viewer_name,
        json={"project_id": project_id, "title": "越权创建"},
    )
    assert r.status_code == 403

    # viewer 详情可以读（因为项目可见性）。
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "合法缺陷"},
    )
    assert r.status_code == 201
    bug_id = r.json()["id"]
    r = api.get(f"/bugs/{bug_id}", username=viewer_name)
    assert r.status_code == 200

    # viewer 修改/删除/队列动作应被拒。
    r = api.put(f"/bugs/{bug_id}", username=viewer_name, json={"title": "被拒改"})
    assert r.status_code == 403
    r = api.post(f"/bugs/{bug_id}/actions", username=viewer_name, json={"action": "confirm"})
    assert r.status_code == 403
    r = api.delete(f"/bugs/{bug_id}", username=viewer_name)
    assert r.status_code == 403


def test_defect_invisible_project_hidden_as_not_found(api, admin):
    """其他用户的项目下的缺陷，越权访问应按 404 返回，而不是 403。"""
    observer_name = unique("observer")
    _register_and_login(api, observer_name)
    project_id, _ = _create_project(api, admin)
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "隐藏测试缺陷"},
    )
    assert r.status_code == 201
    bug_id = r.json()["id"]

    # 观察者看不到这个缺陷：详情返回 404，按项目过滤的列表 total=0。
    r = api.get(f"/bugs/{bug_id}", username=observer_name)
    assert r.status_code == 404
    r = api.get("/bugs", username=observer_name, params={"project_id": project_id})
    assert r.status_code == 200
    assert r.json()["total"] == 0


# ---------------------------------------------------------------- 校验

def test_defect_validation_rejects_bad_input(api, admin):
    """非法状态/严重度/标题应返回 422。"""
    project_id, _ = _create_project(api, admin)

    # 严重度 5 越界：Pydantic Literal 直接 422。
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "越界严重度", "severity": 5},
    )
    assert r.status_code == 422

    # 状态非法：Pydantic Literal 422。
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "越界状态", "status": "随便一个"},
    )
    assert r.status_code == 422

    # 标题为空：min_length=1 触发 422。
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": ""},
    )
    assert r.status_code == 422


def test_defect_create_assignee_rejected_with_retirement_message(api, admin):
    """创建时显式指派处理人返回 422 停用提示；传空值兼容旧客户端。"""
    stranger_name = unique("stranger")
    stranger_id = _register_and_login(api, stranger_name)
    project_id, _ = _create_project(api, admin)

    r = api.post(
        "/bugs",
        username=admin,
        json={
            "project_id": project_id,
            "title": "错误处理人",
            "assignee_id": stranger_id,
        },
    )
    assert r.status_code == 422
    assert "处理人字段已停用" in r.text

    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "旧客户端空处理人", "assignee_id": None},
    )
    assert r.status_code == 201, r.text


def test_defect_put_assignee_none_is_ignored(api, admin):
    """PUT 时显式 assignee_id=None 兼容旧客户端；响应不含处理人字段。"""
    project_id, _ = _create_project(api, admin)
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "清空处理人"},
    )
    bug_id = r.json()["id"]

    r = api.put(f"/bugs/{bug_id}", username=admin, json={"assignee_id": None})
    assert r.status_code == 200
    assert "assignee_id" not in r.json()
    assert "assignee_username" not in r.json()


def test_defect_assignee_filter_rejected(api, admin):
    """列表按处理人筛选已停用，返回 400 明确提示。"""
    r = api.get("/bugs", username=admin, params={"assignee_id": 1})
    assert r.status_code == 400
    assert "处理人" in r.text


def test_batch_create_is_atomic_and_attachments_follow_project_permissions(api, admin):
    project_id, _ = _create_project(api, admin)
    body = {
        "project_id": project_id,
        "items": [
            {"title": "批量一", "category": "前端"},
            {"title": "   ", "category": "接口"},
        ],
    }
    r = api.post('/bugs/batch', username=admin, json=body)
    assert r.status_code == 400, r.text
    assert api.get('/bugs', username=admin, params={"project_id": project_id}).json()['total'] == 0
    body["items"][1]["title"] = "批量二"
    response = api.post('/bugs/batch', username=admin, json=body)
    assert response.status_code == 201, response.text
    bug_id = response.json()["items"][0]['id']
    upload = api.post(f'/bugs/{bug_id}/attachments', username=admin, files={'file': ('test.txt', b'proof', 'text/plain')})
    assert upload.status_code == 201, upload.text
    attachment_id = upload.json()['id']
    assert api.get(f'/bugs/{bug_id}/attachments/{attachment_id}', username=admin).content == b'proof'
    viewer = unique('viewer')
    viewer_id = _register_and_login(api, viewer)
    _add_project_member(api, admin, project_id, viewer_id, 'viewer')
    assert api.get(f'/bugs/{bug_id}/attachments', username=viewer).status_code == 200
    assert api.post(f'/bugs/{bug_id}/attachments', username=viewer, files={'file': ('x.txt', b'x')}).status_code == 403
    assert api.delete(f'/bugs/{bug_id}/attachments/{attachment_id}', username=viewer).status_code == 403
    assert api.delete(f'/bugs/{bug_id}/attachments/{attachment_id}', username=admin).status_code == 204
    assert api.get(f'/bugs/{bug_id}/attachments/{attachment_id}', username=admin).status_code == 404