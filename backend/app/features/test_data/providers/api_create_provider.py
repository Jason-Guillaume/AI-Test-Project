"""API_CREATE Provider（§9.1）：调现有 ``ApiRequestExecutor``，不新写 HTTP 客户端。

流程与 §9.1 一一对应：
1. 取接口并校验归属（跨项目 → ``PROVIDER_NOT_FOUND``，对调用方隐藏存在性）。
2. 校验接口状态，沿用业务执行器的 ``API_NOT_EXECUTABLE`` / ``API_DEPRECATED`` 口径。
3. ``VariableResolver`` 先把 ``expression`` 求值成具体值字典（按 target 分组）。
4. 交给现有 ``resolve_input_mappings`` 组装 headers/query/path/body/cookies——
   **不改**它的位置语义，只把 target 映射成 business_variable 传入。
5. ``build_environment_url`` + 共享 ``ApiRequestExecutor.execute``。
6. ``resolve_output_mappings`` 按 JSONPath 取输出。
7. 请求 / 响应快照经 ``SensitiveDataMasker`` 脱敏。
8. Cleanup 句柄只存 method + path **模板**（不存已替换的值），执行清理时再次解析
   并过出站白名单。
"""

from __future__ import annotations

import json
import time

from app.features.api_catalog.models.api_interface import ApiInterface
from app.execution.http.executor import ApiRequestExecutor
from app.execution.http.request_builder import build_environment_url, get_environment_headers
from app.features.business.executors.mapping_resolver import (
    resolve_input_mappings,
    resolve_output_mappings,
)
from app.core.security.sensitive import SensitiveDataMasker
from app.features.test_data.providers.base import (
    CLEANUP_HANDLE_KEY,
    RESPONSE_BODY_KEY,
    BaseProvider,
    ProviderContext,
    ProviderResult,
    config_of,
)
from app.execution.templates.resolver import resolve_token_str
from app.core.http.errors import (
    CODE_DATA_RESOLVE_FAILED,
    CODE_PROVIDER_NOT_FOUND,
    AppError,
)

_EXECUTOR = ApiRequestExecutor()
_MASKER = SensitiveDataMasker()

# 与业务执行器同口径：只允许 ACTIVE 执行。
_EXECUTABLE_STATUSES = {"ACTIVE"}
_STATUS_ERROR_MESSAGES = {"DEPRECATED": "API_DEPRECATED"}


def _try_parse_json(text: str) -> object:
    """尝试将响应文本解析为 JSON；解析失败时返回空结果。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


class ApiCreateProvider(BaseProvider):
    provider_type = "API_CREATE"

    def run(self, ctx: ProviderContext) -> ProviderResult:
        """运行对应数据。"""
        from app.features.test_data.schemas import ApiCreateProviderConfig

        cfg = self.load_config(config_of(ctx), ApiCreateProviderConfig)

        # 环境写死在配置里时，必须与本次运行环境一致，避免 dev 配方打到别的环境。
        if cfg.environment_id is not None and cfg.environment_id != ctx.environment.id:
            raise AppError(
                f"Provider 配置的 environment_id={cfg.environment_id} 与本次运行环境 "
                f"{ctx.environment.id} 不一致",
                status_code=400,
                code=CODE_DATA_RESOLVE_FAILED,
            )

        iface = self._load_interface(ctx.db, cfg.api_id, ctx.project_id)

        # 1) 表达式求值 → 按 target 分组的值字典。
        resolved_values: dict[str, object] = {}
        for rule in cfg.input_mappings:
            try:
                resolved_values[rule.target] = resolve_token_str(rule.expression, ctx.scope, required=True)
            except AppError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise AppError(
                    f"输入映射 {rule.target} 求值失败：{exc}",
                    status_code=400,
                    code=CODE_DATA_RESOLVE_FAILED,
                ) from exc

        # 2) 复用现有映射解析器组装请求各部分（target → business_variable）。
        mapping_dicts = [
            {"direction": "INPUT", "business_variable": r.target, "api_location": r.location,
             "api_field": None, "expression": r.expression}
            for r in cfg.input_mappings
        ]
        required = {r.target: True for r in cfg.input_mappings}
        request_parts, errors = resolve_input_mappings(mapping_dicts, resolved_values, required)
        if errors:
            raise AppError(
                f"输入映射解析失败：{'; '.join(errors)}",
                status_code=400,
                code=CODE_DATA_RESOLVE_FAILED,
            )

        # 静态 body 先落底，映射结果覆盖同名键。
        body = dict(cfg.body or {})
        body.update(request_parts["body"])
        json_body = body or None
        body_type = "json" if json_body else "none"

        base_headers = get_environment_headers(ctx.environment)
        base_headers.update(cfg.headers or {})
        base_headers.update(request_parts["headers"])

        url = build_environment_url(ctx.environment, iface.path, request_parts["path_params"])
        method = iface.method.upper()

        started = time.perf_counter()
        result = _EXECUTOR.execute(
            ctx.db,
            method=method,
            url=url,
            project_id=ctx.project_id,
            headers=base_headers,
            query=request_parts["query"] or None,
            cookies=request_parts["cookies"] or None,
            json_body=json_body,
            timeout=30,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        request_snapshot = _MASKER.mask_request(
            method, url, base_headers, request_parts["query"], json_body or {}, body_type,
        )
        body_obj = _try_parse_json(result.response_body)
        response_snapshot = _MASKER.mask_response(
            result.status_code, result.response_headers, body_obj,
        )

        if result.error_message:
            code = "HTTP_TIMEOUT" if "超时" in result.error_message else "HTTP_REQUEST_FAILED"
            return ProviderResult.fail(
                code, result.error_message,
                request_snapshot=request_snapshot, response_snapshot=response_snapshot,
            )

        # 3) 输出映射：复用现有 JSONPath 提取器。
        outputs: dict[str, object] = {}
        missing: list[str] = []
        if cfg.output_mappings:
            out_dicts = [
                {"direction": "OUTPUT", "business_variable": m.name, "expression": m.expression, "api_field": None}
                for m in cfg.output_mappings
            ]
            extracted, _warnings = resolve_output_mappings(
                out_dicts, result.response_body, {m.name: True for m in cfg.output_mappings},
            )
            for m in cfg.output_mappings:
                value = extracted.get(m.name)
                if value is not None:
                    outputs[m.name] = value
                else:
                    missing.append(m.name)
        if missing and not result.success:
            return ProviderResult.fail(
                "HTTP_REQUEST_FAILED",
                f"HTTP {result.status_code}: {result.response_body[:300]}",
                request_snapshot=request_snapshot, response_snapshot=response_snapshot,
            )
        if missing and result.success:
            return ProviderResult.fail(
                "OUTPUT_EXTRACTION_FAILED",
                f"输出映射未取到值：{', '.join(missing)}",
                request_snapshot=request_snapshot, response_snapshot=response_snapshot,
                outputs=outputs,
            )
        if not result.success:
            return ProviderResult.fail(
                "HTTP_REQUEST_FAILED",
                f"HTTP {result.status_code}: {result.response_body[:300]}",
                request_snapshot=request_snapshot, response_snapshot=response_snapshot,
            )

        # 4) Cleanup 句柄：只存模板，不存已替换的值。
        cleanup_handle = None
        if cfg.cleanup is not None:
            cleanup_handle = {
                "type": "API",
                "method": cfg.cleanup.method,
                "path": cfg.cleanup.path,
                "headers": dict(cfg.cleanup.headers or {}),
                "body": dict(cfg.cleanup.body or {}),
                "environment_id": ctx.environment.id,
            }

        # 完整响应体一起带上（RESPONSE_BODY_KEY），让输出契约能用 ``$.data.id``
        # 这种 JSON 路径取值；落快照时由 data_factory 统一脱敏。
        payload = dict(outputs)
        if isinstance(body_obj, dict):
            payload[RESPONSE_BODY_KEY] = body_obj

        return ProviderResult.ok(
            payload,
            request_snapshot=request_snapshot,
            response_snapshot=response_snapshot,
            cleanup_handle=cleanup_handle,
        )

    @staticmethod
    def _load_interface(db, api_id: int, project_id: int) -> ApiInterface:
        """加载接口。"""
        iface = db.get(ApiInterface, api_id)
        if iface is None or iface.project_id != project_id:
            raise AppError(
                f"接口 {api_id} 不存在",
                status_code=404,
                code=CODE_PROVIDER_NOT_FOUND,
            )
        status = (iface.status or "").upper()
        if status == "DELETED" or status == "":
            raise AppError(
                f"接口状态为 {status or 'NULL'}，不允许执行",
                status_code=400,
                code="API_NOT_EXECUTABLE",
            )
        if status not in _EXECUTABLE_STATUSES:
            raise AppError(
                f"接口状态为 {status}，不允许执行（仅 ACTIVE 状态可执行）",
                status_code=400,
                code=_STATUS_ERROR_MESSAGES.get(status, "API_NOT_EXECUTABLE"),
            )
        return iface


__all__ = ["ApiCreateProvider", "CLEANUP_HANDLE_KEY"]
