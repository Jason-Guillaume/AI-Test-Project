"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any, Mapping
from app.features.security_testing.zap.contracts import (
    AUTH_STATUS_LOGGED_IN,
    AUTH_STATUS_LOGGED_OUT,
    AUTH_STATUS_UNVERIFIABLE,
    AUTH_MODE_MANUAL,
    AUTH_MODE_NONE,
    ZAPAuthResult,
)
from app.features.security_testing.zap.protocol.common import ZAPConnectorError
from app.features.security_testing.zap.protocol.common import ZAPProtocolState
from app.features.security_testing.zap.protocol.common import ZAP_REASON_PLUGIN_MISSING
from app.features.security_testing.zap.protocol.common import _as_bool
from app.features.security_testing.zap.protocol.common import _auth_detail
from app.features.security_testing.zap.protocol.transport import call


def configure_authentication(state: ZAPProtocolState, auth: Mapping[str, Any]) -> ZAPAuthResult:
    """配置认证并把登录态验证结果返回。

    auth 支持的键（其余忽略）：
        auth_mode: NONE / BEARER_TOKEN / HEADER_BASED / BROWSER_AUTH / MANUAL
        session_method: none / headerBased / cookieBased
        session_header: 如 "Authorization"
        session_name:   如 "X-Auth-Token"
        session_value:  **明文凭据，传完即用，本方法不做任何留存**
        logged_in_indicator / logged_out_indicator: 登录态判定正则
        user_agent_script: JS 片段（设置 XSRF token 等）
        strategy: manual / usernamePassword
    """
    mode = str(auth.get("auth_mode") or AUTH_MODE_NONE)
    session_method = str(auth.get("session_method") or "none")
    state.auth_mode = mode
    state.session_method = session_method
    state.has_session_value = bool(str(auth.get("session_value") or "").strip())
    try:
        call(state, "POST", "/JSON/authentication/setAuthenticationMethod",
                   json_body={"value": mode}, timeout_seconds=10.0)
        call(state, "POST", "/JSON/session/setSessionManagementMethod",
                   json_body={"value": session_method}, timeout_seconds=10.0)
        if session_method not in ("none", ""):
            header = str(auth.get("session_header") or "")
            name = str(auth.get("session_name") or "")
            if header:
                call(state, "POST", "/JSON/session/setHeader", json_body={"header": header},
                           timeout_seconds=10.0)
            if name:
                call(state, "POST", "/JSON/session/setName", json_body={"value": name},
                           timeout_seconds=10.0)
            call(state, "POST", "/JSON/session/setValue",
                       json_body={"value": str(auth.get("session_value") or "")},
                       timeout_seconds=10.0)
            # headerBased 模式必须告诉 ZAP 这是 header，不是 cookie。
            call(state, "POST", "/JSON/session/setTokenName",
                       json_body={"value": header or name}, timeout_seconds=10.0)
        indicator = str(auth.get("logged_in_indicator") or "")
        out_indicator = str(auth.get("logged_out_indicator") or "")
        if indicator:
            call(state, "POST", "/JSON/authentication/setLoggedInIndicator",
                       json_body={"regex": indicator}, timeout_seconds=10.0)
        if out_indicator:
            call(state, "POST", "/JSON/authentication/setLoggedOutIndicator",
                       json_body={"regex": out_indicator}, timeout_seconds=10.0)
        script = str(auth.get("user_agent_script") or "")
        if script:
            call(state, "POST", "/JSON/authentication/setUserAgent", json_body={"script": script},
                       timeout_seconds=10.0)
        strategy = str(auth.get("strategy") or "manual")
        call(state, "POST", "/JSON/authentication/setAuthenticationStrategy",
                   json_body={"value": strategy}, timeout_seconds=10.0)
    except ZAPConnectorError:
        raise

    authenticated, verified = verify_authentication(state, )
    if authenticated:
        status = AUTH_STATUS_LOGGED_IN
    elif verified:
        status = AUTH_STATUS_LOGGED_OUT
    else:
        status = AUTH_STATUS_UNVERIFIABLE
    return ZAPAuthResult(
        authenticated=authenticated,
        verified=verified,
        auth_mode=mode,
        status=status,
        detail=(_auth_detail(session_method, authenticated, verified)),
    )


def verify_authentication(state: ZAPProtocolState) -> tuple[bool, bool]:
    """调用 ZAP 验证当前认证是否有效，返回 (authenticated, verified)。

    ZAP 的 verifyAuthentication 返回 {"loggedIn": "true|false", "verified": "true|false"}。
    两者语义不同：verified=False 表示「无法判定」，verified=True 且 loggedIn=False
    才是明确的「未登录」。上层不得把 verified=False 当成失败后继续扫描。
    """
    try:
        body = call(state, "POST", "/JSON/authentication/verifyAuthentication",
                          timeout_seconds=15.0, _reason=ZAP_REASON_PLUGIN_MISSING)
    except ZAPConnectorError as exc:
        if exc.reason == ZAP_REASON_PLUGIN_MISSING:
            return False, False
        raise
    if not isinstance(body, dict):
        return False, False
    return _as_bool(body.get("loggedIn")), _as_bool(body.get("verified"))


def browser_session_established(state: ZAPProtocolState) -> tuple[bool, str]:
    """判断当前上下文是否具备「浏览器里的登录态」。

    依据是**已配置的 Session 管理方式**，不是页面实际是否登录——ZAP 没有读取
    浏览器登录态的 API。所以返回值必须和爬取结果一起看：

    - 返回 False 时，Web 爬取只能覆盖登录页，绝不能报「认证后的 Web 扫描完成」；
    - 返回 True 时，Worker 仍需比对 discovered URLs 里有没有命中 logged_in_indicator，
      两者都通过才算覆盖到了业务页面（§十二）。
    """
    method = state.session_method
    if method == "cookieBased" and state.has_session_value:
        return True, "浏览器会话已建立（cookieBased，会话值已导入）"
    if method == "cookieBased" and not state.has_session_value:
        return False, "已声明 cookieBased 会话但未提供会话值，浏览器无法登录"
    if method in ("headerBased", "headerCookieBased", "queryBased", "cookieBasedNameBased"):
        return False, "仅配置了请求级鉴权；浏览器渲染 SPA 时不会带上，前端页面仍会停在登录页"
    if state.auth_mode == AUTH_MODE_MANUAL:
        return False, "手动扫码登录需要人工浏览器交互；本部署未提供该能力，请改用 API Bearer Token 扫描"
    return False, "未配置浏览器可用的认证会话"
