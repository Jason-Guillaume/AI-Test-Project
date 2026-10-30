"""内置工具注册表。

本模块只绑定代码内明确列出的工具处理器，禁止从模型参数动态导入模块或函数。
Agent 图和任务适配器调用同一注册表；目录状态继续由工具目录维护，catalog_only 项不开放给模型。
"""

from __future__ import annotations

from functools import wraps
from inspect import Parameter, signature
from importlib import import_module
from typing import Any

from app.tools.catalog import TOOL_BY_KEY
from app.tools.contracts import ToolBinding, ToolChannel, ToolHandler

_BINDINGS: dict[str, ToolBinding] = {}
_BUILTINS_LOADED = False


class ToolDispatchError(RuntimeError):
    """表示工具未注册、调用通道未授权或参数契约不符。"""


def register_handler(
    key: str,
    handler: ToolHandler,
    *,
    risk: str,
    allowed_channels: tuple[ToolChannel, ...] = ("fixed",),
    input_contract: dict[str, Any] | None = None,
) -> ToolBinding:
    """将一个稳定工具键绑定到仓库内的唯一处理器。

    Args:
        key: 目录使用的稳定键，或仅供固定工作流使用的 ``runtime.*`` 键。
        handler: 受控 Python 处理器，不由请求参数解析得到。
        risk: 工具风险类别，用于目录和审计说明。
        allowed_channels: 服务端允许的固定节点或模型调用来源。
        input_contract: 可选输入字段描述；现有函数签名仍是实际参数校验来源。
    Returns:
        ToolBinding: 已写入注册表的不可变绑定。
    Raises:
        ToolDispatchError: 同一稳定键被重复绑定到另一处理器时抛出。
    """
    existing = _BINDINGS.get(key)
    if existing is not None:
        if existing.handler is handler:
            return existing
        raise ToolDispatchError(f"工具键重复注册：{key}")
    catalog = TOOL_BY_KEY.get(key, {})
    contract = input_contract if input_contract is not None else _handler_input_contract(handler)
    binding = ToolBinding(
        key=key,
        handler=handler,
        risk=risk,
        allowed_channels=frozenset(allowed_channels),
        catalog_status=(catalog.get("runtime_details") or {}).get("status", "runtime_only"),
        input_contract=contract,
    )
    _BINDINGS[key] = binding
    return binding


def _handler_input_contract(handler: ToolHandler) -> dict[str, Any]:
    """从受控处理器签名生成可审阅的输入契约。"""
    fields: list[dict[str, Any]] = []
    for parameter in signature(handler).parameters.values():
        if parameter.kind in {Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD}:
            continue
        annotation = parameter.annotation
        type_name = (
            annotation.__name__ if isinstance(annotation, type)
            else str(annotation) if annotation is not Parameter.empty
            else "any"
        )
        fields.append({
            "name": parameter.name,
            "type": type_name,
            "required": parameter.default is Parameter.empty,
        })
    return {"parameters": fields}


def bind_module_handlers(
    namespace: dict[str, Any],
    bindings: dict[str, tuple[str, str]],
) -> None:
    """将模块内具名函数注册并替换为统一调度代理。"""
    for function_name, (tool_key, risk) in bindings.items():
        handler = namespace.get(function_name)
        if not callable(handler):
            raise ToolDispatchError(f"工具处理器不存在：{function_name}")
        register_handler(tool_key, handler, risk=risk)

        @wraps(handler)
        def routed(*args: Any, __key: str = tool_key, **kwargs: Any) -> Any:
            """从固定工作流入口调用注册处理器并保留原有函数签名。"""
            from app.tools.dispatcher import dispatch_tool

            return dispatch_tool(__key, *args, channel="fixed", **kwargs)

        namespace[function_name] = routed


def load_builtin_handlers() -> None:
    """显式加载内置工具模块，确保目录查找前处理器已完成注册。"""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    modules = (
        "app.tools.builtin.api_catalog.api_catalog_tool",
        "app.tools.builtin.business.business_tool",
        "app.tools.builtin.test_management.test_asset_tool",
        "app.tools.builtin.test_management.execution_tool",
        "app.tools.builtin.test_data.fixture_tool",
        "app.tools.builtin.mocking.mock_tool",
        "app.tools.builtin.security_testing.security_tool",
        "app.tools.builtin.security_testing.zap_scan_tool",
        "app.tools.builtin.web_testing.web_ui_tool",
        "app.tools.builtin.reports.report_tool",
        "app.tools.builtin.notifications.notification_tool",
    )
    for module_name in modules:
        import_module(module_name)
    _BUILTINS_LOADED = True


def get_binding(key: str, *, channel: ToolChannel) -> ToolBinding:
    """查找稳定工具键并校验调用来源是否已由服务端授权。"""
    load_builtin_handlers()
    binding = _BINDINGS.get(key)
    if binding is None:
        raise ToolDispatchError(f"工具未注册：{key}")
    if channel not in binding.allowed_channels:
        raise ToolDispatchError(f"工具不允许从当前调用通道执行：{key}")
    if channel == "model" and binding.catalog_status != "active":
        raise ToolDispatchError(f"工具未开放模型调用：{key}")
    return binding


def registered_keys() -> tuple[str, ...]:
    """返回已经注册的工具键，便于治理页面与运行时校验使用。"""
    load_builtin_handlers()
    return tuple(sorted(_BINDINGS))
