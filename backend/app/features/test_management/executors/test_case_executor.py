"""测试用例执行器：按 target_type 路由执行。

路由契约（§16/§29，禁止重新实现 HTTP/业务流执行器）：
- API → 复用 ApiRequestExecutor（httpx + 出站白名单 + 私网防护）
- BUSINESS_FLOW → 复用 business.executors.business_flow_executor.execute_flow
- BUSINESS_ACTION → 复用业务动作的「绑定 + INPUT 映射 + ApiRequestExecutor」执行能力

快照统一经 SensitiveDataMasker 脱敏后落库（§敏感数据）。
断言统一经 assertion_engine 评估。
JSONPath 复用 mapping_resolver._jsonpath_extract。

本执行器不提交事务（由 run_service 统一 commit），只构造 CaseExecutionResult。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.business.executors.api_executor import ApiRequestExecutor
from app.features.business.executors.business_flow_executor import execute_flow
from app.features.business.executors.mapping_resolver import resolve_input_mappings
from app.features.business.executors.sensitive import SensitiveDataMasker
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_api_mapping import BusinessApiMapping
from app.features.business.models.business_binding import BusinessBinding
from app.features.business.models.business_flow import BusinessFlow
from app.features.business.models.execution import ActionExecution, FlowExecution
from app.features.test_management.executors.assertion_engine import required_all_passed, run_assertions
from app.features.test_management.models.test_assertion import TestAssertion
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_case_data import TestCaseData
from app.features.test_management.models.test_step import TestStep
from app.models.configuration import Environment
from app.models.identity import User

_EXECUTOR = ApiRequestExecutor()

_ENV_ATTR_KEYS = {
    "base_url", "gateway_prefix", "display_name", "name", "description",
    "is_active", "is_default",
}


@dataclass
class CaseExecutionResult:
    """单用例执行结果（由 run_service 落库为 CaseExecution）。"""

    status: str = "PENDING"  # PASSED/FAILED/ERROR/SKIPPED
    executor_type: str | None = None
    request_snapshot: dict[str, Any] | None = None
    response_snapshot: dict[str, Any] | None = None
    assertion_results: list[dict[str, Any]] = field(default_factory=list)
    context_json: dict[str, Any] | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


def execute(db: Session, test_case: TestCase, *, environment: Environment, actor: User) -> CaseExecutionResult:
    """执行单个测试用例，按 target_type 路由。"""
    started = time.perf_counter()
    target = (test_case.target_type or "API").upper()
    try:
        if target == "API":
            result = _execute_api(db, test_case, environment, actor)
        elif target == "BUSINESS_FLOW":
            result = _execute_business_flow(db, test_case, environment, actor)
        elif target == "BUSINESS_ACTION":
            result = _execute_business_action(db, test_case, environment, actor)
        else:
            result = CaseExecutionResult(
                status="ERROR", executor_type=target,
                error_code="UNSUPPORTED_TARGET_TYPE",
                error_message=f"不支持的用例目标类型：{target}",
            )
    except ValueError as exc:
        # execute_flow 对环境/流程不存在抛 ValueError；转为 ERROR。
        result = CaseExecutionResult(
            status="ERROR", executor_type=target,
            error_code="EXECUTION_ERROR", error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — 执行器需兜底，避免单用例拖垮整轮。
        result = CaseExecutionResult(
            status="ERROR", executor_type=target,
            error_code="EXECUTION_ERROR", error_message=f"执行异常：{exc}",
        )
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    if result.executor_type is None:
        result.executor_type = target
    return result


# --------------------------------------------------------------------------- API


def _execute_api(db: Session, test_case: TestCase, environment: Environment, actor: User) -> CaseExecutionResult:
    executor_type = "API"
    if test_case.api_id is None:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="API_NOT_CONFIGURED", error_message="用例未关联接口")
    iface = db.get(ApiInterface, test_case.api_id)
    if iface is None or iface.project_id != test_case.project_id:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="API_NOT_FOUND", error_message="关联接口不存在或不属于本项目")

    data_values = _load_data_values(db, test_case.id, environment)
    step_config = _load_action_step_config(db, test_case.id)

    # 请求构造：step_config 优先，缺省回退接口默认值 / 测试数据。
    method = (step_config.get("method") or iface.method or "GET").upper()
    path_params = _resolve_tokens(step_config.get("path_params") or {}, data_values, environment)
    headers = _EXECUTOR.get_environment_headers(environment)
    headers.update(_resolve_tokens(step_config.get("headers") or {}, data_values, environment))
    query = _resolve_tokens(step_config.get("query") or {}, data_values, environment)
    if step_config.get("body") is not None:
        json_body = _resolve_tokens(step_config.get("body"), data_values, environment)
    elif data_values:
        json_body = data_values
    else:
        json_body = None
    timeout = int(step_config.get("timeout", 30))

    url = _EXECUTOR.build_url(environment, iface.path, path_params)

    resp = _EXECUTOR.execute(
        db, method=method, url=url, project_id=test_case.project_id,
        headers=headers or None, query=query or None, json_body=json_body,
        timeout=timeout,
    )

    response = _build_response_dict(resp)
    assertions = _load_assertions(db, test_case.id)
    assertion_results = run_assertions(assertions, response)

    request_snapshot = SensitiveDataMasker.mask_request(
        method, url, headers, query, json_body or {}, "json" if json_body else "none",
    )
    response_snapshot = SensitiveDataMasker.mask_response(
        resp.status_code, resp.response_headers, _try_parse_json(resp.response_body),
    )

    status, error_code, error_message = _decide_status(resp, assertion_results)
    return CaseExecutionResult(
        status=status, executor_type=executor_type,
        request_snapshot=request_snapshot, response_snapshot=response_snapshot,
        assertion_results=assertion_results, context_json={"data": data_values},
        error_code=error_code, error_message=error_message,
    )


# --------------------------------------------------------------------------- BUSINESS_FLOW


def _execute_business_flow(
    db: Session, test_case: TestCase, environment: Environment, actor: User,
) -> CaseExecutionResult:
    executor_type = "BUSINESS_FLOW"
    if test_case.business_flow_id is None:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="FLOW_NOT_CONFIGURED", error_message="用例未关联业务流程")
    flow = db.get(BusinessFlow, test_case.business_flow_id)
    if flow is None or flow.project_id != test_case.project_id:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="FLOW_NOT_FOUND", error_message="关联业务流程不存在或不属于本项目")

    initial_variables = _load_data_values(db, test_case.id, environment)
    execution = execute_flow(
        db, test_case.business_flow_id,
        environment_id=environment.id, variables=initial_variables, actor=actor,
    )

    action_execs = (
        db.query(ActionExecution)
        .filter(ActionExecution.flow_execution_id == execution.id)
        .order_by(ActionExecution.sequence.asc(), ActionExecution.id.asc())
        .all()
    )
    response = _build_flow_response(execution, action_execs)
    assertions = _load_assertions(db, test_case.id)
    assertion_results = run_assertions(assertions, response)

    request_snapshot = {
        "flow_id": flow.id, "flow_name": flow.name,
        "environment_id": environment.id, "action_count": len(action_execs),
    }
    response_snapshot = {
        "flow_execution_id": execution.id, "status": execution.status,
        "context": execution.context_json,
        "actions": [
            {"sequence": ae.sequence, "action_id": ae.action_id, "status": ae.status,
             "duration_ms": ae.duration_ms, "error_code": ae.error_code}
            for ae in action_execs
        ],
    }

    status, error_code, error_message = _decide_flow_status(execution, assertion_results)
    return CaseExecutionResult(
        status=status, executor_type=executor_type,
        request_snapshot=request_snapshot, response_snapshot=response_snapshot,
        assertion_results=assertion_results,
        context_json=execution.context_json,
        error_code=error_code, error_message=error_message,
    )


# --------------------------------------------------------------------------- BUSINESS_ACTION


def _execute_business_action(
    db: Session, test_case: TestCase, environment: Environment, actor: User,
) -> CaseExecutionResult:
    executor_type = "BUSINESS_ACTION"
    if test_case.business_action_id is None:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="ACTION_NOT_CONFIGURED", error_message="用例未关联业务动作")
    action = db.get(BusinessAction, test_case.business_action_id)
    if action is None:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="ACTION_NOT_FOUND", error_message="关联业务动作不存在")
    flow = db.get(BusinessFlow, action.flow_id)
    if flow is None or flow.project_id != test_case.project_id:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="ACTION_NOT_FOUND", error_message="业务动作不属于本项目")

    # 复用业务动作的默认 API 绑定 + INPUT 映射（§16）。
    binding = (
        db.query(BusinessBinding)
        .filter(
            BusinessBinding.action_id == action.id,
            BusinessBinding.binding_type == "API",
            BusinessBinding.is_default.is_(True),
            BusinessBinding.enabled.is_(True),
        )
        .first()
    )
    if binding is None or binding.api_id is None:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="DEFAULT_BINDING_NOT_FOUND",
                                   error_message="业务动作未配置默认 API 绑定")
    iface = db.get(ApiInterface, binding.api_id)
    if iface is None or iface.project_id != test_case.project_id:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="API_NOT_FOUND", error_message="绑定接口已失效")

    data_values = _load_data_values(db, test_case.id, environment)
    mappings = [
        {"direction": m.direction, "business_variable": m.business_variable,
         "api_location": m.api_location, "api_field": m.api_field, "expression": m.expression}
        for m in db.query(BusinessApiMapping).filter(BusinessApiMapping.binding_id == binding.id).all()
    ]
    request_parts, errors = resolve_input_mappings(mappings, data_values, {})
    if errors:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="INPUT_MAPPING_FAILED",
                                   error_message="; ".join(errors))

    headers = _EXECUTOR.get_environment_headers(environment)
    headers.update(request_parts["headers"])
    url = _EXECUTOR.build_url(environment, iface.path, request_parts["path_params"])
    method = (iface.method or "GET").upper()
    json_body = request_parts["body"] if request_parts["body"] else None

    resp = _EXECUTOR.execute(
        db, method=method, url=url, project_id=test_case.project_id,
        headers=headers or None, query=request_parts["query"] or None,
        json_body=json_body, timeout=30,
    )

    response = _build_response_dict(resp)
    assertions = _load_assertions(db, test_case.id)
    assertion_results = run_assertions(assertions, response)

    request_snapshot = SensitiveDataMasker.mask_request(
        method, url, headers, request_parts["query"], json_body or {},
        "json" if json_body else "none",
    )
    response_snapshot = SensitiveDataMasker.mask_response(
        resp.status_code, resp.response_headers, _try_parse_json(resp.response_body),
    )
    status, error_code, error_message = _decide_status(resp, assertion_results)
    return CaseExecutionResult(
        status=status, executor_type=executor_type,
        request_snapshot=request_snapshot, response_snapshot=response_snapshot,
        assertion_results=assertion_results, context_json={"data": data_values},
        error_code=error_code, error_message=error_message,
    )


# --------------------------------------------------------------------------- 辅助


def _load_data_values(db: Session, case_id: int, environment: Environment) -> dict[str, Any]:
    """加载测试数据并解析为 name→value 字典。"""
    rows = (
        db.query(TestCaseData)
        .filter(TestCaseData.test_case_id == case_id)
        .order_by(TestCaseData.sort.asc(), TestCaseData.id.asc())
        .all()
    )
    values: dict[str, Any] = {}
    for row in rows:
        source = (row.source_type or "STATIC").upper()
        if source == "ENVIRONMENT":
            values[row.name] = _resolve_env_value(environment, row.value or "")
        else:
            # STATIC / VARIABLE / RUNTIME / FAKER / FIXTURE：第一阶段取字面值。
            values[row.name] = _parse_value(row.value, row.value_type)
    return values


def _resolve_env_value(environment: Environment, key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if key in _ENV_ATTR_KEYS:
        return str(getattr(environment, key, "") or "")
    dh = environment.default_headers if isinstance(environment.default_headers, dict) else {}
    return str(dh.get(key, ""))


def _parse_value(raw: str | None, value_type: str | None) -> Any:
    """按 value_type 把字符串值解析为对应类型；解析失败保留字符串。"""
    if raw is None:
        return None
    vt = (value_type or "STRING").upper()
    if vt == "STRING":
        return raw
    if vt in ("INTEGER", "NUMBER"):
        try:
            return int(raw) if vt == "INTEGER" else float(raw)
        except (ValueError, TypeError):
            return raw
    if vt == "BOOLEAN":
        return raw.strip().lower() in ("true", "1", "yes", "on")
    if vt in ("OBJECT", "ARRAY"):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
    return raw


def _load_action_step_config(db: Session, case_id: int) -> dict[str, Any]:
    """取首个 ACTION 步骤的 config_json（无则空 dict）。"""
    step = (
        db.query(TestStep)
        .filter(TestStep.test_case_id == case_id, TestStep.step_type == "ACTION")
        .order_by(TestStep.sort.asc(), TestStep.id.asc())
        .first()
    )
    if step is None:
        # 退而取任意步骤。
        step = db.query(TestStep).filter(TestStep.test_case_id == case_id).order_by(TestStep.sort.asc()).first()
    cfg = step.config_json if (step is not None and isinstance(step.config_json, dict)) else {}
    return cfg


def _load_assertions(db: Session, case_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(TestAssertion)
        .filter(TestAssertion.test_case_id == case_id)
        .order_by(TestAssertion.sort.asc(), TestAssertion.id.asc())
        .all()
    )
    return [
        {"id": a.id, "assertion_type": a.assertion_type, "source": a.source,
         "path": a.path, "operator": a.operator, "expected_value": a.expected_value,
         "required": a.required}
        for a in rows
    ]


def _resolve_tokens(obj: Any, data_values: dict[str, Any], environment: Environment) -> Any:
    """递归替换 ${data.NAME} / ${env.KEY} 占位符。"""
    if isinstance(obj, str):
        return _resolve_token_str(obj, data_values, environment)
    if isinstance(obj, dict):
        return {k: _resolve_tokens(v, data_values, environment) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_tokens(v, data_values, environment) for v in obj]
    return obj


def _resolve_token_str(text: str, data_values: dict[str, Any], environment: Environment) -> Any:
    """替换单个字符串中的占位符。整串恰好是占位符时保留原类型。"""
    import re
    pattern = re.compile(r"\$\{(data|env)\.([A-Za-z0-9_]+)\}")

    matches = list(pattern.finditer(text))
    if not matches:
        return text
    # 整串即单一占位符 → 返回原类型值。
    if len(matches) == 1 and matches[0].group(0) == text:
        kind, key = matches[0].group(1), matches[0].group(2)
        if kind == "data":
            return data_values.get(key)
        return _resolve_env_value(environment, key)
    # 多占位符 / 混合文本 → 字符串拼接。
    def repl(m: re.Match) -> str:
        kind, key = m.group(1), m.group(2)
        val = data_values.get(key) if kind == "data" else _resolve_env_value(environment, key)
        return "" if val is None else str(val)
    return pattern.sub(repl, text)


def _build_response_dict(resp) -> dict[str, Any]:
    return {
        "status_code": resp.status_code,
        "headers": dict(resp.response_headers or {}),
        "body": _try_parse_json(resp.response_body),
        "raw_body": resp.response_body or "",
        "response_time_ms": resp.response_time_ms,
    }


def _build_flow_response(execution: FlowExecution, action_execs: list[ActionExecution]) -> dict[str, Any]:
    """把业务流执行结果合成成断言引擎可消费的响应字典。

    业务流用例通常断言：STATUS_CODE==200（流程成功）与 JSON_PATH（上下文变量）。
    """
    status_code = 200 if execution.status == "SUCCESS" else 500
    context = execution.context_json if isinstance(execution.context_json, dict) else {}
    total_ms = sum((ae.duration_ms or 0) for ae in action_execs)
    return {
        "status_code": status_code,
        "headers": {},
        "body": context,
        "raw_body": json.dumps(context, ensure_ascii=False, default=str),
        "response_time_ms": total_ms,
    }


def _decide_status(resp, assertion_results: list[dict[str, Any]]) -> tuple[str, str | None, str | None]:
    if resp.error_message:
        if "超时" in resp.error_message:
            return "ERROR", "HTTP_TIMEOUT", resp.error_message
        return "ERROR", "HTTP_REQUEST_FAILED", resp.error_message
    if not resp.success:
        return "FAILED", "HTTP_REQUEST_FAILED", f"HTTP {resp.status_code}"
    if not required_all_passed(assertion_results):
        return "FAILED", "ASSERTION_FAILED", "断言未全部通过"
    return "PASSED", None, None


def _decide_flow_status(
    execution: FlowExecution, assertion_results: list[dict[str, Any]],
) -> tuple[str, str | None, str | None]:
    if execution.status != "SUCCESS":
        return "FAILED", execution.error_code or "FLOW_FAILED", execution.error_message or "业务流程执行失败"
    if not required_all_passed(assertion_results):
        return "FAILED", "ASSERTION_FAILED", "断言未全部通过"
    return "PASSED", None, None


def _try_parse_json(text: str) -> object:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
