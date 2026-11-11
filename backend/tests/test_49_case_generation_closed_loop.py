"""用例生成闭环：批次列表、批量审核、恢复、再生成、入库幂等与审计。"""

from __future__ import annotations

from unittest.mock import patch

from app.core.models.identity import User
from app.features.test_management.models.case_generation import CaseDraft, CaseGenerationBatch
from app.features.test_management.services.generation_service import GenerationService
from tests.conftest import unique


def _project(api, actor) -> int:
    """创建项目。"""
    response = api.post("/projects", username=actor, json={"name": unique("闭环项目"), "description": "loop"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _actor(db) -> User:
    """测试管理员已经由夹具写入。"""
    return db.query(User).filter(User.username == "platform_admin").one()


def _case(title: str, **overrides) -> dict:
    """一条合法草稿载荷。"""
    payload = {
        "title": title, "priority": "P1", "requirement": "需求描述",
        "preconditions": ["前置已就绪"], "test_data": ["合成数据"],
        "steps": ["执行操作"], "expected_results": ["返回明确结果"],
        "coverage": ["功能"], "needs_confirmation": [],
    }
    payload.update(overrides)
    return payload


def _suite(*, security_cases: list[dict] | None = None, security_status: str = "FAILED") -> dict:
    """接口成功、安全模块结果可配的生成结果。"""
    return {
        "status": "PARTIAL_FAILED" if security_status != "SUCCEEDED" or not security_cases else "COMPLETED",
        "supervisor": {"id": None, "name": "主 Agent", "version": 3, "model_config_id": None, "model_name": "synthetic"},
        "review": {"status": "SUCCEEDED", "summary": "覆盖了主路径", "gaps": ["阈值待确认"]},
        "modules": [
            {
                "id": None, "name": "接口子 Agent", "version": 2, "module": "api", "status": "SUCCEEDED",
                "model_config_id": None, "model_name": "synthetic",
                "cases": [_case(unique("接口用例"))],
            },
            {
                "id": None, "name": "安全子 Agent", "version": 1, "module": "security", "status": security_status,
                "cases": security_cases or [], "error": None if security_status == "SUCCEEDED" else "模块用例生成失败",
            },
        ],
    }


def _persist(db, api, admin, suite=None):
    """落一个批次并返回项目 ID。"""
    project_id = _project(api, admin)
    service = GenerationService()
    batch = service.persist(
        db, _actor(db), project_id=project_id, direction="API", scope_node_id=None,
        requirements="登录", suite=suite or _suite(),
    )
    return project_id, service, batch


def test_batch_list_filters_and_stats(api, admin, db):
    """批次列表分页、状态统计与模块/关键字筛选。"""
    project_id, _, batch = _persist(db, api, admin)
    listed = api.get(f"/projects/{project_id}/case-generation-batches", username=admin)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    assert body["partial_failed_count"] == 1
    item = body["items"][0]
    assert item["id"] == batch.id
    assert item["draft_total"] == 1
    assert item["pending_count"] == 1
    assert item["module_error_count"] == 1
    by_module = api.get(
        f"/projects/{project_id}/case-generation-batches", username=admin, params={"module": "security"},
    )
    assert by_module.json()["total"] == 1
    missing = api.get(
        f"/projects/{project_id}/case-generation-batches", username=admin, params={"module": "asr"},
    )
    assert missing.json()["total"] == 0
    by_keyword = api.get(
        f"/projects/{project_id}/case-generation-batches", username=admin, params={"keyword": "登录"},
    )
    assert by_keyword.json()["total"] == 1


def test_batch_review_requires_confirm_and_imports_partially(api, admin, db):
    """无 confirm 拒绝执行；批量接受时重名草稿失败但不影响其他草稿。"""
    project_id = _project(api, admin)
    service = GenerationService()
    suite = _suite()
    duplicate_title = unique("重复标题")
    suite["modules"][0]["cases"] = [_case(unique("正常入库")), _case(duplicate_title)]
    batch = service.persist(
        db, _actor(db), project_id=project_id, direction="API", scope_node_id=None,
        requirements="登录", suite=suite,
    )
    created = api.post(
        f"/projects/{project_id}/test-cases", username=admin, json={"name": duplicate_title},
    )
    assert created.status_code == 201, created.text

    denied = api.post(
        f"/case-generation-batches/{batch.id}/review", username=admin,
        json={"action": "accept", "scope": "all"},
    )
    assert denied.status_code == 400, denied.text

    reviewed = api.post(
        f"/case-generation-batches/{batch.id}/review", username=admin,
        json={"action": "accept", "scope": "all", "confirm": True},
    )
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["affected"] == 1
    items = {item["ok"]: item for item in body["items"]}
    assert items[True]["test_case_id"]
    assert "同名" in items[False]["error"]

    detail = api.get(f"/case-generation-batches/{batch.id}", username=admin)
    drafts = {row["id"]: row for row in detail.json()["drafts"]}
    failed_draft = next(row for row in drafts.values() if row["status"] == "PENDING")
    assert "同名" in (failed_draft["import_error"] or "")
    accepted = next(row for row in drafts.values() if row["status"] == "ACCEPTED")
    case_detail = api.get(f"/test-cases/{accepted['test_case_id']}", username=admin)
    assert case_detail.json()["status"] == "DRAFT"

    # 重复批量接受：没有待审核草稿，受影响为 0，不产生重复用例。
    again = api.post(
        f"/case-generation-batches/{batch.id}/review", username=admin,
        json={"action": "accept", "scope": "all", "confirm": True},
    )
    assert again.json()["affected"] == 0


def test_batch_reject_by_module_and_reopen(api, admin, db):
    """按模块批量拒绝；拒绝后可恢复待审核；已入库不可恢复。"""
    project_id, service, batch = _persist(db, api, admin)
    draft_id = batch.drafts[0].id
    rejected = api.post(
        f"/case-generation-batches/{batch.id}/review", username=admin,
        json={"action": "reject", "scope": "module", "module": "api", "comment": "覆盖不足", "confirm": True},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["affected"] == 1
    detail = api.get(f"/case-generation-batches/{batch.id}", username=admin)
    draft = detail.json()["drafts"][0]
    assert draft["status"] == "REJECTED"
    assert draft["review_comment"] == "覆盖不足"
    assert draft["reviewed_at"]

    reopened = api.post(f"/case-drafts/{draft_id}/reopen", username=admin)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "PENDING"

    accepted = api.post(f"/case-drafts/{draft_id}/accept", username=admin)
    assert accepted.status_code == 200, accepted.text
    cannot_reopen = api.post(f"/case-drafts/{draft_id}/reopen", username=admin)
    assert cannot_reopen.status_code == 400, cannot_reopen.text


def test_regenerate_failed_module_keeps_reviewed_drafts(api, admin, db):
    """只重跑失败模块；已拒绝草稿保持原样；成功后批次转 COMPLETED。"""
    project_id, service, batch = _persist(db, api, admin)
    # 合成批次没有真实主 Agent：补一个启用的主 Agent 行供再生成校验。
    from app.agents.models import AgentDefinition

    supervisor = AgentDefinition(
        key=unique("supervisor"), name="合成主 Agent", workflow_template="case_generation",
        instruction="", is_enabled=True, version=1,
    )
    db.add(supervisor)
    db.flush()
    row = db.get(CaseGenerationBatch, batch.id)
    row.supervisor_agent_id = supervisor.id
    db.commit()
    old_draft_id = batch.drafts[0].id
    rejected = api.post(f"/case-drafts/{old_draft_id}/reject", username=admin, json={"comment": "先拒绝"})
    assert rejected.status_code == 200, rejected.text

    retry_suite = _suite(security_cases=[_case(unique("安全用例"))], security_status="SUCCEEDED")
    retry_suite["modules"] = [retry_suite["modules"][1]]
    retry_suite["status"] = "COMPLETED"
    # regenerate 内部惰性导入生成服务，patch 源头模块即可拦截。
    import app.agents.services.case_generation_service as case_gen_module

    with patch.object(case_gen_module, "generate_case_suite", return_value=retry_suite):
        regenerated = api.post(
            f"/case-generation-batches/{batch.id}/regenerate", username=admin,
            json={"cases_per_module": 3},
        )
    assert regenerated.status_code == 200, regenerated.text
    body = regenerated.json()
    assert body["status"] == "COMPLETED"
    assert body["module_errors"] == []
    drafts = body["drafts"]
    assert len(drafts) == 2
    old = next(row for row in drafts if row["id"] == old_draft_id)
    assert old["status"] == "REJECTED"
    new = next(row for row in drafts if row["id"] != old_draft_id)
    assert new["module"] == "security"
    assert new["status"] == "PENDING"

    again = api.post(
        f"/case-generation-batches/{batch.id}/regenerate", username=admin, json={},
    )
    assert again.status_code == 400, again.text


def test_accept_idempotent_and_conflict(api, admin, db):
    """重复接受返回同一用例；项目内重名报 409；审计完整留痕。"""
    project_id, service, batch = _persist(db, api, admin)
    draft_id = batch.drafts[0].id
    first = api.post(f"/case-drafts/{draft_id}/accept", username=admin)
    assert first.status_code == 200, first.text
    second = api.post(f"/case-drafts/{draft_id}/accept", username=admin)
    assert second.status_code == 200, second.text
    assert first.json()["test_case_id"] == second.json()["test_case_id"]

    other = service.persist(
        db, _actor(db), project_id=project_id, direction="API", scope_node_id=None,
        requirements="登录", suite=_suite(),
    )
    same_title = db.get(CaseDraft, other.drafts[0].id)
    same_title.payload_json = {**same_title.payload_json, "title": batch.drafts[0].title}
    same_title.title = batch.drafts[0].title
    db.commit()
    conflicted = api.post(f"/case-drafts/{other.drafts[0].id}/accept", username=admin)
    assert conflicted.status_code == 409, conflicted.text

    audits = api.get(f"/case-generation-batches/{batch.id}/audits", username=admin)
    assert audits.status_code == 200, audits.text
    actions = [row["action"] for row in audits.json()]
    assert actions == ["CREATE", "APPROVE"]
    approve = audits.json()[1]
    assert approve["draft_id"] == draft_id
    assert approve["detail"]["test_case_id"] == first.json()["test_case_id"]


def test_quality_flags_on_persist(api, admin, db):
    """规则校验：批内重名、与正式用例相似、步骤预期不匹配、缺前置。"""
    project_id = _project(api, admin)
    created = api.post(
        f"/projects/{project_id}/test-cases", username=admin, json={"name": unique("已有用例")},
    )
    assert created.status_code == 201, created.text
    existing_name = created.json()["name"]
    suite = _suite()
    duplicate_title = unique("双标题")
    suite["modules"][0]["cases"] = [
        _case(existing_name),
        _case(duplicate_title, steps=["步骤一", "步骤二"], expected_results=["只有一个预期"], preconditions=[]),
        _case(duplicate_title),
    ]
    service = GenerationService()
    batch = service.persist(
        db, _actor(db), project_id=project_id, direction="API", scope_node_id=None,
        requirements="登录", suite=suite,
    )
    rules = {row.id: {issue["rule"] for issue in row.quality} for row in batch.drafts}
    drafts_by_title = {row.title: row for row in batch.drafts}
    assert "TITLE_SIMILAR_TO_EXISTING" in rules[drafts_by_title[existing_name].id]
    mismatched = next(row for row in batch.drafts if "只有一个预期" in (row.payload.get("expected_results") or []))
    assert "STEP_EXPECTED_MISMATCH" in rules[mismatched.id]
    assert "PRECONDITION_MISSING" in rules[mismatched.id]
    duplicate_rows = [row for row in batch.drafts if row.title == duplicate_title]
    assert len(duplicate_rows) == 2
    assert all("TITLE_DUPLICATE_IN_BATCH" in rules[row.id] for row in duplicate_rows)


def test_cross_project_batch_is_hidden(api, admin, db):
    """非项目成员访问批次与审计统一 404。"""
    _, _, batch = _persist(db, api, admin)
    outsider = unique("旁观者")
    assert api.register(outsider).status_code == 201
    api.login(outsider)
    detail = api.get(f"/case-generation-batches/{batch.id}", username=outsider)
    assert detail.status_code == 404, detail.text
    audits = api.get(f"/case-generation-batches/{batch.id}/audits", username=outsider)
    assert audits.status_code == 404, audits.text
    draft_id = batch.drafts[0].id
    accepted = api.post(f"/case-drafts/{draft_id}/accept", username=outsider)
    assert accepted.status_code in (403, 404), accepted.text
