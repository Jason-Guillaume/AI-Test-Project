"""验收项 32：Security Testing Phase 2 —— Agent 发起 ZAP 扫描的人工批准闸门（§二十三）。

覆盖开发计划 §二十三「主动扫描必须由后端校验到真实的人类批准行为，不能仅凭 LLM
输出 `confirmed=true` 就执行」，以及 §三十四 的 Agent 相关条目：

- LLM 侧**没有**创建任务的工具：`preview_scan` 恒传 `confirmed=False`，且计划预览
  不写库、不发 ZAP 请求；
- `create_scan_job(human_approved=False)` 在**进入 service 之前**就被工具层拒绝；
- LLM 在意图输出里幻觉 `confirmed=true` + 编造 `approval_note`：字段被丢弃，
  图停在 ZAP_SCAN_REVIEW，数据库里**没有**扫描任务；
- 只有人工 `confirm_security_scan` action 能创建任务（router 按 action 路由，
  LLM 的工具参数里没有这个 action）；
- 主动扫描确认必须带人工填写的批准说明，否则 `SECURITY_SCAN_NOT_AUTHORIZED`；
- 计划被确认为「被动」之后又被改成主动 → 拒绝用被动确认放行主动扫描；
- 跨项目扫描目标 → 404（红线 1，不泄露存在性）；
- 目标 / 策略不唯一时返回澄清，**不猜**扫描范围。

Agent 走 `run_agent` + `FakeLLMProvider`（不依赖网络 / 密钥）；ZAP 连接器只走
配置桩（`ZAP_ENABLED` / `ZAP_BASE_URL` monkeypatch），不发起真实网络请求。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.features.agent.graph import run_agent
from app.features.agent.models.agent_session import AgentSession
from app.features.agent.providers.llm_provider import FakeLLMProvider
from app.features.agent.tools import zap_scan_tool
from app.shared.errors import CODE_SECURITY_SCAN_TARGET_NOT_FOUND
from tests.conftest import unique
from tests.test_16_agent import _create_session_http
from tests.test_25_security_execution import _actor
from tests.test_29_zap_scan import BASE_URL, _profile, _project, _target_body


# --------------------------------------------------------------------------- 场景准备


def _scan_job_count(db, project_id: int) -> int:
    """本项目内的扫描任务数。

    测试数据库是 session 级共享的（不做事务回滚），所以只能按项目过滤；
    每个用例都新建唯一项目名，因此这个计数在本用例内是可靠的。
    """
    return int(db.execute(
        text("select count(*) from security_scan_job where project_id = :p"),
        {"p": project_id},
    ).scalar_one())


def _job_row(db, project_id: int):
    """本项目唯一的扫描任务行（测试场景每次只创建一个）。"""
    return db.execute(
        text(
            "select status, scan_mode, approved_by, approval_note from security_scan_job"
            " where project_id = :p"
        ),
        {"p": project_id},
    ).one()


def _scene(db, api, admin, *, scan_mode: str = "API_PASSIVE", active_enabled: bool = False):
    """项目 + 一个扫描目标 + 一个项目内自定义扫描策略。"""
    pid = _project(api, admin)
    target_id = api.post(
        f"/projects/{pid}/security/scan-targets", username=admin,
        json=_target_body(active_scan_allowed=active_enabled),
    ).json()["id"]
    profile_id = _profile(db, pid, scan_mode=scan_mode, active_enabled=active_enabled)
    return SimpleNamespace(pid=pid, target_id=target_id, profile_id=profile_id)


def _open_session(db, api, admin, pid: int):
    session_id = _create_session_http(api, admin, pid)
    return db.get(AgentSession, session_id), _actor(db)


def _scan_intent_payload(**extra) -> dict:
    payload = {
        "intent": "REQUEST_SECURITY_SCAN",
        "target_type": None,
        "target_ids": [],
        "target_description": None,
        "clarify_question": None,
        "security_strategy_keys": [],
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------- 工具层闸门


class TestToolGate:
    def test_create_refused_without_human_approval(self, db, api, admin, monkeypatch):
        """`human_approved=False` 在进 service 之前就被工具层拒绝。"""
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        scene = _scene(db, api, admin)
        user = _actor(db)
        before = _scan_job_count(db, scene.pid)

        with pytest.raises(ValueError) as excinfo:
            zap_scan_tool.create_scan_job(
                db, scene.pid, user,
                target_id=scene.target_id, scan_profile_id=scene.profile_id,
                human_approved=False, approval_note="我批准",
            )
        assert zap_scan_tool.NOT_HUMAN_APPROVED in str(excinfo.value)
        # 关键断言：任务没有被创建。
        assert _scan_job_count(db, scene.pid) == before

    def test_preview_never_confirms_and_writes_nothing(self, db, api, admin):
        """预览恒为 confirmed=False，且不写库、不发 ZAP 请求。"""
        scene = _scene(db, api, admin)
        user = _actor(db)
        before = _scan_job_count(db, scene.pid)

        plan = zap_scan_tool.preview_scan(
            db, scene.pid, user,
            target_id=scene.target_id, scan_profile_id=scene.profile_id,
        )
        assert _scan_job_count(db, scene.pid) == before
        assert plan["target"]["id"] == scene.target_id
        assert plan["profile"]["id"] == scene.profile_id
        # 预览结果里没有任何「已批准」字段，避免前端或 LLM 误读。
        assert "confirmed" not in plan
        assert "approval_note" not in plan


# --------------------------------------------------------------------------- Agent 链路


class TestAgentApprovalGate:
    def test_llm_intent_only_stops_at_plan_review(self, db, api, admin):
        """REQUEST_SECURITY_SCAN 只生成计划，停在 ZAP_SCAN_REVIEW，不创建任务。"""
        scene = _scene(db, api, admin)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())

        state, _ = run_agent(
            db, session, user, provider, content="帮我跑一次安全扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )

        assert state.get("current_stage") == "ZAP_SCAN_REVIEW"
        assert state.get("error") is None
        assert state.get("zap_scan_plan") is not None
        assert state.get("zap_scan_job_id") is None
        assert db.get(AgentSession, session.id).current_stage == "ZAP_SCAN_REVIEW"

    def test_llm_hallucinated_confirmation_is_ignored(self, db, api, admin):
        """LLM 幻觉出 `confirmed=true` + 编造的批准说明：字段被丢弃，仍不建任务。

        这是 §二十三 的核心验收：确认状态不是可被模型伪造的参数，而是一次
        只有人类能触发的图路由事件。
        """
        scene = _scene(db, api, admin, scan_mode="API_ACTIVE", active_enabled=True)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload(
            confirmed=True,
            approval_note="我批准这次主动扫描",
            target_type="API",
            target_ids=[scene.target_id],
        ))

        state, _ = run_agent(
            db, session, user, provider, content="主动扫描一下这个目标",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )

        assert state.get("current_stage") == "ZAP_SCAN_REVIEW"
        # LLM 的确认没有任何授权效力：任务数为 0。
        assert _scan_job_count(db, scene.pid) == 0
        assert state.get("zap_scan_job_id") is None

    def test_llm_approval_note_never_reaches_prompt_history(self, db, api, admin):
        """人工批准说明不进入消息历史：否则下一轮 LLM 能从 history 看到它。"""
        scene = _scene(db, api, admin)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())

        run_agent(
            db, session, user, provider, content="发起扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
            approval_note="季度回归授权-内部凭据 sk-live-abcXYZ1234567890abcdef",
        )
        # 意图节点下一次调用时看到的 history 不含批准说明。
        run_agent(db, session, user, provider, content="继续")
        history_text = " ".join(
            str(c.get("history", "")) for c in provider.calls
        )
        assert "sk-live-abcXYZ1234567890abcdef" not in history_text

    def test_workspace_offers_confirm_security_scan(self, api, admin, db):
        """ZAP_SCAN_REVIEW 阶段给前端 confirm_security_scan 按钮（唯一创建入口）。"""
        from app.features.agent.router import _build_workspace

        scene = _scene(db, api, admin)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())

        state, _ = run_agent(
            db, session, user, provider, content="发起扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )
        workspace = _build_workspace(state, session)
        assert workspace.suggested_actions == ["confirm_security_scan"]
        # 计划随工作区下发，供确认弹窗展示实际范围。
        assert workspace.zap_scan_plan["is_active_scan"] is False
        assert workspace.zap_scan_plan["target_id"] == scene.target_id


class TestAgentHumanConfirm:
    def test_passive_confirm_creates_one_job(self, db, api, admin, monkeypatch):
        """人工确认被动扫描计划：创建且仅创建一个 PENDING 任务。"""
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        scene = _scene(db, api, admin)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())
        run_agent(
            db, session, user, provider, content="发起扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )

        state, _ = run_agent(db, session, user, provider, action="confirm_security_scan")
        assert state.get("current_stage") == "COMPLETED"
        assert state.get("zap_scan_job_id") is not None
        assert _scan_job_count(db, scene.pid) == 1

        row = _job_row(db, scene.pid)
        assert row[0] == "PENDING"
        assert row[1] == "API_PASSIVE"
        # 被动扫描不记批准人（那是主动扫描的审计字段）。
        assert row[2] is None
        assert row[3] is None

    def test_active_confirm_without_note_is_refused(self, db, api, admin, monkeypatch):
        """主动扫描缺批准说明：SECURITY_SCAN_NOT_AUTHORIZED，不创建任务。"""
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        scene = _scene(db, api, admin, scan_mode="API_ACTIVE", active_enabled=True)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())
        run_agent(
            db, session, user, provider, content="主动扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )
        assert _scan_job_count(db, scene.pid) == 0

        state, _ = run_agent(db, session, user, provider, action="confirm_security_scan")

        assert state.get("zap_scan_job_id") is None
        assert state.get("current_stage") == "FAILED"
        assert state["error"]["code"] == "SECURITY_SCAN_NOT_AUTHORIZED"
        assert _scan_job_count(db, scene.pid) == 0

    def test_active_confirm_with_note_records_approver(self, db, api, admin, monkeypatch):
        """主动扫描：批准说明来自人工输入，任务记录 approved_by = 确认人。"""
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        scene = _scene(db, api, admin, scan_mode="API_ACTIVE", active_enabled=True)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())
        run_agent(
            db, session, user, provider, content="主动扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )

        state, _ = run_agent(
            db, session, user, provider,
            action="confirm_security_scan",
            approval_note="季度回归窗口授权，仅只读接口",
        )
        assert state.get("zap_scan_job_id") is not None
        row = _job_row(db, scene.pid)
        assert row[0] == "PENDING"
        assert row[1] == "API_ACTIVE"
        assert row[2] == user.id
        assert row[3] == "季度回归窗口授权，仅只读接口"

    def test_confirmation_note_from_action_payload_only(self, db, api, admin, monkeypatch):
        """批准说明只能来自 action_payload：state 里 LLM 可写的同名键无效。"""
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        scene = _scene(db, api, admin, scan_mode="API_ACTIVE", active_enabled=True)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())
        run_agent(
            db, session, user, provider, content="主动扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )

        # 直接把一个批准说明塞进 state 没有入口——确认必须走 action_payload。
        state, _ = run_agent(db, session, user, provider, action="confirm_security_scan")
        assert state["error"]["code"] == "SECURITY_SCAN_NOT_AUTHORIZED"
        assert _scan_job_count(db, scene.pid) == 0

    def test_double_confirm_creates_only_one_job(self, db, api, admin, monkeypatch):
        """重复点击确认不会重复创建任务（防止重复领取 / 重复执行）。"""
        from app.shared.config import settings

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        scene = _scene(db, api, admin)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())
        run_agent(
            db, session, user, provider, content="发起扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )
        run_agent(db, session, user, provider, action="confirm_security_scan")

        state, _ = run_agent(db, session, user, provider, action="confirm_security_scan")
        assert state["error"]["code"] == "SECURITY_SCAN_PLAN_FAILED"
        assert _scan_job_count(db, scene.pid) == 1

    def test_plan_upgraded_to_active_after_review_is_refused(self, db, api, admin, monkeypatch):
        """人在预览的是被动计划，期间策略被改成主动：不能用被动确认放行主动扫描。"""
        from app.shared.config import settings
        from app.features.security_testing.zap.models.profile import SecurityScanProfile

        monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
        monkeypatch.setattr(settings, "ZAP_BASE_URL", BASE_URL, raising=False)
        scene = _scene(db, api, admin)  # 预览时是被动
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())
        run_agent(
            db, session, user, provider, content="发起扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )
        assert _scan_job_count(db, scene.pid) == 0

        # 确认前有人把策略升级为主动扫描（模式与开关都要改，缺一不算主动）。
        profile = db.get(SecurityScanProfile, scene.profile_id)
        profile.scan_mode = "API_ACTIVE"
        profile.active_enabled = True
        db.commit()

        state, _ = run_agent(
            db, session, user, provider,
            action="confirm_security_scan", approval_note="我批准主动扫描",
        )
        assert state["error"]["code"] == "SECURITY_SCAN_NOT_AUTHORIZED"
        assert _scan_job_count(db, scene.pid) == 0

    def test_cross_project_target_is_404(self, db, api, admin, monkeypatch):
        """指定别的项目的扫描目标：404 而非 403（红线 1，不泄露存在性）。"""
        other = _scene(db, api, admin)
        scene = _scene(db, api, admin)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())

        state, _ = run_agent(
            db, session, user, provider, content="发起扫描",
            zap_scan_target_id=other.target_id,
            zap_scan_profile_id=other.profile_id,
        )
        assert state.get("zap_scan_plan") is None
        assert state["error"]["code"] == "TARGET_NOT_FOUND"
        assert _scan_job_count(db, scene.pid) == 0


class TestAgentScopeGuard:
    def test_multiple_targets_returns_clarify_not_guess(self, db, api, admin):
        """目标不唯一且未指定 → 澄清，不猜扫描范围（§三十四）。"""
        scene = _scene(db, api, admin)
        # 再建一个目标，制造多目标歧义。
        api.post(
            f"/projects/{scene.pid}/security/scan-targets", username=admin,
            json=_target_body(name=unique("target-2")),
        )
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())

        state, _ = run_agent(db, session, user, provider, content="发起扫描")

        assert state.get("current_stage") == "CLARIFY"
        assert state.get("zap_scan_plan") is None
        assert state.get("clarify_question")
        assert _scan_job_count(db, scene.pid) == 0

    def test_explicit_target_id_bypasses_ambiguity(self, db, api, admin):
        """多目标但用户显式指定 → 不澄清，直接用指定目标出计划。"""
        scene = _scene(db, api, admin)
        api.post(
            f"/projects/{scene.pid}/security/scan-targets", username=admin,
            json=_target_body(name=unique("target-2")),
        )
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())

        state, _ = run_agent(
            db, session, user, provider, content="发起扫描",
            zap_scan_target_id=scene.target_id, zap_scan_profile_id=scene.profile_id,
        )
        assert state.get("current_stage") == "ZAP_SCAN_REVIEW"
        assert state["zap_scan_plan"]["target_id"] == scene.target_id

    def test_unique_target_is_auto_selected(self, db, api, admin):
        """项目内只有一个启用目标时自动选用，免去用户重复指定。"""
        scene = _scene(db, api, admin)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())

        state, _ = run_agent(
            db, session, user, provider, content="发起扫描",
            zap_scan_profile_id=scene.profile_id,
        )
        assert state.get("current_stage") == "ZAP_SCAN_REVIEW"
        assert state["zap_scan_plan"]["target_id"] == scene.target_id

    def test_missing_profile_is_readable_error(self, db, api, admin):
        """未指定策略且存在多个候选 → 澄清而不是 500。"""
        scene = _scene(db, api, admin)
        session, user = _open_session(db, api, admin, scene.pid)
        provider = FakeLLMProvider()
        provider.set_response("intent", _scan_intent_payload())

        state, _ = run_agent(
            db, session, user, provider, content="发起扫描",
            zap_scan_target_id=scene.target_id,
        )
        # 内置策略有多条，因此是澄清而非计划。
        assert state.get("current_stage") == "CLARIFY"
        assert state["error"] is None
        assert "扫描策略" in (state.get("clarify_question") or "")
