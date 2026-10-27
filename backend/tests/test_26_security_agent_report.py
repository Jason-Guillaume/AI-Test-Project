"""验收项 26：Security Testing Phase F —— Agent 对话链路、基线解析与报告安全摘要。

覆盖开发计划 §20.3 与 §21（Phase F）：

- 意图「检查创建任务越权」解析为 ``GENERATE_SECURITY_TEST``，目标是该 API
- 计划生成后图停在 ``SECURITY_PLAN_REVIEW``，**未确认时数据库没有新的 SECURITY TestCase**
- LLM 输出带 ``script`` 被硬拒绝（``STRUCTURED_OUTPUT_INVALID``，不重试）
- 一次只测一个目标：多目标返回澄清，不猜
- 人工确认后执行：报告 ``summary.security.potential_issues`` 与未关闭 Finding 数一致，
  Finding 严重级别由代码判定（规则写 MEDIUM，去掉鉴权头后被放行 → HIGH）
- 高风险未确认：执行直接 SKIPPED + 不发出站，不生成 Finding
- 报告 AI 总结失败不影响 ``summary.security`` 已写入
- 计划预览按 API 目标解析基线用例（排除安全用例 / 业务动作型 / 停用用例），
  解析不到基线给可读错误而不是空计划

Agent 走 ``run_agent`` + ``FakeLLMProvider``（不依赖网络 / 密钥）；HTTP 出站沿用
``test_15`` 的 stub 方式，不访问真实公网。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.features.agent.graph import run_agent
from app.features.agent.models.agent_session import AgentSession
from app.features.agent.providers.llm_provider import FakeLLMProvider
from app.features.security_testing.models import (
    SecurityCase,
    SecurityExecution,
    SecurityFinding,
    SecurityPlan,
)
from app.features.reports.models.report import TestReport
from app.features.security_testing.schemas import PlanPreviewRequest
from app.features.security_testing.services.plan_service import PlanService
from app.features.test_management.models.execution import CaseExecution
from app.features.test_management.models.test_case import TestCase
from app.shared.errors import CODE_SECURITY_BASELINE_NOT_FOUND, AppError
from tests.conftest import unique
from tests.test_16_agent import _create_session_http
from tests.test_25_security_execution import (
    _TOKEN,
    _admin_id,
    _actor,
    _auth_step,
    _env,
    _make_case,
    _make_iface,
    _make_rule,
    _new_project,
    _route_by_auth,
    _whitelist,
    CountingStub,
)


# --------------------------------------------------------------------------- 场景准备


def _scene(db, api, admin, *, port=None, env_base_url: str | None = None,
           mutation_type: str = "REMOVE_TOKEN", target_location: str = "HEADER",
           target_field: str | None = "Authorization",
           expected: str = "EXPECTED_DENY", codes: tuple[int, ...] = (401, 403),
           severity: str = "MEDIUM", confirmation_required: bool = True,
           step: dict | None = None, with_baseline: bool = True,
           baseline_enabled: bool = True) -> SimpleNamespace:
    """项目 + 出站白名单 + 环境 + 接口 + 基线用例 + 安全策略/规则。

    与 ``test_25`` 的 ``_seed`` 不同：**不**建 SECURITY TestCase 与扩展行——安全用例
    由 Agent 的 ``confirm_security_plan`` 落库，这正是本文件要验证的边界。
    """
    project_id = _new_project(db, api, admin)
    admin_id = _admin_id(db)

    if port is not None:
        _whitelist(db, project_id, port, admin_id)

    iface = _make_iface(db, project_id)
    baseline = None
    if with_baseline:
        baseline = _make_case(
            db, project_id, admin_id, api_id=iface.id,
            name=unique("baseline"), steps=[step or _auth_step()],
        )
        if not baseline_enabled:
            baseline.enabled = False
    strategy, rule = _make_rule(
        db, project_id, mutation_type=mutation_type, target_location=target_location,
        target_field=target_field, expected=expected, codes=codes,
        severity=severity, confirmation_required=confirmation_required,
    )
    env = _env(db, admin_id, name="dev", base_url=env_base_url)

    db.commit()
    return SimpleNamespace(
        project_id=project_id, admin_id=admin_id, iface=iface,
        baseline=baseline,
        strategy=strategy, rule=rule, env=env,
    )


def _open_session(db, api, admin, project_id: int):
    """建会话并取回 ORM 行 + 管理员 ORM 行。"""
    session_id = _create_session_http(api, admin, project_id)
    return db.get(AgentSession, session_id), _actor(db)


def _intent_payload(scene: SimpleNamespace) -> dict:
    """构造请求安全测试的智能体意图数据。"""
    return {
        "intent": "GENERATE_SECURITY_TEST",
        "target_type": "API",
        "target_ids": [scene.iface.id],
        "target_description": "创建任务接口",
        "clarify_question": None,
        "security_strategy_keys": [scene.strategy.strategy_key],
    }


def _drive_to_review(db, api, admin, scene, *, provider=None):
    """自然语言 → 意图 → 计划 review 暂停点。"""
    session, user = _open_session(db, api, admin, scene.project_id)
    provider = provider or FakeLLMProvider()
    provider.set_response("intent", _intent_payload(scene))
    state, _ = run_agent(db, session, user, provider, content="检查创建任务越权")
    return state, session, user, provider


def _drive_to_report(db, api, admin, scene, *, provider_cls=FakeLLMProvider):
    """意图 → 确认计划 → 确认风险 → 执行到报告 review。返回 (state, case_id, provider)。"""
    session, user = _open_session(db, api, admin, scene.project_id)
    provider = provider_cls()
    provider.set_response("intent", _intent_payload(scene))

    run_agent(db, session, user, provider, content="检查创建任务越权")
    state, _ = run_agent(db, session, user, provider, action="confirm_security_plan")
    case_id = state["generated_test_cases"][0]["id"]
    state, _ = run_agent(db, session, user, provider, action="confirm_security_risk")
    state, _ = run_agent(
        db, session, user, provider,
        action="execute", case_ids=[case_id], environment_id=scene.env.id,
    )
    return state, case_id, provider


class ExplodingProvider(FakeLLMProvider):
    """只让报告 AI 总结失败：其余 kind 正常返回，验证 summary.security 不受影响。"""

    def generate_structured(self, system, user_content, schema=None, *,
                            kind=None, history=None, validator=None):
        """生成`structured`。"""
        if kind == "report_summary":
            raise RuntimeError("LLM 不可用")
        return super().generate_structured(
            system, user_content, schema, kind=kind, history=history, validator=validator,
        )


# --------------------------------------------------------------------------- 查询助手


def _security_cases(db, project_id: int) -> list[TestCase]:
    """查询项目下的安全测试用例。"""
    return (
        db.query(TestCase)
        .filter(TestCase.project_id == project_id, TestCase.case_type == "SECURITY")
        .all()
    )


def _plans(db, project_id: int) -> list[SecurityPlan]:
    """查询项目下的安全测试计划。"""
    return db.query(SecurityPlan).filter(SecurityPlan.project_id == project_id).all()


def _findings(db, project_id: int) -> list[SecurityFinding]:
    """查询项目下的安全发现项。"""
    return db.query(SecurityFinding).filter(SecurityFinding.project_id == project_id).all()


def _execution(db, run_id: int) -> SecurityExecution:
    """按标识查询安全执行记录。"""
    return (
        db.query(SecurityExecution)
        .filter(SecurityExecution.test_run_id == run_id)
        .one()
    )


def _case_execution(db, run_id: int) -> CaseExecution:
    """查询用例执行记录。"""
    return (
        db.query(CaseExecution)
        .filter(CaseExecution.test_run_id == run_id)
        .one()
    )


def _report(db, report_id: int) -> TestReport:
    """按标识查询测试报告。"""
    return db.get(TestReport, report_id)


def _report_summary(db, report_id: int) -> dict:
    """读取测试报告摘要。"""
    return _report(db, report_id).summary or {}


# --------------------------------------------------------------------------- 意图


class TestSecurityIntent:
    """意图识别：一次一个目标、策略可解析、拒绝夹带脚本。"""

    def test_generate_security_test_intent_stops_at_plan_review(self, db, api, admin):
        """验证生成安全测试意图`stops``at`计划`review`场景及其预期结果。"""
        with CountingStub() as stub:
            scene = _scene(db, api, admin, port=stub.port, env_base_url=stub.base_url)
            state, session, user, provider = _drive_to_review(db, api, admin, scene)

        assert state["intent"] == "GENERATE_SECURITY_TEST"
        assert state["current_stage"] == "SECURITY_PLAN_REVIEW"
        assert state["error"] is None
        assert session.current_stage == "SECURITY_PLAN_REVIEW"

        plan = state["security_plan"] or {}
        assert plan["estimated_count"] == 1
        assert plan["baseline_case_id"] == scene.baseline.id
        assert plan["strategy_keys"] == [scene.strategy.strategy_key]
        item = plan["items"][0]
        assert item["mutation_type"] == "REMOVE_TOKEN"
        assert item["api_id"] == scene.iface.id
        assert "REMOVE_TOKEN" in item["name"]
        assert item["expectation"] == "EXPECTED_DENY"
        assert item["expected_status_codes"] == [401, 403]
        # 规则声明的默认级别（严重级别最终以代码判定为准）。
        assert item["severity"] == "MEDIUM"
        assert item["confirmation_required"] is True
        assert item["blocked_reason"] is None

        # 未确认：不落 TestCase，只留一条 DRAFT 计划。
        assert _security_cases(db, scene.project_id) == []
        plans = _plans(db, scene.project_id)
        assert len(plans) == 1
        assert plans[0].status == "DRAFT"
        assert plans[0].baseline_case_id == scene.baseline.id
        assert _findings(db, scene.project_id) == []

    def test_multi_target_returns_clarify(self, db, api, admin):
        """验证`multi`目标`returns``clarify`场景及其预期结果。"""
        with CountingStub() as stub:
            scene = _scene(db, api, admin, port=stub.port, env_base_url=stub.base_url)
            other = _make_iface(db, scene.project_id, path="/tasks/detail")
            db.commit()
            session, user = _open_session(db, api, admin, scene.project_id)
            provider = FakeLLMProvider()
            provider.set_response(
                "intent",
                {**_intent_payload(scene), "target_ids": [scene.iface.id, other.id]},
            )

            state, _ = run_agent(db, session, user, provider, content="检查创建任务越权")

        assert state["intent"] == "GENERATE_SECURITY_TEST"
        assert state["current_stage"] == "CLARIFY"
        assert state["error"] is None
        assert "一次只测一个目标" in state["clarify_question"]
        assert state["security_plan"] is None
        assert state["security_plan_id"] is None
        assert _security_cases(db, scene.project_id) == []
        assert _plans(db, scene.project_id) == []

    def test_unmatched_strategy_gives_readable_error(self, db, api, admin):
        """验证`unmatched`策略`gives``readable`错误场景及其预期结果。"""
        with CountingStub() as stub:
            scene = _scene(db, api, admin, port=stub.port, env_base_url=stub.base_url)
            session, user = _open_session(db, api, admin, scene.project_id)
            provider = FakeLLMProvider()
            provider.set_response(
                "intent",
                {**_intent_payload(scene), "security_strategy_keys": ["NOT_A_STRATEGY"]},
            )

            state, _ = run_agent(db, session, user, provider, content="检查创建任务越权")

        assert state["error"]["code"] == "SECURITY_PLAN_FAILED"
        assert "没有可用的安全策略" in state["error"]["message"]
        assert "NOT_A_STRATEGY" in state["error"]["message"]
        assert state["current_stage"] == "FAILED"
        assert state["security_plan"] is None
        assert _security_cases(db, scene.project_id) == []
        assert _plans(db, scene.project_id) == []

    def test_llm_output_with_script_is_rejected(self, db, api, admin):
        """验证LLM输出包含`script`是否被拒绝场景及其预期结果。"""
        with CountingStub() as stub:
            scene = _scene(db, api, admin, port=stub.port, env_base_url=stub.base_url)
            session, user = _open_session(db, api, admin, scene.project_id)
            provider = FakeLLMProvider()
            provider.set_response(
                "intent",
                {**_intent_payload(scene), "script": "curl -X POST http://x/tasks"},
            )

            state, _ = run_agent(db, session, user, provider, content="检查创建任务越权")

        assert state["error"]["code"] == "STRUCTURED_OUTPUT_INVALID"
        assert "禁止字段" in state["error"]["message"]
        assert state["current_stage"] == "FAILED"
        assert state["security_plan"] is None
        assert _security_cases(db, scene.project_id) == []


# --------------------------------------------------------------------------- 工作区


class TestWorkspaceActions:
    """review 暂停点的按钮由持久化状态重建，刷新后不丢。"""

    def test_plan_review_offers_confirm_security_plan(self, db, api, admin):
        """验证计划`review``offers`确认安全计划场景及其预期结果。"""
        with CountingStub() as stub:
            scene = _scene(db, api, admin, port=stub.port, env_base_url=stub.base_url)
            state, session, user, provider = _drive_to_review(db, api, admin, scene)

        # 走 HTTP 端点：重新 load_state，验证按钮不依赖进程内内存。
        response = api.get(f"/agent/sessions/{session.id}/workspace", username=admin)
        assert response.status_code == 200, response.text
        workspace = response.json()

        assert workspace["stage"] == "SECURITY_PLAN_REVIEW"
        assert workspace["suggested_actions"] == ["confirm_security_plan"]
        assert workspace["security_plan"]["estimated_count"] == 1
        assert workspace["security_plan"]["baseline_case_id"] == scene.baseline.id
        assert workspace["test_cases"] == []
        assert workspace["report_id"] is None

    def test_pending_risk_adds_confirm_security_risk(self, db, api, admin):
        """验证`pending`风险`adds`确认安全风险场景及其预期结果。"""
        with CountingStub() as stub:
            scene = _scene(db, api, admin, port=stub.port, env_base_url=stub.base_url)
            state, session, user, provider = _drive_to_review(db, api, admin, scene)
            state, _ = run_agent(
                db, session, user, provider, action="confirm_security_plan",
            )

        assert state["current_stage"] == "TEST_CASE_REVIEW"
        assert (state["security_risk_pending"] or {}).get("count") == 1

        response = api.get(f"/agent/sessions/{session.id}/workspace", username=admin)
        assert response.status_code == 200, response.text
        workspace = response.json()

        assert workspace["stage"] == "TEST_CASE_REVIEW"
        assert "confirm_security_risk" in workspace["suggested_actions"]
        assert "execute" in workspace["suggested_actions"]

        case = workspace["test_cases"][0]
        assert case["case_type"] == "SECURITY"
        assert case["security_confirmation_status"] == "PENDING_CONFIRM"
        assert case["security_confirmation_required"] is True


# --------------------------------------------------------------------------- 基线解析


class TestPlanBaselineResolution:
    """计划预览的目标解析：基线用例是变异请求的唯一事实来源。"""

    def test_preview_by_api_id_resolves_baseline_case(self, db, api, admin):
        """验证预览按API标识`resolves`基线用例场景及其预期结果。"""
        scene = _scene(db, api, admin)

        preview = PlanService.preview(
            db, scene.project_id,
            PlanPreviewRequest(
                api_id=scene.iface.id, strategy_ids=[scene.strategy.id],
                name="安全计划",
            ),
            actor=_actor(db),
        )

        assert preview.status == "DRAFT"
        assert preview.estimated_count == 1
        assert preview.baseline_case_id == scene.baseline.id
        assert preview.baseline_case_name == scene.baseline.name
        assert "REMOVE_TOKEN" in preview.items[0].name
        assert preview.items[0].api_id == scene.iface.id
        assert preview.items[0].confirmation_required is True

    @pytest.mark.parametrize("variant", ["no_case", "security_case_only", "disabled_only"])
    def test_preview_by_api_id_requires_a_usable_baseline(
        self, db, api, admin, variant,
    ):
        """验证预览按API标识需要`a``usable`基线场景及其预期结果。"""
        scene = _scene(db, api, admin, with_baseline=False)

        if variant == "security_case_only":
            _make_case(
                db, scene.project_id, scene.admin_id, api_id=scene.iface.id,
                name=unique("sec"), case_type="SECURITY",
            )
        elif variant == "disabled_only":
            case = _make_case(
                db, scene.project_id, scene.admin_id, api_id=scene.iface.id,
                name=unique("func"),
            )
            case.enabled = False
        db.commit()

        with pytest.raises(AppError) as excinfo:
            PlanService.preview(
                db, scene.project_id,
                PlanPreviewRequest(api_id=scene.iface.id, strategy_ids=[scene.strategy.id]),
                actor=_actor(db),
            )

        assert excinfo.value.status_code == 404
        assert excinfo.value.code == CODE_SECURITY_BASELINE_NOT_FOUND
        assert "基线" in excinfo.value.message

    def test_missing_baseline_reaches_agent_as_readable_error(self, db, api, admin):
        """验证缺失基线`reaches`智能体`as``readable`错误场景及其预期结果。"""
        with CountingStub() as stub:
            scene = _scene(db, api, admin, with_baseline=False, port=stub.port,
                           env_base_url=stub.base_url)
            session, user = _open_session(db, api, admin, scene.project_id)
            provider = FakeLLMProvider()
            provider.set_response("intent", _intent_payload(scene))

            state, _ = run_agent(db, session, user, provider, content="检查创建任务越权")

        assert state["error"]["code"] == "TARGET_NOT_FOUND"
        assert "基线" in state["error"]["message"]
        assert _plans(db, scene.project_id) == []
        assert _security_cases(db, scene.project_id) == []


# --------------------------------------------------------------------------- 执行与报告


class TestSecurityExecutionAndReport:
    """确认链路、执行结果与报告安全摘要。"""

    def test_execute_without_risk_confirmation_is_skipped(self, db, api, admin):
        """验证执行不带风险`confirmation`是否跳过场景及其预期结果。"""
        with CountingStub() as stub:
            _route_by_auth(
                stub, denied_status=200, denied_body={"code": 0, "data": {"id": 101}},
                hit_sink=[],
            )
            scene = _scene(db, api, admin, port=stub.port, env_base_url=stub.base_url)
            session, user = _open_session(db, api, admin, scene.project_id)
            provider = FakeLLMProvider()
            provider.set_response("intent", _intent_payload(scene))

            run_agent(db, session, user, provider, content="检查创建任务越权")
            state, _ = run_agent(
                db, session, user, provider, action="confirm_security_plan",
            )
            case_id = state["generated_test_cases"][0]["id"]
            # 跳过 confirm_security_risk：高风险用例必须被 runner 拦下。
            state, _ = run_agent(
                db, session, user, provider,
                action="execute", case_ids=[case_id], environment_id=scene.env.id,
            )

        assert state["error"] is None
        assert state["current_stage"] == "REPORT_REVIEW"
        # 一个出站都没发。
        assert stub.hits == []

        execution = _execution(db, state["test_run_id"])
        assert execution.security_result == "SKIPPED"
        assert execution.error_code == "SECURITY_CONFIRMATION_REQUIRED"
        assert _case_execution(db, state["test_run_id"]).status == "SKIPPED"
        assert _findings(db, scene.project_id) == []

        summary = _report_summary(db, state["report_id"])["security"]
        assert summary["cases"] == 1
        assert summary["skipped"] == 1
        assert summary["potential_issues"] == 0
        assert summary["pass"] == 0
        assert summary["findings"] == {"INFO": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}

    def test_confirm_execute_report_security_summary(self, db, api, admin):
        """验证确认执行报告安全摘要场景及其预期结果。"""
        hits: list[str] = []
        with CountingStub() as stub:
            _route_by_auth(
                stub, denied_status=200, denied_body={"code": 0, "data": {"id": 101}},
                hit_sink=hits,
            )
            scene = _scene(db, api, admin, port=stub.port, env_base_url=stub.base_url)
            state, case_id, provider = _drive_to_report(db, api, admin, scene)

        assert state["error"] is None
        assert state["current_stage"] == "REPORT_REVIEW"
        assert hits == ["baseline", "mutation"]
        assert provider.last_call["kind"] == "report_summary"

        # 确认计划后才落用例，且扩展行指向原基线、确认后 confirmed_at 被写。
        cases = _security_cases(db, scene.project_id)
        assert len(cases) == 1
        extension = (
            db.query(SecurityCase)
            .filter(SecurityCase.test_case_id == case_id)
            .one()
        )
        assert extension.baseline_case_id == scene.baseline.id
        assert extension.rule_id == scene.rule.id
        assert extension.confirmation_required is True
        assert extension.confirmed_at is not None

        # 报告摘要：potential_issues 必须等于本 Run 未关闭 Finding 数（§14 口径一致）。
        summary = _report_summary(db, state["report_id"])["security"]
        open_findings = [
            finding for finding in _findings(db, scene.project_id)
            if finding.test_run_id == state["test_run_id"]
        ]
        assert summary["cases"] == 1
        assert summary["pass"] == 0
        assert summary["potential_issues"] == len(open_findings) == 1
        assert summary["inconclusive"] == 0
        assert summary["failed_execution"] == 0
        assert summary["skipped"] == 0
        assert summary["findings"] == {"INFO": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 1, "CRITICAL": 0}

        finding = open_findings[0]
        assert finding.status == "OPEN"
        assert finding.mutation_type == "REMOVE_TOKEN"
        assert finding.api_id == scene.iface.id
        # 规则写的是 MEDIUM：级别由代码按「去掉鉴权头后被放行」判成 HIGH。
        assert scene.rule.severity == "MEDIUM"
        assert finding.severity == "HIGH"
        assert finding.bug_id is None
        # 风险等级取自 Finding 级别（用例是 P1 默认优先级，不会更高）。
        assert _report(db, state["report_id"]).risk_level == "HIGH"

        top = summary["top_findings"]
        assert len(top) == 1
        assert top[0]["id"] == finding.id
        assert top[0]["severity"] == "HIGH"
        assert top[0]["mutation_type"] == "REMOVE_TOKEN"
        assert top[0]["api_id"] == scene.iface.id
        assert "evidence" not in top[0]

        # Agent 回给用户的 brief 里带同一份安全摘要，且不含原始 token。
        brief = state["report_brief"] or {}
        assert brief["report_id"] == state["report_id"]
        assert brief["risk_level"] == "HIGH"
        assert brief["security_summary"]["cases"] == summary["cases"]
        assert brief["security_summary"]["potential_issues"] == summary["potential_issues"]
        assert brief["security_summary"]["findings"] == summary["findings"]
        assert not _has_token(brief)
        assert not _has_token(summary)

        assert _case_execution(db, state["test_run_id"]).status == "FAILED"

    def test_ai_summary_failure_does_not_break_security_summary(self, db, api, admin):
        """验证`ai`摘要失败是否不`break`安全摘要场景及其预期结果。"""
        with CountingStub() as stub:
            _route_by_auth(
                stub, denied_status=200, denied_body={"code": 0, "data": {"id": 101}},
                hit_sink=[],
            )
            scene = _scene(db, api, admin, port=stub.port, env_base_url=stub.base_url)
            state, _, _ = _drive_to_report(db, api, admin, scene, provider_cls=ExplodingProvider)

        assert state["error"] is None
        assert state["current_stage"] == "REPORT_REVIEW"

        report = _report(db, state["report_id"])
        assert report.status == "COMPLETED"
        assert report.ai_summary is None
        summary = (report.summary or {}).get("security")
        assert summary is not None
        assert summary["cases"] == 1
        assert summary["potential_issues"] == 1
        assert summary["findings"]["HIGH"] == 1


# --------------------------------------------------------------------------- 断言辅助


def _has_token(obj) -> bool:
    """报告 / brief 里不许出现原始鉴权头取值。"""
    return _TOKEN in str(obj)
