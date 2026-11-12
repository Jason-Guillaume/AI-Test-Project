"""接口调试执行器：用项目环境发真实请求，强制校验出站白名单。

仅平台管理员可调用（router 用 require_platform_admin 依赖保证）；本服务仍二次校验，
防止误挂。流程（spec §10）：
1. 加载接口与子表；admin 视为可见（accessible_project_ids 返回 None）。
2. 由 environment_name 取 Environment（仅 is_active）。
3. URL = environment.base_url + gateway_prefix + interface.path，path 参数 {id} 用 override_path_params 替换。
4. 出站白名单：解析 scheme/host/port，查 ProjectOutboundTarget(project_id, scheme, host, port, enabled=True)；
   未命中 → 403「目标不在项目出站白名单」。
5. headers：环境默认 < 接口 HEADER 参数 < override_headers。
6. body 按 body_type 组装（json/form/multipart/raw）；httpx 同步 client，timeout 由调用方给。
7. 返回 {status_code, response_body, response_headers, response_time_ms, request_url, outbound_target_id}。
   仅临时请求，不生成用例、不落库。
"""

from __future__ import annotations

import json as _json
from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.schemas import ApiDebugRequest, ApiDebugResponse
from app.features.api_catalog.services.request_service import (
    load_interface_request_body,
    load_interface_request_params,
)
from app.platform.environment_configuration.services.environment_service import resolve_project_environment_by_name
from app.execution.http.executor import send_http_request
from app.execution.http.outbound_policy import resolve_project_outbound_target
from app.execution.http.request_builder import (
    build_environment_url,
    get_environment_headers,
    merge_request_fields,
)
from app.core.http.errors import bad_request, forbidden, not_found


class DebugService:
    """调试执行器。无状态。"""

    def execute(
        self, db: Session, api_id: int, body: ApiDebugRequest, *, actor
    ) -> ApiDebugResponse:
        """执行对应数据。"""
        # actor 已由 require_platform_admin 保证为平台管理员；二次校验防御误挂。
        from app.core.security.roles import is_platform_admin

        if not is_platform_admin(actor):
            raise forbidden("调试仅限平台管理员")

        iface = db.get(ApiInterface, api_id)
        if iface is None:
            raise not_found("接口不存在")

        environment = resolve_project_environment_by_name(db, iface.project_id, body.environment_name)

        url = build_environment_url(environment, iface.path or "", body.override_path_params or {})

        # 非法端口发生在任何网络 I/O 之前，维持调试接口原有的 400 错误契约。
        try:
            decision = resolve_project_outbound_target(db, url, iface.project_id)
        except ValueError as exc:
            raise bad_request(f"调试目标地址端口非法：{url}") from exc
        if decision.target is None:
            raise forbidden("目标不在项目出站白名单")

        # 覆盖顺序保持为环境默认、接口示例、调试覆盖，后值只替换同名字段。
        params = load_interface_request_params(db, iface.id)
        interface_headers: dict[str, str] = {}
        interface_query: dict[str, str] = {}
        for parameter in params:
            if parameter.location == "HEADER" and parameter.example:
                interface_headers[parameter.name] = parameter.example
            if parameter.location == "QUERY" and parameter.example:
                interface_query[parameter.name] = parameter.example
        headers = merge_request_fields(
            get_environment_headers(environment),
            interface_headers,
            {str(key): str(value) for key, value in (body.override_headers or {}).items()},
        )
        query = merge_request_fields(interface_query, body.override_query)

        body_obj = load_interface_request_body(db, iface.id)
        send_kwargs = self._build_send_kwargs(body_obj, body)
        # 调试仅将共享发送结果映射成原 HTTP 错误和响应字段。
        result = send_http_request(
            method=iface.method.upper(),
            url=url,
            headers=headers,
            query=query,
            json_body=send_kwargs.get("json"),
            json_body_present="json" in send_kwargs,
            form_body=send_kwargs.get("data"),
            files=send_kwargs.get("files"),
            raw_body=send_kwargs.get("content"),
            timeout=body.timeout,
        )
        if result.transport_error_kind == "connect":
            raise bad_request(f"连接失败：{result.transport_error_detail}")
        if result.transport_error_kind == "timeout":
            raise bad_request(f"请求超时（{body.timeout}s）")
        if result.transport_error_kind == "http":
            raise bad_request(f"请求失败：{result.transport_error_detail}")
        if result.transport_error_kind == "dependency":
            raise bad_request(f"请求依赖缺失：{result.transport_error_detail}")

        return ApiDebugResponse(
            status_code=result.status_code,
            response_body=result.response_body,
            response_headers=result.response_headers,
            response_time_ms=result.response_time_ms,
            request_url=result.request_url,
            outbound_target_id=decision.target.id,
        )

    def _build_send_kwargs(self, body_obj, body: ApiDebugRequest) -> dict:
        """按 body_type 组装 httpx 请求体参数。"""
        if body.override_body is not None:
            # 用户覆盖优先：尝试当 JSON 发送。
            try:
                return {"json": body.override_body}
            except (TypeError, ValueError):
                return {"content": str(body.override_body)}
        if body_obj is None or (body_obj.body_type or "none") == "none":
            return {}
        bt = body_obj.body_type
        if bt == "json":
            raw = body_obj.raw_text
            if raw:
                try:
                    return {"json": _json.loads(raw)}
                except (ValueError, TypeError):
                    # 不能带 "headers" 键：调用点已用 headers= 关键字传入，重复即
                    # 异常说明：传入 headers 关键字参数时重复赋值会触发 TypeError。
                    # 且该 TypeError 不在下面的 except 列表里 → 直接 500。
                    return {"content": raw}
            if isinstance(body_obj.schema_json, dict) and "example" in body_obj.schema_json:
                return {"json": body_obj.schema_json["example"]}
            return {}
        if bt == "form":
            fields = self._form_fields(body_obj)
            return {"data": fields} if fields else {}
        if bt == "multipart":
            files = self._multipart_fields(body_obj)
            return {"files": files} if files else {}
        if bt == "raw":
            return {"content": body_obj.raw_text or ""}
        return {}

    def _form_fields(self, body_obj) -> dict[str, str]:
        """提取表单请求字段。"""
        props = (body_obj.schema_json or {}).get("properties") or {}
        out: dict[str, str] = {}
        for name, info in props.items():
            if isinstance(info, dict):
                ex = info.get("example")
                out[name] = str(ex) if ex is not None else ""
        return out

    def _multipart_fields(self, body_obj) -> list[tuple[str, str]]:
        """提取 multipart 请求字段及文件信息。"""
        props = (body_obj.schema_json or {}).get("properties") or {}
        out: list[tuple[str, str]] = []
        for name, info in props.items():
            if isinstance(info, dict):
                ex = info.get("example")
                out.append((name, str(ex) if ex is not None else ""))
        return out


__all__ = ["DebugService"]
