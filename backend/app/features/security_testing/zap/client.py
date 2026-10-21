"""ZAP 连接器工厂。

唯一的构造入口：Worker 与服务层都从这里拿 ``ZAPConnector``，不要在各处自己拼
transport（§六「不允许 Router 直接拼 ZAP API 请求」）。

测试注入：``build_connector(transport=MockZAPTransport(...))`` 可完全绕开网络，
这也是 test_28 全量单测不发任何出站请求的原因。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.features.security_testing.zap.connector import ZAPConnector
from app.features.security_testing.zap.transport import (
    ZAP_API_KEY_MODE_HEADER,
    ZAP_API_KEY_MODE_QUERY,
    HttpZAPTransport,
    ZAPTransport,
)
from app.shared.config import settings


@dataclass(slots=True)
class ZapServiceState:
    """ZAP 服务配置状态（不含任何明文密钥）。"""

    enabled: bool
    configured: bool
    api_key_configured: bool
    api_key_mode: str
    base_host: str = ""
    message: str = ""


def get_zap_state() -> ZapServiceState:
    """读取 ZAP 服务配置状态，用于健康检查页与能力检测页。

    不返回 ZAP_BASE_URL 全文，只返回 host——避免把内网拓扑信息扩散到前端。
    """
    base_url = (settings.ZAP_BASE_URL or "").strip().rstrip("/")
    api_key = _api_key()
    mode = settings.ZAP_API_KEY_MODE if settings.ZAP_API_KEY_MODE in (
        ZAP_API_KEY_MODE_HEADER, ZAP_API_KEY_MODE_QUERY,
    ) else ZAP_API_KEY_MODE_HEADER
    configured = bool(base_url)
    return ZapServiceState(
        enabled=bool(settings.ZAP_ENABLED),
        configured=configured,
        api_key_configured=bool(api_key),
        api_key_mode=mode,
        base_host=_host_only(base_url),
        message=_state_message(bool(settings.ZAP_ENABLED), configured, bool(api_key)),
    )


def build_connector(transport: ZAPTransport | None = None, *, base_url: str | None = None) -> ZAPConnector:
    """构造一个 ZAPConnector。

    Args:
        transport: 传入则直接使用（测试用 Mock）。不传时按配置构造 HttpZAPTransport。
        base_url: 覆盖配置里的 ZAP_BASE_URL（仅在未传 transport 时生效）。

    Raises:
        ValueError: 未配置 ZAP_BASE_URL 且未注入 transport。
    """
    if transport is None:
        url = (base_url or settings.ZAP_BASE_URL or "").strip().rstrip("/")
        if not url:
            raise ValueError("ZAP 服务未配置：请在部署侧设置 ZAP_BASE_URL")
        mode = settings.ZAP_API_KEY_MODE if settings.ZAP_API_KEY_MODE in (
            ZAP_API_KEY_MODE_HEADER, ZAP_API_KEY_MODE_QUERY,
        ) else ZAP_API_KEY_MODE_HEADER
        transport = HttpZAPTransport(
            url,
            _api_key(),
            timeout_seconds=float(settings.ZAP_TIMEOUT_SECONDS),
            api_key_mode=mode,
            verify_tls=bool(settings.ZAP_VERIFY_TLS),
        )
    return ZAPConnector(transport, timeout_seconds=float(settings.ZAP_TIMEOUT_SECONDS))


def _api_key() -> str:
    """读取 ZAP API Key 明文（进程内传递，不写日志）。"""
    try:
        from app.shared.config import zap_api_key

        return zap_api_key()
    except Exception:  # noqa: BLE001 - 配置缺失时按「未配置」处理，不阻断健康检查
        return ""


def _host_only(url: str) -> str:
    """只保留 scheme://netloc，用于展示；不泄露路径与查询串。"""
    from urllib.parse import urlsplit

    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme else parts.netloc


def _state_message(enabled: bool, configured: bool, key_configured: bool) -> str:
    """给出面向前端的中文状态说明。"""
    if not enabled:
        return "ZAP 安全扫描未启用（ZAP_ENABLED=false）"
    if not configured:
        return "ZAP 服务未配置：缺少 ZAP_BASE_URL"
    if not key_configured:
        return "ZAP 服务已配置，但未设置 ZAP_API_KEY_ENCRYPTED，连接可能会被拒绝"
    return "ZAP 服务已配置"


def settings_dict() -> dict[str, Any]:
    """当前 ZAP 相关配置的可展示副本（不含密钥）。"""
    return {
        "ZAP_ENABLED": bool(settings.ZAP_ENABLED),
        "ZAP_API_KEY_MODE": settings.ZAP_API_KEY_MODE,
        "ZAP_VERIFY_TLS": bool(settings.ZAP_VERIFY_TLS),
        "ZAP_TIMEOUT_SECONDS": float(settings.ZAP_TIMEOUT_SECONDS),
        "ZAP_MAX_CONCURRENT_JOBS": int(settings.ZAP_MAX_CONCURRENT_JOBS),
        "ZAP_MAX_JOB_DURATION_SECONDS": int(settings.ZAP_MAX_JOB_DURATION_SECONDS),
        "ZAP_PASSIVE_WAIT_SECONDS": int(settings.ZAP_PASSIVE_WAIT_SECONDS),
        "ZAP_REQUEST_BUDGET": int(settings.ZAP_REQUEST_BUDGET),
    }
