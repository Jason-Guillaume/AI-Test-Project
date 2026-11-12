"""ZAP 传输层：把「怎么发一个 ZAP API 请求」单独抽成一个协议。

为什么要有这一层（而不是 Connector 直接 httpx）：
1. 真实集成测试环境不一定有 Docker / ZAP 容器；MockZAPTransport 让单元测试能跑通
   Connector 的全部逻辑（URL 拼装、参数名、响应解析、错误映射、状态机），
   不需要起容器、也不会触碰出站白名单。
2. ZAP 的 API Key 只在这一层出现。上层（Connector / 业务层 / 日志）看不到明文 key，
   因此不可能被写进日志、事件表或 prompt（§十一、§三十四 第 8 条）。

约定：
- path 统一写成 ZAP 的完整相对路径，如 "/JSON/core/about"，不在此层拼接。
- 所有响应都解析成 JSON 并原样返回（dict / list）；非 2xx 抛 ZAPTransportError。
- transport 不做任何重试：重试是 Worker 的职责，避免扫描动作被静默重放。
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import httpx


class ZAPTransportError(Exception):
    """ZAP 传输层错误。

    与 AppError 分开：transport 不知道业务错误码，只把 HTTP 状态码与响应体带上去，
    由 Connector 决定映射成哪个 SECURITY_SCAN_* 错误码。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any = None,
        method: str = "",
        path: str = "",
    ) -> None:
        """初始化传输层错误。message 不允许带 API Key。"""
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        self.method = method
        self.path = path


#: API Key 传递方式。header 是 ZAP 较新版本支持的写法，不进入 URL，也不会被
#: 访问日志/代理日志记录；query 是历史兼容写法。
ZAP_API_KEY_MODE_HEADER = "header"
ZAP_API_KEY_MODE_QUERY = "query"
ZAP_API_KEY_MODES = frozenset({ZAP_API_KEY_MODE_HEADER, ZAP_API_KEY_MODE_QUERY})

#: ZAP 约定的 API Key 请求头名（新版）与查询参数名（旧版）。
ZAP_API_KEY_HEADER = "X-ZAP-API-Key"
ZAP_API_KEY_PARAM = "apikey"
#: ZAP 自带的 CSRF 防护会拦掉脚本请求，脚本调用必须显式关掉。
ZAP_DISABLE_CSRF_HEADER = "api-disable-csrf-check"
#: ZAP REST API 的响应格式参数。
ZAP_FORMAT_PARAM = "format"


class ZAPTransport(Protocol):
    """ZAP API 传输协议。真实 HTTP 实现与 Mock 实现共用这一个契约。"""

    def request(
        self,
        *,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """发一个请求并返回解析后的 JSON。

        Args:
            method: HTTP 方法，如 "GET" / "POST"。
            path: ZAP 相对路径，必须以 "/" 开头。
            params: 查询参数。
            json_body: JSON 请求体。
            files: multipart 文件（OpenAPI 导入用）。
            timeout: 覆盖实例默认超时的秒数。

        Returns:
            Any: ZAP 返回的 JSON（dict 或 list）。

        Raises:
            ZAPTransportError: 网络失败、超时、非 2xx、响应不是 JSON。
        """
        ...

    def close(self) -> None:
        """释放底层连接资源。必须幂等。"""
        ...


class HttpZAPTransport:
    """真实 ZAP REST API 传输实现。

    安全约定：
    - base_url 只能来自服务端配置，不接受用户输入（§三 第 1、8 条）。
    - api_key 只作为请求头传递，永不进入日志；日志里只打 base_url 的 host。
    - ``trust_env=False``：不继承环境代理。ZAP 管理 API 必须走内网直连，
      如果因为 socks 代理缺失而 ModuleNotFoundError，会直接 500 而不是变成一条
      可读的错误（与 feishu_service 同一个理由）。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        timeout_seconds: float = 30.0,
        api_key_mode: str = ZAP_API_KEY_MODE_HEADER,
        disable_csrf: bool = True,
        verify_tls: bool = True,
    ) -> None:
        """初始化传输。

        Args:
            base_url: ZAP 管理 API 地址，如 "http://10.0.0.10:8090"。
            api_key: ZAP API Key 明文；只在内存与请求头中出现。
            timeout_seconds: 默认超时秒数。
            api_key_mode: "header" 或 "query"。
            disable_csrf: 是否发送 api-disable-csrf-check 头。
            verify_tls: 是否校验 TLS 证书。
        """
        base = (base_url or "").strip().rstrip("/")
        if not base:
            raise ValueError("ZAP base_url 不能为空")
        self._base_url = base
        self._api_key = api_key or ""
        self._timeout = float(timeout_seconds)
        self._api_key_mode = api_key_mode if api_key_mode in ZAP_API_KEY_MODES else ZAP_API_KEY_MODE_HEADER
        self._disable_csrf = bool(disable_csrf)
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            verify=verify_tls,
            trust_env=False,
            headers=self._static_headers(),
        )

    @property
    def base_host(self) -> str:
        """仅 host:port，用于日志。不含路径与查询参数。"""
        parts = urlsplit(self._base_url)
        return f"{parts.scheme}://{parts.netloc}"

    def _static_headers(self) -> dict[str, str]:
        """每次请求都会带的头。"""
        headers: dict[str, str] = {}
        if self._api_key and self._api_key_mode == ZAP_API_KEY_MODE_HEADER:
            headers[ZAP_API_KEY_HEADER] = self._api_key
        if self._disable_csrf:
            headers[ZAP_DISABLE_CSRF_HEADER] = "true"
        return headers

    def _resolve_path(self, path: str) -> str:
        """保证 path 以单个 / 开头，且不意外逃出自己的 base_url。"""
        if not path.startswith("/"):
            path = "/" + path
        # 防御：绝对 URL 会被 httpx 当独立地址，绕过 base_url 约束。
        if "://" in path:
            raise ZAPTransportError("非法的 ZAP 路径（包含协议头）", path=path)
        return path

    def request(
        self,
        *,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """发请求并解析 JSON 响应。"""
        resolved = self._resolve_path(path)
        query = dict(params or {})
        query.setdefault(ZAP_FORMAT_PARAM, "json")
        if self._api_key and self._api_key_mode == ZAP_API_KEY_MODE_QUERY:
            query[ZAP_API_KEY_PARAM] = self._api_key

        try:
            if files:
                # OpenAPI 导入走 multipart；ZAP 要求字段名与文件成对提交。
                response = self._client.request(
                    method.upper(), resolved, params=query, files=dict(files),
                    timeout=timeout or self._timeout,
                )
            else:
                response = self._client.request(
                    method.upper(), resolved,
                    params=query,
                    json=json_body,
                    timeout=timeout or self._timeout,
                )
        except httpx.TimeoutException as exc:
            raise ZAPTransportError(
                f"ZAP 请求超时：{type(exc).__name__}", method=method.upper(), path=resolved,
            ) from exc
        except httpx.HTTPError as exc:
            raise ZAPTransportError(
                f"ZAP 连接失败：{type(exc).__name__}", method=method.upper(), path=resolved,
            ) from exc

        return self._parse(response, method=method.upper(), path=resolved)

    def _parse(self, response: httpx.Response, *, method: str, path: str) -> Any:
        """把响应解析成 JSON；非 2xx 或非法 JSON 抛 ZAPTransportError。"""
        try:
            body = response.json()
        except ValueError:
            # 连接成功但返回了 HTML（常见于 API Key 错误页或反向代理错误页）。
            raise ZAPTransportError(
                f"ZAP 返回非 JSON 响应（HTTP {response.status_code}）",
                status_code=response.status_code,
                response_body=response.text[:300],
                method=method,
                path=path,
            ) from None

        if response.status_code >= 400:
            # 错误体里可能有 ZAP 的 detail 字段；截断避免把内部信息带出。
            detail = body if isinstance(body, (dict, list)) else str(body)
            raise ZAPTransportError(
                f"ZAP 返回 HTTP {response.status_code}",
                status_code=response.status_code,
                response_body=_truncate(detail),
                method=method,
                path=path,
            )
        return body

    def close(self) -> None:
        """关闭底层客户端。幂等。"""
        try:
            self._client.close()
        except Exception:  # noqa: BLE001 — 关闭失败不影响清理流程
            pass


def _truncate(value: Any, limit: int = 500) -> Any:
    """截断过长的错误体，避免错误信封里塞进大段 ZAP 输出。"""
    text = value if isinstance(value, str) else str(value)
    return text[:limit] if len(text) > limit else value
