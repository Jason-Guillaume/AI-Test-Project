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
import time
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.schemas import ApiDebugRequest, ApiDebugResponse
from app.features.api_catalog.services.api_service import _load_body, _load_params
from app.features.environment_configuration.services.environment_service import resolve_project_environment_by_name
from app.models.project import ProjectOutboundTarget
from app.shared.errors import bad_request, forbidden, not_found

# 响应体截断上限，避免超大响应撑爆上下文。
_MAX_RESPONSE_BODY = 200_000


class DebugService:
    """调试执行器。无状态。"""

    def execute(
        self, db: Session, api_id: int, body: ApiDebugRequest, *, actor
    ) -> ApiDebugResponse:
        """执行对应数据。"""
        # actor 已由 require_platform_admin 保证为平台管理员；二次校验防御误挂。
        from app.shared.roles import is_platform_admin

        if not is_platform_admin(actor):
            raise forbidden("调试仅限平台管理员")

        iface = db.get(ApiInterface, api_id)
        if iface is None:
            raise not_found("接口不存在")

        environment = resolve_project_environment_by_name(db, iface.project_id, body.environment_name)

        # 拼接 URL 并替换 path 参数。
        base = (environment.base_url or "").rstrip("/")
        gateway = (environment.gateway_prefix or "").rstrip("/")
        path = iface.path or ""
        path_params = body.override_path_params or {}
        if path_params:
            for k, v in path_params.items():
                path = path.replace(f"{{{k}}}", str(v))
        url = f"{base}{gateway}{path}"

        # 端口非法（非数字 / 越界）时 urlsplit().port 抛 ValueError。这里必须显式接住：
        # 它发生在下面的 try 之外、且早于出站白名单校验，不接住就是 500 而非 4xx。
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise bad_request(f"调试目标地址端口非法：{url}") from exc
        scheme = (parsed.scheme or "http").lower()
        host = (parsed.hostname or "").lower()
        # 显式端口用之；http 默认 80，https 默认 443。
        port = port or (443 if scheme == "https" else 80)

        # 出站白名单校验。
        target = (
            db.query(ProjectOutboundTarget)
            .filter(
                ProjectOutboundTarget.project_id == iface.project_id,
                ProjectOutboundTarget.scheme == scheme,
                ProjectOutboundTarget.host == host,
                ProjectOutboundTarget.port == port,
                ProjectOutboundTarget.enabled.is_(True),
            )
            .first()
        )
        if target is None:
            raise forbidden("目标不在项目出站白名单")

        # 合并 headers：环境默认 < 接口 HEADER 参数 < override。
        headers: dict[str, str] = {}
        if isinstance(environment.default_headers, dict):
            headers.update({str(k): str(v) for k, v in environment.default_headers.items()})
        for p in _load_params(db, iface.id):
            if p.location == "HEADER" and p.example:
                headers[p.name] = p.example
        if body.override_headers:
            headers.update({str(k): str(v) for k, v in body.override_headers.items()})

        # query：接口 QUERY 参数 < override。
        query: dict[str, str] = {}
        for p in _load_params(db, iface.id):
            if p.location == "QUERY" and p.example:
                query[p.name] = p.example
        if body.override_query:
            query.update({str(k): str(v) for k, v in body.override_query.items()})

        # 请求体组装。
        body_obj = _load_body(db, iface.id)
        send_kwargs = self._build_send_kwargs(body_obj, body)

        method = iface.method.upper()
        # 超时策略：connect 收紧到 10s 内，connect/write/read/pool 分开设。
        # 只给 httpx 一个标量 timeout 不够——read 超时是「单次读」粒度，服务端每
        # 零点几秒挤一点数据就能绕过它，让连接无限期挂着。所以下面改用 client.stream()
        # 边读边按 _MAX_RESPONSE_BODY 截断，再用墙钟 deadline 兜住总时长。
        timeout_config = httpx.Timeout(
            connect=min(body.timeout, 10.0),
            write=body.timeout,
            read=body.timeout,
            pool=body.timeout,
        )
        started = time.perf_counter()
        deadline = started + body.timeout
        resp_headers: dict[str, str] = {}
        resp_url = url
        status_code = 0
        chunks: list[bytes] = []
        truncated = False
        try:
            # trust_env=False：调试请求直连白名单目标，不沿用环境代理（HTTP_PROXY/ALL_PROXY）。
            # 白名单已控制目的地；经环境代理转发既不安全也会引入 SOCKS 等可选依赖问题。
            with httpx.Client(timeout=timeout_config, follow_redirects=False, trust_env=False) as client:
                with client.stream(method, url, headers=headers, params=query, **send_kwargs) as resp:
                    # 状态码与响应头在流开始时就已可读，先取出来再进入 body 循环。
                    status_code = resp.status_code
                    resp_headers = {str(k): str(v) for k, v in resp.headers.items()}
                    resp_url = str(resp.request.url)
                    size = 0
                    for chunk in resp.iter_bytes(chunk_size=65_536):
                        chunks.append(chunk)
                        size += len(chunk)
                        # 超出截断上限或超过总时长上限即停止拉取；剩余部分由服务端
                        # 断连，对大响应而言这是预期行为。
                        if size > _MAX_RESPONSE_BODY or time.perf_counter() >= deadline:
                            truncated = True
                            break
        except httpx.ConnectError as exc:
            raise bad_request(f"连接失败：{exc}")
        except httpx.TimeoutException:
            raise bad_request(f"请求超时（{body.timeout}s）")
        except httpx.HTTPError as exc:
            raise bad_request(f"请求失败：{exc}")
        except ImportError as exc:
            # 缺少可选传输依赖（如 socksio）：归为可读的 400 而非 500。
            raise bad_request(f"请求依赖缺失：{exc}")
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # 边读边截断，不整包落内存；截断后按字符上限再切一次，保证返回体不超过约定。
        resp_body = "".join(chunk.decode("utf-8", errors="replace") for chunk in chunks)
        if truncated:
            resp_body = resp_body[:_MAX_RESPONSE_BODY] + "\n...[已截断]"

        return ApiDebugResponse(
            status_code=status_code,
            response_body=resp_body,
            response_headers=resp_headers,
            response_time_ms=elapsed_ms,
            request_url=resp_url,
            outbound_target_id=target.id,
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
