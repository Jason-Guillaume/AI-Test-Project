"""主流程执行器：顺序执行 Business Flow。

执行流程：
读取 BusinessFlow → 按 sort 加载 Action → 读取前置条件 →
读取默认 API Binding → 校验接口状态 → 解析 INPUT Mapping →
从 Context 获取变量 → 构造 HTTP Request → 执行 API →
保存 Request/Response → 解析 OUTPUT Mapping → 写入 Context →
执行 VariableRef → 进入下一 Action

任意步骤失败：默认停止整个 Flow。

错误代码标准化（Section 15）：
- FLOW_NOT_FOUND: 业务流程不存在
- ACTION_NOT_FOUND: 步骤不存在
- DEFAULT_BINDING_NOT_FOUND: 默认绑定未配置
- API_NOT_FOUND: 接口不存在
- API_DEPRECATED: 接口已废弃
- API_NOT_EXECUTABLE: 接口状态不允许执行（DEVELOPING/MOCK）
- MISSING_RUNTIME_VARIABLE: 运行时变量缺失
- PRECONDITION_FAILED: 前置条件不满足
- PRECONDITION_UNVERIFIED: 前置条件无法自动验证
- INPUT_MAPPING_FAILED: 输入映射失败
- OUTPUT_EXTRACTION_FAILED: 输出提取失败
- HTTP_REQUEST_FAILED: HTTP 请求失败
- HTTP_TIMEOUT: HTTP 请求超时
- INVALID_RESPONSE: 响应格式无效
- EXECUTION_CANCELLED: 执行已取消
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.features.business.executors.api_executor import ApiRequestExecutor
from app.features.business.executors.context import ExecutionContext
from app.features.business.executors.mapping_resolver import (
    resolve_input_mappings,
    resolve_output_mappings,
)
from app.features.business.executors.precondition_evaluator import evaluate_preconditions
from app.features.business.executors.sensitive import SensitiveDataMasker
from app.features.environment_configuration.services.environment_service import resolve_project_environment
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_api_mapping import BusinessApiMapping
from app.features.business.models.business_binding import BusinessBinding
from app.features.business.models.business_precondition import BusinessPrecondition
from app.features.business.models.business_variable import BusinessVariable
from app.features.business.models.business_variable_ref import BusinessVariableRef
from app.features.business.models.execution import ActionExecution, FlowExecution
from app.models.configuration import Environment
from app.models.identity import User
from app.shared.errors import not_found

_EXECUTOR = ApiRequestExecutor()

# 可执行的接口状态
_EXECUTABLE_API_STATUSES = {"ACTIVE"}
# 不可执行但需要特定错误信息的接口状态
_API_STATUS_ERROR_MESSAGES = {
    "DEPRECATED": "API_DEPRECATED",
    "DEVELOPING": "API_NOT_EXECUTABLE",
    "MOCK": "API_NOT_EXECUTABLE",
    "DELETED": "API_NOT_EXECUTABLE",
}


@dataclass
class ActionRunResult:
    """单个业务动作的执行结果（内存对象，不落库）。

    Data Factory 的 BUSINESS_ACTION Provider 消费它；``_execute_action`` 只是把它
    的字段搬到 ``ActionExecution`` 行上。快照已脱敏，错误码沿用执行器既有口径。
    """

    status: str = "FAILED"
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    outputs: dict[str, object] = field(default_factory=dict)
    input_context: dict[str, object] = field(default_factory=dict)
    output_context: dict[str, object] = field(default_factory=dict)
    request_snapshot: dict | None = None
    response_snapshot: dict | None = None
    binding_id: int | None = None
    unverified_preconditions: list[dict] = field(default_factory=list)


def run_action(
    db: Session,
    action_id: int,
    *,
    environment: Environment,
    variables: dict[str, object] | None = None,
    actor: User,
    project_id: int,
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
        ActionRunResult: 不写 ActionExecution 行；状态与错误码与 ``_execute_action`` 一致。
    """
    action = db.get(BusinessAction, action_id)
    if action is None:
        raise not_found("业务动作不存在")
    ctx = ExecutionContext(variables=variables or {})
    return _run_action_core(
        db, action, environment=environment, ctx=ctx, project_id=project_id, flow_id=None,
    )


def execute_flow(
    db: Session,
    flow_id: int,
    *,
    environment_id: int,
    variables: dict[str, object] | None = None,
    actor: User,
) -> FlowExecution:
    """执行一个业务流程。

    Args:
        db: 数据库会话。
        flow_id: 业务流程ID。
        environment_id: 执行环境ID。
        variables: 初始运行时变量。
        actor: 执行用户。

    Returns:
        FlowExecution: 执行记录（状态已更新）。
    """
    # 1. 加载环境与流程。
    # 资源不存在统一返 404（AppError 体系）：裸 ValueError 会被全局 handler
    # 归为 500「服务器内部错误」，用户看不到可读提示。
    flow = db.get(_FlowModel, flow_id)
    if flow is None:
        raise not_found("业务流程不存在")
    environment = resolve_project_environment(db, flow.project_id, environment_id)

    # 2. 创建执行记录。
    execution = FlowExecution(
        project_id=flow.project_id,
        flow_id=flow_id,
        environment_id=environment_id,
        status="RUNNING",
        started_at=datetime.now(),
        context_json=variables or {},
        created_by=actor.id,
    )
    db.add(execution)
    db.flush()

    ctx = ExecutionContext(variables=variables or {})

    # 3. 加载按 sort 排序的动作列表。
    actions = (
        db.query(BusinessAction)
        .filter(BusinessAction.flow_id == flow_id)
        .order_by(BusinessAction.sort.asc(), BusinessAction.id.asc())
        .all()
    )

    # 4. 顺序执行每个动作。
    # seq 从 0 开始，直接作为 ActionExecution.sequence：该列
    # server_default 为 0，注释为「执行序号（从 0 开始）」，故无需 +1。
    for seq, action in enumerate(actions):
        action_exec = _execute_action(
            db, execution, action, environment, ctx, project_id=flow.project_id,
            sequence=seq,
        )
        if action_exec.status == "FAILED":
            execution.status = "FAILED"
            execution.error_code = action_exec.error_code
            execution.error_message = action_exec.error_message
            execution.finished_at = datetime.now()
            # 保存当前上下文（脱敏后）。
            execution.context_json = _mask_context_for_storage(ctx)
            db.commit()
            return execution

    # 5. 所有步骤成功。
    execution.status = "SUCCESS"
    execution.context_json = _mask_context_for_storage(ctx)
    execution.finished_at = datetime.now()
    db.commit()
    return execution


def _mask_context_for_storage(ctx: ExecutionContext) -> dict:
    """将上下文序列化为可存储的 dict，并脱敏敏感字段。"""
    data = ctx.to_dict()
    if "variables" in data:
        data["variables"] = SensitiveDataMasker.mask_body(data["variables"])
    if "actions" in data:
        for k, v in data["actions"].items():
            data["actions"][k] = SensitiveDataMasker.mask_body(v)
    return _mask_web_secrets(data, ctx)


def _execute_action(
    db: Session,
    execution: FlowExecution,
    action: BusinessAction,
    environment: Environment,
    ctx: ExecutionContext,
    *,
    project_id: int,
    sequence: int = 0,
) -> ActionExecution:
    """执行单个业务动作并落库 ActionExecution。

    只负责「建行 + 把核心结果搬进字段」；前置条件、绑定、映射、HTTP、输出回写都在
    ``_run_action_core`` 里，与 ``run_action`` 共用，避免两套绑定查询漂移。
    """
    action_exec = ActionExecution(
        flow_execution_id=execution.id,
        action_id=action.id,
        sequence=sequence,
        status="RUNNING",
        started_at=datetime.now(),
    )
    db.add(action_exec)
    db.flush()

    result = _run_action_core(
        db, action, environment=environment, ctx=ctx,
        project_id=project_id, flow_id=execution.flow_id,
    )
    action_exec.status = result.status
    action_exec.error_code = result.error_code
    action_exec.error_message = result.error_message
    action_exec.duration_ms = result.duration_ms
    action_exec.binding_id = result.binding_id
    # 原实现把列表原样赋上去（可能为空列表）：保持空列表而不是 NULL，
    # 避免 report / 前端把它当「未采集」而不是「采集到 0 条」。
    action_exec.unverified_preconditions = result.unverified_preconditions
    action_exec.input_context = _mask_web_secrets(result.input_context, ctx)
    action_exec.output_context = _mask_web_secrets(result.output_context, ctx)
    action_exec.request_snapshot = _mask_web_secrets(result.request_snapshot, ctx)
    action_exec.response_snapshot = _mask_web_secrets(result.response_snapshot, ctx)
    action_exec.finished_at = datetime.now()
    return action_exec


def _run_action_core(
    db: Session,
    action: BusinessAction,
    *,
    environment: Environment,
    ctx: ExecutionContext,
    project_id: int,
    flow_id: int | None,
) -> ActionRunResult:
    """单个动作的执行核心：不建行、不提交事务，返回内存结果。"""
    result = ActionRunResult()
    try:
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
        web_binding = db.query(BusinessBinding).filter_by(
            action_id=action.id, binding_type="WEB", is_default=True, enabled=True,
        ).first()
        if web_binding is not None:
            from app.features.web_ui.runtime.adapter import run_web_binding
            web_result = run_web_binding(db, web_binding, environment=environment, ctx=ctx, project_id=project_id)
            ctx.set_action_output(action.action_key, web_result.outputs)
            if flow_id is not None and web_result.status == "SUCCESS":
                _apply_output_refs(db, flow_id, action, ctx)
            web_result.unverified_preconditions = unverified_pcs
            return web_result

        # 2. 加载默认 API Binding。
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
        if binding is None:
            result.error_code = "DEFAULT_BINDING_NOT_FOUND"
            result.error_message = f"动作「{action.name}」未配置默认 API 绑定"
            return result
        result.binding_id = binding.id

        # 3. 加载绑定接口。
        if binding.api_id is None:
            result.error_code = "API_NOT_FOUND"
            result.error_message = "绑定接口已失效（api_id 为空）"
            return result

        from app.features.api_catalog.models.api_interface import ApiInterface
        iface = db.get(ApiInterface, binding.api_id)
        if iface is None:
            result.error_code = "API_NOT_FOUND"
            result.error_message = "绑定接口已失效（接口不存在）"
            return result

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
            mapping_dicts, ctx.variables, required_vars,
        )
        result.input_context = _mask_context_variables(
            {k: ctx.get(k) for k in required_vars},
        )
        if errors:
            result.error_code = "MISSING_RUNTIME_VARIABLE"
            result.error_message = "; ".join(errors)
            return result

        # 7. 构造并执行 HTTP 请求。
        base_headers = _EXECUTOR.get_environment_headers(environment)
        base_headers.update(request_parts["headers"])

        url = _EXECUTOR.build_url(environment, iface.path, request_parts["path_params"])
        method = iface.method.upper()

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
            cookies=request_parts["cookies"] or None,
            json_body=json_body,
            timeout=30,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # 8. 保存脱敏后的请求/响应快照。
        result.request_snapshot = SensitiveDataMasker.mask_request(
            method, url, base_headers, request_parts["query"], json_body or {}, body_type,
        )
        result.response_snapshot = SensitiveDataMasker.mask_response(
            http_result.status_code, http_result.response_headers, _try_parse_json(http_result.response_body),
        )

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
            _apply_output_refs(db, flow_id, action, ctx)

        # 13. 标记成功。
        result.status = "SUCCESS"
        result.error_code = None
        result.error_message = None
        result.output_context = _mask_context_variables(
            {k: ctx.get(k) for k in output_vars},
        )
        result.duration_ms = elapsed_ms
        return result

    except Exception as exc:
        result.error_code = "EXECUTION_CANCELLED"
        result.error_message = f"执行异常：{exc}"
        return result


def _mask_web_secrets(data, ctx):
    """仅含 Web 动作时清除内存凭据登记并替换已知秘密值，API 原有路径不受影响。"""
    secrets = ctx.get("__web_sensitive_values", [])
    if not secrets:
        return data
    from app.features.web_ui.runtime.playwright_executor import scrub
    if isinstance(data, dict):
        data = dict(data)
        if isinstance(data.get("variables"), dict):
            data["variables"] = {k: v for k, v in data["variables"].items() if k != "__web_sensitive_values"}
    return scrub(data, secrets)


def _apply_output_refs(db, flow_id, action, ctx):
    """将动作输出通过既有 VariableRef 传递给后续动作，不改变上下文契约。"""
    refs = (
        db.query(BusinessVariableRef)
        .filter(BusinessVariableRef.flow_id == flow_id)
        .all()
    )
    for ref in refs:
        if ref.source_action_id == action.id and ref.target_action_id:
            # 模型列为 source_variable/target_variable（与 schemas 一致），此处必须同名读取。
            if ref.source_variable and ref.target_variable:
                # 优先从 action_output 命名空间查找，其次从 variables 查找。
                action_output = ctx.get_action_output(action.action_key)
                if action_output and ref.source_variable in action_output:
                    ctx.set(ref.target_variable, action_output[ref.source_variable])
                elif ref.source_variable in ctx.variables:
                    ctx.apply_ref(ref.source_variable, ref.target_variable)


def _mask_context_variables(data: dict) -> dict:
    """对上下文字典中的敏感字段进行脱敏。"""
    return SensitiveDataMasker.mask_body(data) if data else {}


def _try_parse_json(text: str) -> object:
    """尝试将文本解析为 JSON 对象。"""
    import json
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


# 延迟导入以避免循环依赖。
from app.features.business.models.business_flow import BusinessFlow as _FlowModel  # noqa: E402
