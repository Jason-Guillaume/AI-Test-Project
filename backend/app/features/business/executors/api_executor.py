"""HTTP API 执行器。

封装 HTTP 请求发送能力，供 Business Flow Executor 调用。
复用 DebugService 的 httpx 模式，但更通用：不依赖 ApiInterface 模型，
而是接受显式的 URL/method/headers/body 参数。

支持：
- Environment base_url + gateway_prefix 拼接
- Path 参数替换
- Header/Query/Cookie/JSON Body/Form/Multipart
- 出站白名单校验 + 私网地址防护
- 超时控制（connect/write/read 独立）
- 响应体流式截断
"""

from __future__ import annotations

import ipaddress
import time
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.models.configuration import Environment
from app.models.project import ProjectOutboundTarget


class ApiRequestResult:
    """HTTP 请求执行结果。"""

    __slots__ = (
        "status_code", "response_body", "response_headers",
        "response_time_ms", "request_url", "error_message",
    )

    def __init__(self):
        """初始化对象状态。"""
        self.status_code: int = 0
        self.response_body: str = ""
        self.response_headers: dict[str, str] = {}
        self.response_time_ms: int = 0
        self.request_url: str = ""
        self.error_message: str | None = None

    @property
    def success(self) -> bool:
        """判断操作是否成功。"""
        return self.error_message is None and 200 <= self.status_code < 400


_MAX_RESPONSE_BODY = 200_000


def _is_private_ip(host: str) -> bool:
    """判断 IP 是否为私网地址（localhost、127.0.0.1、0.0.0.0、link-local、metadata 等）。"""
    try:
        ip = ipaddress.ip_address(host)
        return (
            ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_private
            or ip.is_unspecified
        )
    except ValueError:
        return False


class ApiRequestExecutor:
    """HTTP API 执行器。无状态，可全局复用。"""

    def execute(
        self,
        db: Session,
        *,
        method: str,
        url: str,
        project_id: int,
        headers: dict[str, str] | None = None,
        query: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        json_body: dict | None = None,
        form_body: dict[str, str] | None = None,
        raw_body: str | None = None,
        timeout: int = 30,
    ) -> ApiRequestResult:
        """执行 HTTP 请求。

        Args:
            db: 数据库会话（用于出站白名单校验）。
            method: HTTP 方法。
            url: 完整请求 URL。
            project_id: 项目ID（用于出站白名单校验）。
            headers: 请求头。
            query: 查询参数。
            cookies: Cookie。
            json_body: JSON 请求体。
            form_body: Form 表单请求体（multipart/form-data）。
            raw_body: 原始请求体。
            timeout: 超时秒数，同时也是整次请求的总时长上限。

        Returns:
            ApiRequestResult: 执行结果。
        """
        # 1. 出站白名单 + 私网地址校验。
        block_reason = self._check_outbound(db, url, project_id)
        if block_reason:
            result = ApiRequestResult()
            result.error_message = block_reason
            return result

        # 2. 组装 httpx 参数。
        send_kwargs: dict = {}
        if json_body is not None:
            send_kwargs["json"] = json_body
        elif form_body is not None:
            send_kwargs["data"] = form_body
        elif raw_body is not None:
            send_kwargs["content"] = raw_body

        # 3. 超时策略：connect/write/read/pool 分开设。注意 read 是「单次读」粒度，
        # 服务端慢慢挤数据就能绕过它，所以第 5 步还要用墙钟 deadline 兜总时长。
        timeout_config = httpx.Timeout(
            connect=min(timeout, 10),
            write=timeout,
            read=timeout,
            pool=timeout,
        )

        result = ApiRequestResult()
        started = time.perf_counter()
        deadline = started + timeout
        status_code = 0
        request_url = url
        resp_headers: dict[str, str] = {}
        chunks: list[bytes] = []
        truncated = False
        try:
            with httpx.Client(
                timeout=timeout_config,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    method.upper(),
                    url,
                    headers=headers,
                    params=query,
                    cookies=cookies,
                    **send_kwargs,
                ) as resp:
                    # 状态码与响应头在流开始时就已可读，先取出再进 body 循环。
                    status_code = resp.status_code
                    request_url = str(resp.request.url)
                    resp_headers = {str(k): str(v) for k, v in resp.headers.items()}
                    size = 0
                    for chunk in resp.iter_bytes(chunk_size=65_536):
                        chunks.append(chunk)
                        size += len(chunk)
                        # 超出截断上限或超过总时长上限即停止拉取。
                        if size > _MAX_RESPONSE_BODY or time.perf_counter() >= deadline:
                            truncated = True
                            break
        except httpx.ConnectError as exc:
            result.error_message = f"连接失败：{exc}"
            return result
        except httpx.TimeoutException:
            result.error_message = f"请求超时（总时长上限 {timeout}s)"
            return result
        except httpx.HTTPError as exc:
            result.error_message = f"请求失败：{exc}"
            return result

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        result.status_code = status_code
        result.response_time_ms = elapsed_ms
        result.request_url = request_url
        result.response_headers = resp_headers

        # 4. 边读边截断：不整包落内存，超出 _MAX_RESPONSE_BODY 即停止拉取。
        body = "".join(chunk.decode("utf-8", errors="replace") for chunk in chunks)
        if truncated:
            body = body[:_MAX_RESPONSE_BODY] + "\n...[已截断]"
        result.response_body = body

        return result

    def _check_outbound(self, db: Session, url: str, project_id: int) -> str | None:
        """校验目标 URL 是否在项目出站白名单内 + 私网地址防护。

        Returns:
            None 如果允许；否则返回错误信息。
        """
        parsed = urlsplit(url)
        scheme = (parsed.scheme or "http").lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port or (443 if scheme == "https" else 80)

        # 1. 私网地址防护：localhost、127.0.0.1、0.0.0.0、link-local 等。
        # 如果平台明确允许内网测试环境，应通过白名单显式放行。
        if _is_private_ip(host):
            # 检查白名单是否显式放行了该私网地址。
            target = (
                db.query(ProjectOutboundTarget)
                .filter(
                    ProjectOutboundTarget.project_id == project_id,
                    ProjectOutboundTarget.scheme == scheme,
                    ProjectOutboundTarget.host == host,
                    ProjectOutboundTarget.port == port,
                    ProjectOutboundTarget.enabled.is_(True),
                )
                .first()
            )
            if target is None:
                return f"目标地址 {host}:{port} 为私网/环回地址，不在出站白名单"

        # 2. 常规白名单校验。
        target = (
            db.query(ProjectOutboundTarget)
            .filter(
                ProjectOutboundTarget.project_id == project_id,
                ProjectOutboundTarget.scheme == scheme,
                ProjectOutboundTarget.host == host,
                ProjectOutboundTarget.port == port,
                ProjectOutboundTarget.enabled.is_(True),
            )
            .first()
        )
        if target is None:
            return "目标不在项目出站白名单"

        return None

    @staticmethod
    def build_url(environment: Environment, path: str, path_params: dict[str, str] | None = None) -> str:
        """拼接完整 URL：base_url + gateway_prefix + path，替换 path 参数。"""
        base = (environment.base_url or "").rstrip("/")
        gateway = (environment.gateway_prefix or "").rstrip("/")
        p = path or ""
        if path_params:
            for k, v in path_params.items():
                p = p.replace(f"{{{k}}}", str(v))
        return f"{base}{gateway}{p}"

    @staticmethod
    def get_environment_headers(environment: Environment) -> dict[str, str]:
        """获取环境默认请求头。"""
        if isinstance(environment.default_headers, dict):
            return {str(k): str(v) for k, v in environment.default_headers.items()}
        return {}
