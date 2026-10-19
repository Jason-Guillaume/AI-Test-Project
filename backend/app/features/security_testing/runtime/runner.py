"""安全用例执行器：现有生命周期里唯一的「安全分支」。

Runner 顺序固定（开发计划 §21 Phase E）：

1. 读 ``security_case``。没有则返回 None，调用方退回原有执行器，非安全用例零改动。
2. 环境闸门。生产环境直接 SKIPPED，不构造请求、不发请求。
3. 确认闸门。高风险未确认则 SKIPPED，不发请求。
4. 用基线用例的 step / data / fixture 输出组装 ``BaselineRequest``。
5. 执行基线。基线不是 2xx 直接 INCONCLUSIVE，**之后不再发任何变异请求**。
6. ``SecurityMutationEngine.apply``。
7. ``ApiRequestExecutor.execute``；重放类型重复 2～3 次。
8. 安全断言。
9. 写 ``security_execution``，并映射成既有四态 ``CaseExecutionResult``。
10. 需要时 upsert Finding（同 fingerprint 只保留一条 OPEN）。

本模块是 §6.3 的唯一例外：整个 runtime 目录里只有这里查库、import 执行器。
变异、断言、严重级别本身仍然是纯函数。

Runner 不自己 cleanup：Fixture 与 Mock 由 ``RunService`` 在调用 executor 前后处理，
本函数只是把「一次用例执行」换成安全语义。commit 也交给 RunService 统一做。
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.features.business.executors.api_executor import ApiRequestExecutor
from app.features.security_testing.models import (
    SecurityCase,
    SecurityExecution,
    SecurityFinding,
    SecurityMutationRule,
    SecurityProjectSetting,
)
from app.features.security_testing.runtime.baseline import EnvironmentDecision
from app.features.test_data.security.db_guard import classify as classify_environment
from app.features.security_testing.runtime import baseline as baseline_mod
from app.features.security_testing.runtime import assertion as assertion_mod
from app.features.security_testing.runtime import candidate_resolver
from app.features.security_testing.runtime import replay as replay_mod, severity as severity_mod, trace as trace_mod
from app.features.security_testing.runtime.mutation_engine import SecurityMutationEngine
from app.features.security_testing.runtime.types import (
    ConfirmationRequiredError,
    MutationRuleView,
    MutationTraceEntry,
    ResolveScope,
    RuleNotApplicableError,
)
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.business.models.business_binding import BusinessBinding
from app.features.test_management.executors import test_case_executor as tce
from app.features.test_management.models.test_case import TestCase
from app.models.configuration import Environment
from app.models.identity import User
from app.models.project import ProjectOutboundTarget
from app.shared.errors import (
    CODE_SECURITY_BASELINE_FAILED,
    CODE_SECURITY_CONFIRMATION_REQUIRED,
    CODE_SECURITY_EXECUTION_FAILED,
    CODE_SECURITY_MUTATION_NOT_ALLOWED,
    CODE_SECURITY_PRODUCTION_FORBIDDEN,
    CODE_SECURITY_TARGET_NOT_ALLOWED,
    AppError,
)

__all__ = ["run_security_case"]

_EXECUTOR = ApiRequestExecutor()

#: 安全结论 → 既有 case_execution.status（与 schemas.SECURITY_RESULT_TO_CASE_STATUS 同值；
#: 就近定义，让 runner 不依赖接口层 schema）。
_CASE_STATUS_BY_RESULT = {
    "PASS": "PASSED",
    "POTENTIAL_ISSUE": "FAILED",
    "FAILED_EXECUTION": "ERROR",
    "INCONCLUSIVE": "SKIPPED",
    "SKIPPED": "SKIPPED",
}

#: 不改动请求、只按 replay_count 重复提交的类型。
REPLAY_FAMILY = ("REPLAY_SAME_REQUEST", "DUPLICATE_SUBMIT")
#: 需要业务流程语义（终态数据 / 步骤跳序）的类型：Phase 1 只生成计划与用例，
#: 不自建业务执行器，执行时记 SKIPPED，绝不退化成盲发 HTTP 请求。
BUSINESS_FLOW_FAMILY = ("BUSINESS_STATE", "SEQUENCE_BYPASS")

#: 基线必须落在这个分段里才允许继续变异；否则基线本身没跑通，结论不可信。
_BASELINE_OK_MIN = 200
_BASELINE_OK_MAX = 300

_AUTH_HEADER_KEY = "authorization"


# --------------------------------------------------------------------------- 读取


def _load_security_case(db: Session, test_case: TestCase) -> SecurityCase | None:
    """按 test_case_id 取安全扩展行；没有就是普通用例。"""
    if not test_case or not test_case.id:
        return None
    return db.query(SecurityCase).filter(SecurityCase.test_case_id == test_case.id).one_or_none()


def _resolve_api(
    db: Session,
    security_case: SecurityCase,
    baseline_case: TestCase | None,
) -> tuple[int | None, ApiInterface | None]:
    """定出要变异的目标接口。

    优先级：``security_case.api_id`` → 基线用例的 ``api_id`` → 业务动作绑定到的接口。
    三条都拿不到返回 ``(None, None)``，由调用方记 TARGET_BLOCKED。
    """
    api_id = security_case.api_id
    if api_id is None and baseline_case is not None:
        api_id = baseline_case.api_id
    if api_id is None and security_case.business_action_id is not None:
        binding = (
            db.query(BusinessBinding)
            .filter(BusinessBinding.business_action_id == security_case.business_action_id)
            .order_by(BusinessBinding.id.asc())
            .first()
        )
        api_id = getattr(binding, "api_id", None) if binding is not None else None
    if api_id is None:
        return None, None
    return api_id, db.get(ApiInterface, api_id)


def _outbound_is_production(
    db: Session, project_id: int | None, environment: Environment
) -> bool:
    """环境 base_url 指向的出站目标是否被登记为生产目标。

    环境名写着 ``dev`` 但目标其实是生产网关时，只有白名单里那一行
    ``is_production=True`` 能拦住它（§20.2）。解析不出 scheme/host/port 时返回
    False——那种 base_url 本来也发不出请求。
    """
    base = (getattr(environment, "base_url", "") or "").strip()
    if not base or "://" not in base:
        return False
    scheme, rest = base.split("://", 1)
    hostport = rest.split("/", 1)[0]
    if ":" in hostport:
        host, port_text = hostport.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            return False
    else:
        host = hostport
        port = 443 if scheme.lower() == "https" else 80
    if not host or project_id is None:
        return False
    row = (
        db.query(ProjectOutboundTarget)
        .filter(
            ProjectOutboundTarget.project_id == project_id,
            ProjectOutboundTarget.scheme == scheme.lower(),
            ProjectOutboundTarget.host == host,
            ProjectOutboundTarget.port == port,
            ProjectOutboundTarget.enabled.is_(True),
        )
        .first()
    )
    return bool(getattr(row, "is_production", False)) if row is not None else False


def _environment_decision(
    db: Session, project_id: int | None, environment: Environment
) -> EnvironmentDecision:
    """按 §18.3 判定环境。

    归类由 ``db_guard.classify`` 给出（未知环境名归 STAGING），三个开关取项目设置，
    没有设置行时按默认值（DEV/TEST 开、STAGING 关）。生产与「指向生产目标的出站」
    永远拒绝，不看 ``allow_production``。
    """
    name = getattr(environment, "name", None)
    setting = (
        db.query(SecurityProjectSetting)
        .filter(SecurityProjectSetting.project_id == project_id)
        .first()
        if project_id is not None
        else None
    )
    return baseline_mod.decide_environment(
        name,
        classification=classify_environment(name),
        outbound_production=_outbound_is_production(db, project_id, environment),
        allow_dev=bool(getattr(setting, "allow_dev", True)) if setting is not None else True,
        allow_test=bool(getattr(setting, "allow_test", True)) if setting is not None else True,
        allow_staging=bool(getattr(setting, "allow_staging", False)) if setting is not None else False,
    )


#: 环境闸门拒绝原因 → 错误码。只有生产用专门的生产错误码。
_ENVIRONMENT_CODE_BY_REASON = {
    "PRODUCTION": CODE_SECURITY_PRODUCTION_FORBIDDEN,
}


def _environment_error_code(decision: EnvironmentDecision) -> str:
    return _ENVIRONMENT_CODE_BY_REASON.get(decision.reason, CODE_SECURITY_TARGET_NOT_ALLOWED)


def _environment_message(decision: EnvironmentDecision) -> str:
    """拒绝原因对应的中文提示；不透露白名单细节。"""
    return {
        "PRODUCTION": "生产环境禁止执行安全变异请求",
        "STAGING_NOT_ALLOWED": "预发环境默认禁止执行安全变异请求",
        "DEV_NOT_ALLOWED": "开发环境的安全变异请求已被项目设置关闭",
        "TEST_NOT_ALLOWED": "测试环境的安全变异请求已被项目设置关闭",
    }.get(decision.reason, "当前环境不允许执行安全变异请求")


def _load_fields(db: Session, api_id: int) -> list[Any]:
    """读接口的可变异字段 schema；读不到按「无字段规则」跑，不阻断执行。"""
    try:
        from app.features.api_catalog.models.api_parameter import ApiParameter
        from app.features.api_catalog.models.api_request_body import ApiRequestBody
        from app.features.security_testing.runtime import schema_reader

        # 这两张表的关联列都叫 interface_id（历史命名），不是 api_id。
        params = db.query(ApiParameter).filter(ApiParameter.interface_id == api_id).all()
        body_row = db.query(ApiRequestBody).filter(ApiRequestBody.interface_id == api_id).first()
        return list(schema_reader.read_fields(params, body_row))
    except Exception:  # noqa: BLE001 - 没有 schema 时参数类算子会自己按不适用跳过。
        return []


def _build_request(
    db: Session,
    case_id: int,
    iface: ApiInterface,
    environment: Environment,
    fixture_outputs: dict[str, dict[str, Any]],
    extra_headers: dict[str, str] | None,
) -> Any:
    """组装基线请求：变量解析、测试数据、step 配置全部复用现有执行器的实现。"""
    data_values, _overrides = tce._load_data_values(db, case_id, environment, fixture_outputs)
    scope = tce._scope(data_values, environment, fixture_outputs)
    step_config = tce._load_action_step_config(db, case_id)
    return baseline_mod.build_request(
        method=getattr(iface, "method", None),
        path=getattr(iface, "path", ""),
        step_config=step_config,
        scope=scope,
        resolve=tce._resolve_tokens,
        data_values=data_values,
        environment_headers=_EXECUTOR.get_environment_headers(environment),
        extra_headers=extra_headers,
        auth_type=getattr(iface, "auth_type", None),
        api_id=iface.id,
        project_id=getattr(iface, "project_id", None),
    )


def _run_baseline(
    db: Session,
    baseline_case: TestCase,
    environment: Environment,
    actor: User,
    fixture_outputs: dict[str, dict[str, Any]],
    extra_headers: dict[str, str] | None,
) -> Any:
    """执行基线用例本身；判定只看 HTTP 状态码分段，不看业务断言。"""
    target = str(getattr(baseline_case, "target_type", None) or "API").upper()
    if target == "BUSINESS_FLOW":
        return tce._execute_business_flow(db, baseline_case, environment, actor, fixture_outputs)
    if target == "BUSINESS_ACTION":
        return tce._execute_business_action(
            db, baseline_case, environment, actor, fixture_outputs, extra_headers
        )
    return tce._execute_api(db, baseline_case, environment, actor, fixture_outputs, extra_headers)


def _baseline_status_of(result: Any) -> int:
    """基线响应里的 HTTP 状态码；取不到是 0。"""
    snapshot = getattr(result, "response_snapshot", None) or {}
    return int(snapshot.get("status_code") or 0) if isinstance(snapshot, dict) else 0


def _baseline_conclusion_of(http_status: int | None) -> str | None:
    """基线 HTTP 状态码 → 落库的 ``PASSED/FAILED``；没打出去时为空。"""
    status = int(http_status or 0)
    if status == 0:
        return None
    return "PASSED" if _BASELINE_OK_MIN <= status < _BASELINE_OK_MAX else "FAILED"


def _rule_view(security_case: SecurityCase, rule: SecurityMutationRule | None, config: dict[str, Any]) -> MutationRuleView:
    """规则被删时退回到 security_case 上的快照，保证用例还能解释得通。"""
    if rule is not None:
        return MutationRuleView.from_row(rule)
    return MutationRuleView(
        mutation_type=str(security_case.mutation_type or ""),
        target_location=str(config.get("location") or ""),
        target_field=str(config.get("field") or "") or None,
        mutation_config=dict(config),
        expected_security_behavior=str(security_case.security_expectation or "EXPECTED_DENY"),
        expected_status_codes=config.get("expected_status_codes"),
        severity=str(security_case.risk_level or "MEDIUM"),
        confirmation_required=bool(security_case.confirmation_required),
    )


# --------------------------------------------------------------------------- 落库


def _write_execution(
    db: Session,
    *,
    project_id: int | None,
    test_run_id: int | None,
    case_execution_id: int | None,
    security_case: SecurityCase,
    environment: Environment,
    actor: User,
    baseline_status: int | None,
    security_result: str,
    classification: str | None,
    mutation_trace: list[dict[str, Any]],
    replay_count: int,
    actual_status_codes: list[int],
    evidence: dict[str, Any] | None,
    error_code: str | None,
    started_at: datetime,
) -> SecurityExecution:
    """写一行 security_execution。commit 由 RunService 统一做。

    ``baseline_status`` 存的是基线 HTTP 状态码，列上是 ``PASSED/FAILED``，
    原始码另存 ``baseline_http_status``（§4.6）。
    """
    row = SecurityExecution(
        project_id=project_id,
        test_run_id=test_run_id,
        case_execution_id=case_execution_id,
        security_case_id=security_case.id,
        environment_id=getattr(environment, "id", None),
        actor_id=getattr(actor, "id", None),
        baseline_status=_baseline_conclusion_of(baseline_status),
        baseline_http_status=baseline_status,
        security_result=security_result,
        classification=classification,
        mutation_trace=mutation_trace,
        replay_count=replay_count,
        actual_status_codes=actual_status_codes,
        evidence=evidence,
        error_code=error_code,
        started_at=started_at,
        finished_at=datetime.now(),
    )
    db.add(row)
    db.flush()
    return row


def _parsed_body(raw: Any) -> Any:
    """把执行器返回的原始响应文本解析成 JSON；解析不了原样返回。

    断言层要读业务 ID、严重级别要判断是否泄露候选资源，都必须拿到结构化
    响应；执行器给的是文本。
    """
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw
    return raw


def _single_outcome(result: Any) -> replay_mod.ReplayOutcome:
    """非重放变异的单次执行结果，形状与重放一致，断言层不用分叉。"""
    return replay_mod.ReplayOutcome(
        (int(getattr(result, "status_code", 0) or 0),),
        (getattr(result, "response_body", None),),
        (getattr(result, "error_message", None),),
    )


def _auth_header_present(headers: dict[str, Any] | None) -> bool:
    """基线请求是否带了鉴权头（键名大小写不敏感）。"""
    return _AUTH_HEADER_KEY in {str(key).lower() for key in (headers or {})}


def _fingerprint(*, api_id: Any, mutation_type: str, location: Any, field: Any, baseline_case_id: Any) -> str:
    """sha256(api_id|mutation_type|target_location|target_field|baseline_case_id)。"""
    raw = "|".join(str(v) for v in (api_id, mutation_type, location, field, baseline_case_id))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evidence(
    *,
    rule_view: MutationRuleView,
    baseline_status: int | None,
    actual_status_codes: list[int],
    trace: list[dict[str, Any]],
    message: str,
    mutation_type: str,
    name: str | None,
) -> dict[str, Any]:
    """Finding 证据：只放脱敏后的状态码、trace 与固定中文结论。"""
    return {
        "mutation_type": mutation_type,
        "rule_name": name,
        "baseline_status": baseline_status,
        "actual_status_codes": actual_status_codes,
        "trace": trace,
        "message": message,
        "expected": {
            "expectation": rule_view.expected_security_behavior,
            "expected_status_codes": rule_view.expected_status_codes,
            "severity": rule_view.severity,
        },
    }


def _rule_text(rule: SecurityMutationRule | None, field_name: str) -> str:
    """读规则上的中文文案字段，规则被删时返回空串。"""
    return str(getattr(rule, field_name, None) or "").strip()


def _finding_title(name: str, mutation_type: str) -> str:
    """标题来自规则文案，不用 LLM 生成。"""
    return f"{name}（{mutation_type}）" if name else f"安全变异问题（{mutation_type}）"


def _finding_description(description: str, message: str) -> str:
    """描述：规则的中文说明 + 本次实际判定结论。"""
    return f"{description}\n\n本次判定：{message}" if description else message


def _finding_recommendation(mutation_type: str) -> str:
    """整改建议是固定模板文案：Phase 1 不做 LLM 发挥，也不自动建缺陷。"""
    if mutation_type in ("CROSS_USER", "IDOR", "RESOURCE_OWNER_CHANGE"):
        return "服务端读写资源时必须校验资源归属与调用方身份，不能只依赖前端隐藏入口。"
    if mutation_type == "ROLE_DOWNGRADE":
        return "服务端必须按会话里的真实角色重新判定权限，不要信任客户端传入的角色字段。"
    if mutation_type.startswith(
        ("REMOVE_TOKEN", "EMPTY_TOKEN", "INVALID_TOKEN", "MALFORMED", "WRONG_AUTH", "EXPIRED", "AUTHORIZATION")
    ):
        return "受保护接口在缺失或无效凭据时应当返回 401/403，不要放行匿名访问。"
    if mutation_type in ("REPLAY_SAME_REQUEST", "DUPLICATE_SUBMIT"):
        return "写入类接口应声明并校验幂等键，重复提交不应产生第二份业务数据。"
    if mutation_type.startswith(("REMOVE_FIELD", "NULL", "EMPTY", "TYPE_", "ZERO", "NEGATIVE", "OVER_MAX", "UNDER_MIN", "INVALID_")):
        return "服务端应按接口契约校验输入，非法输入应被拒绝而不是被静默接受。"
    return "服务端应按接口契约校验输入并在越权或非法输入时明确拒绝。"


def _upsert_finding(
    db: Session,
    *,
    project_id: int | None,
    test_run_id: int | None,
    case_execution_id: int | None,
    security_execution_id: int | None,
    security_case: SecurityCase,
    fingerprint: str,
    severity: str,
    evidence: dict[str, Any],
    title: str,
    description: str,
    recommendation: str,
    actor: User,
    mutation_type: str,
) -> SecurityFinding | None:
    """同 fingerprint 的未关闭 Finding 只保留一条，重复执行只累加 ``evidence.repeat_count``。

    部分唯一索引只在 status IN ('OPEN','CONFIRMED') 上生效，所以误报 / 忽略 / 已解决
    之后可以重新开一条 OPEN，并把旧状态写进 ``evidence.prior_status`` 留作复核线索；
    并发插入撞索引时改走更新分支。
    """
    if not severity or not project_id:
        return None
    open_row = (
        db.query(SecurityFinding)
        .filter(
            SecurityFinding.project_id == project_id,
            SecurityFinding.fingerprint == fingerprint,
            SecurityFinding.status.in_(("OPEN", "CONFIRMED")),
        )
        .order_by(SecurityFinding.id.desc())
        .first()
    )
    if open_row is not None:
        # 还在跟的那一条：累加次数、把指针指向最新一次执行，不重复开记录。
        count = int((open_row.evidence or {}).get("repeat_count") or 1)
        evidence["repeat_count"] = count + 1
        open_row.security_execution_id = security_execution_id
        open_row.case_execution_id = case_execution_id
        open_row.test_run_id = test_run_id or open_row.test_run_id
        open_row.evidence = evidence
        open_row.updated_at = datetime.now()
        db.add(open_row)
        db.flush()
        return open_row

    prior = (
        db.query(SecurityFinding)
        .filter(
            SecurityFinding.project_id == project_id,
            SecurityFinding.fingerprint == fingerprint,
        )
        .order_by(SecurityFinding.id.desc())
        .first()
    )
    prior_status = str(getattr(prior, "status", None) or "") if prior is not None else None
    return SecurityFinding(
        project_id=project_id,
        test_run_id=test_run_id,
        case_execution_id=case_execution_id,
        security_execution_id=security_execution_id,
        api_id=security_case.api_id,
        business_action_id=security_case.business_action_id,
        strategy_id=security_case.strategy_id,
        security_case_id=security_case.id,
        mutation_type=mutation_type,
        severity=severity,
        status="OPEN",
        title=title,
        description=description,
        # 误报 / 忽略 / 已解决之后又出现：留一条旧状态线索，便于复核为什么重新开。
        evidence={**evidence, "prior_status": prior_status or None, "repeat_count": 1},
        recommendation=recommendation,
        fingerprint=fingerprint,
        created_by=getattr(actor, "id", None),
    )


def _candidate_value(config: dict[str, Any], outputs: dict[str, dict[str, Any]]) -> Any:
    """从 Fixture 输出取候选资源 ID，供严重级别表判断响应是否泄露它。

    取不到不影响判定本身，只影响严重级别（没有候选就没法说「泄露了它」）。
    """
    if not isinstance(config, dict):
        return None
    try:
        rule_view = MutationRuleView(
            mutation_type="", mutation_config=dict(config), target_location="", target_field=None
        )
        _location, _field, value = candidate_resolver.resource_target(
            rule_view, ResolveScope(fixtures=outputs), label="候选资源"
        )
        return value
    except Exception:  # noqa: BLE001 - 缺 Fixture 时按「无候选」继续。
        return None


# --------------------------------------------------------------------------- 结果


class _CaseContext:
    """一次安全执行的落库上下文，避免各分支重复传参。"""

    def __init__(
        self,
        db: Session,
        *,
        security_case: SecurityCase,
        environment: Environment,
        actor: User,
        run_id: int | None,
        case_execution_id: int | None,
        started_at: datetime,
    ) -> None:
        self.db = db
        self.security_case = security_case
        self.environment = environment
        self.actor = actor
        self.run_id = run_id
        self.case_execution_id = case_execution_id
        self.started_at = started_at

    def finish(
        self,
        test_case: TestCase,
        *,
        security_result: str,
        classification: str,
        message: str,
        error_code: str | None,
        baseline_result: Any = None,
        mutation_trace: list[dict[str, Any]] | None = None,
        replay_count: int = 0,
        actual_status_codes: list[int] | None = None,
        evidence: dict[str, Any] | None = None,
        assertion_results: list[dict[str, Any]] | None = None,
    ) -> Any:
        """写 execution 并返回既有四态的 CaseExecutionResult。"""
        baseline_http = _baseline_status_of(baseline_result) if baseline_result is not None else None
        execution = _write_execution(
            self.db,
            project_id=self.security_case.project_id,
            test_run_id=self.run_id,
            case_execution_id=self.case_execution_id,
            security_case=self.security_case,
            environment=self.environment,
            actor=self.actor,
            baseline_status=baseline_http,
            security_result=security_result,
            classification=classification,
            mutation_trace=list(mutation_trace or []),
            replay_count=replay_count,
            actual_status_codes=list(actual_status_codes or []),
            evidence=evidence,
            error_code=error_code,
            started_at=self.started_at,
        )
        return tce.CaseExecutionResult(
            status=_CASE_STATUS_BY_RESULT.get(security_result, "SKIPPED"),
            executor_type="SECURITY",
            request_snapshot=getattr(baseline_result, "request_snapshot", None),
            response_snapshot=getattr(baseline_result, "response_snapshot", None),
            assertion_results=list(assertion_results or []),
            context_json={
                "security_execution_id": execution.id,
                "security_case_id": self.security_case.id,
                "security_result": security_result,
                "security_classification": classification,
                "security_message": message,
            },
            error_code=error_code,
            error_message=message,
        )


# --------------------------------------------------------------------------- 入口


def run_security_case(
    db: Session,
    test_case: TestCase,
    *,
    environment: Environment,
    actor: User,
    fixture_outputs: dict[str, dict[str, Any]] | None = None,
    extra_headers: dict[str, str] | None = None,
    run_id: int | None = None,
    case_execution_id: int | None = None,
    request_sender: Callable[..., Any] | None = None,
) -> Any | None:
    """执行一条安全用例；没有 ``security_case`` 行时返回 None 让调用方走原路径。"""
    security_case = _load_security_case(db, test_case)
    if security_case is None:
        return None

    started = datetime.now()
    outputs = dict(fixture_outputs or {})
    ctx = _CaseContext(
        db,
        security_case=security_case,
        environment=environment,
        actor=actor,
        run_id=run_id,
        case_execution_id=case_execution_id,
        started_at=started,
    )

    # 2. 环境闸门（§18.3）：不构造请求，也不发请求；基线同样不发。
    decision = _environment_decision(db, security_case.project_id, environment)
    if not decision.allowed:
        return ctx.finish(
            test_case,
            security_result="SKIPPED",
            classification="TARGET_BLOCKED",
            error_code=_environment_error_code(decision),
            message=_environment_message(decision),
            evidence={"environment_reason": decision.reason},
        )

    # 3. 确认闸门：高风险未确认不发请求。
    confirmed = bool(security_case.confirmed_by and security_case.confirmed_at)
    if bool(security_case.confirmation_required) and not confirmed:
        return ctx.finish(
            test_case,
            security_result="SKIPPED",
            classification="CONFIRMATION_REQUIRED",
            error_code=CODE_SECURITY_CONFIRMATION_REQUIRED,
            message="高风险变异未确认，未发出请求",
        )

    baseline_case = db.get(TestCase, security_case.baseline_case_id) if security_case.baseline_case_id else None
    if baseline_case is None:
        return ctx.finish(
            test_case,
            security_result="INCONCLUSIVE",
            classification="BASELINE_FAILED",
            error_code=CODE_SECURITY_BASELINE_FAILED,
            message="基线用例不存在，无法执行安全测试",
        )

    api_id, iface = _resolve_api(db, security_case, baseline_case)
    if iface is None:
        return ctx.finish(
            test_case,
            security_result="SKIPPED",
            classification="TARGET_BLOCKED",
            error_code=CODE_SECURITY_TARGET_NOT_ALLOWED,
            message="该安全用例没有可变异的目标接口",
        )

    # 4. 组装基线请求。
    try:
        request = _build_request(
            db, baseline_case.id, iface, environment, outputs, extra_headers
        )
    except AppError as exc:
        return ctx.finish(
            test_case,
            security_result="INCONCLUSIVE",
            classification="TARGET_BLOCKED",
            error_code=getattr(exc, "code", CODE_SECURITY_MUTATION_NOT_ALLOWED),
            message=str(exc),
        )

    # 5. 执行基线；基线不通就不发任何变异请求。
    baseline_result = _run_baseline(db, baseline_case, environment, actor, outputs, extra_headers)
    baseline_http = _baseline_status_of(baseline_result)
    if baseline_result.error_message or not _BASELINE_OK_MIN <= baseline_http < _BASELINE_OK_MAX:
        return ctx.finish(
            test_case,
            security_result="INCONCLUSIVE",
            classification="BASELINE_FAILED",
            error_code=CODE_SECURITY_BASELINE_FAILED,
            message="基线用例未通过，未执行任何安全变异",
            baseline_result=baseline_result,
            evidence={
                "baseline_status": baseline_http or None,
                "baseline_message": baseline_result.error_message,
            },
        )

    rule = db.get(SecurityMutationRule, security_case.rule_id) if security_case.rule_id else None
    # 规则是变异配置的权威来源；security_case 上是生成时的快照。
    config = dict(getattr(rule, "mutation_config", None) or security_case.mutation_config or {})
    rule_view = _rule_view(security_case, rule, config)
    mutation_type = str(rule_view.mutation_type or "")
    is_replay = mutation_type in REPLAY_FAMILY
    replay_count = 1
    interval_ms = 0

    if mutation_type in BUSINESS_FLOW_FAMILY:
        return ctx.finish(
            test_case,
            security_result="SKIPPED",
            classification="TARGET_BLOCKED",
            error_code=CODE_SECURITY_MUTATION_NOT_ALLOWED,
            message="该变异类型依赖业务流程语义，第一阶段暂不执行",
            baseline_result=baseline_result,
        )

    # 6. 变异。重放类不改动请求，只重复提交。
    if is_replay:
        # 重放参数在这里校验：次数或间隔越界按配置错误处理，不静默改成默认值。
        try:
            replay_count, interval_ms = replay_mod.read_replay_params(config)
        except AppError as exc:
            return ctx.finish(
                test_case,
                security_result="SKIPPED",
                classification="TARGET_BLOCKED",
                error_code=exc.code,
                message=str(exc),
                baseline_result=baseline_result,
            )
        mutated_request = request
        traces: list[MutationTraceEntry] = [
            MutationTraceEntry(
                mutation_type=mutation_type,
                location="BODY",
                note=f"未改动请求体，按 replay_count={replay_count} 重复提交",
            )
        ]
        notes: list[str] = []
    else:
        try:
            mutated = SecurityMutationEngine.apply(
                copy.deepcopy(request),
                rule_view,
                scope=outputs or None,
                fields=_load_fields(db, iface.id),
                confirmed=confirmed,
                auth_type=getattr(iface, "auth_type", None),
            )
        except ConfirmationRequiredError as exc:
            return ctx.finish(
                test_case,
                security_result="SKIPPED",
                classification="CONFIRMATION_REQUIRED",
                error_code=exc.code,
                message=str(exc),
                baseline_result=baseline_result,
            )
        except RuleNotApplicableError as exc:
            return ctx.finish(
                test_case,
                security_result="SKIPPED",
                classification="TARGET_BLOCKED",
                error_code=exc.code,
                message=str(exc),
                baseline_result=baseline_result,
            )
        except AppError as exc:
            return ctx.finish(
                test_case,
                security_result="SKIPPED",
                classification="TARGET_BLOCKED",
                error_code=exc.code,
                message=str(exc),
                baseline_result=baseline_result,
            )
        mutated_request = mutated.request
        traces = mutated.traces
        notes = mutated.notes

    # 7. 执行变异请求（重放 2～3 次）。
    send = request_sender or _EXECUTOR.execute
    project_id = security_case.project_id or iface.project_id

    def send_once(request: Any = None) -> Any:
        # 重放循环会把同一个请求对象传回来；这里只用它作为「本次是重放执行」的信号，
        # 请求内容始终是上面变异出来的那份。
        return send(
            db,
            method=mutated_request.method,
            url=_EXECUTOR.build_url(environment, mutated_request.path, mutated_request.path_params),
            project_id=project_id,
            headers=mutated_request.headers or None,
            query=mutated_request.query or None,
            json_body=mutated_request.json_body,
            form_body=mutated_request.form_body,
            raw_body=mutated_request.raw_body,
            timeout=mutated_request.timeout,
        )

    try:
        if is_replay:
            outcome = replay_mod.run_replay(None, send_once, count=replay_count, interval_ms=interval_ms)
        else:
            # 非重放变异只发一次：重放循环的校验只接受 2～3 次，不适合单次执行。
            outcome = _single_outcome(send_once())
    except AppError as exc:
        return ctx.finish(
            test_case,
            security_result="FAILED_EXECUTION",
            classification="TRANSPORT_ERROR",
            error_code=getattr(exc, "code", CODE_SECURITY_EXECUTION_FAILED),
            message=str(exc),
            baseline_result=baseline_result,
            mutation_trace=[entry.to_dict() for entry in traces],
        )

    trace_dicts = [entry.to_dict() for entry in traces]
    statuses = list(outcome.statuses)
    transport_errors = [message for message in outcome.errors if message]
    reached_server = any(code != 0 for code in statuses)

    # 8. 断言。
    expected_codes = list(rule_view.expected_status_codes or [])
    assertion_result = assertion_mod.assert_expectation(
        rule_view.expected_security_behavior,
        statuses,
        rule_name=str(getattr(rule, "name", None) or "") or None,
        mutation_type=mutation_type,
        response_body=_parsed_body(outcome.bodies[-1]) if outcome.bodies else None,
        response_bodies=[_parsed_body(body) for body in outcome.bodies],
        trace=trace_dicts,
        expected_status_codes=expected_codes or None,
        auth_type=getattr(iface, "auth_type", "none"),
        baseline_auth_present=_auth_header_present(request.headers),
    )

    # 请求一次都没打到服务端时，业务断言没有意义。
    if not reached_server:
        security_result = "FAILED_EXECUTION"
        classification = "TRANSPORT_ERROR"
    else:
        security_result = assertion_result.security_result
        classification = assertion_result.classification

    # 9. 写 execution。
    execution = _write_execution(
        db,
        project_id=project_id,
        test_run_id=run_id,
        case_execution_id=case_execution_id,
        security_case=security_case,
        environment=environment,
        actor=actor,
        baseline_status=baseline_http,
        security_result=security_result,
        classification=classification,
        mutation_trace=trace_dicts,
        replay_count=outcome.attempts,
        actual_status_codes=statuses,
        evidence={
            "message": assertion_result.message,
            "baseline_status": baseline_http,
            "actual_status_codes": statuses,
            "transport_errors": transport_errors,
            "notes": notes,
        },
        error_code=None,
        started_at=started,
    )

    # 10. 需要时 upsert Finding。
    if security_result == "POTENTIAL_ISSUE":
        severity_value = severity_mod.resolve_severity(
            severity_mod.SeverityContext(
                mutation_type=mutation_type,
                classification=classification,
                status_codes=statuses,
                auth_type=getattr(iface, "auth_type", "none"),
                response_body=_parsed_body(outcome.bodies[-1]) if outcome.bodies else None,
                candidate_resource_id=_candidate_value(config, outputs),
                method=mutated_request.method,
                rule_severity=rule_view.severity,
            )
        )
        if severity_value:
            finding = _upsert_finding(
                db,
                project_id=project_id,
                test_run_id=run_id,
                case_execution_id=case_execution_id,
                security_execution_id=execution.id,
                security_case=security_case,
                fingerprint=_fingerprint(
                    api_id=api_id,
                    mutation_type=mutation_type,
                    location=rule_view.target_location,
                    field=rule_view.target_field,
                    baseline_case_id=baseline_case.id,
                ),
                severity=severity_value,
                evidence=_evidence(
                    rule_view=rule_view,
                    baseline_status=baseline_http,
                    actual_status_codes=statuses,
                    trace=trace_dicts,
                    message=assertion_result.message,
                    mutation_type=mutation_type,
                    name=_rule_text(rule, "name") or None,
                ),
                title=_finding_title(_rule_text(rule, "name"), mutation_type),
                description=_finding_description(
                    _rule_text(rule, "description"), message=assertion_result.message
                ),
                recommendation=_finding_recommendation(mutation_type),
                actor=actor,
                mutation_type=mutation_type,
            )
            if finding is not None:
                db.add(finding)
                db.flush()

    return tce.CaseExecutionResult(
        status=_CASE_STATUS_BY_RESULT.get(security_result, "SKIPPED"),
        executor_type="SECURITY",
        request_snapshot=baseline_result.request_snapshot,
        response_snapshot={
            "status_code": statuses[-1] if statuses else 0,
            "actual_status_codes": statuses,
            "body": trace_mod.mask_body(_parsed_body(outcome.bodies[-1])) if outcome.bodies else None,
            "transport_errors": transport_errors,
        },
        assertion_results=[
            {"name": "security", "passed": security_result == "PASS", "message": assertion_result.message}
        ],
        context_json={
            "security_execution_id": execution.id,
            "security_case_id": security_case.id,
            "security_result": security_result,
            "security_classification": classification,
            "security_message": assertion_result.message,
        },
        error_code=None,
        error_message=assertion_result.message,
    )
