"""跨领域 HTTP 请求发送实现。

业务执行器和接口调试共享单一流式发送循环；出站授权由共享策略协调，调用方继续适配各自错误契约。
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.execution.http.contracts import ApiRequestResult, HttpExecutionResult
from app.execution.http.outbound_policy import resolve_project_outbound_target

_MAX_RESPONSE_BODY = 200_000


def send_http_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    json_body: Any = None,
    json_body_present: bool = False,
    form_body: dict[str, str] | None = None,
    files: list[tuple[str, str]] | None = None,
    raw_body: str | bytes | None = None,
    timeout: float = 30,
) -> HttpExecutionResult:
    """使用统一的安全 httpx 配置流式发送一次请求并返回有界响应。"""
    result = HttpExecutionResult()
    send_kwargs: dict[str, Any] = {}
    request_headers = headers
    if json_body_present and json_body is None:
        # HTTPX 会把 json=None 当成没有请求体；显式 JSON null 必须发送四个字节，
        # 并保留调用方已经设置的 Content-Type。
        send_kwargs["content"] = b"null"
        if not any(key.lower() == "content-type" for key in (headers or {})):
            request_headers = {**(headers or {}), "Content-Type": "application/json"}
    elif json_body is not None:
        send_kwargs["json"] = json_body
    else:
        if form_body is not None:
            send_kwargs["data"] = form_body
        if files is not None:
            send_kwargs["files"] = files
        if raw_body is not None and form_body is None and files is None:
            send_kwargs["content"] = raw_body

    timeout_config = httpx.Timeout(
        connect=min(timeout, 10), write=timeout, read=timeout, pool=timeout,
    )
    started = time.perf_counter()
    chunks: list[bytes] = []
    try:
        _run_coroutine_sync(_send_streamed_request(
            result,
            method=method,
            url=url,
            headers=request_headers,
            query=query,
            cookies=cookies,
            send_kwargs=send_kwargs,
            timeout_config=timeout_config,
            chunks=chunks,
        ), timeout=timeout)
    except httpx.ConnectError as exc:
        result.transport_error_kind = "connect"
        result.transport_error_detail = str(exc)
        return result
    except (asyncio.TimeoutError, httpx.TimeoutException):
        result.transport_error_kind = "timeout"
        return result
    except httpx.HTTPError as exc:
        result.transport_error_kind = "http"
        result.transport_error_detail = str(exc)
        return result
    except ImportError as exc:
        result.transport_error_kind = "dependency"
        result.transport_error_detail = str(exc)
        return result

    result.response_time_ms = int((time.perf_counter() - started) * 1000)
    return result


async def _send_streamed_request(
    result: HttpExecutionResult,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None,
    query: dict[str, str] | None,
    cookies: dict[str, str] | None,
    send_kwargs: dict[str, Any],
    timeout_config: httpx.Timeout,
    chunks: list[bytes],
) -> None:
    """发送并读取一次响应；总时限由同步入口统一管理。"""
    # 环境代理关闭且不跟随重定向，避免请求离开已授权目标或跟随未校验的新主机。
    async with httpx.AsyncClient(
        timeout=timeout_config,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async with client.stream(
            method.upper(),
            url,
            headers=headers,
            params=query,
            cookies=cookies,
            **send_kwargs,
        ) as response:
            result.status_code = response.status_code
            result.request_url = str(response.request.url)
            result.response_headers = {str(key): str(value) for key, value in response.headers.items()}
            size = 0
            # aiter_bytes 可切开 UTF-8 多字节字符；先收集原始字节，再整体解码。
            async for chunk in response.aiter_bytes(chunk_size=65_536):
                chunks.append(chunk)
                size += len(chunk)
                if size > _MAX_RESPONSE_BODY:
                    result.response_body = _decode_chunks(chunks, truncated=True)
                    break
            else:
                result.response_body = _decode_chunks(chunks, truncated=False)


def _run_coroutine_sync(coroutine, *, timeout: float) -> None:
    """从同步调用方为整个 HTTP 协程设置墙钟总时限。

    执行器对外维持同步接口；若调用方已运行 asyncio 事件循环，则把协程放入专用
    线程的新事件循环执行，避免在活动中的循环内嵌套 ``asyncio.run``。
    """
    operation = asyncio.wait_for(coroutine, timeout=timeout)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(operation)
        return
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="http-executor") as pool:
        pool.submit(asyncio.run, operation).result()


def _decode_chunks(chunks: list[bytes], *, truncated: bool) -> str:
    """解码已读取响应分块，并保留原 200,000 字符截断标记。"""
    body = b"".join(chunks).decode("utf-8", errors="replace")
    if truncated:
        return body[:_MAX_RESPONSE_BODY] + "\n...[已截断]"
    return body


class ApiRequestExecutor:
    """带项目出站白名单检查的 HTTP 执行器，供业务、测试、安全和造数域调用。"""

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
        """校验项目出站授权后发送请求；传输错误沿用业务执行器的结果字段。"""
        try:
            decision = resolve_project_outbound_target(db, url, project_id)
        except ValueError:
            # 业务执行器原来不把非法端口转成出站拒绝结果，保持异常继续向上层传播。
            raise
        if decision.rejection_message:
            result = ApiRequestResult()
            result.error_message = decision.rejection_message
            return result

        result = send_http_request(
            method=method,
            url=url,
            headers=headers,
            query=query,
            cookies=cookies,
            json_body=json_body,
            form_body=form_body,
            raw_body=raw_body,
            timeout=timeout,
        )
        if result.transport_error_kind == "connect":
            result.error_message = f"连接失败：{result.transport_error_detail}"
        elif result.transport_error_kind == "timeout":
            result.error_message = f"请求超时（总时长上限 {timeout}s)"
        elif result.transport_error_kind == "http":
            result.error_message = f"请求失败：{result.transport_error_detail}"
        elif result.transport_error_kind == "dependency":
            # 旧业务执行器未把缺失传输依赖改成普通结果错误，继续让调用方看到导入异常。
            raise ImportError(result.transport_error_detail or "HTTP 请求依赖缺失")
        return result

__all__ = ["ApiRequestExecutor", "ApiRequestResult", "HttpExecutionResult", "send_http_request"]
