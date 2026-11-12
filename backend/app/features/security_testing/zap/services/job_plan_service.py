"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.platform.projects.services.access_service import get_project_or_404

from sqlalchemy.orm import Session
from app.features.security_testing.zap import scope_guard
from app.features.security_testing.zap.contracts import (
    AUTH_MODE_MANUAL,
    BROWSER_AUTH_MODES,
    JOB_NOT_DONE_STATUSES,
    JOB_STATUS_PENDING,
    is_active_scan,
)
from app.features.security_testing.zap.models.job import SecurityScanJob
from app.features.security_testing.zap.schemas import ScanJobCreate, ScanPlanRead
from app.features.security_testing.zap.services import (
    _access,
    auth_profile_service,
    profile_service,
    target_service,
)
from app.core.models.identity import User
from app.core.config import settings
from app.core.http.errors import (
    CODE_SECURITY_SCAN_ALREADY_RUNNING,
    CODE_SECURITY_SCAN_PROFILE_NOT_FOUND,
    CODE_SECURITY_SCAN_PRODUCTION_FORBIDDEN,
    CODE_SECURITY_SCAN_TARGET_NOT_FOUND,
    CODE_ZAP_SERVICE_UNAVAILABLE,
    AppError,
)
from app.features.security_testing.zap.services.job_access import check_test_run
from app.features.security_testing.zap.services.job_access import emit_job_event
from app.features.security_testing.zap.services.scanner_query_service import get_zap_state_snapshot
from app.features.security_testing.zap.services.job_access import job_not_authorized
from app.features.security_testing.zap.services.job_access import load_profile
from app.features.security_testing.zap.services.job_access import load_target
from app.features.security_testing.zap.services.job_access import merge_paths
from app.features.security_testing.zap.services.job_access import resolve_environment


def plan(db: Session, project_id: int, user: User, payload: ScanJobCreate) -> ScanPlanRead:
    """生成扫描计划预览。纯读取：不写库、不发任何 ZAP 请求。"""
    get_project_or_404(db, project_id, user)
    target = load_target(db, project_id, payload.target_id)
    profile = load_profile(db, project_id, payload.scan_profile_id)
    # 计划预览也要校验：预览会显示「Finding 会挂到这次测试执行」，指向别的项目就是误导。
    check_test_run(db, project_id, payload.test_run_id)
    env = resolve_environment(db, project_id, target.environment_id)
    environment_name = env.name if env is not None else ""

    active = is_active_scan(profile.scan_mode) and bool(profile.active_enabled)
    production_blocked = active and scope_guard.is_production_environment(environment_name)
    if production_blocked:
        # 计划阶段就拦下来：生产环境主动扫描在接口层就是 403，不进入确认流程。
        raise AppError(
            f"生产环境（{environment_name}）禁止主动扫描",
            status_code=403,
            code=CODE_SECURITY_SCAN_PRODUCTION_FORBIDDEN,
        )

    auth_row = (
        auth_profile_service.get_or_none(db, project_id, profile.authentication_profile_id)
        if profile.authentication_profile_id
        else None
    )
    auth_mode = auth_row.auth_mode if auth_row is not None else None
    # 浏览器登录态是硬前提：SPA 只认 Cookie，配了 Authorization 头也停在登录页（§十二）。
    browser_ready = bool(
        auth_row is not None
        and auth_mode in BROWSER_AUTH_MODES
        and auth_row.has_credential
        and (auth_row.session_method or "") == "cookieBased"
    )

    state = get_zap_state_snapshot()
    zap_available = bool(state.enabled and state.configured)
    limitations: list[str] = []
    if not state.enabled:
        limitations.append("ZAP 安全扫描未启用（ZAP_ENABLED=false），任务会登记为待执行但不会运行")
    if not state.api_key_configured:
        limitations.append("未配置 ZAP_API_KEY_ENCRYPTED，ZAP 可能会拒绝连接")
    if active and not bool(target.active_scan_allowed):
        limitations.append("该目标未开启主动扫描，任务会被拒绝执行")
    if active and target.authorization_status != scope_guard.AUTHORIZATION_STATUS_AUTHORIZED:
        limitations.append("该目标的主动扫描授权状态不是「已授权」，任务会被拒绝执行")
    if active and not payload.confirmed:
        limitations.append("主动扫描需要发起人在确认弹窗里显式确认，并填写批准说明")
    if auth_mode in BROWSER_AUTH_MODES and not browser_ready:
        limitations.append("无法建立浏览器登录态：SPA 页面将停在登录页，只能扫到登录前内容")
    if auth_mode == AUTH_MODE_MANUAL:
        limitations.append("飞书扫码等人工登录需要人工浏览器交互，本部署不支持，将如实标记为无法验证")
    if not profile.passive_enabled and not active:
        limitations.append("该策略既关闭被动扫描也未启用主动扫描，只会爬取并记录覆盖情况")

    exclude_paths = merge_paths(list(target.exclude_paths or []), list(profile.exclude_paths or []))
    if active and not exclude_paths:
        # 用户没配排除路径时不能默认放行 logout / delete / payment。
        exclude_paths = list(scope_guard.HIGH_RISK_ACTIVE_PATH_PATTERNS)
        limitations.append("未配置排除路径，已默认排除 logout / delete / payment 等高危路径")

    budget = profile.max_request_budget or int(settings.ZAP_REQUEST_BUDGET)
    estimated = min(budget, int(settings.ZAP_REQUEST_BUDGET)) if active else None

    return ScanPlanRead(
        target=target_service.to_read(db, target).model_dump(mode="json"),
        profile=profile_service.to_read(profile).model_dump(mode="json"),
        environment={
            "id": env.id if env is not None else None,
            "name": environment_name,
            "base_url": env.base_url if env is not None else None,
            "is_production": scope_guard.is_production_environment(environment_name),
        },
        is_active_scan=active,
        production_blocked=production_blocked,
        authentication_mode=auth_mode,
        browser_session_established=browser_ready,
        zap_available=zap_available,
        limitations=limitations,
        estimated_requests=estimated,
        max_duration_minutes=int(profile.max_duration or 30),
        max_depth=int(profile.max_depth or 5),
        max_concurrency=int(profile.max_concurrency or 4),
        request_delay_ms=int(profile.request_delay or 300),
        exclude_paths=exclude_paths,
        warning="ZAP 服务当前不可用，任务无法执行" if not zap_available else None,
    )


def create(db: Session, project_id: int, user: User, payload: ScanJobCreate) -> SecurityScanJob:
    """发起扫描：member+ 可发起被动扫描；主动扫描需要 editor+ 与显式批准。"""
    project = get_project_or_404(db, project_id, user)
    target = load_target(db, project_id, payload.target_id)
    profile = load_profile(db, project_id, payload.scan_profile_id)
    check_test_run(db, project_id, payload.test_run_id)
    if not bool(target.enabled):
        raise AppError("扫描目标已停用，无法发起扫描", status_code=400, code=CODE_SECURITY_SCAN_TARGET_NOT_FOUND)
    if not bool(profile.enabled):
        raise AppError("扫描策略已停用，无法发起扫描", status_code=400, code=CODE_SECURITY_SCAN_PROFILE_NOT_FOUND)

    env = resolve_environment(db, project_id, target.environment_id)
    environment_name = env.name if env is not None else ""
    active = is_active_scan(profile.scan_mode) and bool(profile.active_enabled)

    if active:
        # 主动扫描是受控动作：权限、环境、目标授权、人工批准四关都要过（§二十三 / §三十四）。
        _access.require_admin(db, project, user)
        scope_guard.assert_active_scan_authorized(
            environment_name=environment_name,
            scan_mode=profile.scan_mode,
            active_authorized=target.authorization_status == scope_guard.AUTHORIZATION_STATUS_AUTHORIZED,
            environment_active_allowed=bool(target.active_scan_allowed),
        )
        if not payload.confirmed:
            raise job_not_authorized("主动扫描需要发起人显式确认")
        if not (payload.approval_note or "").strip():
            raise job_not_authorized("主动扫描需要填写批准说明")
    else:
        _access.require_member(db, project, user)

    if payload.idempotency_key:
        prior = db.query(SecurityScanJob).filter(
            SecurityScanJob.project_id == project_id,
            SecurityScanJob.idempotency_key == payload.idempotency_key,
        ).first()
        if prior is not None:
            if (
                prior.target_id != target.id
                or prior.scan_profile_id != profile.id
                or prior.test_run_id != payload.test_run_id
                or prior.initiated_by != user.id
                or prior.approval_note != ((payload.approval_note or "").strip()[:500] if active else None)
            ):
                raise AppError("相同 idempotency_key 已用于不同扫描内容", status_code=409)
            return prior

    if not (settings.ZAP_ENABLED and (settings.ZAP_BASE_URL or "").strip()):
        raise AppError(
            "ZAP 服务未启用或未配置，请先在部署侧设置 ZAP_ENABLED 与 ZAP_BASE_URL",
            status_code=409,
            code=CODE_ZAP_SERVICE_UNAVAILABLE,
        )

    # 同一目标的查重要覆盖「排队中」和「执行中」两种状态：
    # 只查中间态会漏掉 PENDING，管理员可以无限堆积同一目标的待执行任务（§八 并发限制）。
    pending = (
        db.query(SecurityScanJob)
        .filter(
            SecurityScanJob.project_id == project_id,
            SecurityScanJob.target_id == target.id,
            SecurityScanJob.status.in_(JOB_NOT_DONE_STATUSES),
        )
        .count()
    )
    if pending:
        raise AppError(
            "该目标已有扫描任务在排队或执行中，请等待结束后再发起",
            status_code=409,
            code=CODE_SECURITY_SCAN_ALREADY_RUNNING,
        )

    row = SecurityScanJob(
        project_id=project_id,
        target_id=target.id,
        environment_id=target.environment_id,
        scan_profile_id=profile.id,
        scan_mode=profile.scan_mode,
        status=JOB_STATUS_PENDING,
        progress=0,
        stage="等待后台任务领取",
        authentication_mode=None,
        authentication_status=None,
        browser_session_established=False,
        initiated_by=user.id,
        approved_by=user.id if active else None,
        approval_note=(payload.approval_note or "").strip()[:500] if active else None,
        idempotency_key=payload.idempotency_key,
        test_run_id=payload.test_run_id,
        cancel_requested=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    emit_job_event(db, row.id, row.project_id, "STAGE", JOB_STATUS_PENDING, "扫描任务已创建，等待后台任务领取")
    db.commit()
    return row
