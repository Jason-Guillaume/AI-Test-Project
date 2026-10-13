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
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_api_mapping import BusinessApiMapping
from app.features.business.models.business_binding import BusinessBinding
from app.features.business.models.business_precondition import BusinessPrecondition
from app.features.business.models.business_variable import BusinessVariable
from app.features.business.models.business_variable_ref import BusinessVariableRef
from app.features.business.models.execution import ActionExecution, FlowExecution
from app.models.configuration import Environment
from app.models.identity import User

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
    environment = db.get(Environment, environment_id)
    if environment is None or not environment.is_active:
        raise ValueError("环境不存在或已停用")

    flow = db.get(_FlowModel, flow_id)
    if flow is None:
        raise ValueError("业务流程不存在")

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
    for seq, action in enumerate(actions):
        action_exec = _execute_action(
            db, execution, action, environment, ctx, project_id=flow.project_id,
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
    return data


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
    """执行单个业务动作。"""
    action_exec = ActionExecution(
        flow_execution_id=execution.id,
        action_id=action.id,
        sequence=sequence,
        status="RUNNING",
        started_at=datetime.now(),
    )
    db.add(action_exec)
    db.flush()

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
        for pc, result in zip(pc_dicts, pc_results):
            if "MANUAL" in (result.reason or "") or "NOT_EXECUTABLE" in (result.reason or ""):
                unverified_pcs.append({
                    "id": pc["id"],
                    "type": pc["type"],
                    "target": pc["target"],
                    "reason": result.reason,
                })

        if not all_passed:
            action_exec.status = "FAILED"
            action_exec.error_code = "PRECONDITION_FAILED"
            action_exec.error_message = "前置条件不满足"
            action_exec.finished_at = datetime.now()
            return action_exec

        # 记录无法验证的前置条件（不阻断执行，但标记为未验证）。
        if unverified_pcs:
            action_exec.unverified_preconditions = unverified_pcs

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
            action_exec.status = "FAILED"
            action_exec.error_code = "DEFAULT_BINDING_NOT_FOUND"
            action_exec.error_message = f"动作「{action.name}」未配置默认 API 绑定"
            action_exec.finished_at = datetime.now()
            return action_exec

        action_exec.binding_id = binding.id

        # 3. 加载绑定接口。
        if binding.api_id is None:
            action_exec.status = "FAILED"
            action_exec.error_code = "API_NOT_FOUND"
            action_exec.error_message = "绑定接口已失效（api_id 为空）"
            action_exec.finished_at = datetime.now()
            return action_exec

        from app.features.api_catalog.models.api_interface import ApiInterface
        iface = db.get(ApiInterface, binding.api_id)
        if iface is None:
            action_exec.status = "FAILED"
            action_exec.error_code = "API_NOT_FOUND"
            action_exec.error_message = "绑定接口已失效（接口不存在）"
            action_exec.finished_at = datetime.now()
            return action_exec

        # 3.1. 校验接口状态（Section 5）。
        api_status = (iface.status or "").upper()
        if api_status == "DELETED" or api_status == "":
            action_exec.status = "FAILED"
            action_exec.error_code = "API_NOT_EXECUTABLE"
            action_exec.error_message = f"接口状态为 {api_status or 'NULL'}，不允许执行"
            action_exec.finished_at = datetime.now()
            return action_exec
        if api_status not in _EXECUTABLE_API_STATUSES:
            action_exec.status = "FAILED"
            action_exec.error_code = _API_STATUS_ERROR_MESSAGES.get(api_status, "API_NOT_EXECUTABLE")
            action_exec.error_message = f"接口状态为 {api_status}，不允许执行（仅 ACTIVE 状态可执行）"
            action_exec.finished_at = datetime.now()
            return action_exec

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
        if errors:
            action_exec.status = "FAILED"
            action_exec.error_code = "MISSING_RUNTIME_VARIABLE"
            action_exec.error_message = "; ".join(errors)
            action_exec.input_context = _mask_context_variables(
                {k: ctx.get(k) for k in required_vars},
            )
            action_exec.finished_at = datetime.now()
            return action_exec

        # 7. 构造并执行 HTTP 请求。
        base_headers = _EXECUTOR.get_environment_headers(environment)
        base_headers.update(request_parts["headers"])

        url = _EXECUTOR.build_url(environment, iface.path, request_parts["path_params"])
        method = iface.method.upper()

        # 构造 body。
        json_body = request_parts["body"] if request_parts["body"] else None
        body_type = "json" if json_body else "none"

        started = time.perf_counter()
        result = _EXECUTOR.execute(
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
        action_exec.request_snapshot = SensitiveDataMasker.mask_request(
            method, url, base_headers, request_parts["query"], json_body or {}, body_type,
        )
        action_exec.response_snapshot = SensitiveDataMasker.mask_response(
            result.status_code, result.response_headers, _try_parse_json(result.response_body),
        )
        action_exec.input_context = _mask_context_variables(
            {k: ctx.get(k) for k in required_vars},
        )

        if result.error_message:
            action_exec.status = "FAILED"
            # 判断超时 vs 连接失败。
            if "超时" in result.error_message:
                action_exec.error_code = "HTTP_TIMEOUT"
            else:
                action_exec.error_code = "HTTP_REQUEST_FAILED"
            action_exec.error_message = result.error_message
            action_exec.duration_ms = elapsed_ms
            action_exec.finished_at = datetime.now()
            return action_exec

        # 9. 解析 OUTPUT 映射。
        output_vars = {v.name: v.required for v in variables if v.direction == "OUTPUT"}
        extracted, warnings = resolve_output_mappings(
            mapping_dicts, result.response_body, output_vars,
        )

        # 如果提取失败但有 required 变量，记录错误代码。
        missing_required = [
            w for w in warnings
            if "required" in w.lower() or "缺失" in w
        ]
        if missing_required:
            action_exec.error_code = "OUTPUT_EXTRACTION_FAILED"

        for var_name, value in extracted.items():
            if value is not None:
                ctx.set(var_name, value)

        # 10. 检查 HTTP 状态码。
        if not result.success:
            action_exec.status = "FAILED"
            action_exec.error_code = "HTTP_REQUEST_FAILED"
            action_exec.error_message = f"HTTP {result.status_code}: {result.response_body[:500]}"
            action_exec.duration_ms = elapsed_ms
            action_exec.finished_at = datetime.now()
            return action_exec

        # 11. 保存 Action 输出到 namespaced context（Section 3）。
        output_output = {k: extracted.get(k) for k in output_vars if extracted.get(k) is not None}
        ctx.set_action_output(action.action_key, output_output)

        # 12. 执行 VariableRef 传递。
        refs = (
            db.query(BusinessVariableRef)
            .filter(BusinessVariableRef.flow_id == execution.flow_id)
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

        # 13. 标记成功。
        action_exec.status = "SUCCESS"
        action_exec.output_context = _mask_context_variables(
            {k: ctx.get(k) for k in output_vars},
        )
        action_exec.duration_ms = elapsed_ms
        action_exec.finished_at = datetime.now()
        return action_exec

    except Exception as exc:
        action_exec.status = "FAILED"
        action_exec.error_code = "EXECUTION_CANCELLED"
        action_exec.error_message = f"执行异常：{exc}"
        action_exec.finished_at = datetime.now()
        return action_exec


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
