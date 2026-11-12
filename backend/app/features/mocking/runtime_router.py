"""Mock Runtime 执行面路由（§十四 / §十七）。

挂在 ``/api/v1/mock`` 下，catch-all ``/{project_id}/{service_key}/{path:path}``，
**不要求平台 JWT**：鉴权走 X-Mock-Token（或 public_runtime 放行），与执行面分离。

延迟 / 超时由本路由 ``asyncio.sleep`` 应用（``MockRuntimeService.handle_request``
只返回 ``delay_ms``，不 sleep）。同步 DB 操作（匹配 + 记录）放线程池，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.features.mocking.services.mock_runtime_service import (
    MockRuntimeService,
)
from app.core.database.session import get_db

router = APIRouter(prefix="/mock", tags=["Mock Runtime"])

_RUNTIME = MockRuntimeService()

# 执行面接受的全部 HTTP 方法（含 HEAD/OPTIONS，便于覆盖被测依赖的真实动词）。
_RUNTIME_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _parse_body(raw: bytes) -> Any:
    """把原始请求体解析成 JSON；失败回退字符串，空体返回 None。"""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        return raw.decode("utf-8", errors="replace")



@router.api_route("/{project_id}/{service_key}/{path:path}", methods=_RUNTIME_METHODS)
async def mock_runtime(
    project_id: int,
    service_key: str,
    path: str,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Mock Runtime 入口：匹配 Scenario → 构造响应 → 应用延迟 → 返回。"""
    started = time.perf_counter()
    request_id = getattr(request.state, "request_id", "") or ""

    method = request.method
    # {path:path} 捕获不含前导斜杠，补回以与 Endpoint.path（/payments/{id}）对齐。
    actual_path = path if path.startswith("/") else "/" + path
    query = {k: v for k, v in request.query_params.multi_items()}
    headers = {k: v for k, v in request.headers.items()}
    raw_body = await request.body()
    body = _parse_body(raw_body)

    result = await run_in_threadpool(
        _RUNTIME.handle_runtime_request, db,
        project_id=project_id, service_key=service_key, method=method, path=actual_path,
        query=query, headers=headers, body=body,
        request_id=request_id, started_perf=started,
    )

    # 延迟 / 超时模拟：DELAY_RESPONSE / TIMEOUT 在此真正等待。
    if result.delay_ms and result.delay_ms > 0:
        await asyncio.sleep(result.delay_ms / 1000.0)

    return JSONResponse(
        status_code=result.status_code,
        content=result.body if result.body is not None else None,
        headers=dict(result.headers),
    )


__all__ = ["router"]
