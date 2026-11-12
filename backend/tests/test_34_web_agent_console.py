"""验收项 34：UI 智能体二轮 Phase C —— 沙箱会话提升为正式 Web 用例并闭环执行。

覆盖 Phase C 的验收口径：

- `POST /web-agent/sessions/{id}/promote` 只取**已接受**（ACCEPTED + AI）的步骤，
  被驳回的提案不会进入正式用例；
- 产物是**未确认草稿**（confirmed=false、source_type=AI），带目标页时补一条
  NAVIGATE 作为可重放入口；
- 提升出的用例可直接被 Web 编辑器读取（步骤解密、重排后可回读）；
- 提升不等于放行：未确认前 debug 仍返回 409，确认后才允许正式执行；
- 正式执行经 run_web_case 产出 TestRun，与沙箱探索阶段（恒 0）明确区分；
- 会话内没有已接受步骤时拒绝提升；跨项目提升统一 404。

受控浏览器会话沿用 Phase B 的做法直连 service 打开（HTTP 端点由 Phase A 覆盖）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.execution.browser.session_manager import registry
from tests.conftest import unique
from tests.test_16_agent import _create_session_http
from tests.test_25_security_execution import _actor
from tests.test_32_web_agent_runtime import target_server, web_setup  # noqa: F401 — 复用 Phase A 夹具
from tests.test_33_web_agent_loop import (
    ScriptedProvider,
    _agent_session,
    _close_browser_session,
    _drive,
    _open_browser_session,
    _propose,
    _test_run_count,
    _web_intent,
)


@pytest.fixture(autouse=True)
def _clean_browser_sessions():
    """每个用例前后清空进程级浏览器会话，避免并发槽与句柄泄漏。"""
    registry.close_all()
    yield
    registry.close_all()


def _explore_to_accepted(db, api, admin, project_id, env_id, *, budget=2):
    """跑一轮沙箱探索：观测 → 决策 PROPOSE → 人工确认 → 执行一步（ACCEPTED）。"""
    wsid, _ = _open_browser_session(db, project_id, env_id, budget=budget)
    sid = _agent_session(api, admin, project_id)
    provider = ScriptedProvider([_propose("CLICK", "submit"), _propose("CLICK", "submit")])
    provider.set_response("intent", _web_intent())
    user = _actor(db)

    state = _drive(db, sid, user, provider, content="点击提交按钮", web_session_id=wsid)[0]
    assert state.get("current_stage") == "WEB_STEP_REVIEW"
    state2 = _drive(db, sid, user, provider, action="confirm_web_step")[0]
    assert state2.get("error") is None, state2.get("error")
    return wsid


def _confirm(api, admin, case):
    """人工确认当前版本（门禁的合法入口）。"""
    resp = api.post(f"/web-cases/{case['id']}/confirm", username=admin,
                    json={"revision": case["revision"]})
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestPromote:
    def test_promote_confirm_debug_end_to_end(self, api, admin, db, web_setup):
        """完整闭环：沙箱探索 → 提升为未确认用例 → 人工确认 → 正式执行通过。"""
        project_id, env_id = web_setup
        wsid = _explore_to_accepted(db, api, admin, project_id, env_id)
        assert _test_run_count(db, project_id) == 0, "沙箱探索不得产生正式执行记录"

        resp = api.post(f"/web-agent/sessions/{wsid}/promote", username=admin,
                        json={"name": unique("promoted"), "description": "沙箱探索提升"})
        assert resp.status_code == 201, resp.text
        case = resp.json()

        # 产物是未确认的 AI 来源草稿
        assert case["confirmed"] is False
        assert case["source_type"] == "AI"
        assert case["revision"] == 1
        # 步骤顺序：目标页 NAVIGATE 在前，智能体执行过的 CLICK 在后
        ops = [s["operation"] for s in case["steps"]]
        assert ops == ["NAVIGATE", "CLICK"], ops
        assert case["steps"][0]["value"] == "/"
        assert case["steps"][1]["locator"]["value"] == "submit"

        # 未确认前不允许正式执行
        denied = api.post(f"/web-cases/{case['id']}/debug", username=admin,
                          json={"environment_id": env_id})
        assert denied.status_code == 409, denied.text

        # 人工确认后才放行
        confirmed = _confirm(api, admin, case)
        assert confirmed["confirmed"] is True

        result = api.post(f"/web-cases/{case['id']}/debug", username=admin,
                          json={"environment_id": env_id})
        assert result.status_code == 200, result.text
        run = result.json()
        # TestRun 级状态词表是 SUCCESS/FAILED（与步骤级 PASSED 不同）
        assert run["status"] == "SUCCESS", run
        # 计数按用例计（1 个用例通过），步骤级结果在响应快照里
        assert (run["passed"], run["failed"], run["error"]) == (1, 0, 0), run
        # 步骤级：两条步骤（目标页 + 智能体执行过的 CLICK）都通过
        history = api.get(f"/projects/{project_id}/web-executions", username=admin).json()["items"]
        step_logs = history[0]["response_snapshot"]["web"]["steps"]
        assert [s["operation"] for s in step_logs] == ["NAVIGATE", "CLICK"], step_logs
        assert {s["status"] for s in step_logs} == {"PASSED"}, step_logs
        # 正式执行产生了 TestRun，与沙箱阶段的 0 条形成区分
        assert _test_run_count(db, project_id) == 1
        _close_browser_session(db, wsid)

    def test_rejected_proposals_never_reach_official_case(self, api, admin, db, web_setup):
        """被驳回的提案不进正式用例：先驳回再确认另一条，产物只含已接受步骤。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id, budget=2)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([_propose("CLICK", "submit"), _propose("CLICK", "submit")])
        provider.set_response("intent", _web_intent())
        user = _actor(db)

        _drive(db, sid, user, provider, content="点击提交", web_session_id=wsid)
        # 第一条提案被驳回（不执行），继续探索
        state2 = _drive(db, sid, user, provider, action="reject_web_step")[0]
        assert state2.get("web_proposed_steps") == []
        _drive(db, sid, user, provider, action="confirm_web_step")

        resp = api.post(f"/web-agent/sessions/{wsid}/promote", username=admin,
                        json={"name": unique("promoted-reject")})
        assert resp.status_code == 201, resp.text
        # 目标页 NAVIGATE + 已执行的 CLICK，共 2 步
        assert [s["operation"] for s in resp.json()["steps"]] == ["NAVIGATE", "CLICK"]
        _close_browser_session(db, wsid)

    def test_promote_without_accepted_steps_is_rejected(self, api, admin, db, web_setup):
        """会话内没有已接受步骤时拒绝提升，且不留下坏用例。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id)
        before = api.get(f"/projects/{project_id}/web-cases", username=admin).json()
        resp = api.post(f"/web-agent/sessions/{wsid}/promote", username=admin,
                        json={"name": unique("promoted-empty")})
        assert resp.status_code == 400, resp.text
        after = api.get(f"/projects/{project_id}/web-cases", username=admin).json()
        assert before["total"] == after["total"]
        _close_browser_session(db, wsid)

    def test_cross_project_promote_is_404(self, api, admin, db, web_setup):
        """非项目成员提升统一 404：不泄露会话存在性，也不创建任何用例。"""
        project_id, env_id = web_setup
        wsid = _explore_to_accepted(db, api, admin, project_id, env_id)
        other = api.post("/projects", username=admin, json={"name": unique("promote-other")})
        assert other.status_code == 201, other.text
        other_id = other.json()["id"]

        # 路径不带 project_id，归属由会话行判定：非项目成员访问按 404 处理，不泄露存在性。
        outsider = unique("promote-outsider")
        api.register(outsider)
        api.login(outsider)
        outsider_resp = api.post(f"/web-agent/sessions/{wsid}/promote",
                                 username=outsider, json={"name": unique("x")})
        assert outsider_resp.status_code == 404, outsider_resp.text
        # 提升请求没有创建任何用例
        assert api.get(f"/projects/{other_id}/web-cases", username=admin).json()["total"] == 0
        _close_browser_session(db, wsid)

    def test_viewer_cannot_observe_or_promote(self, api, admin, db, web_setup):
        """viewer 不可驱动会话：观测会推进共享浏览器并改写会话状态，提升会创建用例。

        两个端点路径都不带 project_id，归属由会话行判定。观测虽是「只读语义」，
        但会推进浏览器上下文并在句柄失效时把会话置为 FAILED，所以按写权限校验。
        """
        from app.features.web_testing.models import WebAgentSession

        project_id, env_id = web_setup
        wsid = _explore_to_accepted(db, api, admin, project_id, env_id)

        viewer = unique("webagent-viewer")
        uid = api.register(viewer).json()["user"]["id"]
        api.login(viewer)
        api.put(f"/projects/{project_id}/members/{uid}", username=admin,
                json={"user_id": uid, "role": "viewer"})
        api.login(viewer)

        assert api.post(f"/web-agent/sessions/{wsid}/observe", username=viewer).status_code == 403
        promote_resp = api.post(f"/web-agent/sessions/{wsid}/promote", username=viewer,
                                json={"name": unique("viewer-promote")})
        assert promote_resp.status_code == 403, promote_resp.text

        # 会话未被观测破坏，仍为 ACTIVE；也未产生任何用例
        assert db.get(WebAgentSession, wsid).status == "ACTIVE"
        assert api.get(f"/projects/{project_id}/web-cases", username=admin).json()["total"] == 0
        _close_browser_session(db, wsid)

    def test_promoted_case_readable_by_editor(self, api, admin, db, web_setup):
        """提升产物能被 Web 编辑器正常读取（步骤解密回读），确认指纹初始为空。"""
        project_id, env_id = web_setup
        wsid = _explore_to_accepted(db, api, admin, project_id, env_id)
        resp = api.post(f"/web-agent/sessions/{wsid}/promote", username=admin,
                        json={"name": unique("promoted-read")})
        assert resp.status_code == 201, resp.text
        case_id = resp.json()["id"]

        detail = api.get(f"/web-cases/{case_id}", username=admin)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["confirmed"] is False
        assert body["source_type"] == "AI"
        assert [s["operation"] for s in body["steps"]] == ["NAVIGATE", "CLICK"]
        # 响应不得泄露加密细节或确认摘要
        assert "web_encrypted" not in str(body)
        assert "digest" not in str(body)
        _close_browser_session(db, wsid)


class TestStepStatusBoundary:
    def test_illegal_step_status_is_rejected(self, db, web_setup):
        """写入侧收窄步骤状态词表，避免未确认步骤被标成 ACCEPTED 而混入 promote。

        promote 只取 ACCEPTED 的步骤，所以「是否已确认执行过」这条不变量不能只靠
        图拓扑保证：record_agent_step 是服务层公开方法，直接在写入侧校验状态值。
        """
        from fastapi import HTTPException

        from app.features.web_testing.models import WebAgentStep
        from app.features.web_testing.router import service as web_ui_service

        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id, budget=2)
        user = _actor(db)
        step = {"name": "点击提交", "operation": "CLICK",
                "locator": {"strategy": "TEST_ID", "value": "submit"}}

        for illegal in ("CONFIRMED", "DONE", "accepted", "", "PROPOSED_EXECUTED"):
            with pytest.raises(HTTPException) as excinfo:
                web_ui_service.record_agent_step(
                    db, wsid, sort=1, step=step, result={}, status=illegal, actor=user)
            assert excinfo.value.status_code == 400

        assert db.query(WebAgentStep).filter_by(session_id=wsid).count() == 0
        # 合法状态仍可写入，且写入的是加密文本而非明文步骤。
        web_ui_service.record_agent_step(
            db, wsid, sort=1, step=step, result={"status": "PASSED"},
            status="ACCEPTED", actor=user)
        row = db.query(WebAgentStep).filter_by(session_id=wsid).one()
        assert row.status == "ACCEPTED"
        assert "submit" not in (row.step_encrypted or "")
        _close_browser_session(db, wsid)
