"""认证配置的进程内转换与在线验证（§十一 / §十二 / §十三）。

两件独立的事：

1. ``build_auth_config``：把库里的一行 SecurityScanAuthProfile 转成
   ``connector.configure_authentication`` 需要的 dict。凭据在这里解密一次，
   传完即用，本模块不写日志、不落库、不返回明文字符串到任何响应。

2. ``check_credential_live``：在扫描前调用用户在认证配置里填的验证接口，
   用 ``logged_in_indicator`` / ``logged_out_indicator`` / ``expected_user_id``
   判断是否真的登录。**不以 HTTP 200 作为登录成功依据**——200 只说明接口通，
   只有命中 logged_in_indicator 或响应体里出现 expected_user_id 才算登录成功。
   任何拿不到响应、判定不了的情况一律返回 ``(False, False, 原因)``，
   由编排器决定是记 UNVERIFIABLE 还是失败，绝不错报为 LOGGED_IN。
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.features.security_testing.zap.contracts import (
    AUTH_MODE_BEARER_TOKEN,
    AUTH_MODE_BROWSER_AUTH,
    AUTH_MODE_HEADER_BASED,
    AUTH_MODE_MANUAL,
    AUTH_MODE_NONE,
)
from app.features.security_testing.zap.models.auth_profile import SecurityScanAuthProfile
from app.features.security_testing.zap.services import auth_profile_service
from app.core.config import settings

log = logging.getLogger(__name__)

#: ZAP authentication 组件的登录策略取值。
STRATEGY_MANUAL = "manual"
STRATEGY_USERNAME_PASSWORD = "usernamePassword"

#: 浏览器登录模式下把会话值以 cookie 形式写入。
COOKIE_SESSION_METHOD = "cookieBased"
#: 请求级鉴权模式下以 header 形式附加。
HEADER_SESSION_METHOD = "headerBased"
NONE_SESSION_METHOD = "none"


def build_auth_config(auth_profile: SecurityScanAuthProfile | None) -> dict[str, Any]:
    """把认证配置行转成 connector 需要的 dict（凭据明文只出现在这个返回值里）。"""
    if auth_profile is None:
        return {"auth_mode": AUTH_MODE_NONE, "session_method": NONE_SESSION_METHOD}

    credential = auth_profile_service.decrypt_credential(auth_profile)
    mode = auth_profile.auth_mode
    config: dict[str, Any] = {
        "auth_mode": mode,
        "session_method": NONE_SESSION_METHOD,
    }
    if mode == AUTH_MODE_MANUAL:
        # 人工扫码：不注入任何凭据，也不冒充已登录（§十三）。
        config.update({
            "auth_mode": AUTH_MODE_MANUAL,
            "session_method": NONE_SESSION_METHOD,
            "strategy": STRATEGY_MANUAL,
        })
        return config
    if mode == AUTH_MODE_NONE:
        return config

    header = (auth_profile.session_header or "").strip() or "Authorization"
    name = (auth_profile.session_name or "").strip()
    if mode == AUTH_MODE_BEARER_TOKEN:
        # Bearer Token 固定走 Authorization: Bearer <token>。
        config.update({
            "auth_mode": AUTH_MODE_BEARER_TOKEN,
            "session_method": HEADER_SESSION_METHOD,
            "session_header": "Authorization",
            "session_name": "Authorization",
            "session_value": f"Bearer {credential}".strip(),
            "strategy": STRATEGY_MANUAL,
        })
        return config
    if mode == AUTH_MODE_HEADER_BASED:
        config.update({
            "auth_mode": AUTH_MODE_HEADER_BASED,
            "session_method": HEADER_SESSION_METHOD,
            "session_header": header,
            "session_name": name or header,
            "session_value": credential,
            "strategy": STRATEGY_MANUAL,
        })
        return config
    if mode == AUTH_MODE_BROWSER_AUTH:
        # 浏览器登录态：以 cookie 会话方式交给 Client Spider。
        config.update({
            "auth_mode": AUTH_MODE_BROWSER_AUTH,
            "session_method": COOKIE_SESSION_METHOD,
            "session_header": header,
            "session_name": name or header,
            "session_value": credential,
            "strategy": STRATEGY_MANUAL,
        })
        return config
    config.update({"strategy": STRATEGY_MANUAL})
    return config


def check_credential_live(
    *,
    check_url: str,
    credential: str,
    auth_mode: str = AUTH_MODE_HEADER_BASED,
    session_header: str = "Authorization",
    session_name: str = "",
    logged_in_indicator: str = "",
    logged_out_indicator: str = "",
    expected_user_id: str = "",
    allowed_hosts: list[str] | None = None,
    timeout_seconds: float | None = None,
    client: httpx.Client | None = None,
) -> tuple[bool, bool, str]:
    """调用用户配置的验证接口，判断凭据是否仍处于登录态。

    Returns:
        (reachable, logged_in, detail)：
        - reachable=False 表示接口没通（连接失败、超时、404 等），此时
          logged_in 必为 False，调用方不得把它当成「登录成功」。
        - logged_in=True 必须命中 logged_in_indicator 或 expected_user_id。
        - 未配置任何判定依据时返回 (True, False, "未配置登录态判定依据")，
          由编排器记为 UNVERIFIABLE。
    """
    from app.features.security_testing.zap import scope_guard

    url = (check_url or "").strip()
    if not url:
        return False, False, "认证配置未提供验证接口"
    try:
        scope_guard.validate_target_url(url, allowed_hosts=allowed_hosts or None)
    except Exception as exc:  # noqa: BLE001 - 校验失败按「不可达」返回，不抛
        return False, False, f"验证接口地址不合规：{getattr(exc, 'message', '') or exc}"

    headers: dict[str, str] = {}
    if credential and auth_mode in (AUTH_MODE_HEADER_BASED, AUTH_MODE_BROWSER_AUTH):
        name = (session_name or session_header or "X-Auth-Token").strip() or "X-Auth-Token"
        headers[name] = credential
    elif credential and auth_mode == AUTH_MODE_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {credential}".strip()

    timeout = timeout_seconds if timeout_seconds is not None else max(2.0, float(settings.ZAP_TIMEOUT_SECONDS))
    close_after = client is None
    http_client = client or httpx.Client(verify=bool(settings.ZAP_VERIFY_TLS), trust_env=False, follow_redirects=False)
    try:
        response = http_client.get(url, headers=headers, timeout=timeout)
        body = (response.text or "")[:8000]
    except httpx.HTTPError as exc:
        return False, False, f"验证接口调用失败：{type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001
        log.warning("认证验证接口调用出现未预期异常：%s", exc)
        return False, False, "验证接口调用出现未预期异常"
    finally:
        if close_after:
            http_client.close()

    if response.status_code >= 500:
        return False, False, f"验证接口返回服务端错误（HTTP {response.status_code}）"
    if response.status_code >= 400:
        # 401/403/404 都说明这条凭据在验证接口上不被接受。
        return True, False, f"验证接口返回 HTTP {response.status_code}，凭据未被接受"

    if not logged_in_indicator and not logged_out_indicator and not expected_user_id:
        return True, False, "未配置登录态判定依据（logged_in_indicator / expected_user_id）"

    if logged_out_indicator and _match(logged_out_indicator, body):
        return True, False, "命中未登录判定正则"
    if logged_in_indicator:
        if _match(logged_in_indicator, body):
            return True, True, "命中已登录判定正则"
        return True, False, "未命中已登录判定正则"
    if expected_user_id:
        if expected_user_id in body:
            return True, True, "响应体中出现预期用户标识"
        return True, False, "响应体中未出现预期用户标识"
    return True, False, "无法判定登录态"


def _match(pattern: str, body: str) -> bool:
    """按正则匹配登录态判定依据；正则本身非法时按字面量匹配，不误判。"""
    text = pattern or ""
    if not text:
        return False
    try:
        return re.search(text, body, re.DOTALL) is not None
    except re.error:
        return text in body
