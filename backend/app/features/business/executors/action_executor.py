"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import time
from sqlalchemy.orm import Session
from app.execution.http.executor import ApiRequestExecutor
from app.execution.http.request_builder import build_environment_url, get_environment_headers
from app.features.business.executors.context import ExecutionContext
from app.features.business.executors.mapping_resolver import resolve_input_mappings, resolve_output_mappings
from app.features.business.executors.precondition_evaluator import evaluate_preconditions
from app.core.security.sensitive import SensitiveDataMasker
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_api_mapping import BusinessApiMapping
from app.features.business.models.business_precondition import BusinessPrecondition
from app.features.business.models.business_variable import BusinessVariable
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.errors import not_found
from app.features.business.executors.contracts import ActionRunResult, PreparedActionTarget
from app.features.business.executors.targets import load_default_binding
from app.features.business.executors.output_state import apply_output_refs
from app.features.business.executors.masking import mask_context_variables
from app.features.business.executors.masking import try_parse_json


_EXECUTOR = ApiRequestExecutor()


_EXECUTABLE_API_STATUSES = {"ACTIVE"}


_API_STATUS_ERROR_MESSAGES = {
    "DEPRECATED": "API_DEPRECATED",
    "DEVELOPING": "API_NOT_EXECUTABLE",
    "MOCK": "API_NOT_EXECUTABLE",
    "DELETED": "API_NOT_EXECUTABLE",
}


def merge_action_headers(ctx: ExecutionContext, environment_headers: dict, action_headers: dict) -> dict:
    """Inject runtime headers while preserving environment and action overrides."""
    runtime_headers = ctx.get("__web_headers")
    headers = dict(runtime_headers) if isinstance(runtime_headers, dict) else {}
    headers.update(environment_headers)
    headers.update(action_headers)
    return headers


def run_action(
    db: Session,
    action_id: int,
    *,
    environment: Environment,
    variables: dict[str, object] | None = None,
    actor: User,
    project_id: int,
    case_mode: bool = False,
    extra_headers: dict[str, str] | None = None,
    web_variables: dict[str, object] | None = None,
    prepared_target: PreparedActionTarget | None = None,
) -> ActionRunResult:
    """执行单个业务动作（不跑整条流程）。

    给 Data Factory 的 BUSINESS_ACTION Provider 用：动作输入来自当前私有变量
    （依赖 Fixture 已经注入的 user_id 等），输出合并回私有变量后再由
    ``fixture_output`` 挑选。

    注意：这里是**单个动作**，不是 ``execute_flow``。调用 ``execute_flow`` 会把
    整条流程跑完，且它会自己 commit，外层事务边界会不可控。

    Args:
        db: 数据库会话。
        action_id: 业务动作 ID。
        environment: 执行环境（调用方已解析好，不再由动作自己挑）。
        variables: 初始运行时变量。
        actor: 执行用户。
        project_id: 归属项目（供出站白名单校验用）。

    Returns:
        ActionRunResult: 不写 ActionExecution 行；状态与错误码与 ``execute_action`` 一致。
    """
    action = db.get(BusinessAction, action_id)
    if action is None:
        raise not_found("业务动作不存在")
    ctx = ExecutionContext(variables=variables or {})
    if extra_headers and not case_mode:
        ctx.set("__web_headers", dict(extra_headers))
    return run_action_core(
        db, action, environment=environment, ctx=ctx, project_id=project_id, flow_id=None,
        case_mode=case_mode, extra_headers=extra_headers, web_variables=web_variables, prepared_target=prepared_target,
    )


def run_action_core(
    db: Session,
    action: BusinessAction,
    *,
    environment: Environment,
    ctx: ExecutionContext,
    project_id: int,
    flow_id: int | None,
    case_mode: bool = False,
    extra_headers: dict[str, str] | None = None,
    web_variables: dict[str, object] | None = None,
    prepared_target: PreparedActionTarget | None = None,
) -> ActionRunResult:
    """单个动作的执行核心：不建行、不提交事务，返回内存结果。"""
    result = ActionRunResult()
    try:
        unverified_pcs = []
        # 测试动作沿用既有用例语义；流程/Provider 仍校验业务前置条件。
        if not case_mode:
            # 1. 评估前置条件。
            preconditions = (
                db.query(BusinessPrecondition)
                .filter(BusinessPrecondition.action_id == action.id)
                .order_by(BusinessPrecondition.sort.asc())
                .all()
            )
            pc_dicts = [
                {"id": pc.id, "type": pc.type, "target": pc.target,
                 "operator": pc.operator, "expected_value": pc.expected_value}
                for pc in preconditions
            ]
            pc_results, all_passed = evaluate_preconditions(pc_dicts, ctx.variables)

            # 收集无法自动验证的前置条件（BUSINESS/TEXT 类型）。
            unverified_pcs = []
            for pc, pr in zip(pc_dicts, pc_results):
                if "MANUAL" in (pr.reason or "") or "NOT_EXECUTABLE" in (pr.reason or ""):
                    unverified_pcs.append({
                        "id": pc["id"],
                        "type": pc["type"],
                        "target": pc["target"],
                        "reason": pr.reason,
                    })
            result.unverified_preconditions = unverified_pcs

            if not all_passed:
                result.error_code = "PRECONDITION_FAILED"
                result.error_message = "前置条件不满足"
                return result

        # 显式 WEB 默认绑定优先；API 路径及既有签名不变，浏览器会话由 Web 资源池独占。
        web_binding = (
            prepared_target.binding if prepared_target and prepared_target.is_web
            else None if prepared_target else load_default_binding(db, action.id, "WEB")
        )
        if web_binding is not None:
            from app.features.web_testing.services.execution_adapter import run_web_binding
            if case_mode and web_variables is not None:
                for key, value in web_variables.items():
                    ctx.set(key, value)
            web_result = run_web_binding(db, web_binding, environment=environment, ctx=ctx, project_id=project_id, extra_headers=extra_headers)
            web_result.is_web = True
            web_result.web_sensitive_values = list(ctx.get("__web_sensitive_values", []))
            ctx.set_action_output(action.action_key, web_result.outputs)
            if flow_id is not None and web_result.status == "SUCCESS":
                apply_output_refs(db, flow_id, action, ctx)
            web_result.unverified_preconditions = unverified_pcs
            return web_result

        # 2. 加载默认 API Binding。
        binding = prepared_target.binding if prepared_target else load_default_binding(db, action.id, "API")
        if binding is None or (case_mode and binding.api_id is None):
            result.error_code = "DEFAULT_BINDING_NOT_FOUND"
            result.error_message = "业务动作未配置默认 API 绑定" if case_mode else f"动作「{action.name}」未配置默认 API 绑定"
            return result
        result.binding_id = binding.id

        # 3. 加载绑定接口。
        if binding.api_id is None:
            result.error_code = "API_NOT_FOUND"
            result.error_message = "绑定接口已失效（api_id 为空）"
            return result

        from app.features.api_catalog.models.api_interface import ApiInterface
        iface = prepared_target.interface if prepared_target else db.get(ApiInterface, binding.api_id)
        if iface is None or (case_mode and iface.project_id != project_id):
            result.error_code = "API_NOT_FOUND"
            result.error_message = "绑定接口已失效" if case_mode else "绑定接口已失效（接口不存在）"
            return result

        if not case_mode:
            # 3.1. 校验接口状态（Section 5）。
            api_status = (iface.status or "").upper()
            if api_status == "DELETED" or api_status == "":
                result.error_code = "API_NOT_EXECUTABLE"
                result.error_message = f"接口状态为 {api_status or 'NULL'}，不允许执行"
                return result
            if api_status not in _EXECUTABLE_API_STATUSES:
                result.error_code = _API_STATUS_ERROR_MESSAGES.get(api_status, "API_NOT_EXECUTABLE")
                result.error_message = f"接口状态为 {api_status}，不允许执行（仅 ACTIVE 状态可执行）"
                return result

        # 4. 加载 INPUT/OUTPUT 映射。
        mappings = (
            db.query(BusinessApiMapping)
            .filter(BusinessApiMapping.binding_id == binding.id)
            .all()
        )
        mapping_dicts = [
            {"direction": m.direction, "business_variable": m.business_variable,
             "api_location": m.api_location, "api_field": m.api_field,
             "expression": m.expression}
            for m in mappings
        ]

        # 5. 加载变量 required 信息。
        variables = (
            db.query(BusinessVariable)
            .filter(BusinessVariable.action_id == action.id)
            .all()
        )
        required_vars = {v.name: v.required for v in variables if v.direction == "INPUT"}

        # 6. 解析 INPUT 映射。
        request_parts, errors = resolve_input_mappings(
            mapping_dicts, ctx.variables, {} if case_mode else required_vars,
        )
        result.input_context = mask_context_variables(
            {k: ctx.get(k) for k in required_vars},
        )
        if errors:
            result.error_code = "INPUT_MAPPING_FAILED" if case_mode else "MISSING_RUNTIME_VARIABLE"
            result.error_message = "; ".join(errors)
            return result

        # 7. 构造并执行 HTTP 请求。
        if case_mode:
            # 用例数据里的保留名称仍是普通映射值，不能变成平台运行时请求头。
            base_headers = dict(extra_headers or {})
            base_headers.update(get_environment_headers(environment))
            base_headers.update(request_parts["headers"])
        else:
            base_headers = merge_action_headers(
                ctx, get_environment_headers(environment), request_parts["headers"]
            )

        url = build_environment_url(environment, iface.path, request_parts["path_params"])
        method = (iface.method or "GET").upper()

        # 构造 body。
        json_body = request_parts["body"] if request_parts["body"] else None
        body_type = "json" if json_body else "none"

        started = time.perf_counter()
        http_result = _EXECUTOR.execute(
            db,
            method=method,
            url=url,
            project_id=project_id,
            headers=base_headers,
            query=request_parts["query"] or None,
            cookies=None if case_mode else (request_parts["cookies"] or None),
            json_body=json_body,
            timeout=30,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # 8. 保存脱敏后的请求/响应快照。
        result.request_snapshot = SensitiveDataMasker.mask_request(
            method, url, base_headers, request_parts["query"], json_body or {}, body_type,
        )
        result.response_snapshot = SensitiveDataMasker.mask_response(
            http_result.status_code, http_result.response_headers, try_parse_json(http_result.response_body),
        )

        # 单动作用例只评估自身断言，不额外运行流程输出契约。
        if case_mode:
            result.http_result = http_result
            result.duration_ms = elapsed_ms
            result.status = "SUCCESS" if http_result.success else "FAILED"
            return result

        if http_result.error_message:
            result.error_code = (
                "HTTP_TIMEOUT" if "超时" in http_result.error_message else "HTTP_REQUEST_FAILED"
            )
            result.error_message = http_result.error_message
            result.duration_ms = elapsed_ms
            return result

        # 9. 解析 OUTPUT 映射。
        output_vars = {v.name: v.required for v in variables if v.direction == "OUTPUT"}
        extracted, warnings = resolve_output_mappings(
            mapping_dicts, http_result.response_body, output_vars,
        )

        # 如果提取失败但有 required 变量，记录错误代码。
        missing_required = [
            w for w in warnings
            if "required" in w.lower() or "缺失" in w
        ]
        if missing_required:
            result.error_code = "OUTPUT_EXTRACTION_FAILED"

        for var_name, value in extracted.items():
            if value is not None:
                ctx.set(var_name, value)

        # 10. 检查 HTTP 状态码。
        if not http_result.success:
            result.error_code = "HTTP_REQUEST_FAILED"
            result.error_message = f"HTTP {http_result.status_code}: {http_result.response_body[:500]}"
            result.duration_ms = elapsed_ms
            return result

        # 11. 保存 Action 输出到 namespaced context（Section 3）。
        output_output = {k: extracted.get(k) for k in output_vars if extracted.get(k) is not None}
        ctx.set_action_output(action.action_key, output_output)
        result.outputs = dict(output_output)

        # 12. API 与 Web 共用同一变量引用传递规则。
        if flow_id is not None:
            apply_output_refs(db, flow_id, action, ctx)

        # 13. 标记成功。
        result.status = "SUCCESS"
        result.error_code = None
        result.error_message = None
        result.output_context = mask_context_variables(
            {k: ctx.get(k) for k in output_vars},
        )
        result.duration_ms = elapsed_ms
        return result

    except Exception as exc:
        result.error_code = "EXECUTION_CANCELLED"
        result.error_message = f"执行异常：{exc}"
        return result
