"""生成草稿审核：失败模块不影响已成功草稿，拒绝不会入库。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.models.identity import User
from app.features.test_management.services.generation_service import GenerationService, modules_for
from tests.conftest import unique


def _project(api, actor) -> int:
    """创建项目。"""
    response = api.post("/projects", username=actor, json={"name": unique("生成项目"), "description": "draft"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _actor(db) -> User:
    """测试管理员已经由夹具写入。"""
    user = db.query(User).filter(User.username == "platform_admin").one()
    return user


def _suite() -> dict:
    """一份不调用模型的生成结果：接口成功，安全失败。"""
    return {
        "status": "PARTIAL_FAILED",
        "supervisor": {"id": None, "name": "主 Agent", "version": 3, "model_config_id": None, "model_name": "synthetic"},
        "review": {"status": "SUCCEEDED", "summary": "覆盖了主路径", "gaps": ["阈值待确认"]},
        "modules": [
            {
                "id": None, "name": "接口子 Agent", "version": 2, "module": "api", "status": "SUCCEEDED",
                "model_config_id": None, "model_name": "synthetic",
                "cases": [{
                    "title": unique("登录成功"), "priority": "P1", "requirement": "使用正确账号可以登录",
                    "preconditions": ["账号已存在"], "test_data": ["username=demo"],
                    "steps": ["提交登录"], "expected_results": ["返回已登录"],
                    "coverage": ["功能"], "needs_confirmation": [],
                }],
            },
            {"id": None, "name": "安全子 Agent", "version": 1, "module": "security", "status": "FAILED", "cases": [], "error": "模块用例生成失败"},
        ],
    }


def test_direction_module_mapping():
    """三个方向映射到既有生成模块；安全模块未绑定时跳过。"""
    modules, notes = modules_for("AI", True, {"ai", "asr"})
    assert modules == ["ai", "asr"]
    assert notes[0]["module"] == "security"
    modules, notes = modules_for("UI", False, {"web"})
    assert modules == ["web"]
    assert notes == []
    with pytest.raises(HTTPException):
        modules_for("API", False, {"web"})


def test_failed_module_keeps_successful_draft_until_review(api, admin, db):
    """安全模块失败仍保留接口草稿；拒绝不入库，接受后才是正式用例。"""
    project_id = _project(api, admin)
    service = GenerationService()
    batch = service.persist(
        db, _actor(db), project_id=project_id, direction="API", scope_node_id=None,
        requirements="登录", suite=_suite(),
    )
    assert batch.status == "PARTIAL_FAILED"
    assert len(batch.drafts) == 1
    assert batch.module_errors[0]["module"] == "security"
    draft_id = batch.drafts[0].id
    renamed = api.patch(f"/case-drafts/{draft_id}", username=admin, json={"title": "改名后的草稿"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "改名后的草稿"

    rejected = api.post(f"/case-drafts/{draft_id}/reject", username=admin)
    assert rejected.status_code == 200, rejected.text
    again = api.post(f"/case-drafts/{draft_id}/accept", username=admin)
    assert again.status_code == 400, again.text
    listed = api.get(f"/projects/{project_id}/test-scope-cases", username=admin, params={"direction": "API"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 0

    second = service.persist(
        db, _actor(db), project_id=project_id, direction="API", scope_node_id=None,
        requirements="登录", suite=_suite(),
    )
    accepted = api.post(f"/case-drafts/{second.drafts[0].id}/accept", username=admin)
    assert accepted.status_code == 200, accepted.text
    case_id = accepted.json()["test_case_id"]
    detail = api.get(f"/test-cases/{case_id}/detail", username=admin)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["source_type"] == "AI"
    assert body["generation"]["supervisor_version"] == 3
    assert body["generation"]["review_status"] == "ACCEPTED"
    assert body["steps"]
    ui = api.get(f"/projects/{project_id}/test-scopes/stats", username=admin, params={"direction": "UI"})
    assert ui.json()["case_count"] == 0
    api_stats = api.get(f"/projects/{project_id}/test-scopes/stats", username=admin, params={"direction": "API"})
    assert api_stats.json()["case_count"] == 1


def test_scope_case_page_stays_bounded(api, admin):
    """分页只返回当前页。连续创建多条用例后，总数增加但单页条数不超过 page_size。"""
    project_id = _project(api, admin)
    for index in range(12):
        response = api.post(
            f"/projects/{project_id}/test-cases", username=admin,
            json={"name": unique(f"分页{index}")},
        )
        assert response.status_code == 201, response.text
    page = api.get(
        f"/projects/{project_id}/test-scope-cases", username=admin,
        params={"direction": "API", "page": 1, "page_size": 5},
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] >= 12
    assert len(body["items"]) == 5
