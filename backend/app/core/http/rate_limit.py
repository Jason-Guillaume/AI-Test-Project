"""登录与注册端点的进程内滑动窗口限流。

多 API 进程部署时应在可信网关侧再叠加共享限制，这里只作为单进程内的附加屏障。
沿用旧项目语义：登录按「IP + 用户名」双维度，注册按「IP / 小时」。
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

from app.core.config import settings

_lock = threading.Lock()
_events: dict[str, deque[float]] = {}
_limits: dict[str, int] = {}
_last_sweep = 0.0
_MAX_TRACKED_KEYS = 50_000


def _client_ip(request: Request) -> str:
    """仅使用直连对端地址；不信任转发头，避免伪造绕过限流。"""
    return request.client.host if request.client else "unknown"


def _count_within(key: str, window_seconds: int, now: float | None = None) -> int:
    """统计窗口内的事件次数并追加本次请求。

    Args:
            key: 计数键（如 "login:ip:1.2.3.4"、"login:user:alice"、"register:1.2.3.4"）。
            window_seconds: 滑动窗口长度，单位秒（登录 60 秒、注册 3600 秒）。
        now: 注入的单调时间，默认取 time.monotonic()；便于单测固定时间。

    Returns:
        int: 追加本次请求之后窗口内的事件总数；超过 _limits[key] 即判定超限。
    """
    now = now if now is not None else time.monotonic()
    limit = _limits[key]
    window = _events.get(key)
    if window is None:
        window = deque()
        _events[key] = window
    while window and now - window[0] > window_seconds:
        window.popleft()
    window.append(now)
    return len(window)


def enforce_auth_rate_limit(request: Request, action: str, *, username: str | None = None) -> None:
    """对登录/注册动作执行限流，超限时抛出 429。"""
    global _last_sweep  # noqa: PLW0603
    ip = _client_ip(request)
    now = time.monotonic()
    with _lock:
        if now - _last_sweep > 300 and len(_events) > _MAX_TRACKED_KEYS:
            _events.clear()
            _limits.clear()
            _last_sweep = now

        if action == "register":
            key = f"register:{ip}"
            limit = int(settings.AUTH_REGISTER_IP_LIMIT_PER_HOUR)
            window = 3600
        elif username:
            key = f"login:user:{username}"
            limit = int(settings.AUTH_LOGIN_USERNAME_LIMIT_PER_MINUTE)
            window = 60
        else:
            key = f"login:ip:{ip}"
            limit = int(settings.AUTH_LOGIN_IP_LIMIT_PER_MINUTE)
            window = 60

        _limits[key] = limit
        count = _count_within(key, window, now)

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        )


def reset_rate_limits() -> None:
    """测试用：清空限流计数。"""
    with _lock:
        _events.clear()
        _limits.clear()
