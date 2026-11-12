"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.security_testing.zap.auth import build_auth_config, check_credential_live
from app.features.security_testing.zap.contracts import (
    AUTH_MODE_MANUAL,
    AUTH_STATUS_LOGGED_IN,
    AUTH_STATUS_UNVERIFIABLE,
    EVENT_TYPE_AUTH,
    EVENT_TYPE_STAGE,
    EVENT_TYPE_WARNING,
    JOB_STATUS_AUTHENTICATING,
    WEB_CRAWL_MODES,
)
from app.features.security_testing.zap.services import auth_profile_service
from app.features.security_testing.zap.stages.contracts import ScanSnapshot
from app.features.security_testing.zap.stages.contracts import ScanStageContext
from app.features.security_testing.zap.stages.control import checkpoint
from app.features.security_testing.zap.stages.persistence import emit
from app.features.security_testing.zap.stages.control import fail
from app.features.security_testing.zap.stages.persistence import load_auth_profile
from app.features.security_testing.zap.stages.persistence import update_job


def stage_authenticating(context: ScanStageContext, snap: ScanSnapshot, started: float) -> None:
    """AUTHENTICATING：配置认证并验证登录态（不是只看 HTTP 200）。"""
    checkpoint(context, snap, JOB_STATUS_AUTHENTICATING, "配置并验证认证状态", progress=8)
    emit(context, snap, EVENT_TYPE_STAGE, JOB_STATUS_AUTHENTICATING, "开始配置认证")

    auth_profile = load_auth_profile(context, snap)
    auth_mode = auth_profile.auth_mode if auth_profile else "NONE"
    credential = auth_profile_service.decrypt_credential(auth_profile) if auth_profile else ""

    # 扫描前先按用户配置的验证接口确认真实登录态，不以 HTTP 200 为准（§十一）。
    live_ok = False
    live_logged_in = False
    live_detail = ""
    if auth_profile is not None and auth_profile.authentication_check_url and auth_mode != AUTH_MODE_MANUAL:
        live_ok, live_logged_in, live_detail = check_credential_live(
            check_url=auth_profile.authentication_check_url,
            credential=credential,
            auth_mode=auth_mode,
            session_header=auth_profile.session_header or "",
            session_name=auth_profile.session_name or "",
            logged_in_indicator=auth_profile.logged_in_indicator or "",
            logged_out_indicator=auth_profile.logged_out_indicator or "",
            expected_user_id=auth_profile.expected_user_id or "",
            allowed_hosts=snap.allowed_hosts or None,
        )
        emit(context,
            snap, EVENT_TYPE_AUTH, JOB_STATUS_AUTHENTICATING,
            f"登录态预检查：{'可达' if live_ok else '不可达'}，{'已登录' if live_logged_in else '未登录或无法判定'}",
            {"reachable": live_ok, "logged_in": live_logged_in, "detail": live_detail},
        )
        if not live_ok:
            fail(context, snap, "SECURITY_SCAN_AUTH_FAILED", f"登录态验证失败：{live_detail}")
        if live_ok and not live_logged_in:
            fail(context, snap, "SECURITY_SCAN_AUTH_EXPIRED", f"登录态验证未通过：{live_detail}")

    config = build_auth_config(auth_profile)
    result = context.connector.configure_authentication(config)
    browser_ok, browser_reason = context.connector.browser_session_established()

    status = result.status
    if auth_profile is not None:
        # 以验证接口的结论为准：它是我们唯一能真实观测到的登录态。
        status = AUTH_STATUS_LOGGED_IN if live_logged_in else AUTH_STATUS_UNVERIFIABLE
    if snap.scan_mode in WEB_CRAWL_MODES and not browser_ok:
        status = AUTH_STATUS_UNVERIFIABLE
        emit(context,
            snap, EVENT_TYPE_WARNING, JOB_STATUS_AUTHENTICATING,
            f"无法建立浏览器登录态：{browser_reason}",
            {"browser_reason": browser_reason},
        )
    emit(context,
        snap, EVENT_TYPE_AUTH, JOB_STATUS_AUTHENTICATING,
        f"认证验证结果：{status}",
        {"auth_mode": auth_mode, "authenticated": bool(result.authenticated),
         "verified": bool(result.verified), "live_check": live_ok,
         "live_logged_in": live_logged_in, "live_detail": live_detail,
         "browser_session": browser_ok, "browser_reason": browser_reason},
    )
    update_job(context,
        snap,
        authentication_mode=auth_mode,
        authentication_status=status,
        browser_session_established=bool(browser_ok),
        stage=JOB_STATUS_AUTHENTICATING,
        progress=12,
    )
    if status != AUTH_STATUS_LOGGED_IN and auth_profile is not None:
        # 需要登录才能继续爬业务页面，但明确验证为未登录 → 记为失败而不是静默继续。
        if result.verified and not result.authenticated:
            fail(context, snap, "SECURITY_SCAN_AUTH_FAILED", "认证凭据验证失败：当前会话未登录")
