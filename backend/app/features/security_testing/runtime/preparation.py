"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.execution.http.request_builder import get_environment_headers
from app.features.security_testing.models import SecurityCase, SecurityMutationRule, SecurityProjectSetting
from app.features.security_testing.runtime.baseline import EnvironmentDecision
from app.features.test_data.security.db_guard import classify as classify_environment
from app.features.security_testing.runtime import baseline as baseline_mod
from app.features.security_testing.runtime.types import MutationRuleView
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.business.models.business_binding import BusinessBinding
from app.features.test_management.executors import preparation
from app.features.test_management.models.test_case import TestCase
from app.core.models.configuration import Environment
from app.core.models.project import ProjectOutboundTarget
from app.core.http.errors import CODE_SECURITY_TARGET_NOT_ALLOWED
from app.core.http.errors import CODE_SECURITY_PRODUCTION_FORBIDDEN


_ENVIRONMENT_CODE_BY_REASON = {
    "PRODUCTION": CODE_SECURITY_PRODUCTION_FORBIDDEN,
}


_BASELINE_OK_MIN = 200


_BASELINE_OK_MAX = 300


def load_security_case(db: Session, test_case: TestCase) -> SecurityCase | None:
    """按 test_case_id 取安全扩展行；没有就是普通用例。"""
    if not test_case or not test_case.id:
        return None
    return db.query(SecurityCase).filter(SecurityCase.test_case_id == test_case.id).one_or_none()


def resolve_api(
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


def outbound_is_production(
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


def environment_decision(
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
        outbound_production=outbound_is_production(db, project_id, environment),
        allow_dev=bool(getattr(setting, "allow_dev", True)) if setting is not None else True,
        allow_test=bool(getattr(setting, "allow_test", True)) if setting is not None else True,
        allow_staging=bool(getattr(setting, "allow_staging", False)) if setting is not None else False,
    )


def environment_error_code(decision: EnvironmentDecision) -> str:
    """将环境异常映射为平台错误代码。"""
    return _ENVIRONMENT_CODE_BY_REASON.get(decision.reason, CODE_SECURITY_TARGET_NOT_ALLOWED)


def environment_message(decision: EnvironmentDecision) -> str:
    """拒绝原因对应的中文提示；不透露白名单细节。"""
    return {
        "PRODUCTION": "生产环境禁止执行安全变异请求",
        "STAGING_NOT_ALLOWED": "预发环境默认禁止执行安全变异请求",
        "DEV_NOT_ALLOWED": "开发环境的安全变异请求已被项目设置关闭",
        "TEST_NOT_ALLOWED": "测试环境的安全变异请求已被项目设置关闭",
    }.get(decision.reason, "当前环境不允许执行安全变异请求")


def load_fields(db: Session, api_id: int) -> list[Any]:
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


def build_request(
    db: Session,
    case_id: int,
    iface: ApiInterface,
    environment: Environment,
    fixture_outputs: dict[str, dict[str, Any]],
    extra_headers: dict[str, str] | None,
) -> Any:
    """组装基线请求：变量解析、测试数据、step 配置全部复用现有执行器的实现。"""
    data_values, _overrides = preparation.load_data_values(db, case_id, environment, fixture_outputs)
    scope = preparation.build_execution_scope(data_values, environment, fixture_outputs)
    step_config = preparation.load_action_step_config(db, case_id)
    return baseline_mod.build_request(
        method=getattr(iface, "method", None),
        path=getattr(iface, "path", ""),
        step_config=step_config,
        scope=scope,
        resolve=preparation.resolve_tokens,
        data_values=data_values,
        environment_headers=get_environment_headers(environment),
        extra_headers=extra_headers,
        auth_type=getattr(iface, "auth_type", None),
        api_id=iface.id,
        project_id=getattr(iface, "project_id", None),
    )


def baseline_status_of(result: Any) -> int:
    """基线响应里的 HTTP 状态码；取不到是 0。"""
    snapshot = getattr(result, "response_snapshot", None) or {}
    return int(snapshot.get("status_code") or 0) if isinstance(snapshot, dict) else 0


def baseline_conclusion_of(http_status: int | None) -> str | None:
    """基线 HTTP 状态码 → 落库的 ``PASSED/FAILED``；没打出去时为空。"""
    status = int(http_status or 0)
    if status == 0:
        return None
    return "PASSED" if _BASELINE_OK_MIN <= status < _BASELINE_OK_MAX else "FAILED"


def build_rule_view(security_case: SecurityCase, rule: SecurityMutationRule | None, config: dict[str, Any]) -> MutationRuleView:
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
