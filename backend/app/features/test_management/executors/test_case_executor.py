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
from app.features.business.executors.context import ExecutionContext
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
from app.features.test_data.runtime.data_factory import build_scope_variables
from app.features.test_data.runtime.variable_resolver import (
    ResolveScope,
    generate_faker_value,
    resolve_env_key,
    resolve_template,
)
from app.models.configuration import Environment
from app.models.identity import User
from app.shared.errors import CODE_DATA_RESOLVE_FAILED, CODE_VARIABLE_RESOLVE_FAILED, AppError

_EXECUTOR = ApiRequestExecutor()

#: source_type 里从已注入变量取的两种：value 是变量名，不是字面值。
_VAR_SOURCES = ("VARIABLE", "RUNTIME")


@dataclass
class CaseExecutionResult:
    """单用例执行结果（由 run_service 落库为 CaseExecution）。"""

    status: str = "PENDING"  # 执行状态：PASSED/FAILED/ERROR/SKIPPED
    executor_type: str | None = None
    request_snapshot: dict[str, Any] | None = None
    response_snapshot: dict[str, Any] | None = None
    assertion_results: list[dict[str, Any]] = field(default_factory=list)
    context_json: dict[str, Any] | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None


def execute(
    db: Session,
    test_case: TestCase,
    *,
    environment: Environment,
    actor: User,
    variables: ExecutionContext | None = None,
    extra_headers: dict[str, str] | None = None,
    run_id: int | None = None,
    case_execution_id: int | None = None,
) -> CaseExecutionResult:
    """执行单个测试用例，按 target_type 路由。

    ``variables`` 是 Data Factory 注入的运行时上下文（``LifecycleManager`` 产出，
    ``variables`` 里按 fixture_key 分组存契约输出）。不传时行为与原来一致，
    没有造数的旧用例照常执行。

    ``extra_headers`` 由调用方注入、平台级请求头（如 Mock 执行作用域的
    X-Mock-Context，见 MockLifecycle.context_headers）。先并入、再让用例自己的
    header 配置覆盖，所以被测系统侧显式配置优先；不传时行为与原来完全一致。
    仅 API / BUSINESS_ACTION 路径生效——BUSINESS_FLOW 由 business_flow_executor
    自行构造每个动作的请求，暂未接这条通道。

    ``run_id`` / ``case_execution_id`` 只供安全分支写 ``security_execution`` 时使用
    （Phase E 的最小签名扩展），对非安全用例没有任何影响。
    """
    started = time.perf_counter()
    target = (test_case.target_type or "API").upper()
    fixture_outputs = _fixture_outputs(variables)
    try:
        # 安全用例分支（Phase E）：只有存在 security_case 行才接管，非安全用例
        # 走下面的原分支，一行都不改。
        security_result = _try_security(
            db, test_case, environment=environment, actor=actor,
            fixture_outputs=fixture_outputs, extra_headers=extra_headers,
            run_id=run_id, case_execution_id=case_execution_id,
        )
        if security_result is not None:
            result = security_result
        elif target == "WEB":
            # Web 只增加独立分派，沿用 Fixture/Mock 与 CaseExecution 结果契约。
            from app.features.web_ui.runtime.adapter import run_web_case
            result = run_web_case(
                db, test_case, environment=environment, actor=actor,
                fixture_outputs=fixture_outputs,
                variables=variables.variables if variables else {},
                extra_headers=extra_headers, case_execution_id=case_execution_id,
            )
        elif target == "API":
            result = _execute_api(
                db, test_case, environment, actor, fixture_outputs, extra_headers
            )
        elif target == "BUSINESS_FLOW":
            result = _execute_business_flow(db, test_case, environment, actor, fixture_outputs, extra_headers)
        elif target == "BUSINESS_ACTION":
            result = _execute_business_action(
                db, test_case, environment, actor, fixture_outputs, extra_headers
            )
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
    except AppError as exc:
        # 造数/模板解析失败：ERROR + 原始错误码（DATA_RESOLVE_FAILED 等），
        # 绝不降级成 FAILED —— 断言从未执行过。
        result = CaseExecutionResult(
            status="ERROR", executor_type=target,
            error_code=exc.code or "EXECUTION_ERROR", error_message=str(exc),
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


def _try_security(
    db: Session,
    test_case: TestCase,
    *,
    environment: Environment,
    actor: User,
    fixture_outputs: dict[str, dict[str, Any]],
    extra_headers: dict[str, str] | None,
    run_id: int | None,
    case_execution_id: int | None,
) -> CaseExecutionResult | None:
    """安全用例分支：存在 ``security_case`` 行时接管，否则返回 None。

    延迟 import：安全侧 runner 反向引用本模块的执行助手，模块顶层不能互引。
    """
    from app.features.security_testing.runtime.runner import run_security_case

    return run_security_case(
        db,
        test_case,
        environment=environment,
        actor=actor,
        fixture_outputs=fixture_outputs,
        extra_headers=extra_headers,
        run_id=run_id,
        case_execution_id=case_execution_id,
    )


def _fixture_outputs(variables: ExecutionContext | None) -> dict[str, dict[str, Any]]:
    """从 ExecutionContext 取出 ``{fixture_key: {output_name: value}}``。

    值本身是 dict 的条目视为一个 Fixture 命名空间；扁平标量条目留给 ``${runtime.X}``，
    不参与 Fixture 解析。
    """
    if variables is None:
        return {}
    raw = variables.variables if isinstance(variables, ExecutionContext) else dict(variables or {})
    return {
        key: dict(value)
        for key, value in raw.items()
        if isinstance(value, dict)
    }


# --------------------------------------------------------------------------- API 接口


def _execute_api(
    db: Session,
    test_case: TestCase,
    environment: Environment,
    actor: User,
    fixture_outputs: dict[str, dict[str, Any]],
    extra_headers: dict[str, str] | None = None,
) -> CaseExecutionResult:
    """执行API。"""
    executor_type = "API"
    if test_case.api_id is None:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="API_NOT_CONFIGURED", error_message="用例未关联接口")
    iface = db.get(ApiInterface, test_case.api_id)
    if iface is None or iface.project_id != test_case.project_id:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="API_NOT_FOUND", error_message="关联接口不存在或不属于本项目")

    data_values, overrides = _load_data_values(db, test_case.id, environment, fixture_outputs)
    scope = _scope(data_values, environment, fixture_outputs)
    step_config = _load_action_step_config(db, test_case.id)

    # 请求构造：step_config 优先，缺省回退接口默认值 / 测试数据。
    # extra_headers 最先并入，环境头与用例 header 配置依次覆盖（显式配置优先）。
    method = (step_config.get("method") or iface.method or "GET").upper()
    path_params = _resolve_tokens(step_config.get("path_params") or {}, scope)
    headers = dict(extra_headers or {})
    headers.update(_EXECUTOR.get_environment_headers(environment))
    headers.update(_resolve_tokens(step_config.get("headers") or {}, scope))
    query = _resolve_tokens(step_config.get("query") or {}, scope)
    if step_config.get("body") is not None:
        json_body = _resolve_tokens(step_config.get("body"), scope)
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
    context_json: dict[str, Any] = {"data": data_values}
    if overrides:
        # 数据项名与 Fixture 输出同名时以数据项为准，冲突写进快照便于排查。
        context_json["fixture_overrides"] = overrides
    return CaseExecutionResult(
        status=status, executor_type=executor_type,
        request_snapshot=request_snapshot, response_snapshot=response_snapshot,
        assertion_results=assertion_results, context_json=context_json,
        error_code=error_code, error_message=error_message,
    )


# --------------------------------------------------------------------------- 业务流程 BUSINESS_FLOW


def _execute_business_flow(
    db: Session,
    test_case: TestCase,
    environment: Environment,
    actor: User,
    fixture_outputs: dict[str, dict[str, Any]],
    extra_headers: dict[str, str] | None = None,
) -> CaseExecutionResult:
    """执行业务流程。"""
    executor_type = "BUSINESS_FLOW"
    if test_case.business_flow_id is None:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="FLOW_NOT_CONFIGURED", error_message="用例未关联业务流程")
    flow = db.get(BusinessFlow, test_case.business_flow_id)
    if flow is None or flow.project_id != test_case.project_id:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code="FLOW_NOT_FOUND", error_message="关联业务流程不存在或不属于本项目")

    # Fixture 输出先进入，test_case_data 覆盖同名键（用例作者显式绑定优先）。
    data_values, overrides = _load_data_values(db, test_case.id, environment, fixture_outputs)
    initial_variables = {**_fixture_flat(fixture_outputs), **data_values}
    if extra_headers:
        initial_variables["__web_headers"] = extra_headers

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

    web_actions = [(ae, (ae.response_snapshot or {}).get("web")) for ae in action_execs]
    web_actions = [(ae, web) for ae, web in web_actions if web]
    if web_actions:
        # 报告仍读取 CaseExecution，混合流程的 Web 附件在原响应快照内聚合。
        response_snapshot["web"] = {
            "steps": [{**entry, "action_id": ae.action_id} for ae, web in web_actions for entry in web.get("steps", [])],
            "artifacts": [item for _, web in web_actions for item in web.get("artifacts", [])],
        }

    status, error_code, error_message = _decide_flow_status(execution, assertion_results)
    return CaseExecutionResult(
        status=status, executor_type=executor_type,
        request_snapshot=request_snapshot, response_snapshot=response_snapshot,
        assertion_results=assertion_results,
        context_json=execution.context_json,
        error_code=error_code, error_message=error_message,
    )


# --------------------------------------------------------------------------- 业务动作 BUSINESS_ACTION


def _execute_business_action(
    db: Session,
    test_case: TestCase,
    environment: Environment,
    actor: User,
    fixture_outputs: dict[str, dict[str, Any]],
    extra_headers: dict[str, str] | None = None,
) -> CaseExecutionResult:
    """执行业务动作。"""
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

    web_binding = db.query(BusinessBinding).filter_by(
        action_id=action.id, binding_type="WEB", is_default=True, enabled=True,
    ).first()
    if web_binding is not None:
        from app.features.web_ui.runtime.adapter import run_web_binding
        from app.features.web_ui.runtime.playwright_executor import scrub
        data_values, _ = _load_data_values(db, test_case.id, environment, fixture_outputs)
        ctx = ExecutionContext(variables={**_fixture_flat(fixture_outputs), **data_values})
        result = run_web_binding(
            db, web_binding, environment=environment, ctx=ctx,
            project_id=test_case.project_id, extra_headers=extra_headers,
        )
        # 外层 BUSINESS_ACTION 用例仍必须评估自身断言，不能因 WEB 内部通过而跳过。
        assertion_results = run_assertions(_load_assertions(db, test_case.id), {
            "status_code": 200 if result.status == "SUCCESS" else 500,
            "body": result.outputs, "raw_body": json.dumps(result.outputs, ensure_ascii=False),
            "headers": {}, "response_time_ms": result.duration_ms or 0,
        })
        passed = result.status == "SUCCESS" and required_all_passed(assertion_results)
        return CaseExecutionResult(
            status="PASSED" if passed else "FAILED", executor_type="BUSINESS_ACTION",
            request_snapshot=result.request_snapshot, response_snapshot=result.response_snapshot,
            assertion_results=scrub(assertion_results, ctx.get("__web_sensitive_values", [])),
            error_code=result.error_code or ("ASSERTION_FAILED" if not passed else None),
            error_message=result.error_message or ("业务动作断言失败" if not passed else None),
        )

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

    data_values, overrides = _load_data_values(db, test_case.id, environment, fixture_outputs)
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

    headers = dict(extra_headers or {})
    headers.update(_EXECUTOR.get_environment_headers(environment))
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
    context_json: dict[str, Any] = {"data": data_values}
    if overrides:
        context_json["fixture_overrides"] = overrides
    return CaseExecutionResult(
        status=status, executor_type=executor_type,
        request_snapshot=request_snapshot, response_snapshot=response_snapshot,
        assertion_results=assertion_results, context_json=context_json,
        error_code=error_code, error_message=error_message,
    )


# --------------------------------------------------------------------------- 辅助


def _load_data_values(
    db: Session,
    case_id: int,
    environment: Environment,
    fixture_outputs: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """加载测试数据并解析为 name→value（§12.1 的 source_type 分派）。

    - STATIC：value 字面值
    - ENVIRONMENT：环境键（base_url / gateway_prefix / default_headers）
    - FIXTURE：从 Data Factory 注入的契约输出取
    - FAKER：白名单生成器现取现造
    - VARIABLE / RUNTIME：value 是变量名，从已注入变量里取

    缺失且 ``required`` 的项抛 ``AppError(DATA_RESOLVE_FAILED)`` —— 用例 ERROR，
    不是 FAILED（造数/解析失败不等于产品断言失败）。
    返回的第二个元素是「数据项名与 Fixture 输出同名」的冲突列表，写进 context_json。
    """
    fixture_outputs = fixture_outputs or {}
    flat_names = {f"{key}.{name}" for key, values in fixture_outputs.items() for name in values}

    rows = (
        db.query(TestCaseData)
        .filter(TestCaseData.test_case_id == case_id)
        .order_by(TestCaseData.sort.asc(), TestCaseData.id.asc())
        .all()
    )
    values: dict[str, Any] = {}
    overrides: list[str] = []
    for row in rows:
        source = (row.source_type or "STATIC").upper()
        cfg = row.config_json if isinstance(row.config_json, dict) else {}
        if source == "ENVIRONMENT":
            values[row.name] = resolve_env_key(environment, row.value or "")
        elif source == "FIXTURE":
            values[row.name] = _fixture_output_value(row, cfg, fixture_outputs)
        elif source == "FAKER":
            values[row.name] = _faker_data_value(row, cfg)
        elif source in _VAR_SOURCES:
            values[row.name] = _lookup_variable((row.value or "").strip(), fixture_outputs, row)
        else:
            values[row.name] = _parse_value(row.value, row.value_type)
        if row.name in flat_names:
            overrides.append(row.name)
    return values, overrides


def _fixture_output_value(
    row: TestCaseData,
    cfg: dict[str, Any],
    fixture_outputs: dict[str, dict[str, Any]],
) -> Any:
    """FIXTURE 数据项：按 config_json 的 fixture_key/output 取已注入的契约输出。"""
    key = str(cfg.get("fixture_key") or "").strip()
    output = str(cfg.get("output") or "").strip()
    if not key or not output:
        raise AppError(
            f"测试数据 {row.name} 的 FIXTURE 配置缺少 fixture_key 或 output",
            status_code=400,
            code=CODE_DATA_RESOLVE_FAILED,
        )
    outs = fixture_outputs.get(key)
    found = isinstance(outs, dict) and output in outs and outs[output] is not None
    if not found and row.required:
        raise AppError(
            f"测试数据 {row.name} 引用的 Fixture 输出 {key}.{output} 不可用",
            status_code=400,
            code=CODE_DATA_RESOLVE_FAILED,
        )
    return outs.get(output) if isinstance(outs, dict) else None


def _faker_data_value(row: TestCaseData, cfg: dict[str, Any]) -> Any:
    """FAKER 数据项：只调白名单生成器，不执行用户代码。"""
    generator = str(cfg.get("generator") or "").strip()
    if not generator:
        raise AppError(
            f"测试数据 {row.name} 的 FAKER 配置缺少 generator",
            status_code=400,
            code=CODE_VARIABLE_RESOLVE_FAILED,
        )
    locale = str(cfg.get("locale") or "zh_CN")
    choices = cfg.get("choices") if isinstance(cfg.get("choices"), list) else None
    try:
        return generate_faker_value(generator, locale=locale, choices=choices)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - Faker 内部异常收敛成统一错误码
        raise AppError(
            f"测试数据 {row.name} 的 FAKER 生成失败（generator={generator}）：{exc}",
            status_code=400,
            code=CODE_VARIABLE_RESOLVE_FAILED,
        ) from exc


def _lookup_variable(
    target: str,
    fixture_outputs: dict[str, dict[str, Any]],
    row: TestCaseData,
) -> Any:
    """VARIABLE / RUNTIME 数据项：value 是变量名，不是字面值。

    依次按 fixture_key、输出名、`KEY.name` 三种写法找；找不到且必需时报
    ``DATA_RESOLVE_FAILED``。
    """
    if not target:
        if row.required:
            raise AppError(
                f"测试数据 {row.name} 的 source_type={row.source_type} 缺少变量名",
                status_code=400,
                code=CODE_DATA_RESOLVE_FAILED,
            )
        return None
    for key, values in fixture_outputs.items():
        if target == key:
            return dict(values)
        if isinstance(values, dict) and target in values:
            return values[target]
        if isinstance(values, dict) and f"{key}.{target}" in values:
            return values[f"{key}.{target}"]
    if row.required:
        raise AppError(
            f"测试数据 {row.name} 引用的变量 {target} 不可用",
            status_code=400,
            code=CODE_DATA_RESOLVE_FAILED,
        )
    return None


def _fixture_flat(fixture_outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fixture 输出的扁平视图 ``KEY.name → value``，供业务流变量使用。"""
    flat: dict[str, Any] = {}
    for key, values in fixture_outputs.items():
        for name, value in values.items():
            flat[f"{key}.{name}"] = value
    return flat


def _scope(
    data_values: dict[str, Any],
    environment: Environment,
    fixture_outputs: dict[str, dict[str, Any]],
) -> ResolveScope:
    """用例执行器的模板作用域：`${data.X}` 走测试数据，`${env.X}` 走环境，
    `${fixture.K.n}` / `${runtime.X}` 走 Data Factory 注入的输出。"""
    return ResolveScope(
        variables=build_scope_variables(fixture_outputs),
        data_values=data_values,
        environment=environment,
    )


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
    """加载`assertions`。"""
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


def _resolve_tokens(obj: Any, scope: ResolveScope) -> Any:
    """占位符解析统一委托 VariableResolver（§12.1：执行器不再自己写正则）。

    支持 ``${data.X}`` / ``${env.X}``（原有语义不变），以及 Phase C 新增的
    ``${fixture.KEY.name}`` / ``${runtime.X}`` / ``${faker.X}``。
    """
    return resolve_template(obj, scope, required=False)


def _build_response_dict(resp) -> dict[str, Any]:
    """构建响应字典。"""
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
    """处理`decide`状态相关数据。"""
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
    """处理`decide`流程状态相关数据。"""
    if execution.status != "SUCCESS":
        return "FAILED", execution.error_code or "FLOW_FAILED", execution.error_message or "业务流程执行失败"
    if not required_all_passed(assertion_results):
        return "FAILED", "ASSERTION_FAILED", "断言未全部通过"
    return "PASSED", None, None


def _try_parse_json(text: str) -> object:
    """尝试将响应文本解析为 JSON；解析失败时返回空结果。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
