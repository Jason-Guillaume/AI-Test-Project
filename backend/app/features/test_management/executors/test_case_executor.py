"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import time
from typing import Any
from sqlalchemy.orm import Session
from app.features.business.executors.context import ExecutionContext
from app.features.test_management.models.test_case import TestCase
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.errors import AppError
from app.features.test_management.executors.contracts import CaseExecutionResult
from app.features.test_management.executors.adapters.api import execute_api
from app.features.test_management.executors.adapters.business import execute_business_action
from app.features.test_management.executors.adapters.business import execute_business_flow
from app.features.test_management.executors.preparation import extract_fixture_outputs


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
    BUSINESS_FLOW 将请求头传给流程内的 API 和 Web 动作。

    ``run_id`` / ``case_execution_id`` 只供安全分支写 ``security_execution`` 时使用
    （Phase E 的最小签名扩展），对非安全用例没有任何影响。
    """
    started = time.perf_counter()
    target = (test_case.target_type or "API").upper()
    fixture_outputs = extract_fixture_outputs(variables)
    try:
        # 安全用例分支（Phase E）：只有存在 security_case 行才接管，非安全用例
        # 走下面的原分支，一行都不改。
        security_result = try_security(
            db, test_case, environment=environment, actor=actor,
            fixture_outputs=fixture_outputs, extra_headers=extra_headers,
            run_id=run_id, case_execution_id=case_execution_id,
        )
        if security_result is not None:
            result = security_result
        elif target == "WEB":
            # Web 只增加独立分派，沿用 Fixture/Mock 与 CaseExecution 结果契约。
            from app.features.test_management.executors.adapters.web import execute_web
            result = execute_web(
                db, test_case, environment=environment, actor=actor,
                fixture_outputs=fixture_outputs,
                variables=variables.variables if variables else {},
                extra_headers=extra_headers, case_execution_id=case_execution_id,
            )
        elif target == "API":
            result = execute_api(
                db, test_case, environment, actor, fixture_outputs, extra_headers
            )
        elif target == "BUSINESS_FLOW":
            result = execute_business_flow(db, test_case, environment, actor, fixture_outputs, extra_headers)
        elif target == "BUSINESS_ACTION":
            result = execute_business_action(
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


def try_security(
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
