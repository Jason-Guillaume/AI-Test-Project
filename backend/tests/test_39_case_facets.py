"""用例双维过滤与覆盖矩阵（P0：对象 × 维度交叉替代范围树）。

覆盖：
- GET /projects/{id}/test-cases 新增 case_type / strategy_id 过滤（非法枚举 400）
- GET /projects/{id}/test-cases/coverage 按 target_type × case_type 聚合用例数与接口数
- strategy_id 过滤经测试点归属，未挂测试点的用例不进结果
- 项目隔离：coverage 不混计其他项目的用例；不可见项目 404

权限约定不变：读 viewer+；越权与不存在共用 404。
"""

from __future__ import annotations

from tests.conftest import unique

API = "/api/v1"


def _create_project(api, actor):
    """创建项目并返回项目ID。"""
    r = api.post("/projects", username=actor, json={"name": unique("proj"), "description": "case-facets"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_case(api, actor, project_id, name, **overrides):
    """创建一条用例并返回响应体。"""
    body = {"name": name, **overrides}
    r = api.post(f"/projects/{project_id}/test-cases", username=actor, json=body)
    assert r.status_code == 201, r.text
    return r.json()


class TestCaseFacetFilters:
    """列表新增 case_type / strategy_id 过滤。"""

    def test_case_type_filter(self, api, admin):
        """按用例维度过滤，只回该维度用例；非法取值 400。"""
        project_id = _create_project(api, admin)
        _create_case(api, admin, project_id, unique("功能"), case_type="FUNCTIONAL")
        _create_case(api, admin, project_id, unique("边界"), case_type="BOUNDARY")

        r = api.get(f"/projects/{project_id}/test-cases", username=admin, params={"case_type": "BOUNDARY"})
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) == 1
        assert items[0]["case_type"] == "BOUNDARY"

        r = api.get(f"/projects/{project_id}/test-cases", username=admin, params={"case_type": "NOPE"})
        assert r.status_code == 400, r.text

    def test_strategy_filter_via_point(self, api, admin):
        """用例经测试点归属策略；未挂测试点的用例不进 strategy_id 过滤结果。"""
        project_id = _create_project(api, admin)
        r = api.post(
            f"/projects/{project_id}/test-strategies", username=admin,
            json={"name": unique("策略"), "category": "SECURITY"},
        )
        assert r.status_code == 201, r.text
        strategy_id = r.json()["id"]
        r = api.post(
            f"/projects/{project_id}/test-points", username=admin,
            json={"name": unique("测试点"), "strategy_id": strategy_id, "target_type": "API"},
        )
        assert r.status_code == 201, r.text
        point_id = r.json()["id"]

        in_scope = _create_case(api, admin, project_id, unique("挂在点上"), test_point_id=point_id)
        _create_case(api, admin, project_id, unique("没挂点"))

        r = api.get(
            f"/projects/{project_id}/test-cases", username=admin, params={"strategy_id": strategy_id},
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert [item["id"] for item in items] == [in_scope["id"]]

    def test_ai_target_accepted(self, api, admin):
        """AI 对象已进枚举：可建、可过滤、进覆盖矩阵。"""
        project_id = _create_project(api, admin)
        _create_case(api, admin, project_id, unique("AI"), target_type="AI", case_type="SECURITY")

        r = api.get(f"/projects/{project_id}/test-cases", username=admin, params={"target_type": "AI"})
        assert r.status_code == 200, r.text
        assert len(r.json()) == 1

        r = api.get(f"/projects/{project_id}/test-cases/coverage", username=admin)
        cells = {(i["target_type"], i["case_type"]): i for i in r.json()["items"]}
        assert cells[("AI", "SECURITY")]["case_count"] == 1

    def test_combined_facets(self, api, admin):
        """target_type 与 case_type 叠加取交集。"""
        project_id = _create_project(api, admin)
        _create_case(api, admin, project_id, unique("接口边界"), target_type="API", case_type="BOUNDARY")
        _create_case(api, admin, project_id, unique("界面边界"), target_type="WEB", case_type="BOUNDARY")

        r = api.get(
            f"/projects/{project_id}/test-cases", username=admin,
            params={"target_type": "WEB", "case_type": "BOUNDARY"},
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) == 1
        assert items[0]["target_type"] == "WEB"


class TestCaseCoverage:
    """覆盖矩阵端点。"""

    def test_coverage_matrix(self, api, admin):
        """同一交叉格聚合用例数；无 api_id 时接口数为 0。"""
        project_id = _create_project(api, admin)
        _create_case(api, admin, project_id, unique("a"), target_type="API", case_type="BOUNDARY")
        _create_case(api, admin, project_id, unique("b"), target_type="API", case_type="BOUNDARY")
        _create_case(api, admin, project_id, unique("c"), target_type="API", case_type="SECURITY")
        _create_case(api, admin, project_id, unique("d"), target_type="WEB", case_type="FUNCTIONAL")

        r = api.get(f"/projects/{project_id}/test-cases/coverage", username=admin)
        assert r.status_code == 200, r.text
        cells = {(i["target_type"], i["case_type"]): i for i in r.json()["items"]}
        assert cells[("API", "BOUNDARY")]["case_count"] == 2
        assert cells[("API", "BOUNDARY")]["api_count"] == 0
        assert cells[("API", "SECURITY")]["case_count"] == 1
        assert cells[("WEB", "FUNCTIONAL")]["case_count"] == 1
        assert ("WEB", "SECURITY") not in cells

    def test_coverage_target_type_filter(self, api, admin):
        """coverage 支持按对象收窄；非法取值 400。"""
        project_id = _create_project(api, admin)
        _create_case(api, admin, project_id, unique("a"), target_type="API")
        _create_case(api, admin, project_id, unique("b"), target_type="WEB")

        r = api.get(
            f"/projects/{project_id}/test-cases/coverage", username=admin, params={"target_type": "WEB"},
        )
        assert r.status_code == 200, r.text
        assert {item["target_type"] for item in r.json()["items"]} == {"WEB"}

        r = api.get(
            f"/projects/{project_id}/test-cases/coverage", username=admin, params={"target_type": "NOPE"},
        )
        assert r.status_code == 400, r.text

    def test_coverage_project_isolation(self, api, admin):
        """矩阵只统计本项目；不可见项目 404。"""
        project_a = _create_project(api, admin)
        project_b = _create_project(api, admin)
        _create_case(api, admin, project_a, unique("a"), target_type="API")

        r = api.get(f"/projects/{project_b}/test-cases/coverage", username=admin)
        assert r.status_code == 200, r.text
        assert r.json()["items"] == []

        r = api.register(unique("outsider"))
        assert r.status_code == 201, r.text
        outsider = r.json()["user"]["username"]
        api.login(outsider, "Init-Password-123")
        r = api.get(f"/projects/{project_a}/test-cases/coverage", username=outsider)
        assert r.status_code == 404, r.text
