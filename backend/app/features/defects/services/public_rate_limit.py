"""免登录缺陷分享的进程内限流。

登录和注册继续使用 app.core.http.rate_limit 的固定键。
这里单独计数，避免公开接口的访问量改写那三组认证限流键。
多进程部署时仍应在网关再加一层限制。
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

_lock = threading.Lock()
_events: dict[str, deque[float]] = {}
_LIMITS = {"view": 60, "resolve": 8, "failure": 8}
_WINDOW_SECONDS = 60
_MAX_KEYS = 5_000


def _client_ip(request: Request) -> str:
    """只使用直连地址，不读取可伪造的转发头。"""
    return request.client.host if request.client else "unknown"


def enforce_public_share_limit(request: Request, bucket: str) -> None:
    """按 IP 和动作计数。超过窗口上限时返回 429。

    bucket 只能是 view、resolve 或 failure。failure 用于连续错误凭证，
    用来拖慢对 share_id 的猜测，不替代凭证本身的随机强度。
    """
    if bucket not in _LIMITS:
        raise RuntimeError("未知的公开分享限流桶")
    key = f"public-share:{bucket}:{_client_ip(request)}"
    now = time.monotonic()
    limit = _LIMITS[bucket]
    with _lock:
        if len(_events) > _MAX_KEYS:
            _events.clear()
        window = _events.setdefault(key, deque())
        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()
        window.append(now)
        count = len(window)
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        )


def reset_public_share_limits() -> None:
    """测试清空公开分享计数，不影响登录限流。"""
    with _lock:
        _events.clear()
