"""免登录缺陷分享的分布式限流与可信代理 IP 解析。

特性：
1. 支持 Redis Sorted-Set 原子 Lua 滑动窗口（IPv4/IPv6 + share_id + action/failure 多维限流）；
2. Redis 键使用 HMAC-SHA256 哈希，不直接存储原始 IP / share_id；
3. 每个滑窗键设置精确 TTL（window + 5s），避免 Redis 内存无限增长；
4. 仅信任显式配置于 TRUSTED_PROXY_CIDRS 的反向代理转发头（自右向左剥离可信代理），
   未匹配可信代理时忽略客户端伪造的 X-Forwarded-For / X-Real-IP；
5. Redis 不可用时按 PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED 执行明确降级：
   False -> 节流告警并退化到有界进程内滑窗；True -> 返回 503 拒绝放行。
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import threading
import time
import uuid
from collections import deque

from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60
_IP_LIMITS = {"view": 60, "resolve": 8, "failure": 8}
_SHARE_LIMITS = {"view": 180, "resolve": 20, "failure": 20}
_MAX_LOCAL_KEYS = 5_000
_KEY_PREFIX = "public-share:rl"

_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count >= limit then
  redis.call('PEXPIRE', key, window + 5000)
  return {0, count}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window + 5000)
return {1, count + 1}
"""

_lock = threading.Lock()
_events: dict[str, deque[float]] = {}
_redis_lock = threading.Lock()
_redis_url_cached: str | None = None
_redis_client = None
_redis_script = None
_last_error_log_at: float = 0.0
_trusted_nets_cache_raw: str | None = None
_trusted_nets_cache: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()


def _parse_ip(raw: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse IPv4/IPv6 string (optionally bracketed and/or with :port) safely."""
    if not raw:
        return None
    text = raw.strip().strip('"').strip("'")
    if not text:
        return None
    if text.startswith("["):
        end = text.find("]")
        if end == -1:
            return None
        text = text[1:end]
    elif text.count(":") == 1 and "." in text:
        # IPv4 with port, e.g. 203.0.113.10:54321
        text = text.split(":", 1)[0]
    if "%" in text:
        text = text.split("%", 1)[0]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _trusted_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    global _trusted_nets_cache_raw, _trusted_nets_cache
    raw = (settings.TRUSTED_PROXY_CIDRS or "").strip()
    if raw == _trusted_nets_cache_raw:
        return _trusted_nets_cache
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for token in raw.split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            nets.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            logger.warning("忽略无效的 TRUSTED_PROXY_CIDRS 配置项：%s", candidate)
    _trusted_nets_cache_raw = raw
    _trusted_nets_cache = tuple(nets)
    return _trusted_nets_cache


def _is_trusted(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address, nets: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]) -> bool:
    return any(ip_obj in net for net in nets)


def extract_client_ip(request: Request) -> str:
    """解析真实客户端 IP：仅当直连对端属于可信代理网段时才采信转发头。"""
    peer_raw = request.client.host if request.client else ""
    peer_ip = _parse_ip(peer_raw)
    if peer_ip is None:
        return "unknown"

    trusted_nets = _trusted_networks()
    if not trusted_nets or not _is_trusted(peer_ip, trusted_nets):
        return peer_ip.compressed

    xff = request.headers.get("x-forwarded-for") or ""
    if xff.strip():
        hops = [part.strip() for part in xff.split(",") if part.strip()]
        # Right-to-left walk ignores spoofed left entries prepended by untrusted clients.
        for raw_hop in reversed(hops):
            hop_ip = _parse_ip(raw_hop)
            if hop_ip is None:
                # Malformed hop inserted inside proxy chain: stop trusting further left.
                return peer_ip.compressed
            if not _is_trusted(hop_ip, trusted_nets):
                return hop_ip.compressed

    real_ip = _parse_ip(request.headers.get("x-real-ip"))
    if real_ip is not None and not _is_trusted(real_ip, trusted_nets):
        return real_ip.compressed

    return peer_ip.compressed


def _hash_dimension(kind: str, value: str) -> str:
    salt = (settings.PUBLIC_SHARE_RATE_LIMIT_SALT or settings.SECRET_KEY or "rate-limit").encode("utf-8")
    digest = hmac.new(salt, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:24]


def _get_redis_script():
    global _redis_url_cached, _redis_client, _redis_script
    url = (settings.REDIS_URL or "").strip()
    if not url:
        return None
    with _redis_lock:
        if _redis_client is not None and _redis_url_cached == url:
            return _redis_script
        import redis

        _redis_client = redis.Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        _redis_script = _redis_client.register_script(_SLIDING_WINDOW_LUA)
        _redis_url_cached = url
        return _redis_script


def _consume_local(key: str, limit: int) -> bool:
    now = time.monotonic()
    with _lock:
        if len(_events) > _MAX_LOCAL_KEYS:
            _events.clear()
        window = _events.setdefault(key, deque())
        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True


def _consume_bucket(key: str, limit: int) -> None:
    global _last_error_log_at
    script = None
    try:
        script = _get_redis_script()
    except Exception as exc:  # noqa: BLE001 - 统一走降级分支
        script = None
        _log_redis_degraded(exc)

    if script is not None:
        now_ms = int(time.time() * 1000)
        window_ms = _WINDOW_SECONDS * 1000
        member = f"{now_ms}:{uuid.uuid4().hex[:12]}"
        try:
            allowed, _count = script(keys=[key], args=[now_ms, window_ms, limit, member])
            if int(allowed) == 0:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="请求过于频繁，请稍后再试",
                )
            return
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - Redis 不可用时按配置执行降级策略
            _log_redis_degraded(exc)
            if settings.PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="限流服务暂不可用，请稍后重试",
                ) from exc

    if settings.PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED and (settings.REDIS_URL or "").strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="限流服务暂不可用，请稍后重试",
        )

    if not _consume_local(key, limit):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        )


def _log_redis_degraded(exc: BaseException) -> None:
    global _last_error_log_at
    now = time.monotonic()
    if now - _last_error_log_at >= 30.0:
        _last_error_log_at = now
        logger.warning(
            "公开分享分布式限流 Redis 不可用（fail_closed=%s）：%s",
            settings.PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED,
            type(exc).__name__,
        )


def enforce_public_share_limit(request: Request, bucket: str, share_id: str | None = None) -> None:
    """按客户端 IP 与 share_id 双维度执行动作限流，超限返回 429。"""
    if bucket not in _IP_LIMITS:
        raise RuntimeError("未知的公开分享限流桶")

    client_ip = extract_client_ip(request)
    ip_digest = _hash_dimension("ip", client_ip)
    _consume_bucket(f"{_KEY_PREFIX}:{bucket}:ip:{ip_digest}", _IP_LIMITS[bucket])

    if share_id:
        share_digest = _hash_dimension("share", share_id)
        _consume_bucket(f"{_KEY_PREFIX}:{bucket}:share:{share_digest}", _SHARE_LIMITS[bucket])
        if bucket == "failure":
            pair_digest = _hash_dimension("pair", f"{client_ip}:{share_id}")
            _consume_bucket(f"{_KEY_PREFIX}:failure:pair:{pair_digest}", _IP_LIMITS["failure"])


def reset_public_share_limits() -> None:
    """测试清理本地滑窗与测试期 Redis 限流键。"""
    with _lock:
        _events.clear()
    url = (settings.REDIS_URL or "").strip()
    if not url:
        return
    try:
        _get_redis_script()
        if _redis_client is not None:
            cursor = 0
            while True:
                cursor, keys = _redis_client.scan(cursor=cursor, match=f"{_KEY_PREFIX}:*", count=200)
                if keys:
                    _redis_client.delete(*keys)
                if cursor == 0:
                    break
    except Exception:  # noqa: BLE001 - 测试清理忽略不可达的 Redis
        pass
