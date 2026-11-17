"""缺陷前后端划分与原子批量创建测试。

覆盖：
- 单条缺陷前后端划分（前端/前后端/接口；旧「后端」自动归并为「接口」）创建、编辑、更新保留语义、按分类与「未划分」筛选
- 批量创建接口 POST /bugs/batch：全字段写入、站内通知、权限控制（viewer 403 / outsider 404）
- 批量创建原子事务与行号精确定位：任一行失败时整批不入库并返回 meta.errors
- Alembic 0091 迁移升降级及历史存量空分类兼容；0092 将存量「后端」归并为「接口」
"""

from __future__ import annotations

from alembic import command
from sqlalchemy import inspect, text

from app.features.defects.models.bug import Bug
from tests.conftest import DEFAULT_PASSWORD, unique


def _create_project(api, actor, name: str | None = None) -> int:
    """创建测试项目并返回项目 ID。"""
    response = api.post(
        "/projects",
        username=actor,
        json={"name": name or unique("defect-proj"), "description": "defect category & batch test"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _register_and_login(api, username: str) -> int:
    """注册并登录测试用户，返回用户 ID。"""
    response = api.register(username)
    assert response.status_code == 201, response.text
    api.login(username, DEFAULT_PASSWORD)
    return response.json()["user"]["id"]


def _add_member(api, actor, project_id: int, user_id: int, role: str = "member") -> None:
    """将用户加入项目并授予指定角色。"""
    response = api.put(
        f"/projects/{project_id}/members/{user_id}",
        username=actor,
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 200, response.text


def test_bug_category_crud_and_filtering(api, admin):
    """缺陷支持前后端划分创建、修改及按前端/前后端/接口/未划分过滤；旧「后端」入参自动归并为「接口」。"""
    project_id = _create_project(api, admin)

    # 1. 创建前端缺陷、接口缺陷（含旧「后端」入参）、前后端缺陷与未划分缺陷
    r_fe = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "按钮样式错位", "category": "前端", "severity": 2},
    )
    assert r_fe.status_code == 201, r_fe.text
    fe_bug = r_fe.json()
    assert fe_bug["category"] == "前端"

    # 旧入参「后端」自动归并为「接口」：选择后端即关联接口缺陷
    r_legacy_be = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "接口超时 504", "category": "后端", "severity": 4},
    )
    assert r_legacy_be.status_code == 201, r_legacy_be.text
    legacy_be_bug = r_legacy_be.json()
    assert legacy_be_bug["category"] == "接口"

    r_both = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "鉴权字段前后端协议不一致", "category": "前后端", "severity": 3},
    )
    assert r_both.status_code == 201, r_both.text
    both_bug = r_both.json()
    # 「前后端」与「前端」共用同一提交表单，但落库类型保留「前后端」
    assert both_bug["category"] == "前后端"

    r_api = api.post(
        "/bugs",
        username=admin,
        json={
            "project_id": project_id,
            "title": "订单查询接口返回字段缺失",
            "category": "接口",
            "severity": 3,
            "api_method": "GET",
            "api_url": "/v1/orders/SO-12345",
            "api_request_headers": '{"Authorization": "Bearer ***"}',
            "api_request_body": None,
            "api_response": '{"code": 200, "data": {"orderNo": null}}',
        },
    )
    assert r_api.status_code == 201, r_api.text
    api_bug = r_api.json()
    assert api_bug["category"] == "接口"
    # 接口专属字段随创建落库并在响应中回显
    assert api_bug["api_method"] == "GET"
    assert api_bug["api_url"] == "/v1/orders/SO-12345"
    assert api_bug["api_request_headers"] == '{"Authorization": "Bearer ***"}'
    assert api_bug["api_response"] == '{"code": 200, "data": {"orderNo": null}}'

    r_uncat = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "历史未划分缺陷"},
    )
    assert r_uncat.status_code == 201, r_uncat.text
    uncat_bug = r_uncat.json()
    assert uncat_bug["category"] is None

    # 2. 按前后端划分过滤列表；「接口」与旧「后端」筛选值同义
    fe_list = api.get("/bugs", username=admin, params={"project_id": project_id, "category": "前端"})
    assert fe_list.status_code == 200
    assert [item["id"] for item in fe_list.json()["items"]] == [fe_bug["id"]]

    api_cat_list = api.get("/bugs", username=admin, params={"project_id": project_id, "category": "接口"})
    assert api_cat_list.status_code == 200
    assert {item["id"] for item in api_cat_list.json()["items"]} == {legacy_be_bug["id"], api_bug["id"]}

    alias_list = api.get("/bugs", username=admin, params={"project_id": project_id, "category": "后端"})
    assert alias_list.status_code == 200
    assert {item["id"] for item in alias_list.json()["items"]} == {legacy_be_bug["id"], api_bug["id"]}

    both_list = api.get("/bugs", username=admin, params={"project_id": project_id, "category": "前后端"})
    assert both_list.status_code == 200
    assert [item["id"] for item in both_list.json()["items"]] == [both_bug["id"]]

    uncat_list = api.get("/bugs", username=admin, params={"project_id": project_id, "category": "未划分"})
    assert uncat_list.status_code == 200
    assert [item["id"] for item in uncat_list.json()["items"]] == [uncat_bug["id"]]

    # 3. 非法分类入参和筛选分别被拒绝
    bad_create = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "非法归属", "category": "移动端"},
    )
    assert bad_create.status_code == 422

    bad_filter = api.get("/bugs", username=admin, params={"project_id": project_id, "category": "移动端"})
    assert bad_filter.status_code == 400

    # 4. 更新状态时不传 category 保持原归属不变；显式传 category 可切换归属
    keep_cat = api.put(f"/bugs/{fe_bug['id']}", username=admin, json={"status": "处理中"})
    assert keep_cat.status_code == 200
    assert keep_cat.json()["category"] == "前端"

    switch_cat = api.put(f"/bugs/{uncat_bug['id']}", username=admin, json={"category": "前后端"})
    assert switch_cat.status_code == 200
    assert switch_cat.json()["category"] == "前后端"

    merge_cat = api.put(f"/bugs/{fe_bug['id']}", username=admin, json={"category": "后端"})
    assert merge_cat.status_code == 200
    assert merge_cat.json()["category"] == "接口"

    # 5. 类别从「接口」切走时，提交置空的接口专属字段会被清空
    clear_api = api.put(
        f"/bugs/{api_bug['id']}",
        username=admin,
        json={"category": "前端", "api_method": None, "api_url": None,
              "api_request_headers": None, "api_response": None},
    )
    assert clear_api.status_code == 200
    cleared = clear_api.json()
    assert cleared["category"] == "前端"
    assert cleared["api_method"] is None
    assert cleared["api_url"] is None
    assert cleared["api_request_headers"] is None
    assert cleared["api_response"] is None

    # 非法请求方法被拒绝
    bad_method = api.post(
        "/bugs",
        username=admin,
        json={"project_id": project_id, "title": "非法方法", "category": "接口", "api_method": "FETCH"},
    )
    assert bad_method.status_code == 422


def test_batch_create_bugs_success_and_notifications(api, admin, db):
    """批量创建支持完整字段并写入缺陷及创建通知。"""
    project_id = _create_project(api, admin)
    dev_name = unique("dev")
    dev_id = _register_and_login(api, dev_name)
    _add_member(api, admin, project_id, dev_id, role="member")

    payload = {
        "project_id": project_id,
        "items": [
            {
                "title": "表单校验提示遮挡输入框",
                "category": "前端",
                "description": "窄屏下提示文案与输入框重叠",
                "severity": 2,
                "status": "待确认",
                "steps_to_reproduce": "1. 打开弹窗\n2. 直接点保存",
                "environment": "test",
                "assignee_id": dev_id,
            },
            {
                "title": "批量导出接口偶发 500",
                "category": "接口",
                "description": "并发请求时连接池耗尽",
                "severity": 4,
                "status": "处理中",
                "steps_to_reproduce": "1. 连续触发 10 次导出",
                "environment": "staging",
            },
            {
                "title": "登录态过期后前端未清理缓存且接口返回 401",
                "category": "前后端",
                "description": "token 刷新与拦截器跳转配合异常",
                "severity": 3,
                "status": "待确认",
                "environment": "test",
            },
        ],
    }
    response = api.post("/bugs/batch", username=admin, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created_count"] == 3
    assert len(body["items"]) == 3
    assert body["items"][0]["category"] == "前端"
    assert body["items"][0]["assignee_id"] == dev_id
    assert body["items"][0]["assignee_username"] == dev_name
    assert body["items"][0]["environment"] == "test"
    assert body["items"][1]["category"] == "接口"
    assert body["items"][1]["severity"] == 4
    assert body["items"][1]["status"] == "处理中"
    assert body["items"][2]["category"] == "前后端"

    # 数据库落库数量核对
    assert db.query(Bug).filter(Bug.project_id == project_id, Bug.deleted_at.is_(None)).count() == 3

    # 站内通知核对
    notifs = api.get("/notifications", username=admin, params={"page_size": 20})
    assert notifs.status_code == 200
    created_ids = {item["id"] for item in body["items"]}
    notified_bug_ids = {
        item["payload"]["detail"]["bug_id"]
        for item in notifs.json()["items"]
        if item["event_type"] == "defect.created"
    }
    assert created_ids <= notified_bug_ids


def test_batch_create_bugs_is_atomic_and_reports_row_errors(api, admin, db):
    """批量创建中任一行不合法时，整批回滚并精确返回出错行号和原因。"""
    project_id = _create_project(api, admin)
    stranger_name = unique("stranger")
    stranger_id = _register_and_login(api, stranger_name)

    response = api.post(
        "/bugs/batch",
        username=admin,
        json={
            "project_id": project_id,
            "items": [
                {"title": "第一条合法缺陷", "category": "前端", "severity": 2},
                {"title": "   ", "category": "接口", "assignee_id": stranger_id},
            ],
        },
    )
    assert response.status_code == 400, response.text
    err = response.json()
    assert "第 2 行" in err["message"]
    row_errors = err["meta"]["errors"]
    assert all(item["row"] == 2 for item in row_errors)
    assert {item["field"] for item in row_errors} == {"title", "assignee_id"}

    # 原子性验证：第一条合法缺陷也不能入库
    assert db.query(Bug).filter(Bug.project_id == project_id).count() == 0

    # 缺少 category 或超过上限 / 空列表走 422
    missing_cat = api.post(
        "/bugs/batch",
        username=admin,
        json={"project_id": project_id, "items": [{"title": "缺少分类"}]},
    )
    assert missing_cat.status_code == 422

    empty_items = api.post(
        "/bugs/batch",
        username=admin,
        json={"project_id": project_id, "items": []},
    )
    assert empty_items.status_code == 422


def test_batch_create_bugs_permissions(api, admin):
    """viewer 不能批量创建（403）；项目外用户隐藏项目存在性（404）。"""
    project_id = _create_project(api, admin)
    viewer_name = unique("viewer")
    viewer_id = _register_and_login(api, viewer_name)
    _add_member(api, admin, project_id, viewer_id, role="viewer")

    member_name = unique("member")
    member_id = _register_and_login(api, member_name)
    _add_member(api, admin, project_id, member_id, role="member")

    outsider_name = unique("outsider")
    _register_and_login(api, outsider_name)

    body = {
        "project_id": project_id,
        "items": [{"title": "权限校验缺陷", "category": "后端"}],
    }
    assert api.post("/bugs/batch", username=viewer_name, json=body).status_code == 403
    assert api.post("/bugs/batch", username=outsider_name, json=body).status_code == 404
    ok = api.post("/bugs/batch", username=member_name, json=body)
    assert ok.status_code == 201, ok.text
    assert ok.json()["created_count"] == 1


def test_migration_0091_downgrade_and_upgrade_idempotent(isolated_migration_database):
    """验证 0091 迁移可安全降级到 0090 再重新升级并保留索引。"""
    config, engine = isolated_migration_database

    command.downgrade(config, "0090")
    with engine.connect() as connection:
        inspector = inspect(connection)
        cols = {col["name"] for col in inspector.get_columns("bug")}
        assert "category" not in cols
        assert "bug_attachment" in set(inspector.get_table_names())
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0090"

    command.upgrade(config, "0091")
    with engine.connect() as connection:
        inspector = inspect(connection)
        cols = {col["name"] for col in inspector.get_columns("bug")}
        indexes = {idx["name"] for idx in inspector.get_indexes("bug")}
        assert "category" in cols
        assert {"ix_bug_category", "ix_bug_project_category"} <= indexes
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0091"

    # 重复执行 upgrade head 保持幂等
    command.upgrade(config, "head")
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "category" in {col["name"] for col in inspector.get_columns("bug")}


def test_migration_0092_merges_backend_into_api(isolated_migration_database):
    """0092 迁移把存量「后端」类别归并为「接口」；降级不回写数据。"""
    config, engine = isolated_migration_database

    command.downgrade(config, "0091")
    with engine.begin() as connection:
        # 跳过外键触发器直接插入缺陷行：迁移测试只关心 category 数据改写。
        connection.execute(text("SET session_replication_role = replica"))
        connection.execute(
            text(
                "INSERT INTO bug (project_id, title, category) "
                "VALUES (424242, '历史后端缺陷', '后端')"
            )
        )

    command.upgrade(config, "0092")
    with engine.connect() as connection:
        category = connection.execute(
            text("SELECT category FROM bug WHERE title = '历史后端缺陷'")
        ).scalar_one()
        assert category == "接口"
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0092"
