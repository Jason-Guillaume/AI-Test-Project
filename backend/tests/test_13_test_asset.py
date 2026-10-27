"""验收项 13：测试资产（TestStrategy / TestPoint / TestCase）CRUD + 项目隔离 + 乐观锁 + 子实体。

覆盖 §33 测试资产相关用例：
- TestStrategy CRUD（建/列/查/改/删）+ 无效枚举 422
- TestPoint CRUD + strategy 跨项目校验
- TestCase CRUD + revision 乐观锁（stale→409，正确→递增）
- TestCase 子实体：前置条件 / 测试数据 / 步骤 / 断言 的 CRUD + 聚合详情
- 项目隔离：跨项目访问 404；viewer 只读（写 403、读 200）

权限约定（§25/§30）：所有测试资产归属 Project；越权与不存在共用 404。
"""

from __future__ import annotations

from tests.conftest import unique

API = "/api/v1"


# ---------------------------------------------------------------- 项目/成员辅助


def _create_project(api, actor, name=None):
    """创建项目。"""
    proj_name = name or unique("proj")
    r = api.post("/projects", username=actor, json={"name": proj_name, "description": "test-asset project"})
    assert r.status_code == 201, r.text
    return r.json()["id"], proj_name


def _register_and_login(api, username):
    """注册测试用户并完成登录，返回用户标识。"""
    r = api.register(username)
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    api.login(username, "Init-Password-123")
    return user_id


def _add_member(api, actor, project_id, user_id, role="member"):
    """添加成员。"""
    r = api.put(
        f"/projects/{project_id}/members/{user_id}",
        username=actor, json={"user_id": user_id, "role": role},
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- 测试策略


class TestStrategy:
    """测试策略 CRUD 与枚举校验。"""

    def test_strategy_crud(self, api, admin):
        """验证策略增删改查场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        # 建。
        r = api.post(
            f"/projects/{project_id}/test-strategies", username=admin,
            json={"name": "登录功能策略", "description": "覆盖登录正向", "category": "AUTH", "enabled": True},
        )
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        assert r.json()["category"] == "AUTH"
        assert r.json()["source_type"] == "MANUAL"  # §27：预留 AI，默认 MANUAL
        # 列。
        r = api.get(f"/projects/{project_id}/test-strategies", username=admin)
        assert r.status_code == 200
        assert any(s["id"] == sid for s in r.json())
        # 查。
        r = api.get(f"/test-strategies/{sid}", username=admin)
        assert r.status_code == 200
        assert r.json()["name"] == "登录功能策略"
        # 改。
        r = api.patch(f"/test-strategies/{sid}", username=admin, json={"name": "登录功能策略v2", "enabled": False})
        assert r.status_code == 200
        assert r.json()["name"] == "登录功能策略v2"
        assert r.json()["enabled"] is False
        # 删。
        r = api.delete(f"/test-strategies/{sid}", username=admin)
        assert r.status_code == 204
        r = api.get(f"/test-strategies/{sid}", username=admin)
        assert r.status_code == 404

    def test_strategy_invalid_category_rejected(self, api, admin):
        """验证策略无效`category`被拒绝场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        r = api.post(
            f"/projects/{project_id}/test-strategies", username=admin,
            json={"name": "x", "category": "BOGUS"},
        )
        # 枚举非法 → Pydantic 校验 422。
        assert r.status_code == 422

    def test_strategy_filter_by_category(self, api, admin):
        """验证策略筛选条件按`category`场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        for cat in ("AUTH", "FUNCTIONAL"):
            api.post(f"/projects/{project_id}/test-strategies", username=admin,
                     json={"name": unique(f"strat-{cat}"), "category": cat})
        r = api.get(f"/projects/{project_id}/test-strategies", username=admin, params={"category": "AUTH"})
        assert r.status_code == 200
        assert all(s["category"] == "AUTH" for s in r.json())


# ---------------------------------------------------------------- 测试点


class TestPoint:
    """测试点 CRUD + strategy 跨项目校验。"""

    def test_point_crud(self, api, admin):
        """验证检查点增删改查场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        sid = api.post(f"/projects/{project_id}/test-strategies", username=admin,
                       json={"name": unique("strat")}).json()["id"]
        # 建：关联策略 + 接口类型。
        r = api.post(
            f"/projects/{project_id}/test-points", username=admin,
            json={"name": "登录成功返回 token", "priority": "P0", "target_type": "API",
                  "strategy_id": sid, "status": "ACTIVE"},
        )
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        assert r.json()["priority"] == "P0"
        # 列（按 strategy 过滤）。
        r = api.get(f"/projects/{project_id}/test-points", username=admin, params={"strategy_id": sid})
        assert r.status_code == 200
        assert any(p["id"] == pid for p in r.json())
        # 改 / 删。
        r = api.patch(f"/test-points/{pid}", username=admin, json={"priority": "P1"})
        assert r.status_code == 200 and r.json()["priority"] == "P1"
        assert api.delete(f"/test-points/{pid}", username=admin).status_code == 204
        assert api.get(f"/test-points/{pid}", username=admin).status_code == 404

    def test_point_cross_project_strategy_rejected(self, api, admin):
        """测试点引用了别的项目的策略 → 404（跨项目不可见）。"""
        p1, _ = _create_project(api, admin)
        p2, _ = _create_project(api, admin)
        sid = api.post(f"/projects/{p1}/test-strategies", username=admin,
                       json={"name": unique("strat")}).json()["id"]
        r = api.post(
            f"/projects/{p2}/test-points", username=admin,
            json={"name": "跨项目点", "strategy_id": sid},
        )
        assert r.status_code == 404  # 策略不在本项目 → 404


# ---------------------------------------------------------------- 测试用例 + 乐观锁


class TestCaseCrud:
    """测试用例 CRUD + revision 乐观锁。"""

    def test_case_crud(self, api, admin):
        """验证用例增删改查场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        r = api.post(
            f"/projects/{project_id}/test-cases", username=admin,
            json={"name": "登录正向用例", "priority": "P0", "case_type": "FUNCTIONAL",
                  "target_type": "API", "status": "ACTIVE", "enabled": True},
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert r.json()["revision"] == 1  # 初始版本号
        # 列。
        r = api.get(f"/projects/{project_id}/test-cases", username=admin)
        assert r.status_code == 200
        assert any(c["id"] == cid for c in r.json())
        # 查。
        r = api.get(f"/test-cases/{cid}", username=admin)
        assert r.status_code == 200 and r.json()["name"] == "登录正向用例"
        # 删。
        assert api.delete(f"/test-cases/{cid}", username=admin).status_code == 204
        assert api.get(f"/test-cases/{cid}", username=admin).status_code == 404

    def test_revision_optimistic_lock(self, api, admin):
        """§26：stale revision 更新 → 409，提示已被其他用户修改；正确 revision → 递增。"""
        project_id, _ = _create_project(api, admin)
        cid = api.post(
            f"/projects/{project_id}/test-cases", username=admin,
            json={"name": unique("case")},
        ).json()["id"]
        # 初始 revision=1；带正确 revision 更新 → 200，revision→2。
        r = api.patch(f"/test-cases/{cid}", username=admin, json={"name": "v2", "revision": 1})
        assert r.status_code == 200, r.text
        assert r.json()["revision"] == 2
        # 用 stale revision=1 再改 → 409。
        r = api.patch(f"/test-cases/{cid}", username=admin, json={"name": "v3", "revision": 1})
        assert r.status_code == 409
        assert "已被其他用户修改" in r.json()["message"]
        # 当前仍是 v2（stale 未生效）。
        assert api.get(f"/test-cases/{cid}", username=admin).json()["name"] == "v2"
        # 用正确 revision=2 改 → 200，revision→3。
        r = api.patch(f"/test-cases/{cid}", username=admin, json={"name": "v4", "revision": 2})
        assert r.status_code == 200 and r.json()["revision"] == 3

    def test_case_unique_name_per_project(self, api, admin):
        """同项目用例名唯一 → 重复建 409。"""
        project_id, _ = _create_project(api, admin)
        name = unique("dup-case")
        api.post(f"/projects/{project_id}/test-cases", username=admin, json={"name": name})
        r = api.post(f"/projects/{project_id}/test-cases", username=admin, json={"name": name})
        assert r.status_code == 409


# ---------------------------------------------------------------- 用例子实体 + 聚合详情


class TestCaseSubEntities:
    """前置条件 / 测试数据 / 步骤 / 断言 的 CRUD + 聚合详情。"""

    def _make_case(self, api, admin, project_id):
        """构造用例。"""
        return api.post(
            f"/projects/{project_id}/test-cases", username=admin,
            json={"name": unique("case")},
        ).json()["id"]

    def test_sub_crud_and_detail(self, api, admin):
        """验证`sub`增删改查和详情场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        cid = self._make_case(api, admin, project_id)

        # 前置条件。
        pc = api.post(f"/test-cases/{cid}/preconditions", username=admin,
                      json={"type": "VARIABLE", "target": "token", "operator": "EXISTS",
                            "expected_value": None, "sort": 0}).json()
        assert pc["operator"] == "EXISTS"
        api.patch(f"/test-case-preconditions/{pc['id']}", username=admin, json={"operator": "EQ"})

        # 测试数据。
        d1 = api.post(f"/test-cases/{cid}/data", username=admin,
                      json={"name": "username", "value": "admin", "value_type": "STRING",
                            "source_type": "STATIC", "sort": 0}).json()
        d2 = api.post(f"/test-cases/{cid}/data", username=admin,
                      json={"name": "password", "value": "secret", "value_type": "STRING",
                            "source_type": "STATIC", "sort": 1}).json()
        assert d1["name"] == "username"
        # 重复数据名 → 409。
        r = api.post(f"/test-cases/{cid}/data", username=admin,
                     json={"name": "username", "value": "x"})
        assert r.status_code == 409

        # 步骤。
        st = api.post(f"/test-cases/{cid}/steps", username=admin,
                      json={"name": "发送登录请求", "step_type": "ACTION",
                            "config_json": {"method": "POST"}, "sort": 0}).json()
        api.patch(f"/test-steps/{st['id']}", username=admin, json={"name": "发送登录请求v2"})

        # 断言。
        a1 = api.post(f"/test-cases/{cid}/assertions", username=admin,
                      json={"assertion_type": "STATUS_CODE", "operator": "EQ",
                            "expected_value": "200", "required": True, "sort": 0}).json()
        a2 = api.post(f"/test-cases/{cid}/assertions", username=admin,
                      json={"assertion_type": "JSON_PATH", "path": "$.code",
                            "operator": "EQ", "expected_value": "0", "sort": 1}).json()
        assert a2["assertion_type"] == "JSON_PATH"

        # 聚合详情：一次性拿到全部子实体。
        r = api.get(f"/test-cases/{cid}/detail", username=admin)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert len(detail["preconditions"]) == 1
        assert len(detail["test_data"]) == 2
        assert detail["test_data"][0]["name"] == "username"
        assert len(detail["steps"]) == 1
        assert detail["steps"][0]["name"] == "发送登录请求v2"
        assert len(detail["assertions"]) == 2

        # 删子实体。
        assert api.delete(f"/test-case-data/{d2['id']}", username=admin).status_code == 204
        assert api.delete(f"/test-assertions/{a1['id']}", username=admin).status_code == 204
        detail = api.get(f"/test-cases/{cid}/detail", username=admin).json()
        assert len(detail["test_data"]) == 1
        assert len(detail["assertions"]) == 1


# ---------------------------------------------------------------- 项目隔离


class TestProjectIsolation:
    """§25：跨项目访问 404；viewer 只读。"""

    def test_cross_project_hidden_as_404(self, api, admin):
        """验证跨项目项目`hidden``as`场景及其预期结果。"""
        owner = unique("owner")
        observer = unique("observer")
        owner_id = _register_and_login(api, owner)
        _register_and_login(api, observer)  # 观察者：不在项目里
        project_id, _ = _create_project(api, admin)  # admin 建项目
        _add_member(api, admin, project_id, owner_id, "member")
        sid = api.post(f"/projects/{project_id}/test-strategies", username=owner,
                       json={"name": unique("strat")}).json()["id"]
        # 观察者不在项目里 → 列该项目策略 404、查具体策略 404。
        assert api.get(f"/projects/{project_id}/test-strategies", username=observer).status_code == 404
        assert api.get(f"/test-strategies/{sid}", username=observer).status_code == 404

    def test_viewer_can_read_not_write(self, api, admin):
        """验证`viewer`可以读取不写入场景及其预期结果。"""
        owner = unique("owner")
        viewer = unique("viewer")
        owner_id = _register_and_login(api, owner)
        viewer_id = _register_and_login(api, viewer)
        project_id, _ = _create_project(api, admin)
        _add_member(api, admin, project_id, owner_id, "member")
        _add_member(api, admin, project_id, viewer_id, "viewer")
        # viewer 写 → 403。
        r = api.post(f"/projects/{project_id}/test-strategies", username=viewer,
                     json={"name": "越权策略"})
        assert r.status_code == 403
        # viewer 读 → 200。
        assert api.get(f"/projects/{project_id}/test-strategies", username=viewer).status_code == 200
