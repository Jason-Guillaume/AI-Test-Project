"""验收项 25：Security Testing Phase E —— 执行链路、Finding 与 §16.2 API。

覆盖开发计划 §18 / §20.2：

- 环境闸门：``prod`` 直接 SKIPPED + ``SECURITY_PRODUCTION_FORBIDDEN``，连基线请求都不发；
  环境名叫 ``dev`` 但出站目标登记为生产同样拒绝；未知环境名按 STAGING 默认拒绝，
  打开 ``allow_staging`` 后才放行
- 高风险未确认：SKIPPED + ``SECURITY_CONFIRMATION_REQUIRED``，不发出站
- 基线 5xx → INCONCLUSIVE，只发了一次基线请求、一次变异都不发，也不建 Finding
- 基线 2xx + REMOVE_TOKEN 得 200 → CaseExecution FAILED / POTENTIAL_ISSUE / HIGH Finding，
  trace 与证据里都没有原始 token；401 → PASS 且无 Finding；500 → MEDIUM Finding
- DUPLICATE_SUBMIT：第二次 409 → PASS；两次 2xx 且业务 ID 不同 → HIGH Finding
- ``BUSINESS_STATE`` 执行时 SKIPPED，不退化成盲发 HTTP
- 同 fingerprint 执行两次只留一条 OPEN 且 ``evidence.repeat_count == 2``；
  标 FALSE_POSITIVE 后再执行新开一条，带 ``prior_status``
- plan confirm 生成的 TestCase ``case_type='SECURITY'``，``baseline_case_id`` 指向原用例，
  不复制 step 文本作为第二份事实来源
- §16.2：security-cases 启停同步 ``test_case.enabled``、confirm-risk、security-runs 复用
  RunService、security-executions 读取、security-findings 状态机与权限

HTTP 出站沿用 ``test_15`` 的 stub 方式，不访问真实公网。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.security_testing.models import (
    SecurityCase,
    SecurityExecution,
    SecurityFinding,
    SecurityMutationRule,
    SecurityProjectSetting,
    SecurityStrategy,
)
from app.features.security_testing.runtime import runner
from app.features.security_testing.schemas import PlanConfirmRequest, PlanPreviewRequest
from app.features.security_testing.services.plan_service import PlanService
from app.features.test_management.models.execution import CaseExecution, TestRun
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_step import TestStep
from app.models.configuration import Environment
from app.models.identity import User
from app.models.project import ProjectOutboundTarget
from tests.conftest import DEFAULT_PASSWORD, unique
from tests.test_15_test_executor import StubServer

#: 基线用例里带的鉴权头；去掉之后再被放行才算「可比」。
_TOKEN = "baseline-token-abc"


class CountingStub(StubServer):
    """在 stub 上记下实际打到的请求，用来区分基线与变异各发了几次。"""

    def __init__(self) -> None:
        """初始化对象状态。"""
        super().__init__()
        self.hits: list[tuple[str, str]] = []

    def resolve(self, method, full_path):
        """解析并确定对应数据。"""
        self.hits.append((method, full_path.split("?", 1)[0]))
        return super().resolve(method, full_path)


# --------------------------------------------------------------------------- 身份 / 项目


def _admin_id(db) -> int:
    """查询平台管理员用户标识。"""
    return db.query(User).filter(User.username == "platform_admin").one().id


def _actor(db, username: str = "platform_admin") -> User:
    """按用户名查询操作人记录。"""
    return db.query(User).filter(User.username == username).one()


def _new_project(db, api, admin) -> int:
    """通过 API 创建安全测试项目并返回项目标识。"""
    response = api.post(
        "/projects", username=admin,
        json={"name": unique("sec-proj"), "description": "security project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _register_member(api, admin, project_id, *, role: str = "member") -> str:
    """注册新用户并加进项目，返回登录用户名。"""
    username = unique(f"sec-{role}")
    response = api.register(username)
    assert response.status_code == 201, response.text
    api.login(username, DEFAULT_PASSWORD)
    user_id = db_user_id(api, username)
    r = api.put(
        f"/projects/{project_id}/members/{user_id}", username=admin,
        json={"user_id": user_id, "role": role},
    )
    assert r.status_code == 200, r.text
    return username


def db_user_id(api, username: str) -> int:
    """从 API 会话反查用户 ID（注册响应里没有稳定的 id 字段）。"""
    from app.shared.database import SessionLocal

    with SessionLocal() as session:
        return session.query(User).filter(User.username == username).one().id


# --------------------------------------------------------------------------- 场景准备


def _env(db, admin_id: int, *, name: str, base_url: str | None = None) -> Environment:
    """按名取环境（不存在才建）。

    ``environment.name`` 全库唯一，seed 可能已经建了 ``dev`` / ``prod``，所以做
    find-or-create；指向 stub 的用例把 base_url 改过来（测试库是会话级一次性库，
    每个用例指向自己的 stub，互不影响）。
    """
    row = db.query(Environment).filter(Environment.name == name).first()
    if row is None:
        row = Environment(
            name=name, display_name=name, base_url=base_url or "",
            gateway_prefix="", default_headers={}, is_active=True,
            created_by=admin_id,
        )
        db.add(row)
        db.flush()
    if base_url is not None and (row.base_url or "") != base_url:
        row.base_url = base_url
        db.add(row)
        db.flush()
    return row


def _whitelist(db, project_id: int, port: int, admin_id: int,
               *, is_production: bool = False) -> None:
    """为项目添加测试目标的出站访问白名单。"""
    db.add(ProjectOutboundTarget(
        project_id=project_id, scheme="http", host="127.0.0.1", port=port,
        is_production=is_production, enabled=True, approved_by=admin_id,
    ))
    db.flush()


def _make_iface(db, project_id: int, *, method: str = "POST", path: str = "/tasks",
                auth_type: str = "bearer") -> ApiInterface:
    """构造`iface`。"""
    iface = ApiInterface(
        project_id=project_id, name=unique("iface"), method=method, path=path,
        auth_type=auth_type, content_type="application/json",
        status="ACTIVE", source_type="MANUAL",
    )
    db.add(iface)
    db.flush()
    return iface


def _make_case(db, project_id: int, admin_id: int, *, api_id: int, name: str,
               steps=None, case_type: str = "FUNCTIONAL") -> TestCase:
    """基线 / 功能用例：ACTION step 承载请求配置。"""
    case = TestCase(
        project_id=project_id, name=name, target_type="API", api_id=api_id,
        case_type=case_type, status="ACTIVE", enabled=True, created_by=admin_id,
    )
    db.add(case)
    db.flush()
    for index, config in enumerate(steps or [{}]):
        db.add(TestStep(
            test_case_id=case.id, name="请求", step_type="ACTION",
            target_type="API", target_id=api_id, sort=index, config_json=config,
        ))
    db.flush()
    return case


def _make_rule(db, project_id: int, *, mutation_type: str = "REMOVE_TOKEN",
               target_location: str = "HEADER", target_field: str | None = "Authorization",
               mutation_config=None, expected: str = "EXPECTED_DENY", codes=(401, 403),
               severity: str = "MEDIUM", confirmation_required: bool = False):
    """一条项目策略 + 一条规则。runner 以规则行为变异配置的权威来源。"""
    strategy = SecurityStrategy(
        project_id=project_id, scope="PROJECT", name=unique("strategy"),
        strategy_key=f"PROJ_{uuid4().hex[:8].upper()}", category="AUTHENTICATION",
        enabled=True, risk_level="MEDIUM", builtin=False,
    )
    db.add(strategy)
    db.flush()
    rule = SecurityMutationRule(
        project_id=project_id, strategy_id=strategy.id,
        name=f"规则-{mutation_type}",
        mutation_type=mutation_type, target_location=target_location,
        target_field=target_field, operator=mutation_type,
        mutation_config=mutation_config or {},
        expected_security_behavior=expected, expected_status_codes=list(codes),
        severity=severity, enabled=True, confirmation_required=confirmation_required,
    )
    db.add(rule)
    db.flush()
    return strategy, rule


def _auth_step() -> dict:
    """基线请求带 Authorization：去掉之后再放行才有可比的结论。"""
    return {"headers": {"Authorization": f"Bearer {_TOKEN}"}, "body": {"name": "任务A"}}


def _seed(db, api, admin, *, port=None, env_name: str = "dev",
          env_base_url: str | None = None, is_production_target: bool = False,
          allow_staging: bool = False,
          mutation_type: str = "REMOVE_TOKEN", target_location: str = "HEADER",
          target_field: str | None = "Authorization", mutation_config=None,
          expected: str = "EXPECTED_DENY", codes=(401, 403),
          severity: str = "MEDIUM", confirmation_required: bool = False,
          step: dict | None = None, iface_method: str = "POST"):
    """一次搭好「项目 + 出站白名单 + 环境 + 接口 + 基线用例 + 规则 + 安全用例」。

    返回的 scene 上带 project_id / iface / baseline / sec_case / extension /
    rule / strategy / env / admin_id。``port`` 为 None 时不写白名单
    （环境闸门类用例发不出请求，本来也不需要）。
    """
    project_id = _new_project(db, api, admin)
    admin_id = _admin_id(db)

    if port is not None:
        _whitelist(db, project_id, port, admin_id, is_production=is_production_target)
    if allow_staging:
        db.add(SecurityProjectSetting(project_id=project_id, allow_staging=True))

    iface = _make_iface(db, project_id, method=iface_method)
    baseline = _make_case(
        db, project_id, admin_id, api_id=iface.id,
        name=unique("baseline"), steps=[step or _auth_step()],
    )
    strategy, rule = _make_rule(
        db, project_id, mutation_type=mutation_type, target_location=target_location,
        target_field=target_field, mutation_config=mutation_config, expected=expected,
        codes=codes, severity=severity, confirmation_required=confirmation_required,
    )
    sec_case = _security_test_case(db, project_id, admin_id, api_id=iface.id)
    extension = _make_security_case(
        db, project_id, test_case=sec_case, baseline_case=baseline, rule=rule,
        confirmation_required=confirmation_required,
    )
    env = _env(db, admin_id, name=env_name, base_url=env_base_url)

    db.commit()
    return SimpleNamespace(
        project_id=project_id, admin_id=admin_id, iface=iface, baseline=baseline,
        sec_case=sec_case, extension=extension, rule=rule, strategy=strategy, env=env,
    )


def _make_security_case(db, project_id: int, *, test_case: TestCase,
                        baseline_case: TestCase, rule: SecurityMutationRule,
                        api_id: int | None = None,
                        confirmation_required: bool = False,
                        confirmed: bool = False, confirmed_by: int | None = None) -> SecurityCase:
    """安全用例的扩展行。只留 ``baseline_case_id`` 引用，不复制 step。"""
    row = SecurityCase(
        project_id=project_id, test_case_id=test_case.id,
        baseline_case_id=baseline_case.id, strategy_id=rule.strategy_id, rule_id=rule.id,
        api_id=api_id if api_id is not None else test_case.api_id,
        mutation_type=rule.mutation_type,
        mutation_config=dict(rule.mutation_config or {}),
        security_expectation=rule.expected_security_behavior, risk_level=rule.severity,
        confirmation_required=confirmation_required,
        confirmed_by=None if confirmed_by is None else confirmed_by,
        confirmed_at=datetime.now() if confirmed else None,
    )
    db.add(row)
    db.flush()
    return row


def _security_test_case(db, project_id: int, admin_id: int, *, api_id: int) -> TestCase:
    """安全用例本体：``case_type='SECURITY'``，请求配置执行时从基线用例读。"""
    return _make_case(
        db, project_id, admin_id, api_id=api_id,
        name=unique("sec-case"), case_type="SECURITY",
    )


def _make_run(db, project_id: int, test_case_id: int, admin_id: int) -> tuple[TestRun, CaseExecution]:
    """安全执行记录要求挂在真实 TestRun / CaseExecution 上（§4.6 的 NOT NULL）。"""
    run = TestRun(project_id=project_id, status="RUNNING", created_by=admin_id)
    db.add(run)
    db.flush()
    case_execution = CaseExecution(
        test_run_id=run.id, test_case_id=test_case_id, status="RUNNING",
    )
    db.add(case_execution)
    db.flush()
    return run, case_execution


def _run_security(db, sec_case: TestCase, env: Environment, actor: User):
    """执行一次安全用例并提交，返回 CaseExecutionResult。"""
    run, case_execution = _make_run(db, sec_case.project_id, sec_case.id, _admin_id(db))
    result = runner.run_security_case(
        db, sec_case, environment=env, actor=actor,
        run_id=run.id, case_execution_id=case_execution.id,
    )
    db.commit()
    return result


def _execution(db, execution_id: int) -> SecurityExecution:
    """按执行标识查询安全执行记录。"""
    return db.get(SecurityExecution, execution_id)


def _findings(db, project_id: int) -> list[SecurityFinding]:
    """查询项目下的安全发现项。"""
    return db.query(SecurityFinding).filter(SecurityFinding.project_id == project_id).all()


def _new_finding(db, project_id: int, created_by: int, fingerprint_prefix: str,
                 *, severity: str = "HIGH", status: str = "OPEN") -> SecurityFinding:
    """创建安全发现项测试数据。"""
    return SecurityFinding(
        project_id=project_id, mutation_type="REMOVE_TOKEN", severity=severity,
        status=status, title="越权访问任务详情",
        description="去掉鉴权头后请求仍然成功",
        fingerprint=(fingerprint_prefix * 64)[:64], created_by=created_by,
    )


# --------------------------------------------------------------------------- 环境闸门


class TestEnvironmentGate:
    """拒绝发生在任何出站之前，基线请求同样不发。"""

    def test_production_environment_skips_without_request(self, db, api, admin, monkeypatch):
        """验证生产环境环境`skips`不带请求场景及其预期结果。"""
        scene = _seed(
            db, api, admin, port=None, env_name="prod",
            env_base_url="http://127.0.0.1:9",
        )

        outbound_calls: list[dict] = []

        def _explode(self, db_, **kwargs):
            """模拟执行器异常并记录传入参数。"""
            outbound_calls.append(kwargs)
            return SimpleNamespace(
                status_code=200, response_body="{}", response_headers={},
                response_time_ms=1, request_url="", error_message=None,
            )

        monkeypatch.setattr(
            "app.features.business.executors.api_executor.ApiRequestExecutor.execute",
            _explode,
        )

        result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert result.status == "SKIPPED"
        assert result.error_code == "SECURITY_PRODUCTION_FORBIDDEN"
        assert result.context_json["security_result"] == "SKIPPED"
        assert outbound_calls == []

        execution = _execution(db, result.context_json["security_execution_id"])
        assert execution.error_code == "SECURITY_PRODUCTION_FORBIDDEN"
        assert execution.baseline_status is None
        assert execution.actual_status_codes == []

    def test_dev_name_with_production_outbound_target_is_blocked(self, db, api, admin):
        """验证开发环境名称包含生产环境`outbound`目标是否被拦截场景及其预期结果。"""
        with CountingStub() as stub:
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"id": 1}})
            scene = _seed(
                db, api, admin, port=stub.port, env_name="dev",
                env_base_url=stub.base_url, is_production_target=True,
            )

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert result.status == "SKIPPED"
        assert result.error_code == "SECURITY_PRODUCTION_FORBIDDEN"
        assert stub.hits == []

    def test_unknown_environment_name_defaults_to_staging_and_is_denied(self, db, api, admin):
        """验证未知环境名称`defaults`到预发环境和是否被拒绝场景及其预期结果。"""
        with CountingStub() as stub:
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"id": 1}})
            scene = _seed(
                db, api, admin, port=stub.port, env_name="weird-qa",
                env_base_url=stub.base_url,
            )

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert result.status == "SKIPPED"
        assert result.error_code == "SECURITY_TARGET_NOT_ALLOWED"
        assert stub.hits == []

    def test_allow_staging_unlocks_unknown_environment(self, db, api, admin):
        """验证`allow`预发环境`unlocks`未知环境场景及其预期结果。"""
        with CountingStub() as stub:
            scene = _seed(
                db, api, admin, port=stub.port, env_name="weird-qa",
                env_base_url=stub.base_url, allow_staging=True,
            )

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        # 没被闸门挡住：真的发了基线请求（stub 没这条路由 → 404，因此 INCONCLUSIVE）。
        assert result.error_code == "SECURITY_BASELINE_FAILED"
        assert result.context_json["security_result"] == "INCONCLUSIVE"
        assert len(stub.hits) == 1

    def test_high_risk_unconfirmed_skips_without_request(self, db, api, admin):
        """验证高风险风险`unconfirmed``skips`不带请求场景及其预期结果。"""
        with CountingStub() as stub:
            scene = _seed(
                db, api, admin, port=stub.port, env_name="dev",
                env_base_url=stub.base_url,
                mutation_type="REPLAY_SAME_REQUEST",
                target_location="BODY", target_field=None,
                mutation_config={"replay_count": 2},
                expected="EXPECTED_IDEMPOTENT", confirmation_required=True,
            )

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert result.status == "SKIPPED"
        assert result.error_code == "SECURITY_CONFIRMATION_REQUIRED"
        assert stub.hits == []


# --------------------------------------------------------------------------- 基线与变异


class TestBaselineAndMutation:
    """基线结论、变异判定与 Finding 生成。"""

    def test_baseline_5xx_is_inconclusive_and_sends_no_mutation(self, db, api, admin):
        """验证基线`xx`是否`inconclusive`和`sends`无变异场景及其预期结果。"""
        with CountingStub() as stub:
            stub.add("POST", "/tasks", 500, {"code": 500, "message": "boom"})
            scene = _seed(
                db, api, admin, port=stub.port, env_name="dev",
                env_base_url=stub.base_url,
            )

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        # 只发了一次基线请求，变异一次都没发。
        assert len(stub.hits) == 1
        assert result.status == "SKIPPED"
        assert result.context_json["security_result"] == "INCONCLUSIVE"
        assert result.error_code == "SECURITY_BASELINE_FAILED"

        execution = _execution(db, result.context_json["security_execution_id"])
        assert execution.baseline_status == "FAILED"
        assert execution.baseline_http_status == 500
        assert execution.actual_status_codes == []
        assert _findings(db, scene.project_id) == []

    def test_remove_token_200_becomes_potential_issue_with_high_finding(self, db, api, admin):
        """验证移除令牌`becomes``potential``issue`包含高风险发现项场景及其预期结果。"""
        hits: list[str] = []
        with CountingStub() as stub:
            _route_by_auth(stub, denied_status=200, denied_body={"code": 0, "data": {"id": 101}},
                           hit_sink=hits)
            scene = _seed(
                db, api, admin, port=stub.port, env_name="dev",
                env_base_url=stub.base_url,
            )

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert hits == ["baseline", "mutation"]
        assert result.status == "FAILED"
        assert result.context_json["security_result"] == "POTENTIAL_ISSUE"

        execution = _execution(db, result.context_json["security_execution_id"])
        assert execution.baseline_status == "PASSED"
        assert execution.baseline_http_status == 200
        assert execution.actual_status_codes == [200]
        assert execution.replay_count == 1
        # trace 必须脱敏：before / after 都不许出现原始 token。
        assert _TOKEN not in str(execution.mutation_trace)

        findings = _findings(db, scene.project_id)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.severity == "HIGH"
        assert finding.status == "OPEN"
        assert finding.mutation_type == "REMOVE_TOKEN"
        assert finding.bug_id is None
        assert _TOKEN not in str(finding.evidence)

    def test_remove_token_401_passes_without_finding(self, db, api, admin):
        """验证移除令牌`passes`不带发现项场景及其预期结果。"""
        hits: list[str] = []
        with CountingStub() as stub:
            _route_by_auth(stub, denied_status=401, denied_body={"code": 401}, hit_sink=hits)
            scene = _seed(
                db, api, admin, port=stub.port, env_name="dev",
                env_base_url=stub.base_url,
            )

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert hits == ["baseline", "mutation"]
        assert result.status == "PASSED"
        assert result.context_json["security_result"] == "PASS"
        assert result.context_json["security_classification"] == "EXPECTED_DENY_MET"
        assert _findings(db, scene.project_id) == []

    def test_remove_token_server_error_becomes_medium_finding(self, db, api, admin):
        """验证移除令牌服务端错误`becomes`中风险发现项场景及其预期结果。"""
        with CountingStub() as stub:
            _route_by_auth(stub, denied_status=500, denied_body={"code": 500}, hit_sink=[])
            scene = _seed(
                db, api, admin, port=stub.port, env_name="dev",
                env_base_url=stub.base_url,
            )

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert result.context_json["security_result"] == "POTENTIAL_ISSUE"
        assert result.context_json["security_classification"] == "UNEXPECTED_SERVER_ERROR"
        findings = _findings(db, scene.project_id)
        assert len(findings) == 1
        assert findings[0].severity == "MEDIUM"

    def test_same_fingerprint_twice_keeps_one_open_with_repeat_count(self, db, api, admin):
        """验证相同`fingerprint``twice``keeps``one`打开包含`repeat`统计场景及其预期结果。"""
        with CountingStub() as stub:
            _route_by_auth(stub, denied_status=200, denied_body={"code": 0, "data": {"id": 1}},
                           hit_sink=[])
            scene = _seed(
                db, api, admin, port=stub.port, env_name="dev",
                env_base_url=stub.base_url,
            )

            first = _run_security(db, scene.sec_case, scene.env, _actor(db))
            second = _run_security(db, scene.sec_case, scene.env, _actor(db))

        findings = _findings(db, scene.project_id)
        assert len(findings) == 1
        assert findings[0].status == "OPEN"
        assert (findings[0].evidence or {}).get("repeat_count") == 2
        assert findings[0].security_execution_id == second.context_json["security_execution_id"]
        assert first.context_json["security_execution_id"] != second.context_json[
            "security_execution_id"
        ]

    def test_false_positive_rerun_opens_a_new_finding_with_prior_status(self, db, api, admin):
        """验证`false``positive``rerun``opens``a``new`发现项包含`prior`状态场景及其预期结果。"""
        with CountingStub() as stub:
            _route_by_auth(stub, denied_status=200, denied_body={"code": 0, "data": {"id": 1}},
                           hit_sink=[])
            scene = _seed(
                db, api, admin, port=stub.port, env_name="dev",
                env_base_url=stub.base_url,
            )

            _run_security(db, scene.sec_case, scene.env, _actor(db))
            for row in db.query(SecurityFinding).filter(
                SecurityFinding.project_id == scene.project_id,
            ).all():
                row.status = "FALSE_POSITIVE"
            db.commit()

            second = _run_security(db, scene.sec_case, scene.env, _actor(db))

        findings = sorted(_findings(db, scene.project_id), key=lambda row: row.id)
        assert len(findings) == 2
        assert findings[0].status == "FALSE_POSITIVE"
        assert findings[1].status == "OPEN"
        assert (findings[1].evidence or {}).get("prior_status") == "FALSE_POSITIVE"
        assert findings[1].security_execution_id == second.context_json["security_execution_id"]


def _route_by_auth(stub, *, denied_status: int, denied_body: dict, hit_sink: list) -> None:
    """按是否带 Authorization 分流：带 = 基线（200），不带 = 变异请求。"""

    def respond(handler, body):
        """生成响应对应数据。"""
        hit_sink.append("baseline" if handler.headers.get("Authorization") else "mutation")
        if handler.headers.get("Authorization"):
            return 200, {"code": 0, "data": {"id": 101, "name": "任务A"}}
        return denied_status, denied_body

    stub.exact[("POST", "/tasks")] = respond


# --------------------------------------------------------------------------- 重放


class TestReplay:
    """DUPLICATE_SUBMIT：不改请求体，只重复提交。"""

    def _seed_duplicate_submit(self, db, api, admin, stub, responder):
        """构造重复提交接口的模拟响应和安全测试场景。"""
        stub.exact[("POST", "/tasks")] = responder
        scene = _seed(
            db, api, admin, port=stub.port, env_name="dev",
            env_base_url=stub.base_url,
            mutation_type="DUPLICATE_SUBMIT",
            target_location="BODY", target_field=None,
            mutation_config={"replay_count": 2},
            expected="EXPECTED_IDEMPOTENT",
            step={"body": {"name": "任务A"}},
        )
        return scene

    def test_duplicate_submit_second_response_409_passes(self, db, api, admin):
        """验证重复`submit``second`响应`passes`场景及其预期结果。"""
        counter = {"n": 0}

        def respond(handler, body):
            """生成响应对应数据。"""
            counter["n"] += 1
            if counter["n"] == 1:
                return 200, {"code": 0, "data": {"name": "任务A"}}
            if counter["n"] == 2:
                return 201, {"code": 0, "data": {"id": 9001}}
            return 409, {"code": 409, "message": "duplicate"}

        with CountingStub() as stub:
            scene = self._seed_duplicate_submit(db, api, admin, stub, respond)

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert result.status == "PASSED"
        assert result.context_json["security_result"] == "PASS"
        assert result.context_json["security_classification"] == "EXPECTED_IDEMPOTENT_MET"
        assert counter["n"] == 3  # 1 次基线 + 2 次重放
        execution = _execution(db, result.context_json["security_execution_id"])
        assert execution.replay_count == 2
        assert _findings(db, scene.project_id) == []

    def test_duplicate_submit_two_2xx_with_different_ids_records_high(self, db, api, admin):
        """验证重复`submit``two``xx`包含`different``ids`记录高风险场景及其预期结果。"""
        counter = {"n": 0}

        def respond(handler, body):
            """生成响应对应数据。"""
            counter["n"] += 1
            if counter["n"] == 1:
                return 200, {"code": 0, "data": {"name": "任务A"}}
            return 201, {"code": 0, "data": {"id": 9001 if counter["n"] == 2 else 9002}}

        with CountingStub() as stub:
            scene = self._seed_duplicate_submit(db, api, admin, stub, respond)

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert result.status == "FAILED"
        assert result.context_json["security_result"] == "POTENTIAL_ISSUE"
        execution = _execution(db, result.context_json["security_execution_id"])
        assert execution.replay_count == 2
        findings = _findings(db, scene.project_id)
        assert len(findings) == 1
        assert findings[0].severity == "HIGH"


# --------------------------------------------------------------------------- 业务流程型变异


class TestBusinessFlowSkip:
    """BUSINESS_STATE 依赖终态数据与步骤语义，第一阶段执行时必须记 SKIPPED。"""

    def test_business_flow_mutation_type_is_skipped_not_blind_http(self, db, api, admin):
        """验证业务流程变异类型是否跳过不`blind`HTTP场景及其预期结果。"""
        with CountingStub() as stub:
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"id": 1}})
            scene = _seed(
                db, api, admin, port=stub.port, env_name="dev",
                env_base_url=stub.base_url,
                mutation_type="BUSINESS_STATE",
                target_location="BODY", target_field=None,
            )

            result = _run_security(db, scene.sec_case, scene.env, _actor(db))

        assert result.status == "SKIPPED"
        assert result.context_json["security_result"] == "SKIPPED"
        assert result.error_code == "SECURITY_MUTATION_NOT_ALLOWED"
        # 只发了基线，没有退化成盲发变异请求。
        assert len(stub.hits) == 1
        execution = _execution(db, result.context_json["security_execution_id"])
        assert execution.baseline_status == "PASSED"
        assert execution.actual_status_codes == []


# --------------------------------------------------------------------------- 计划落成用例


class TestPlanning:
    """plan confirm 生成的用例形态与 §20.2 的用例约束。"""

    def test_confirm_creates_security_case_referencing_baseline(self, db, api, admin):
        """验证确认`creates`安全用例`referencing`基线场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        admin_id = _admin_id(db)
        iface = _make_iface(db, project_id)
        baseline = _make_case(
            db, project_id, admin_id, api_id=iface.id, name=unique("baseline"),
            steps=[{"headers": {"Authorization": "Bearer x"},
                    "body": {"name": "任务A", "secret": "step-config"}}],
        )
        strategy, _rule = _make_rule(
            db, project_id, expected="EXPECTED_DENY", codes=(401, 403),
            severity="HIGH", confirmation_required=True,
        )
        db.commit()

        preview = PlanService.preview(
            db, project_id,
            PlanPreviewRequest(baseline_case_id=baseline.id, strategy_ids=[strategy.id]),
            actor=_actor(db),
        )
        assert preview.status == "DRAFT"
        assert preview.estimated_count >= 1
        item = preview.items[0]
        assert item.mutation_type == "REMOVE_TOKEN"
        assert item.confirmation_required is True

        confirmed = PlanService.confirm(
            db, preview.plan_id,
            PlanConfirmRequest(accepted_item_indexes=[item.index]),
            actor=_actor(db),
        )
        assert confirmed.created_count == 1
        assert confirmed.status == "CONFIRMED"

        created = db.get(TestCase, confirmed.created_case_ids[0])
        assert created.case_type == "SECURITY"
        assert created.target_type == "API"
        # 不把 step 文本复制成第二份事实来源。
        assert "step-config" not in str(created.description or "")

        extension = db.query(SecurityCase).filter(
            SecurityCase.test_case_id == created.id,
        ).one()
        # 基线引用指向原用例。
        assert extension.baseline_case_id == baseline.id
        assert extension.confirmation_required is True
        assert db.query(TestStep).filter(TestStep.test_case_id == created.id).all() == []

    def test_preview_requires_exactly_one_target(self, db, api, admin):
        """验证预览需要`exactly``one`目标场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        strategy, _rule = _make_rule(db, project_id)
        db.commit()

        with pytest.raises(Exception) as excinfo:
            PlanService.preview(
                db, project_id,
                PlanPreviewRequest(strategy_ids=[strategy.id]),
                actor=_actor(db),
            )
        assert excinfo.value.status_code == 400

    def test_preview_confirmed_twice_is_rejected(self, db, api, admin):
        """验证预览`confirmed``twice`是否被拒绝场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        admin_id = _admin_id(db)
        iface = _make_iface(db, project_id)
        baseline = _make_case(db, project_id, admin_id, api_id=iface.id, name=unique("baseline"))
        strategy, _rule = _make_rule(db, project_id)
        db.commit()

        preview = PlanService.preview(
            db, project_id,
            PlanPreviewRequest(baseline_case_id=baseline.id, strategy_ids=[strategy.id]),
            actor=_actor(db),
        )
        assert PlanService.confirm(
            db, preview.plan_id,
            PlanConfirmRequest(accepted_item_indexes=[preview.items[0].index]),
            actor=_actor(db),
        ).status == "CONFIRMED"

        with pytest.raises(Exception) as excinfo:
            PlanService.confirm(
                db, preview.plan_id,
                PlanConfirmRequest(accepted_item_indexes=[preview.items[0].index]),
                actor=_actor(db),
            )
        assert excinfo.value.code == "SECURITY_PLAN_STATE_INVALID"


# --------------------------------------------------------------------------- §16.2 接口 API 接口


class TestSecurityApi:
    """§16.2 的路由层行为。"""

    def _seed(self, db, project_id, *, mutation_type: str = "REMOVE_TOKEN",
              confirmation_required: bool = False):
        """构造安全执行测试场景及其关联数据。"""
        admin_id = _admin_id(db)
        iface = _make_iface(db, project_id)
        baseline = _make_case(
            db, project_id, admin_id, api_id=iface.id, name=unique("baseline"),
            steps=[_auth_step()],
        )
        _strategy, rule = _make_rule(
            db, project_id, mutation_type=mutation_type,
            confirmation_required=confirmation_required,
        )
        sec_case = _security_test_case(db, project_id, admin_id, api_id=iface.id)
        extension = _make_security_case(
            db, project_id, test_case=sec_case, baseline_case=baseline, rule=rule,
            confirmation_required=confirmation_required,
        )
        db.commit()
        return iface, baseline, sec_case, extension

    def test_list_and_patch_enabled_syncs_test_case(self, db, api, admin):
        """验证列出和局部更新启用状态`syncs`测试用例场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        _iface, _baseline, _sec, extension = self._seed(db, project_id)

        response = api.get(f"/projects/{project_id}/security-cases", username=admin)
        assert response.status_code == 200, response.text
        assert any(item["id"] == extension.id for item in response.json()["items"])

        response = api.patch(
            f"/security-cases/{extension.id}", username=admin, json={"enabled": False},
        )
        assert response.status_code == 200, response.text
        # 接口在自己的会话里改的，先把本会话的缓存丢掉再看库里的真实值。
        db.expire_all()
        assert db.get(TestCase, extension.test_case_id).enabled is False

        response = api.get(f"/security-cases/{extension.id}", username=admin)
        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert response.json()["baseline_case_name"]

    def test_confirm_risk_records_actor_and_blocks_repeat(self, db, api, admin):
        """验证确认风险记录`actor`和`blocks``repeat`场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        _iface, _baseline, _sec, extension = self._seed(
            db, project_id, confirmation_required=True,
        )

        response = api.post(f"/security-cases/{extension.id}/confirm-risk", username=admin)
        assert response.status_code == 200, response.text
        assert response.json()["confirmed_by"] is not None
        assert response.json()["confirmed_at"] is not None

        assert api.post(
            f"/security-cases/{extension.id}/confirm-risk", username=admin,
        ).status_code == 400

    def test_confirm_risk_refuses_case_that_needs_no_confirmation(self, db, api, admin):
        """验证确认风险`refuses`用例`that``needs`无`confirmation`场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        _iface, _baseline, _sec, extension = self._seed(db, project_id)
        assert api.post(
            f"/security-cases/{extension.id}/confirm-risk", username=admin,
        ).status_code == 400

    def test_security_runs_reuses_run_service(self, db, api, admin):
        """验证安全`runs``reuses`运行服务场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        admin_id = _admin_id(db)
        _iface, _baseline, _sec, extension = self._seed(db, project_id)

        with CountingStub() as stub:
            _route_by_auth(stub, denied_status=401, denied_body={"code": 401}, hit_sink=[])
            env = _env(db, admin_id, name="dev", base_url=stub.base_url)
            from tests.test_19_data_factory import _bind_env
            _bind_env(db, project_id, env.id)
            _whitelist(db, project_id, stub.port, admin_id)
            db.commit()

            response = api.post(
                f"/projects/{project_id}/security-runs", username=admin,
                json={
                    "security_case_ids": [extension.id],
                    "environment_id": env.id,
                    "plan_name": "回归前安全冒烟",
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()

        assert payload["total"] == 1
        assert payload["status"] == "SUCCESS"
        case_rows = db.query(CaseExecution).filter(CaseExecution.test_run_id == payload["id"]).all()
        rows = db.query(SecurityExecution).filter(SecurityExecution.test_run_id == payload["id"]).all()
        assert payload["passed"] == 1, ([(r.status, r.error_code, r.error_message) for r in case_rows], [r.evidence for r in rows])
        assert stub.hits == [("POST", "/tasks"), ("POST", "/tasks")]

        execution = db.query(SecurityExecution).filter(
            SecurityExecution.project_id == project_id,
        ).order_by(SecurityExecution.id.desc()).first()
        assert execution is not None
        assert execution.test_run_id == payload["id"]
        assert execution.security_result == "PASS"

        response = api.get(f"/security-executions/{execution.id}", username=admin)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["security_result"] == "PASS"
        assert body["baseline_http_status"] == 200
        assert body["baseline_status"] == "PASSED"

    def test_security_runs_refuses_unknown_or_disabled_cases(self, db, api, admin):
        """验证安全`runs``refuses`未知或`disabled``cases`场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        admin_id = _admin_id(db)
        with CountingStub() as stub:
            env = _env(db, admin_id, name="dev", base_url=stub.base_url)
            db.commit()
            response = api.post(
                f"/projects/{project_id}/security-runs", username=admin,
                json={"security_case_ids": [999999], "environment_id": env.id},
            )
        assert response.status_code == 400

    def test_member_cannot_run_security_cases(self, db, api, admin):
        """验证成员不能运行安全`cases`场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        admin_id = _admin_id(db)
        viewer = _register_member(api, admin, project_id, role="viewer")
        with CountingStub() as stub:
            env = _env(db, admin_id, name="dev", base_url=stub.base_url)
            db.commit()
            response = api.post(
                f"/projects/{project_id}/security-runs", username=viewer,
                json={"security_case_ids": [1], "environment_id": env.id},
            )
        # 项目可见但角色不足：403，不是 404。
        assert response.status_code == 403

    def test_finding_status_transition_matrix(self, db, api, admin):
        """验证发现项状态`transition``matrix`场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        finding = _new_finding(db, project_id, _admin_id(db), "f")
        db.add(finding)
        db.commit()
        db.refresh(finding)

        def patch(status: str) -> int:
            """更新对应数据。"""
            return api.patch(
                f"/security-findings/{finding.id}", username=admin, json={"status": status},
            ).status_code

        assert patch("CONFIRMED") == 200
        assert patch("RESOLVED") == 200
        # 关闭态只能回到 OPEN，不能直接跳到别的关闭态。
        assert patch("FALSE_POSITIVE") == 400
        assert patch("OPEN") == 200
        assert patch("CONFIRMED") == 200
        assert patch("OPEN") == 400
        # CONFIRMED 只能去 RESOLVED / FALSE_POSITIVE。
        assert patch("CONFIRMED") == 200
        assert patch("OPEN") == 400

        # 未知状态由 schema 层拦住。
        assert api.patch(
            f"/security-findings/{finding.id}", username=admin, json={"status": "DONE"},
        ).status_code == 422

    def test_resolve_writes_resolved_by(self, db, api, admin):
        """验证解析并确定`writes``resolved`按场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        finding = _new_finding(db, project_id, _admin_id(db), "r")
        db.add(finding)
        db.commit()
        db.refresh(finding)

        response = api.patch(
            f"/security-findings/{finding.id}", username=admin, json={"status": "RESOLVED"},
        )
        assert response.status_code == 200
        assert response.json()["resolved_by"] == _admin_id(db)
        assert response.json()["status"] == "RESOLVED"

    def test_same_status_is_idempotent_no_op(self, db, api, admin):
        """验证相同状态是否幂等无`op`场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        finding = _new_finding(db, project_id, _admin_id(db), "s")
        db.add(finding)
        db.commit()
        db.refresh(finding)

        response = api.patch(
            f"/security-findings/{finding.id}", username=admin, json={"status": "OPEN"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "OPEN"

    def test_finding_permissions(self, db, api, admin):
        """验证发现项权限场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        finding = _new_finding(db, project_id, _admin_id(db), "p")
        db.add(finding)
        db.commit()
        db.refresh(finding)

        viewer = _register_member(api, admin, project_id, role="viewer")
        member = _register_member(api, admin, project_id, role="member")
        editor = _register_member(api, admin, project_id, role="editor")

        # 读：viewer 可以。
        assert api.get(f"/security-findings/{finding.id}", username=viewer).status_code == 200
        # 写：member 与 viewer 都 403，editor 可以。
        assert api.patch(
            f"/security-findings/{finding.id}", username=viewer, json={"status": "CONFIRMED"},
        ).status_code == 403
        assert api.patch(
            f"/security-findings/{finding.id}", username=member, json={"status": "CONFIRMED"},
        ).status_code == 403
        assert api.patch(
            f"/security-findings/{finding.id}", username=editor, json={"status": "CONFIRMED"},
        ).status_code == 200

    def test_other_project_cannot_read_finding_or_execution(self, db, api, admin):
        """验证其他项目不能读取发现项或执行记录场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        other = _new_project(db, api, admin)
        admin_id = _admin_id(db)

        iface = _make_iface(db, project_id)
        baseline = _make_case(db, project_id, admin_id, api_id=iface.id, name=unique("baseline"))
        _strategy, rule = _make_rule(db, project_id)
        sec_case = _security_test_case(db, project_id, admin_id, api_id=iface.id)
        extension = _make_security_case(
            db, project_id, test_case=sec_case, baseline_case=baseline, rule=rule,
        )

        finding = _new_finding(db, project_id, admin_id, "q")
        db.add(finding)

        run, case_execution = _make_run(db, project_id, sec_case.id, admin_id)
        execution = SecurityExecution(
            project_id=project_id, test_run_id=run.id,
            case_execution_id=case_execution.id, security_case_id=extension.id,
            security_result="PASS", classification="EXPECTED_DENY_MET", replay_count=1,
        )
        db.add(execution)
        db.commit()
        db.refresh(finding)
        db.refresh(execution)

        outsider = _register_member(api, admin, other, role="member")
        assert api.get(f"/security-findings/{finding.id}", username=outsider).status_code == 404
        assert api.get(f"/security-executions/{execution.id}", username=outsider).status_code == 404

    def test_findings_list_filters(self, db, api, admin):
        """验证`findings`列出`filters`场景及其预期结果。"""
        project_id = _new_project(db, api, admin)
        admin_id = _admin_id(db)
        db.add(_new_finding(db, project_id, admin_id, "w", severity="HIGH", status="OPEN"))
        db.add(_new_finding(db, project_id, admin_id, "x", severity="MEDIUM", status="RESOLVED"))
        db.commit()

        response = api.get(
            f"/projects/{project_id}/security-findings", username=admin,
            params={"severity": "HIGH", "status": "OPEN"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["severity"] == "HIGH"
        assert items[0]["status"] == "OPEN"
