"""Mock Response Builder：按 Scenario 构造响应（§十一 / §十二）。

复用 ``app.execution.templates`` 的 ``resolve_template`` 解析 ``${request.*}`` /
``${runtime.*}`` 占位符（§十二：扩展现有解析器，不另起一套模板语言）。

行为类型（§七）：
- STATIC_RESPONSE：立即返回配置响应。
- DELAY_RESPONSE：等待 delay_ms 后返回配置响应。
- TIMEOUT：等待 delay_ms（受 mock_runtime_max_timeout 上限裁剪）后返回 504 空体，
  用于模拟依赖超时——被测系统的 HTTP 客户端通常在此之前已超时。
- EMPTY_RESPONSE：返回配置 status 但空 Body。

禁止任意代码执行（§十三）：只做结构化配置 + 占位符替换。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.features.mocking.models import MockScenario
from app.execution.templates.resolver import (
    RequestContext,
    ResolveScope,
    resolve_template,
)

# Runtime 超时上限（§七）：用户配置超过此值时拒绝保存或裁剪。
MOCK_RUNTIME_MAX_TIMEOUT = 60


@dataclass
class BuiltResponse:
    """构造完成的响应描述（不含延迟副作用，由 Runtime 应用）。"""

    status_code: int
    headers: dict[str, str]
    body: Any
    behavior_type: str
    delay_ms: int  # 实际等待毫秒（TIMEOUT / DELAY_RESPONSE 用，已裁剪到上限）


def build_response(
    scenario: MockScenario,
    *,
    request: RequestContext,
    request_id: str,
    timestamp: Any,
) -> BuiltResponse:
    """按 Scenario 构造响应。

    Args:
        scenario: 命中的 MockScenario（behavior_type / status_code / headers / body / template）。
        request: 请求上下文（path_params / query / headers / body），供 ``${request.*}``。
        request_id: 运行时请求ID，供 ``${runtime.request_id}``。
        timestamp: 运行时时间戳，供 ``${runtime.timestamp}``。

    Returns:
        BuiltResponse：status_code / headers / body / behavior_type / delay_ms。
    """
    scope = ResolveScope(
        request=request,
        runtime_request_id=request_id,
        runtime_timestamp=timestamp,
    )

    behavior = (scenario.behavior_type or "STATIC_RESPONSE").upper()
    delay_ms = _cap_delay(scenario.delay_ms, behavior)

    # 解析响应体：优先 response_template，回退 response_body；都经 resolve_template。
    raw_body = scenario.response_template if scenario.response_template is not None else scenario.response_body
    body = resolve_template(raw_body, scope, required=False) if raw_body is not None else None

    # 解析响应头（允许含占位符，如 ${request.header.X-User-Id}）。
    raw_headers = scenario.response_headers
    headers: dict[str, str] = {}
    if isinstance(raw_headers, dict):
        resolved = resolve_template(raw_headers, scope, required=False)
        if isinstance(resolved, dict):
            headers = {str(k): str(v) for k, v in resolved.items() if v is not None}

    if behavior == "TIMEOUT":
        # 超时模拟：等待后返回 504 空体（被测系统通常已先行超时）。
        return BuiltResponse(
            status_code=504, headers={}, body=None,
            behavior_type=behavior, delay_ms=delay_ms,
        )
    if behavior == "EMPTY_RESPONSE":
        return BuiltResponse(
            status_code=int(scenario.status_code or 200), headers=headers, body=None,
            behavior_type=behavior, delay_ms=0,
        )
    # STATIC_RESPONSE / DELAY_RESPONSE：返回配置响应（DELAY 多等 delay_ms）。
    status_code = int(scenario.status_code or 200)
    return BuiltResponse(
        status_code=status_code, headers=headers, body=body,
        behavior_type=behavior, delay_ms=delay_ms,
    )


def _cap_delay(delay_ms: int | None, behavior: str) -> int:
    """把 delay_ms 裁剪到 MOCK_RUNTIME_MAX_TIMEOUT 上限。

    DELAY_RESPONSE / TIMEOUT 才需要等待；STATIC_RESPONSE / EMPTY_RESPONSE 不等待。
    """
    if behavior not in ("DELAY_RESPONSE", "TIMEOUT"):
        return 0
    raw = int(delay_ms or 0)
    if raw < 0:
        return 0
    return min(raw, MOCK_RUNTIME_MAX_TIMEOUT * 1000)


__all__ = [
    "BuiltResponse",
    "MOCK_RUNTIME_MAX_TIMEOUT",
    "build_response",
]
