"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from app.execution.http.executor import ApiRequestExecutor
from app.execution.http.request_builder import build_environment_url
from app.features.security_testing.models import SecurityMutationRule
from app.features.security_testing.runtime import assertion as assertion_mod
from app.features.security_testing.runtime import (
    replay as replay_mod,
    severity as severity_mod,
    trace as trace_mod,
)
from app.features.security_testing.runtime.mutation_engine import SecurityMutationEngine
from app.features.security_testing.runtime.types import (
    ConfirmationRequiredError,
    MutationTraceEntry,
    RuleNotApplicableError,
)
from app.features.test_management.executors.contracts import CaseExecutionResult
from app.features.test_management.models.test_case import TestCase
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.errors import (
    CODE_SECURITY_BASELINE_FAILED,
    CODE_SECURITY_CONFIRMATION_REQUIRED,
    CODE_SECURITY_EXECUTION_FAILED,
    CODE_SECURITY_MUTATION_NOT_ALLOWED,
    CODE_SECURITY_TARGET_NOT_ALLOWED,
    AppError,
)
from app.features.security_testing.runtime.result_writer import CaseContext
from app.features.security_testing.runtime.preparation import _BASELINE_OK_MAX
from app.features.security_testing.runtime.preparation import _BASELINE_OK_MIN
from app.features.security_testing.runtime.result_writer import _CASE_STATUS_BY_RESULT
from app.features.security_testing.runtime.evidence import auth_header_present
from app.features.security_testing.runtime.preparation import baseline_status_of
from app.features.security_testing.runtime.evidence import build_evidence
from app.features.security_testing.runtime.preparation import build_request
from app.features.security_testing.runtime.candidate_values import candidate_value
from app.features.security_testing.runtime.preparation import environment_decision
from app.features.security_testing.runtime.preparation import environment_error_code
from app.features.security_testing.runtime.preparation import environment_message
from app.features.security_testing.runtime.evidence import finding_description
from app.features.security_testing.runtime.evidence import finding_recommendation
from app.features.security_testing.runtime.evidence import finding_title
from app.features.security_testing.runtime.evidence import fingerprint
from app.features.security_testing.runtime.preparation import load_fields
from app.features.security_testing.runtime.preparation import load_security_case
from app.features.security_testing.runtime.evidence import parsed_body
from app.features.security_testing.runtime.preparation import resolve_api
from app.features.security_testing.runtime.evidence import rule_text
from app.features.security_testing.runtime.preparation import build_rule_view
from app.features.test_management.executors.adapters.api import execute_api
from app.features.test_management.executors.adapters.business import (
    execute_business_action,
    execute_business_flow,
)
from app.features.security_testing.runtime.evidence import single_outcome
from app.features.security_testing.runtime.result_writer import upsert_finding
from app.features.security_testing.runtime.result_writer import write_execution


_EXECUTOR = ApiRequestExecutor()


REPLAY_FAMILY = ("REPLAY_SAME_REQUEST", "DUPLICATE_SUBMIT")


BUSINESS_FLOW_FAMILY = ("BUSINESS_STATE", "SEQUENCE_BYPASS")


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
    security_case = load_security_case(db, test_case)
    if security_case is None:
        return None

    started = datetime.now()
    outputs = dict(fixture_outputs or {})
    ctx = CaseContext(
        db,
        security_case=security_case,
        environment=environment,
        actor=actor,
        run_id=run_id,
        case_execution_id=case_execution_id,
        started_at=started,
    )

    # 2. 环境闸门（§18.3）：不构造请求，也不发请求；基线同样不发。
    decision = environment_decision(db, security_case.project_id, environment)
    if not decision.allowed:
        return ctx.finish(
            test_case,
            security_result="SKIPPED",
            classification="TARGET_BLOCKED",
            error_code=environment_error_code(decision),
            message=environment_message(decision),
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

    api_id, iface = resolve_api(db, security_case, baseline_case)
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
        request = build_request(
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
    baseline_result = run_baseline(db, baseline_case, environment, actor, outputs, extra_headers)
    baseline_http = baseline_status_of(baseline_result)
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
    rule_view = build_rule_view(security_case, rule, config)
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
                fields=load_fields(db, iface.id),
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
        """发送`once`。"""
        # 重放循环会把同一个请求对象传回来；这里只用它作为「本次是重放执行」的信号，
        # 请求内容始终是上面变异出来的那份。
        return send(
            db,
            method=mutated_request.method,
            url=build_environment_url(environment, mutated_request.path, mutated_request.path_params),
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
            outcome = single_outcome(send_once())
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
        response_body=parsed_body(outcome.bodies[-1]) if outcome.bodies else None,
        response_bodies=[parsed_body(body) for body in outcome.bodies],
        trace=trace_dicts,
        expected_status_codes=expected_codes or None,
        auth_type=getattr(iface, "auth_type", "none"),
        baseline_auth_present=auth_header_present(request.headers),
    )

    # 请求一次都没打到服务端时，业务断言没有意义。
    if not reached_server:
        security_result = "FAILED_EXECUTION"
        classification = "TRANSPORT_ERROR"
    else:
        security_result = assertion_result.security_result
        classification = assertion_result.classification

    # 9. 写 execution。
    execution = write_execution(
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
                response_body=parsed_body(outcome.bodies[-1]) if outcome.bodies else None,
                candidate_resource_id=candidate_value(config, outputs),
                method=mutated_request.method,
                rule_severity=rule_view.severity,
            )
        )
        if severity_value:
            finding = upsert_finding(
                db,
                project_id=project_id,
                test_run_id=run_id,
                case_execution_id=case_execution_id,
                security_execution_id=execution.id,
                security_case=security_case,
                fingerprint=fingerprint(
                    api_id=api_id,
                    mutation_type=mutation_type,
                    location=rule_view.target_location,
                    field=rule_view.target_field,
                    baseline_case_id=baseline_case.id,
                ),
                severity=severity_value,
                evidence=build_evidence(
                    rule_view=rule_view,
                    baseline_status=baseline_http,
                    actual_status_codes=statuses,
                    trace=trace_dicts,
                    message=assertion_result.message,
                    mutation_type=mutation_type,
                    name=rule_text(rule, "name") or None,
                ),
                title=finding_title(rule_text(rule, "name"), mutation_type),
                description=finding_description(
                    rule_text(rule, "description"), message=assertion_result.message
                ),
                recommendation=finding_recommendation(mutation_type),
                actor=actor,
                mutation_type=mutation_type,
            )
            if finding is not None:
                db.add(finding)
                db.flush()

    return CaseExecutionResult(
        status=_CASE_STATUS_BY_RESULT.get(security_result, "SKIPPED"),
        executor_type="SECURITY",
        request_snapshot=baseline_result.request_snapshot,
        response_snapshot={
            "status_code": statuses[-1] if statuses else 0,
            "actual_status_codes": statuses,
            "body": trace_mod.mask_body(parsed_body(outcome.bodies[-1])) if outcome.bodies else None,
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


def run_baseline(
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
        return execute_business_flow(db, baseline_case, environment, actor, fixture_outputs)
    if target == "BUSINESS_ACTION":
        return execute_business_action(
            db, baseline_case, environment, actor, fixture_outputs, extra_headers
        )
    return execute_api(db, baseline_case, environment, actor, fixture_outputs, extra_headers)
