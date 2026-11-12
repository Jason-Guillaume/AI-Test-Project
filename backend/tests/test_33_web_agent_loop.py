"""验收项 33：UI 智能体二轮 Phase B —— observe→decide→act 循环与人工步骤 review。

覆盖 Phase B 的验收口径：

- 意图 `INTERACTIVE_WEB_AUTHORING` 进入循环，先取真实页面观测再决策；
- 循环必然收敛：决策脚本用尽后固定 DONE，或步数预算 / 空转轮次耗尽停在 review；
- `PROPOSE` 只产生**提案**并停在 web_step_review，确认前不执行任何操作；
- 只有人工 `confirm_web_step` 才执行单步（沙箱内执行，仍不落 TestRun）；
- `reject_web_step` 驳回后回到决策，不执行任何步骤；
- 步数预算耗尽时强制停在 review，而不是无限循环；
- 无效提案（非白名单操作）在**执行前**被拒绝；
- LLM 只看到脱敏语义树：prompt 里没有原始 DOM，也没有密码与 JWT；
- 跨项目的 Web 智能体会话 → 404。

Agent 走 `run_agent` + `FakeLLMProvider` 脚本注入（不依赖网络 / 密钥）。受控浏览器
会话直接经 service 打开（不经 TestClient）：HTTP 端点已由 Phase A（test_32）覆盖，
且 Playwright Sync API 不能在 TestClient 的 asyncio portal 线程里反复开实例。
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.agents.workflows.legacy.graph import run_agent
from app.agents.models.message import AgentMessage
from app.agents.models.session import AgentSession
from app.llm.providers import FakeLLMProvider
from app.agents.services import session_service
from app.features.web_testing.router import service as web_ui_service
from app.execution.browser.session_manager import registry
from app.features.web_testing.schemas import SessionStartInput
from tests.conftest import unique
from tests.test_16_agent import _create_session_http
from tests.test_25_security_execution import _actor
from tests.test_32_web_agent_runtime import target_server, web_setup  # noqa: F401 — 复用 Phase A 夹具


@pytest.fixture(autouse=True)
def _clean_browser_sessions():
    """每个用例前后清空进程级浏览器会话，避免并发槽与句柄泄漏。"""
    registry.close_all()
    yield
    registry.close_all()


# --------------------------------------------------------------------------- LLM 脚本桩


class ScriptedProvider(FakeLLMProvider):
    """`web_decide` 按脚本次序返回，用尽后固定 DONE —— 保证循环必然收敛。

    其余 kind 交给 FakeLLMProvider 默认样例（intent / test_plan / ...）。
    """

    def __init__(self, decisions: list[dict]):
        """初始化对象状态。"""
        super().__init__()
        self._decisions = list(decisions)

    def generate_structured(self, system, user_content, schema=None, *, kind=None, history=None):
        """生成`structured`。"""
        if kind != "web_decide":
            return super().generate_structured(
                system, user_content, schema, kind=kind, history=history,
            )
        payload = self._decisions.pop(0) if self._decisions else {
            "decision": "DONE", "step": None, "rationale": "决策脚本用尽，收敛结束。",
        }
        self.calls.append({"system": system, "user": user_content, "kind": kind, "history": history or []})
        return payload


def _web_intent() -> dict:
    """意图识别桩：交互式 Web 用例编写（无 target_ids，不走 CLARIFY）。"""
    return {
        "intent": "INTERACTIVE_WEB_AUTHORING",
        "target_type": None,
        "target_ids": [],
        "target_description": None,
        "clarify_question": None,
        "security_strategy_keys": [],
    }


def _propose(operation: str = "CLICK", value: str = "submit") -> dict:
    """构造一条合法的 PROPOSE 决策（WebStep 结构）。"""
    return {
        "decision": "PROPOSE",
        "step": {"name": f"{operation} 步骤", "operation": operation,
                 "locator": {"strategy": "TEST_ID", "value": value}},
        "rationale": "按目标推进这一步操作。",
    }


def _fill_proposal(value: str = "alice@corp.example") -> dict:
    """构造一条带真实输入值的 FILL 提案（FILL 要求同时给 locator 与 value）。"""
    return {
        "decision": "PROPOSE",
        "step": {"name": "填写用户名", "operation": "FILL",
                 "locator": {"strategy": "TEST_ID", "value": "username"}, "value": value},
        "rationale": "把用户名填入用户名输入框。",
    }


# --------------------------------------------------------------------------- 场景准备


def _open_browser_session(db, project_id, env_id, *, budget=10):
    """直接经 service 启动受控浏览器会话，返回 (会话 ID, 初始步数)。"""
    data = web_ui_service.start_session(
        db, project_id,
        SessionStartInput(environment_id=env_id, target_page_path="/", step_budget=budget),
        _actor(db),
    )
    assert data["status"] == "ACTIVE"
    return data["id"], data["step_count"]


def _close_browser_session(db, wsid):
    """关闭浏览器会话。"""
    web_ui_service.close_session(db, wsid, _actor(db))


def _agent_session(api, admin, project_id):
    """建 Agent 会话（对话层），返回 session id。"""
    return _create_session_http(api, admin, project_id)


def _step_rows(db, session_id):
    """会话已落库的步骤提案行。"""
    return db.execute(text(
        "select sort, status, source from web_agent_step where session_id = :s order by sort"
    ), {"s": session_id}).all()


def _test_run_count(db, project_id):
    """项目内正式执行记录数（沙箱探索必须恒为 0）。"""
    return int(db.execute(text(
        "select count(*) from test_run where project_id = :p"
    ), {"p": project_id}).scalar_one())


def _drive(db, session_id, user, provider, **kwargs):
    """推进一轮 Agent：重建 state → invoke → 持久化 → 返回最终 state。"""
    session = db.get(AgentSession, session_id)
    return run_agent(db, session, user, provider, **kwargs)


# --------------------------------------------------------------------------- 循环收敛


class TestLoopConvergence:
    def test_observe_then_converge_without_testrun(self, api, admin, db, web_setup):
        """只 OBSERVE 的决策序列：预算守卫把循环拉到 review，且从不产生正式执行。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id, budget=2)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([
            {"decision": "OBSERVE", "step": None, "rationale": "页面已加载，继续观察。"},
            {"decision": "OBSERVE", "step": None, "rationale": "等待下一步决策。"},
        ])
        provider.set_response("intent", _web_intent())
        user = _actor(db)

        state, emitted = _drive(db, sid, user, provider,
                                content="帮我探索一下这个页面", web_session_id=wsid)

        assert state.get("error") is None
        # 预算耗尽 → 停在人工 review，而不是无限观察
        assert state.get("current_stage") == "WEB_STEP_REVIEW"
        # 会话绑定、目标与预算已固化到 state（预算来自活句柄）
        assert state.get("web_agent_session_id") == wsid
        assert state.get("web_goal") == "帮我探索一下这个页面"
        assert state.get("web_step_budget") == 2
        # 一步都没有执行
        assert state.get("web_proposed_steps") == []
        assert _step_rows(db, wsid) == []
        # 沙箱探索不落正式执行记录
        assert _test_run_count(db, project_id) == 0
        # 观测消息已留痕，且不包含遮罩截图
        obs = [m for m in emitted if m.message_type == "WEB_OBSERVATION"]
        assert obs, "观测应作为 WEB_OBSERVATION 消息留痕"
        blob = str(obs[-1].metadata_json or {})
        assert "Super-Secret" not in blob
        assert "jwt-abcdefghij" not in blob
        assert "screenshot_b64" not in blob

    def test_cross_project_web_session_is_404(self, api, admin, db, web_setup):
        """Web 会话属于别的项目：HTTP 层直接 404，不进图。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id)
        # 另一个项目下的 Agent 会话引用外部 Web 会话
        other = api.post("/projects", username=admin, json={"name": unique("agent-other")})
        assert other.status_code == 201, other.text
        sid = _agent_session(api, admin, other.json()["id"])

        resp = api.post(f"/agent/sessions/{sid}/messages", username=admin,
                        json={"content": "开始探索", "web_session_id": wsid})
        assert resp.status_code == 404
        _close_browser_session(db, wsid)


# --------------------------------------------------------------------------- 提案与人工确认


class TestProposalGate:
    def test_propose_only_proposes_until_human_confirms(self, api, admin, db, web_setup):
        """PROPOSE 只落提案并停在 review；确认前不执行，确认后沙箱内执行。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id, budget=2)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([_propose("CLICK", "submit"), _propose("CLICK", "submit")])
        provider.set_response("intent", _web_intent())
        user = _actor(db)

        # 第 1 轮：观测 → 决策 PROPOSE → 停在 review
        state, _ = _drive(db, sid, user, provider,
                          content="点击提交按钮", web_session_id=wsid)
        assert state.get("error") is None
        assert state.get("current_stage") == "WEB_STEP_REVIEW"
        assert state.get("web_current_step", {}).get("operation") == "CLICK"
        assert state.get("web_proposed_steps") == []
        assert _step_rows(db, wsid) == []

        # 第 2 轮：人工确认 → 执行一步 → 继续观测与决策，再次停在 review
        state2, _ = _drive(db, sid, user, provider, action="confirm_web_step")
        assert state2.get("error") is None
        assert state2.get("current_stage") == "WEB_STEP_REVIEW"
        assert len(state2.get("web_proposed_steps") or []) == 1
        rows = _step_rows(db, wsid)
        assert len(rows) == 1
        assert rows[0].status == "ACCEPTED"
        assert rows[0].source == "AI"
        assert _test_run_count(db, project_id) == 0
        _close_browser_session(db, wsid)

    def test_reject_does_not_execute(self, api, admin, db, web_setup):
        """驳回提案：不执行任何步骤，回到决策重新观察。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id, budget=2)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([_propose("CLICK", "submit"),
                                     {"decision": "DONE", "step": None, "rationale": "人工驳回后结束。"}])
        provider.set_response("intent", _web_intent())
        user = _actor(db)

        _drive(db, sid, user, provider, content="点击提交", web_session_id=wsid)
        state2, _ = _drive(db, sid, user, provider, action="reject_web_step")

        assert state2.get("web_current_step") is None
        assert state2.get("web_proposed_steps") == []
        assert _step_rows(db, wsid) == []
        _close_browser_session(db, wsid)

    def test_budget_guard_stops_at_review(self, api, admin, db, web_setup):
        """步数预算耗尽时强制停在 review（无错误），而不是继续执行下一步。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id, budget=1)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([_propose("CLICK", "submit"), _propose("CLICK", "submit")])
        provider.set_response("intent", _web_intent())
        user = _actor(db)

        _drive(db, sid, user, provider, content="点击提交", web_session_id=wsid)
        state2, _ = _drive(db, sid, user, provider, action="confirm_web_step")

        assert state2.get("current_stage") == "WEB_STEP_REVIEW"
        assert state2.get("error") is None
        # 预算为 1：只允许执行 1 步
        assert len(state2.get("web_proposed_steps") or []) == 1
        assert len(_step_rows(db, wsid)) == 1
        _close_browser_session(db, wsid)

    def test_executed_step_values_do_not_leak_into_message_metadata(self, api, admin, db, web_setup):
        """加密边界：步骤里的真实值不得以明文落 agent_message.metadata_json。

        web_agent_step 表把步骤与观测整体加密落库，但 agent_message.metadata_json
        对会话内所有 viewer 都是明文。web_act 把 {**step, status, result} 写进
        web_proposed_steps，persist_turn 若不掩掉就会把 value 明文落对话表——
        与 web_agent_step 的加密口径自相矛盾，也直接违背「凭据只写不回显」。
        """
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id, budget=2)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([_fill_proposal()])
        provider.set_response("intent", _web_intent())
        user = _actor(db)
        try:
            _drive(db, sid, user, provider, content="填写用户名", web_session_id=wsid)
            _drive(db, sid, user, provider, action="confirm_web_step")

            rows = _step_rows(db, wsid)
            assert len(rows) == 1 and rows[0].status == "ACCEPTED", "步骤应已执行并落库"
            # web_agent_step 是加密列：既不含明文值，也不该是原始 JSON（"operation" 键不应可见）
            encrypted = db.execute(text(
                "select step_encrypted from web_agent_step where session_id = :s"
            ), {"s": wsid}).all()
            assert encrypted, "步骤行应有留痕"
            for row in encrypted:
                blob = row.step_encrypted or ""
                assert blob, "步骤留痕不应为空"
                assert "alice@corp.example" not in blob, "步骤值明文落库"
                assert "operation" not in blob, "步骤留痕未加密，直接落了原始 JSON"

            msgs = (
                db.query(AgentMessage)
                .filter(AgentMessage.session_id == sid)
                .order_by(AgentMessage.id.asc())
                .all()
            )
            meta_rows = [m for m in msgs if m.message_type == "WEB_AGENT_STEP"]
            assert meta_rows, "步骤提案应作为 WEB_AGENT_STEP 消息留痕"
            for msg in meta_rows:
                meta = msg.metadata_json or {}
                assert "alice@corp.example" not in str(meta), "步骤值明文落入 agent_message.metadata_json"
                assert meta.get("steps_redacted") is True, "落库提案必须显式标记已脱敏"
                for step in (meta.get("steps") or []):
                    assert step.get("operation") == "FILL" and step.get("status") == "ACCEPTED", (
                        "掩码后仍要保留操作与状态，供预算守卫与前端提案面板使用",
                    )
                    assert step.get("value") == "[已脱敏]"
                    assert "alice@corp.example" not in str(step.get("result") or {})
            # 预算守卫依赖的步数计数不受脱敏影响：跨轮次重建仍数 1 步，会话绑定不丢。
            restored = session_service.load_state(db, db.get(AgentSession, sid))
            assert restored.get("web_agent_session_id") == wsid
            assert len(restored.get("web_proposed_steps") or []) == 1
            assert restored.get("web_step_budget") == 2
        finally:
            _close_browser_session(db, wsid)

    def test_invalid_proposal_is_refused_before_execution(self, api, admin, db, web_setup):
        """无效提案在**执行前**被拒绝：非白名单操作不放行，也不落任何步骤。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([_propose("EVAL", "document.cookie")])
        provider.set_response("intent", _web_intent())
        user = _actor(db)

        state, _ = _drive(db, sid, user, provider, content="执行一下", web_session_id=wsid)

        assert state.get("current_stage") == "FAILED"
        assert state.get("error", {}).get("code") == "WEB_STEP_INVALID"
        assert state.get("web_current_step") is None
        assert _step_rows(db, wsid) == []
        assert _test_run_count(db, project_id) == 0
        _close_browser_session(db, wsid)

    def test_closed_session_is_reported_not_swallowed(self, api, admin, db, web_setup):
        """会话已关闭时给出明确错误，不静默跳过。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id)
        _close_browser_session(db, wsid)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([_propose("CLICK", "submit")])
        provider.set_response("intent", _web_intent())
        user = _actor(db)

        state, _ = _drive(db, sid, user, provider, content="点击提交", web_session_id=wsid)

        assert state.get("error", {}).get("code") == "WEB_SESSION_CLOSED"
        assert state.get("current_stage") == "FAILED"


# --------------------------------------------------------------------------- LLM 输入脱敏


class TestIntentPromptContract:
    """意图枚举与 intent.md 契约一致：新意图必须写进 prompt，否则生产链路不可达。

    教训：INTERACTIVE_WEB_AUTHORING 曾只加进 AGENT_INTENTS 与路由分支，漏写 intent.md。
    所有单测都绿（ScriptedProvider 直接注入意图，绕过了意图分类），但生产 LLM 永远
    不会吐出该意图，observe→decide→act 整条链路在控制台不可达。
    """

    def test_every_intent_is_advertised_in_intent_prompt(self):
        """验证`every`意图是否`advertised``in`意图提示词场景及其预期结果。"""
        from app.agents.prompts import load_prompt
        from app.agents.session_schemas import AGENT_INTENTS

        prompt = load_prompt("intent")
        missing = [intent for intent in AGENT_INTENTS if f"`{intent}`" not in prompt]
        assert not missing, f"intent.md 未收录意图，生产环境无法路由到该链路：{missing}"

    def test_web_authoring_intent_is_a_first_class_choice(self):
        """Web 编写意图必须有可选描述，而不只是被顺带列名。"""
        from app.agents.prompts import load_prompt

        prompt = load_prompt("intent")
        marker = prompt.find("`INTERACTIVE_WEB_AUTHORING`")
        assert marker >= 0, "intent.md 缺 INTERACTIVE_WEB_AUTHORING"
        # 该意图后面必须跟着一段判定说明（用户怎么说才选它），否则分类器无从判断。
        tail = prompt[marker:marker + 400]
        assert "CLARIFY" not in tail[: tail.find("\n")]
        assert "时选此项" in tail

    def test_prompt_version_bumped_after_intent_change(self):
        """意图枚举变更后版本号同步提升，便于追溯生成资产。"""
        from app.agents.prompts import TEST_INTENT_PROMPT_V3, load_prompt

        # intent.md 头部声明的版本常量必须真实存在，否则追溯链断在文档里。
        assert TEST_INTENT_PROMPT_V3 == "intent-v3"
        prompt = load_prompt("intent")
        assert "TEST_INTENT_PROMPT_V3" in prompt, "prompt 头部必须声明其版本号"


class TestPromptSanitization:
    def test_llm_only_sees_sanitized_tree(self, api, admin, db, web_setup):
        """喂给 LLM 的内容：有语义树结构，无原始 DOM，无密码与 JWT。"""
        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id, budget=1)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([
            {"decision": "OBSERVE", "step": None, "rationale": "观察中。"},
            {"decision": "OBSERVE", "step": None, "rationale": "继续观察。"},
        ])
        provider.set_response("intent", _web_intent())
        user = _actor(db)

        state, _ = _drive(db, sid, user, provider, content="探索页面", web_session_id=wsid)
        assert state.get("error") is None

        calls = [c for c in provider.calls if c["kind"] == "web_decide"]
        assert calls, "应至少调用一次 web_decide"
        user_blob = "\n".join(c["user"] for c in calls)
        system_blob = "\n".join(c["system"] for c in calls)
        combined = user_blob + "\n" + system_blob

        # 结构可见
        assert "页面语义树" in user_blob
        assert "textbox" in user_blob or "button" in user_blob
        assert "用户目标" in user_blob
        # 原始 DOM 与凭据不可见
        for forbidden in ("<input", "<button", "<html", "Super-Secret", "jwt-abcdefghij",
                          "Unique-Pwd", "document.cookie"):
            assert forbidden not in combined, f"prompt 泄漏：{forbidden}"
        # system prompt 明确禁止脚本与凭据
        assert "禁止" in system_blob
        _close_browser_session(db, wsid)


@pytest.mark.usefixtures("web_setup")
class TestHttpEntry:
    """HTTP 正向入口：此前 web_session_id 只经 run_agent 直调验证过。

    HTTP 层还多做三件事——项目归属校验、provider 装配、workspace 序列化——
    它们从未被走通。这里用 monkeypatch 把 ProductionLLMProvider 换成脚本桩，
    让请求真正穿透路由而不产生外网调用。
    """

    def test_http_injects_web_session_and_persists_pause(self, api, admin, db, web_setup, monkeypatch):
        """验证HTTP`injects`Web会话和`persists``pause`场景及其预期结果。"""
        from app.agents import router as agent_router

        project_id, env_id = web_setup
        wsid, _ = _open_browser_session(db, project_id, env_id, budget=1)
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([_propose("CLICK", "submit")])
        provider.set_response("intent", _web_intent())
        monkeypatch.setattr(agent_router, "ProductionLLMProvider", lambda db: provider)

        resp = api.post(
            f"/agent/sessions/{sid}/messages", username=admin,
            json={"content": "打开这个页面看看有什么", "web_session_id": wsid},
        )
        assert resp.status_code == 200, resp.text
        ws = resp.json()["workspace"]
        # 绑定与目标已固化进工作区，阶段停在人工 review 暂停点
        assert ws["web_agent_session_id"] == wsid
        assert ws["stage"] == "WEB_STEP_REVIEW"
        assert ws["suggested_actions"] == ["confirm_web_step", "reject_web_step"]
        assert _test_run_count(db, project_id) == 0

        db.expire_all()
        assert db.get(AgentSession, sid).current_stage == "WEB_STEP_REVIEW"
        _close_browser_session(db, wsid)

    def test_http_requires_web_session_for_authoring_intent(self, api, admin, db, web_setup, monkeypatch):
        """不带 web_session_id 却选到 Web 意图：节点报 WEB_SESSION_CLOSED，不静默猜会话。"""
        from app.agents import router as agent_router

        project_id, _ = web_setup
        sid = _agent_session(api, admin, project_id)
        provider = ScriptedProvider([_propose("CLICK", "submit")])
        provider.set_response("intent", _web_intent())
        monkeypatch.setattr(agent_router, "ProductionLLMProvider", lambda db: provider)

        resp = api.post(
            f"/agent/sessions/{sid}/messages", username=admin,
            json={"content": "帮我写个 Web 用例"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["workspace"]["stage"] == "FAILED"
        db.expire_all()
        assert db.get(AgentSession, sid).current_stage == "FAILED"


@pytest.mark.usefixtures("web_setup")
class TestBudgetBoundary:
    def test_zero_length_budget_is_rejected_upstream(self, api, admin, db, web_setup):
        """0 步预算由 schema 拒绝（ge=1），不进入智能体循环。"""
        project_id, env_id = web_setup
        resp = api.post(f"/projects/{project_id}/web-agent/sessions", username=admin,
                        json={"environment_id": env_id, "target_page_path": "/", "step_budget": 0})
        assert resp.status_code == 422
