"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import json
from typing import Any
from sqlalchemy.orm import Session
from app.features.business.executors.business_flow_executor import execute_flow
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_flow import BusinessFlow
from app.features.business.models.execution import ActionExecution
from app.features.test_management.executors.assertion_engine import required_all_passed, run_assertions
from app.features.test_management.models.test_case import TestCase
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.features.test_management.executors.contracts import CaseExecutionResult
from app.features.test_management.executors.results import build_flow_response
from app.features.test_management.executors.results import build_response_dict
from app.features.test_management.executors.results import decide_flow_status
from app.features.test_management.executors.results import decide_status
from app.features.test_management.executors.preparation import fixture_flat
from app.features.test_management.executors.preparation import load_assertions
from app.features.test_management.executors.preparation import load_data_values


def execute_business_flow(
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
    data_values, overrides = load_data_values(db, test_case.id, environment, fixture_outputs)
    initial_variables = {**fixture_flat(fixture_outputs), **data_values}
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
    response = build_flow_response(execution, action_execs)
    assertions = load_assertions(db, test_case.id)
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

    status, error_code, error_message = decide_flow_status(execution, assertion_results)
    return CaseExecutionResult(
        status=status, executor_type=executor_type,
        request_snapshot=request_snapshot, response_snapshot=response_snapshot,
        assertion_results=assertion_results,
        context_json=execution.context_json,
        error_code=error_code, error_message=error_message,
    )


def execute_business_action(
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

    from app.features.business.executors.action_executor import run_action
    from app.core.security.sanitizer import mask_known_secrets

    from app.features.business.executors.targets import prepare_case_action_target
    target = prepare_case_action_target(db, action.id, test_case.project_id)
    if target.error_code:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code=target.error_code, error_message=target.error_message)
    data_values, overrides = load_data_values(db, test_case.id, environment, fixture_outputs)
    result = run_action(
        db, action.id, environment=environment, actor=actor, project_id=test_case.project_id,
        variables=data_values, case_mode=True, extra_headers=extra_headers, prepared_target=target,
        web_variables={**fixture_flat(fixture_outputs), **data_values},
    )
    if result.is_web:
        assertion_results = run_assertions(load_assertions(db, test_case.id), {
            "status_code": 200 if result.status == "SUCCESS" else 500,
            "body": result.outputs, "raw_body": json.dumps(result.outputs, ensure_ascii=False),
            "headers": {}, "response_time_ms": result.duration_ms or 0,
        })
        passed = result.status == "SUCCESS" and required_all_passed(assertion_results)
        return CaseExecutionResult(
            status="PASSED" if passed else "FAILED", executor_type=executor_type,
            request_snapshot=result.request_snapshot, response_snapshot=result.response_snapshot,
            assertion_results=mask_known_secrets(assertion_results, result.web_sensitive_values),
            error_code=result.error_code or ("ASSERTION_FAILED" if not passed else None),
            error_message=result.error_message or ("业务动作断言失败" if not passed else None),
        )
    if result.http_result is None:
        return CaseExecutionResult(status="ERROR", executor_type=executor_type,
                                   error_code=result.error_code, error_message=result.error_message)
    assertion_results = run_assertions(load_assertions(db, test_case.id), build_response_dict(result.http_result))
    status, error_code, error_message = decide_status(result.http_result, assertion_results)
    context_json = {"data": data_values}
    if overrides:
        context_json["fixture_overrides"] = overrides
    return CaseExecutionResult(
        status=status, executor_type=executor_type,
        request_snapshot=result.request_snapshot, response_snapshot=result.response_snapshot,
        assertion_results=assertion_results, context_json=context_json,
        error_code=error_code, error_message=error_message,
    )
