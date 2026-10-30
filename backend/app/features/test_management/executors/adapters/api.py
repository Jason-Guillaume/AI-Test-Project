"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.features.api_catalog.models.api_interface import ApiInterface
from app.execution.http.executor import ApiRequestExecutor
from app.execution.http.request_builder import build_environment_url, get_environment_headers
from app.core.security.sensitive import SensitiveDataMasker
from app.features.test_management.executors.assertion_engine import run_assertions
from app.features.test_management.models.test_case import TestCase
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.features.test_management.executors.contracts import CaseExecutionResult
from app.features.test_management.executors.results import build_response_dict
from app.features.test_management.executors.results import decide_status
from app.features.test_management.executors.preparation import load_action_step_config
from app.features.test_management.executors.preparation import load_assertions
from app.features.test_management.executors.preparation import load_data_values
from app.features.test_management.executors.preparation import resolve_tokens
from app.features.test_management.executors.preparation import build_execution_scope
from app.features.test_management.executors.results import try_parse_json


_EXECUTOR = ApiRequestExecutor()


def execute_api(
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

    data_values, overrides = load_data_values(db, test_case.id, environment, fixture_outputs)
    scope = build_execution_scope(data_values, environment, fixture_outputs)
    step_config = load_action_step_config(db, test_case.id)

    # 请求构造：step_config 优先，缺省回退接口默认值 / 测试数据。
    # extra_headers 最先并入，环境头与用例 header 配置依次覆盖（显式配置优先）。
    method = (step_config.get("method") or iface.method or "GET").upper()
    path_params = resolve_tokens(step_config.get("path_params") or {}, scope)
    headers = dict(extra_headers or {})
    headers.update(get_environment_headers(environment))
    headers.update(resolve_tokens(step_config.get("headers") or {}, scope))
    query = resolve_tokens(step_config.get("query") or {}, scope)
    if step_config.get("body") is not None:
        json_body = resolve_tokens(step_config.get("body"), scope)
    elif data_values:
        json_body = data_values
    else:
        json_body = None
    timeout = int(step_config.get("timeout", 30))

    url = build_environment_url(environment, iface.path, path_params)

    resp = _EXECUTOR.execute(
        db, method=method, url=url, project_id=test_case.project_id,
        headers=headers or None, query=query or None, json_body=json_body,
        timeout=timeout,
    )

    response = build_response_dict(resp)
    assertions = load_assertions(db, test_case.id)
    assertion_results = run_assertions(assertions, response)

    request_snapshot = SensitiveDataMasker.mask_request(
        method, url, headers, query, json_body or {}, "json" if json_body else "none",
    )
    response_snapshot = SensitiveDataMasker.mask_response(
        resp.status_code, resp.response_headers, try_parse_json(resp.response_body),
    )

    status, error_code, error_message = decide_status(resp, assertion_results)
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
