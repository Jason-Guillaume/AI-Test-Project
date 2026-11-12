"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit
from app.features.security_testing.zap.contracts import AUTH_MODE_NONE
from app.features.security_testing.zap.transport import ZAPTransport, ZAPTransportError
from dataclasses import dataclass, field


ZAP_REASON_UNAVAILABLE = "ZAP_SERVICE_UNAVAILABLE"


ZAP_REASON_API_AUTH_FAILED = "ZAP_API_AUTH_FAILED"


ZAP_REASON_PLUGIN_MISSING = "ZAP_PLUGIN_MISSING"


ZAP_REASON_VERSION_UNSUPPORTED = "ZAP_VERSION_UNSUPPORTED"


ZAP_REASON_CONTEXT_FAILED = "ZAP_CONTEXT_FAILED"


ZAP_REASON_SPIDER_FAILED = "ZAP_SPIDER_FAILED"


ZAP_REASON_ACTIVE_FAILED = "ZAP_ACTIVE_FAILED"


ZAP_REASON_BAD_RESPONSE = "ZAP_BAD_RESPONSE"


ZAP_REASON_SCOPE_VIOLATION = "SECURITY_SCAN_SCOPE_VIOLATION"


MIN_SUPPORTED_ZAP_VERSION = (2, 12, 0)


MIN_SUPPORTED_VERSION_TEXT = "2.12.0"


CAP_ABOUT = "core.about"


CAP_SPIDER = "spider"


CAP_CLIENT_SPIDER = "clientspider"


CAP_AJAX_SPIDER = "ajaxspider"


CAP_PASSIVE = "passive"


CAP_ACTIVE = "active"


CAP_OPENAPI = "openapi"


CAP_AUTH = "authentication"


CAP_SESSION = "session"


CAP_SCANNER_POOL = "scannerpool"


CAP_HISTORY = "core.history"


CAP_URLS = "core.urls"


CAP_ACTIVE_LIMITS = "active.limits"


_ADDON_TO_CAPABILITY: dict[str, str] = {
    "clientSpider": CAP_CLIENT_SPIDER,
    "ajaxSpider": CAP_AJAX_SPIDER,
    "openapi": CAP_OPENAPI,
    "authhelper": CAP_AUTH,
    "openapiSupport": CAP_OPENAPI,
}


ACTIVE_MAX_DURATION_HARD_CAP = 60          # 分钟


ACTIVE_MAX_RULE_DURATION_HARD_CAP = 20     # 分钟


ACTIVE_MAX_CONCURRENCY_HARD_CAP = 20       # 线程


ACTIVE_MIN_REQUEST_DELAY_MS = 0


ACTIVE_MAX_REQUEST_DELAY_MS = 2000         # 毫秒


ACTIVE_MAX_ALERTS_PER_RULE_HARD_CAP = 50


ACTIVE_DEPTH_HARD_CAP = 8


class ZAPConnectorError(Exception):
    """Connector 层错误。

    reason 是稳定的标识符（可直接映射业务错误码）；
    message 是给人看的中文说明，不含 API Key / Token / 响应体原文。
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        status_code: int | None = None,
        path: str = "",
        retryable: bool = False,
    ) -> None:
        """初始化错误。"""
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.status_code = status_code
        self.path = path
        # retryable=True 仅表示「重连后可能成功」，是否重试由 Worker 决定并记录。
        self.retryable = retryable


def parse_zap_version(version: str) -> tuple[int, ...] | None:
    """解析 "2.16.0" → (2, 16, 0)；无法解析返回 None。"""
    parts = (version or "").strip().split(".")
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    if not numbers:
        return None
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers[:3])  # type: ignore[return-value]


def is_supported_version(version: str) -> bool:
    """是否 >= 最低支持版本。"""
    parsed = parse_zap_version(version)
    if parsed is None:
        return False
    return parsed >= MIN_SUPPORTED_ZAP_VERSION


def map_alert_severity(risk: str) -> str:
    """延迟导入避免模块级循环。"""
    from app.features.security_testing.zap.contracts import map_zap_risk

    return map_zap_risk(risk)


def _describe(message: str, *, path: str) -> str:
    """把传输层消息变成带路径上下文的中文说明，去掉内部字段名。"""
    text = (message or "ZAP 请求失败").strip()
    return f"{text}（{path}）" if path and path not in text else text


def _map_reason(exc: ZAPTransportError, *, default: str) -> str:
    """传输层状态码 → Connector 错误原因。"""
    if exc.status_code is None:
        return ZAP_REASON_UNAVAILABLE
    if exc.status_code in (401, 403):
        return ZAP_REASON_API_AUTH_FAILED
    if exc.status_code == 404:
        # 404 可能是「组件不存在」也可能是「该 URL 不在扫描范围内」。
        # 用 default 区分：调用方知道自己期望的是哪个能力。
        return ZAP_REASON_PLUGIN_MISSING if default != ZAP_REASON_BAD_RESPONSE else ZAP_REASON_BAD_RESPONSE
    return default


def _as_bool(value: Any) -> bool:
    """ZAP 的布尔值经常是字符串 "true" / 0 / 1。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return False


def _int_of(value: Any) -> int | None:
    """尽力转 int；失败返回 None 而不是 0（区分「未知」与「真的是 0」）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _string_of(body: dict[str, Any], key: str, fallback: Any = "") -> Any:
    """取一个字段；缺失时返回 fallback。"""
    value = body.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return fallback
    return value


def _auth_detail(session_method: str, authenticated: bool, verified: bool) -> str:
    """生成一句可审计的中文说明，不含任何凭据值。"""
    if session_method in ("none", ""):
        return "未配置认证"
    if not verified:
        return f"认证状态无法判定（Session 管理方式：{session_method}）"
    if authenticated:
        return f"已验证登录成功（Session 管理方式：{session_method}）"
    return f"已验证但登录失败（Session 管理方式：{session_method}）"


def _escape_regex(text: str) -> str:
    """把路径转成安全的正则片段。

    不做转义就是把用户输入的路径当成 ZAP 的正则执行——一次前缀匹配的排除
    路径就能让整站被排除（或反过来把不该扫的扫进来）。
    """
    return re.escape((text or "").strip().lstrip("/"))


def _to_regex(base_url: str, path: str) -> str:
    """把 (base_url, path) 合成一条 ZAP 可用的范围正则。"""
    parts = urlsplit(base_url)
    host = re.escape(parts.netloc)
    base = r"https?://" + host
    needle = re.escape((path or "").strip().lstrip("/"))
    return base + "/" + needle if needle else base


@dataclass
class ZAPProtocolState:
    """单次串行连接器的协议状态；不保存认证凭据或数据库句柄。"""

    transport: ZAPTransport
    timeout: float = 30.0
    scan_ids: list[str] = field(default_factory=list)
    auth_mode: str = AUTH_MODE_NONE
    session_method: str = "none"
    has_session_value: bool = False
    scope_hosts: list[str] = field(default_factory=list)
    scope_base_url: str = ""
