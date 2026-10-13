"""验收项 8：缺陷管理 CRUD + 权限 + 通知。

覆盖：
- CRUD 全链路：创建、列表、详情、更新、删除
- 权限：viewer 无法写、member 可以写、跨项目越权按 404 隐藏
- 通知：defect.created / defect.assigned / defect.status_changed 事件入库
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
    """注册新用户并缓存令牌，返回新用户的 user_id。

    注册接口已改为返回 TokenResponse，其中的 user.id 是后续加入项目、
    分配处理人等操作需要的用户主键。
    """
    response = api.register(username)
    assert response.status_code == 201, response.text
    user_id = response.json()["user"]["id"]
    # 走一次 login 缓存令牌，便于后续用 username= 参数直接发请求。
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

    # 1. 创建缺陷
    create_body = {
        "project_id": project_id,
        "title": "登录页返回 500",
        "description": "使用错误密码登录时服务端异常",
        "severity": 3,
        "status": "待确认",
        "steps_to_reproduce": "1. 打开登录页\n2. 输入错误密码\n3. 点击登录",
        "environment": "dev",
    }
    r = api.post("/bugs", username=admin, json=create_body)
    assert r.status_code == 201, r.text
    bug = r.json()
    assert bug["title"] == "登录页返回 500"
    assert bug["status"] == "待确认"
    assert bug["severity"] == 3
    assert bug["reporter_username"] == admin
    assert bug["project_name"]
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

    # 7. 更新：修改状态 + 严重度
    r = api.put(
        f"/bugs/{bug_id}",
        username=admin,
        json={"status": "处理中", "severity": 4},
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["status"] == "处理中"
    assert updated["severity"] == 4

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


def test_defect_update_status_triggers_notification(api, admin):
    """更新缺陷状态时，报告人应收到 defect.status_changed 通知。"""
    project_id, _ = _create_project(api, admin)
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "状态变更冒烟"},
    )
    bug_id = r.json()["id"]
    r = api.put(f"/bugs/{bug_id}", username=admin, json={"status": "已修复"})
    assert r.status_code == 200

    r = api.get("/notifications", username=admin, params={"page_size": 20})
    event_types = [item["event_type"] for item in r.json()["items"]]
    assert "defect.status_changed" in event_types


def test_defect_assign_triggers_notification(api, admin):
    """修改缺陷处理人时，新处理人应收到 defect.assigned 通知。"""
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
    assert r.status_code == 200, r.text
    assert r.json()["assignee_username"] == target_name

    r = api.get("/notifications", username=target_name, params={"page_size": 20})
    event_types = [item["event_type"] for item in r.json()["items"]]
    assert "defect.assigned" in event_types


def test_defect_notifications_catalog_lists_defect_events(api, admin):
    """GET /notifications/events 应列出三个缺陷事件类型。"""
    r = api.get("/notifications/events", username=admin)
    assert r.status_code == 200
    values = {item["value"] for item in r.json()}
    assert "defect.created" in values
    assert "defect.assigned" in values
    assert "defect.status_changed" in values


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

    # viewer 修改/删除缺陷应被拒。
    r = api.put(f"/bugs/{bug_id}", username=viewer_name, json={"title": "被拒改"})
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
    # 按 project_id 过滤而非全量列表：项目本身对观察者是可见的（未绑定组织的
    # 项目按当前 visibility 口径属于「共享」），全量列表在套件运行中会被
    # 前序用例创建的公开项目污染；用 project_id 过滤才能准确验「该项目下
    # 无观察者可读缺陷」这一不变量。
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


def test_defect_assignee_must_be_project_member(api, admin):
    """assignee 必须是项目成员，否则 400。"""
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
    assert r.status_code == 400


def test_defect_clear_assignee_by_putting_none(api, admin):
    """PUT 时显式 assignee_id=None 应清空处理人。"""
    project_id, _ = _create_project(api, admin)
    r = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "清空处理人"},
    )
    bug_id = r.json()["id"]

    r = api.put(f"/bugs/{bug_id}", username=admin, json={"assignee_id": None})
    assert r.status_code == 200
    assert r.json()["assignee_id"] is None
    assert r.json()["assignee_username"] is None
