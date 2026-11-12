"""验收项 14：测试管理（TestSuite / TestPlan / TestRun 列表）CRUD + 关联 + 项目隔离。

覆盖 §33 测试管理相关用例（执行端到端在 test_15）：
- TestSuite CRUD + 套件-用例关联（加/列/移/去重 409）
- TestPlan CRUD + 计划-套件关联（加/列/移/去重 409）+ environment 校验
- TestRun 列表（空列表 200）
- 项目隔离：跨项目查计划 / 套件 404；viewer 只读

权限约定（§25/§30）：越权与不存在共用 404。
"""

from __future__ import annotations

from tests.conftest import unique

API = "/api/v1"


def _create_project(api, actor, name=None):
    """创建项目。"""
    proj_name = name or unique("proj")
    r = api.post("/projects", username=actor, json={"name": proj_name, "description": "test-mgmt project"})
    assert r.status_code == 201, r.text
    return r.json()["id"], proj_name


def _register_and_login(api, username):
    """注册测试用户并完成登录，返回用户标识。"""
    r = api.register(username)
    assert r.status_code == 201, r.text
    uid = r.json()["user"]["id"]
    api.login(username, "Init-Password-123")
    return uid


def _add_member(api, actor, project_id, user_id, role="member"):
    """添加成员。"""
    r = api.put(f"/projects/{project_id}/members/{user_id}", username=actor,
                json={"user_id": user_id, "role": role})
    assert r.status_code == 200, r.text


def _make_case(api, admin, project_id, name=None):
    """构造用例。"""
    return api.post(
        f"/projects/{project_id}/test-cases", username=admin,
        json={"name": name or unique("case")},
    ).json()["id"]


# ---------------------------------------------------------------- 测试套件


class TestSuite:
    """测试套件 CRUD + 套件-用例关联。"""

    def test_suite_crud(self, api, admin):
        """验证套件增删改查场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        r = api.post(f"/projects/{project_id}/test-suites", username=admin,
                     json={"name": "回归套件", "suite_type": "REGRESSION", "enabled": True})
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        assert r.json()["suite_type"] == "REGRESSION"
        # 列。
        assert any(s["id"] == sid for s in api.get(f"/projects/{project_id}/test-suites", username=admin).json())
        # 改 / 删。
        assert api.patch(f"/test-suites/{sid}", username=admin, json={"name": "回归套件v2"}).status_code == 200
        assert api.delete(f"/test-suites/{sid}", username=admin).status_code == 204
        assert api.get(f"/test-suites/{sid}", username=admin).status_code == 404

    def test_suite_case_association_and_dedup(self, api, admin):
        """验证套件用例`association`和`dedup`场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        sid = api.post(f"/projects/{project_id}/test-suites", username=admin,
                       json={"name": unique("suite")}).json()["id"]
        cid = _make_case(api, admin, project_id)
        # 加入套件。
        r = api.post(f"/test-suites/{sid}/cases", username=admin,
                     json={"test_case_id": cid, "sort": 0, "enabled": True})
        assert r.status_code == 201
        sc_id = r.json()["id"]
        # 列。
        assert any(c["test_case_id"] == cid for c in api.get(f"/test-suites/{sid}/cases", username=admin).json())
        # 重复加入 → 409。
        assert api.post(f"/test-suites/{sid}/cases", username=admin,
                        json={"test_case_id": cid}).status_code == 409
        # 移除。
        assert api.delete(f"/test-suite-cases/{sc_id}", username=admin).status_code == 204
        assert api.get(f"/test-suites/{sid}/cases", username=admin).json() == []

    def test_suite_case_cross_project_rejected(self, api, admin):
        """套件加入别项目的用例 → 404（用例对本项目不可见）。"""
        p1, _ = _create_project(api, admin)
        p2, _ = _create_project(api, admin)
        sid = api.post(f"/projects/{p1}/test-suites", username=admin,
                       json={"name": unique("suite")}).json()["id"]
        cid = _make_case(api, admin, p2)
        assert api.post(f"/test-suites/{sid}/cases", username=admin,
                        json={"test_case_id": cid}).status_code == 404


# ---------------------------------------------------------------- 测试计划


class TestPlan:
    """测试计划 CRUD + 计划-套件关联 + environment 校验。"""

    def test_plan_crud(self, api, admin):
        """验证计划增删改查场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        r = api.post(f"/projects/{project_id}/test-plans", username=admin,
                     json={"name": "每日回归", "status": "DRAFT", "execution_mode": "MANUAL"})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        assert r.json()["environment_id"] is None
        # 列。
        assert any(p["id"] == pid for p in api.get(f"/projects/{project_id}/test-plans", username=admin).json())
        # 改 / 删。
        assert api.patch(f"/test-plans/{pid}", username=admin, json={"status": "ACTIVE"}).status_code == 200
        assert api.delete(f"/test-plans/{pid}", username=admin).status_code == 204
        assert api.get(f"/test-plans/{pid}", username=admin).status_code == 404

    def test_plan_suite_association_and_dedup(self, api, admin):
        """验证计划套件`association`和`dedup`场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        pid = api.post(f"/projects/{project_id}/test-plans", username=admin,
                       json={"name": unique("plan")}).json()["id"]
        sid = api.post(f"/projects/{project_id}/test-suites", username=admin,
                       json={"name": unique("suite")}).json()["id"]
        # 加入计划。
        r = api.post(f"/test-plans/{pid}/suites", username=admin,
                     json={"suite_id": sid, "sort": 0})
        assert r.status_code == 201
        ps_id = r.json()["id"]
        # 列。
        assert any(s["suite_id"] == sid for s in api.get(f"/test-plans/{pid}/suites", username=admin).json())
        # 重复 → 409。
        assert api.post(f"/test-plans/{pid}/suites", username=admin,
                        json={"suite_id": sid}).status_code == 409
        # 移除。
        assert api.delete(f"/test-plan-suites/{ps_id}", username=admin).status_code == 204
        assert api.get(f"/test-plans/{pid}/suites", username=admin).json() == []

    def test_plan_environment_must_be_active(self, api, admin):
        """计划绑定不存在的 environment → 404。"""
        project_id, _ = _create_project(api, admin)
        r = api.post(f"/projects/{project_id}/test-plans", username=admin,
                     json={"name": unique("plan"), "environment_id": 999999})
        assert r.status_code == 404

    def test_plan_suite_cross_project_rejected(self, api, admin):
        """计划加入别项目的套件 → 404。"""
        p1, _ = _create_project(api, admin)
        p2, _ = _create_project(api, admin)
        pid = api.post(f"/projects/{p1}/test-plans", username=admin,
                       json={"name": unique("plan")}).json()["id"]
        sid = api.post(f"/projects/{p2}/test-suites", username=admin,
                       json={"name": unique("suite")}).json()["id"]
        assert api.post(f"/test-plans/{pid}/suites", username=admin,
                        json={"suite_id": sid}).status_code == 404


# ---------------------------------------------------------------- TestRun 列表 + 项目隔离


class TestRunListing:
    """TestRun 列表与项目隔离。执行端到端见 test_15。"""

    def test_run_list_empty(self, api, admin):
        """验证运行列出空值场景及其预期结果。"""
        project_id, _ = _create_project(api, admin)
        r = api.get(f"/projects/{project_id}/test-runs", username=admin)
        assert r.status_code == 200
        assert r.json()["items"] == []
        assert r.json()["total"] == 0

    def test_run_cross_project_hidden_as_404(self, api, admin):
        """验证运行跨项目项目`hidden``as`场景及其预期结果。"""
        observer = unique("observer")
        _register_and_login(api, observer)
        project_id, _ = _create_project(api, admin)
        # 观察者不在项目里 → 列该项目 runs 404。
        assert api.get(f"/projects/{project_id}/test-runs", username=observer).status_code == 404

    def test_plan_cross_project_hidden_as_404(self, api, admin):
        """验证计划跨项目项目`hidden``as`场景及其预期结果。"""
        owner = unique("owner")
        observer = unique("observer")
        owner_id = _register_and_login(api, owner)
        _register_and_login(api, observer)
        project_id, _ = _create_project(api, admin)
        _add_member(api, admin, project_id, owner_id, "member")
        pid = api.post(f"/projects/{project_id}/test-plans", username=owner,
                       json={"name": unique("plan")}).json()["id"]
        # 观察者查别项目的计划 → 404。
        assert api.get(f"/test-plans/{pid}", username=observer).status_code == 404
