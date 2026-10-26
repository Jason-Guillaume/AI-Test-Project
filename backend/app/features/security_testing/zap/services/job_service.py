"""扫描任务（SecurityScanJob）业务服务（§七 / §二十三 / §二十五 / §三十一）。

职责边界：
- 本模块只负责「创建、查询、取消」——**不执行扫描**。执行在 worker.py + orchestrator.py，
  HTTP 请求里绝不同步等待（§八）。
- 扫描计划（plan）是纯读取：把目标 / 策略 / 环境 / ZAP 可用性拼成一次可审计的预览，
  让人在点「开始扫描」之前看到真实范围、请求预算、风险与能力限制。
- 报告（report）的数字全部来自 SecurityScanJob 行，不接受前端传入（§二十五）。

主动扫描授权（§二十三）：
- 必须由**真实的人类**在接口侧带 confirmed=True 且给出 approval_note；
- approved_by 记的就是当前登录用户，Agent 不能自己填 approved_by；
- Agent 路径只能通过 confirm_security_scan 这个后端动作拿到同一个用户身份。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.security_testing.zap import event_log, scope_guard
from app.features.security_testing.zap.contracts import (
    AUTH_MODE_MANUAL,
    BROWSER_AUTH_MODES,
    COVERAGE_NOT_COVERED,
    COVERAGE_STAGES,
    DEFAULT_ZAP_ALERT_SEVERITY,
    JOB_NOT_DONE_STATUSES,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_PENDING,
    JOB_TERMINAL_STATUSES,
    ZAP_RISK_TO_SEVERITY,
    is_active_scan,
    map_zap_risk,
)
from app.features.security_testing.zap.models.finding_link import SecurityScanFinding
from app.features.security_testing.zap.models.job import SecurityScanEvent, SecurityScanJob
from app.features.security_testing.zap.models.profile import SecurityScanProfile
from app.features.security_testing.zap.models.target import SecurityScanTarget
from app.features.security_testing.zap.schemas import (
    CoverageRead,
    CoverageRowRead,
    ScanAlertCountsRead,
    ScanAlertListResponse,
    ScanAlertRead,
    ScanAuthProfileRead,
    ScanEventListResponse,
    ScanEventRead,
    ScanFindingListResponse,
    ScanFindingLinkRead,
    ScanJobCreate,
    ScanJobListResponse,
    ScanJobProgressRead,
    ScanJobRead,
    ScanPlanRead,
    ScanReportRead,
    ZapHealthRead,
)
from app.features.security_testing.zap.services import (
    _access,
    auth_profile_service,
    profile_service,
    target_service,
)
from app.features.test_management.models.execution import TestRun
from app.models.configuration import Environment
from app.models.identity import User
from app.shared.config import settings
from app.shared.errors import (
    CODE_NOT_FOUND,
    CODE_SECURITY_SCAN_ALREADY_RUNNING,
    CODE_SECURITY_SCAN_AUTH_PROFILE_NOT_FOUND,
    CODE_SECURITY_SCAN_NOT_AUTHORIZED,
    CODE_SECURITY_SCAN_PROFILE_NOT_FOUND,
    CODE_SECURITY_SCAN_PRODUCTION_FORBIDDEN,
    CODE_SECURITY_SCAN_TARGET_NOT_FOUND,
    CODE_ZAP_SERVICE_UNAVAILABLE,
    AppError,
)
from app.shared.pagination import paginate

_PROFILE_NOT_FOUND = AppError(
    "扫描策略不存在", status_code=404, code=CODE_SECURITY_SCAN_PROFILE_NOT_FOUND
)
_AUTH_PROFILE_NOT_FOUND = AppError(
    "认证配置不存在", status_code=404, code=CODE_SECURITY_SCAN_AUTH_PROFILE_NOT_FOUND
)


# --------------------------------------------------------------------------- 读取基元

def _get_job(db: Session, project_id: int, job_id: int) -> SecurityScanJob:
    """按 ID 读任务；跨项目一律 404，不暴露是否存在（红线 1）。"""
    row = (
        db.query(SecurityScanJob)
        .filter(SecurityScanJob.id == job_id, SecurityScanJob.project_id == project_id)
        .first()
    )
    if row is None:
        raise _access.job_not_found()
    return row


def _get_target(db: Session, project_id: int, target_id: int) -> SecurityScanTarget:
    """按 ID 读扫描目标；跨项目一律 404。"""
    row = target_service.get_or_none(db, project_id, target_id)
    if row is None:
        raise _access.target_forbidden()
    return row


def _get_profile(db: Session, project_id: int, profile_id: int) -> SecurityScanProfile:
    """按 ID 读扫描策略；内置策略（project_id 为空）对所有项目可见。"""
    row = profile_service.get_or_none(db, project_id, profile_id)
    if row is None:
        raise _PROFILE_NOT_FOUND
    return row


def _check_test_run(db: Session, project_id: int, test_run_id: int | None) -> None:
    """校验关联的测试执行记录是否属于本项目。

    不校验的话，ZAP 打出的 Finding 会以本项目的 project_id 挂到别的项目执行记录上，
    再经报告层（只按 test_run_id 过滤）回流出去。跨资源越权按 404 处理，不暴露存在性。
    """
    if not test_run_id:
        return
    row = db.get(TestRun, test_run_id)
    if row is None or row.project_id != project_id:
        raise AppError("关联的测试执行记录不存在", status_code=404, code=CODE_NOT_FOUND)


def _environment(db: Session, environment_id: int | None) -> Environment | None:
    """读环境；空 ID 返回 None，不视为错误。"""
    if not environment_id:
        return None
    return db.get(Environment, environment_id)


def _now() -> datetime:
    """与仓库其它表一致的时间戳。"""
    return datetime.now()


def _emit(
    db: Session,
    job_id: int,
    project_id: int,
    event_type: str,
    stage: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """写一条过程事件；seq 分配与并发冲突重试统一在 event_log。只 add，提交由调用方负责。"""
    event_log.add_event(
        db,
        job_id=job_id,
        project_id=project_id,
        event_type=event_type,
        stage=stage,
        message=message,
        payload=payload,
    )


def _merge_paths(*groups: list[str]) -> list[str]:
    """合并多组路径清单，去重并保序。"""
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def to_read(db: Session, row: SecurityScanJob) -> ScanJobRead:
    """ORM → 响应；补目标 / 环境 / 策略名称，并把 NULL 的 JSON 列收敛成空对象。

    coverage_summary 在任务结束前一直是 NULL。schema 里的 default_factory 只在字段
    **缺失**时生效，遇到显式 NULL 会直接 ValidationError → 整个任务列表 500，
    所以必须在校验之前收敛。
    """
    data = dict(row.__dict__)
    data.pop("_sa_instance_state", None)
    data["coverage_summary"] = dict(row.coverage_summary or {})
    base = ScanJobRead.model_validate(data)
    target = db.get(SecurityScanTarget, row.target_id) if row.target_id else None
    base.target_name = target.name if target is not None else None
    if row.scan_profile_id:
        profile = db.get(SecurityScanProfile, row.scan_profile_id)
        base.scan_profile_name = profile.name if profile is not None else None
    env = _environment(db, row.environment_id)
    base.environment_name = env.name if env is not None else None
    return base


def job_not_authorized(message: str) -> AppError:
    """主动扫描缺少人类批准：返回 403，让前端明确显示授权不足。"""
    return AppError(message, status_code=403, code=CODE_SECURITY_SCAN_NOT_AUTHORIZED)


# --------------------------------------------------------------------------- 扫描计划

def plan(db: Session, project_id: int, user: User, payload: ScanJobCreate) -> ScanPlanRead:
    """生成扫描计划预览。纯读取：不写库、不发任何 ZAP 请求。"""
    _access.get_project_or_404(db, project_id, user)
    target = _get_target(db, project_id, payload.target_id)
    profile = _get_profile(db, project_id, payload.scan_profile_id)
    # 计划预览也要校验：预览会显示「Finding 会挂到这次测试执行」，指向别的项目就是误导。
    _check_test_run(db, project_id, payload.test_run_id)
    env = _environment(db, target.environment_id)
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

    exclude_paths = _merge_paths(list(target.exclude_paths or []), list(profile.exclude_paths or []))
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


# --------------------------------------------------------------------------- 创建 / 取消

def create(db: Session, project_id: int, user: User, payload: ScanJobCreate) -> SecurityScanJob:
    """发起扫描：member+ 可发起被动扫描；主动扫描需要 editor+ 与显式批准。"""
    project = _access.get_project_or_404(db, project_id, user)
    target = _get_target(db, project_id, payload.target_id)
    profile = _get_profile(db, project_id, payload.scan_profile_id)
    _check_test_run(db, project_id, payload.test_run_id)
    if not bool(target.enabled):
        raise AppError("扫描目标已停用，无法发起扫描", status_code=400, code=CODE_SECURITY_SCAN_TARGET_NOT_FOUND)
    if not bool(profile.enabled):
        raise AppError("扫描策略已停用，无法发起扫描", status_code=400, code=CODE_SECURITY_SCAN_PROFILE_NOT_FOUND)

    env = _environment(db, target.environment_id)
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
    _emit(db, row.id, row.project_id, "STAGE", JOB_STATUS_PENDING, "扫描任务已创建，等待后台任务领取")
    db.commit()
    return row


def cancel(db: Session, project_id: int, user: User, job_id: int) -> SecurityScanJob:
    """请求取消：只置位 cancel_requested，由 Worker 在下一个检查点真正停止。"""
    project = _access.get_project_or_404(db, project_id, user)
    row = _get_job(db, project_id, job_id)
    if row.status in JOB_TERMINAL_STATUSES:
        raise AppError("该任务已结束，无法取消", status_code=409)
    _access.require_member(db, project, user)

    row.cancel_requested = True
    if row.status == JOB_STATUS_PENDING:
        # 还没被领取的任务直接判为取消，不必等 Worker 唤醒。
        row.status = JOB_STATUS_CANCELLED
        row.stage = "已取消"
        row.finished_at = _now()
        row.error_message = "任务尚未开始即被取消"
        _emit(db, row.id, row.project_id, "STAGE", JOB_STATUS_CANCELLED, "任务尚未开始即被取消")
    else:
        _emit(db, row.id, row.project_id, "STAGE", row.status, "已请求取消扫描")
    db.commit()
    db.refresh(row)
    return row


# --------------------------------------------------------------------------- 查询

def list_jobs(
    db: Session,
    project_id: int,
    user: User,
    page: int,
    page_size: int,
    *,
    status: str | None = None,
    target_id: int | None = None,
) -> ScanJobListResponse:
    """列出扫描任务（viewer+）。"""
    _access.get_project_or_404(db, project_id, user)
    query = db.query(SecurityScanJob).filter(SecurityScanJob.project_id == project_id)
    if status:
        query = query.filter(SecurityScanJob.status == status)
    if target_id:
        query = query.filter(SecurityScanJob.target_id == target_id)
    query = query.order_by(SecurityScanJob.id.desc())
    result = paginate(query, page, page_size)
    return ScanJobListResponse(
        items=[to_read(db, row) for row in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
    )


def get_job(db: Session, project_id: int, user: User, job_id: int) -> ScanJobRead:
    """查看单个任务（viewer+）。"""
    _access.get_project_or_404(db, project_id, user)
    return to_read(db, _get_job(db, project_id, job_id))


def progress(db: Session, project_id: int, user: User, job_id: int) -> ScanJobProgressRead:
    """进度查询（viewer+）。ZAP 没给百分比时前端只显示阶段与计数。"""
    _access.get_project_or_404(db, project_id, user)
    return ScanJobProgressRead.model_validate(_get_job(db, project_id, job_id))


def events(
    db: Session,
    project_id: int,
    user: User,
    job_id: int,
    page: int,
    page_size: int,
    *,
    event_type: str | None = None,
) -> ScanEventListResponse:
    """过程事件（viewer+）。payload 已脱敏，可直接展示。"""
    _access.get_project_or_404(db, project_id, user)
    job = _get_job(db, project_id, job_id)
    query = db.query(SecurityScanEvent).filter(SecurityScanEvent.job_id == job.id)
    if event_type:
        query = query.filter(SecurityScanEvent.event_type == event_type)
    # seq 相同（历史数据）时按 id 兜底，保证同一任务的时间线排序稳定。
    query = query.order_by(SecurityScanEvent.seq.asc(), SecurityScanEvent.id.asc())
    result = paginate(query, page, page_size)
    return ScanEventListResponse(
        items=[ScanEventRead.model_validate(row) for row in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
    )


def _alert_read_from_link(link: SecurityScanFinding) -> ScanAlertRead:
    """把一条关系记录转成告警视图：结构化字段优先，evidence_json 兜底。"""
    payload = dict(link.evidence_json or {})
    return ScanAlertRead(
        rule_id=str(link.source_rule_id or payload.get("rule_id", "")),
        name=str(link.source_alert_name or payload.get("name", "")),
        risk=str(link.risk or payload.get("risk", "")),
        confidence=int(link.confidence if link.confidence is not None else payload.get("confidence", 1)),
        severity=str(payload.get("severity") or map_zap_risk(str(link.risk or ""))),
        url=str(link.url or ""),
        method=str(link.method or ""),
        parameter=str(link.parameter or ""),
        description=str(payload.get("description", "")),
        remediation=str(payload.get("remediation", "")),
        evidence=str(payload.get("evidence", "")),
        cwe_id=payload.get("cwe_id"),
        wasc_id=payload.get("wasc_id"),
        reference=str(payload.get("reference", "")),
    )


def alerts(
    db: Session,
    project_id: int,
    user: User,
    job_id: int,
    page: int,
    page_size: int,
    *,
    rule_id: str | None = None,
    severity: str | None = None,
) -> ScanAlertListResponse:
    """本次扫描的告警（viewer+）。

    数据来自 security_scan_finding：一行代表该任务里一次「去重后的告警签名」，
    evidence_json 里是归一化并脱敏后的告警明细。
    """
    _access.get_project_or_404(db, project_id, user)
    job = _get_job(db, project_id, job_id)
    query = db.query(SecurityScanFinding).filter(SecurityScanFinding.job_id == job.id)
    if rule_id:
        query = query.filter(SecurityScanFinding.source_rule_id == rule_id)
    if severity:
        # risk 列存的是 ZAP 原文（"High"），severity 是映射后的平台级别（"HIGH"）。
        # 过滤必须按映射表反查，不能拿 "HIGH" 直接去比 risk——那样永远查不到任何结果。
        wanted = str(severity).strip().upper()
        known_labels = set(ZAP_RISK_TO_SEVERITY)
        labels = {label for label, mapped in ZAP_RISK_TO_SEVERITY.items() if mapped == wanted}
        if not labels:
            # CRITICAL 等平台级别不会由 ZAP 产生：如实返回空结果，不放宽条件凑数。
            labels = {"__ZAP 不产生该级别__"}
        conditions = [SecurityScanFinding.risk.in_(list(labels))]
        if wanted == DEFAULT_ZAP_ALERT_SEVERITY:
            # risk 原文未识别时也按默认级别展示，过滤时要一并算上。
            conditions.append(~SecurityScanFinding.risk.in_(list(known_labels)))
        query = query.filter(or_(*conditions))
    query = query.order_by(SecurityScanFinding.confidence.desc(), SecurityScanFinding.id.desc())
    result = paginate(query, page, page_size)
    return ScanAlertListResponse(
        items=[_alert_read_from_link(link) for link in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
        counts=ScanAlertCountsRead(
            total=int(job.total_alerts or 0),
            high=int(job.high_count or 0),
            medium=int(job.medium_count or 0),
            low=int(job.low_count or 0),
            info=int(job.info_count or 0),
        ),
    )


def findings(
    db: Session,
    project_id: int,
    user: User,
    job_id: int,
    page: int,
    page_size: int,
    *,
    source_rule_id: str | None = None,
) -> ScanFindingListResponse:
    """扫描任务与 Finding 的关联（viewer+）。

    Finding 的生命周期（OPEN / CONFIRMED / FALSE_POSITIVE ...）仍然走 Phase 1 的
    security_finding 接口，这里只给「本次扫描命中了哪些 Finding」的视角。
    """
    _access.get_project_or_404(db, project_id, user)
    job = _get_job(db, project_id, job_id)
    query = db.query(SecurityScanFinding).filter(SecurityScanFinding.job_id == job.id)
    if source_rule_id:
        query = query.filter(SecurityScanFinding.source_rule_id == source_rule_id)
    query = query.order_by(SecurityScanFinding.confidence.desc(), SecurityScanFinding.id.desc())
    result = paginate(query, page, page_size)
    return ScanFindingListResponse(
        items=[ScanFindingLinkRead.model_validate(link) for link in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
    )


def coverage(db: Session, project_id: int, user: User, job_id: int, page: int, page_size: int) -> CoverageRead:
    """覆盖率明细（§三十一）。行数据来自任务上冻结的 coverage_summary 快照。"""
    _access.get_project_or_404(db, project_id, user)
    job = _get_job(db, project_id, job_id)
    snapshot = dict(job.coverage_summary or {})
    summary = {str(k): int(v) for k, v in (snapshot.get("summary") or {}).items()}
    rows: list[CoverageRowRead] = []
    for item in snapshot.get("rows") or []:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or COVERAGE_NOT_COVERED)
        if stage not in COVERAGE_STAGES:
            # 快照里可能出现未知阶段值：按未覆盖处理，不要让一个坏值打断整页。
            stage = COVERAGE_NOT_COVERED
        rows.append(CoverageRowRead(
            identifier=str(item.get("identifier", "")),
            stage=stage,  # type: ignore[arg-type]
            method=str(item.get("method", "")),
            status_code=item.get("status_code"),
            passive_analyzed=bool(item.get("passive_analyzed", False)),
            active_scanned=bool(item.get("active_scanned", False)),
        ))
    offset = (page - 1) * page_size
    return CoverageRead(
        items=rows[offset:offset + page_size],
        total=len(rows),
        page=page,
        page_size=page_size,
        summary=summary,
    )


def report(db: Session, project_id: int, user: User, job_id: int) -> ScanReportRead:
    """独立安全扫描报告（§二十五）。所有数字都来自任务记录本身。"""
    _access.get_project_or_404(db, project_id, user)
    job = _get_job(db, project_id, job_id)

    links = (
        db.query(SecurityScanFinding)
        .filter(SecurityScanFinding.job_id == job.id)
        .order_by(SecurityScanFinding.confidence.desc(), SecurityScanFinding.id.asc())
        .all()
    )
    high_risk: list[ScanAlertRead] = []
    findings_rows: list[ScanFindingLinkRead] = []
    for link in links:
        findings_rows.append(ScanFindingLinkRead.model_validate(link))
        if link.risk in ("High", "Medium"):
            high_risk.append(_alert_read_from_link(link))

    snapshot = dict(job.coverage_summary or {})
    coverage_summary = {str(k): int(v) for k, v in (snapshot.get("summary") or {}).items()}

    target_row = db.get(SecurityScanTarget, job.target_id) if job.target_id else None
    profile_row = db.get(SecurityScanProfile, job.scan_profile_id) if job.scan_profile_id else None
    return ScanReportRead(
        job=to_read(db, job),
        target=target_service.to_read(db, target_row) if target_row is not None else None,
        profile=profile_service.to_read(profile_row) if profile_row is not None else None,
        alert_counts=ScanAlertCountsRead(
            total=int(job.total_alerts or 0),
            high=int(job.high_count or 0),
            medium=int(job.medium_count or 0),
            low=int(job.low_count or 0),
            info=int(job.info_count or 0),
        ),
        high_risk_alerts=high_risk[:50],
        coverage_summary=coverage_summary,
        findings=findings_rows,
        generated_at=_now(),
    )


# --------------------------------------------------------------------------- ZAP 服务状态

def get_zap_state_snapshot():
    """读 ZAP 配置状态（延迟导入，避免测试里提前绑定 settings）。"""
    from app.features.security_testing.zap.client import get_zap_state

    return get_zap_state()


def health() -> ZapHealthRead:
    """ZAP 服务健康（不含任何密钥，也不发起网络请求）。"""
    state = get_zap_state_snapshot()
    available = bool(state.enabled and state.configured)
    return ZapHealthRead(
        enabled=bool(state.enabled),
        available=available,
        version=None,
        reachable=available,
        api_key_configured=bool(state.api_key_configured),
        message=state.message or ("ZAP 服务已配置" if available else "ZAP 服务未启用或未配置"),
    )


def _empty_capabilities(message: str) -> dict[str, Any]:
    """能力探测失败时的空结果：available=False，不让前端误判为已支持。"""
    return {
        "version": None,
        "available": False,
        "message": message,
        "addon_names": [],
        "addon_versions": {},
        "capabilities": [],
    }


def capabilities() -> dict[str, Any]:
    """ZAP 能力清单（只读探测；服务不可达时返回 available=False 而不是抛错）。

    探测只走 about / isRunning / get* 这类**只读**接口，绝不触发扫描动作。
    """
    from app.features.security_testing.zap.client import build_connector, get_zap_state

    state = get_zap_state()
    if not (state.enabled and state.configured):
        return _empty_capabilities(state.message or "ZAP 服务未启用或未配置")

    connector = None
    try:
        connector = build_connector()
        caps = connector.get_capabilities()
        return {
            "version": caps.version,
            "available": True,
            "message": "ZAP 服务可访问",
            "addon_names": list(caps.about.add_on_names),
            "addon_versions": dict(caps.about.add_on_versions),
            "capabilities": [cap.as_dict() for cap in caps.capabilities],
        }
    except Exception as exc:  # noqa: BLE001 - 能力页不能因为 ZAP 不可用而整页报错
        return _empty_capabilities(f"ZAP 服务不可访问：{exc}")
    finally:
        if connector is not None:
            try:
                connector.close()
            except Exception:  # noqa: BLE001
                pass


def get_auth_profile(db: Session, project_id: int, user: User, profile_id: int) -> ScanAuthProfileRead:
    """按 ID 读认证配置（viewer+），只返回脱敏字段。"""
    _access.get_project_or_404(db, project_id, user)
    row = auth_profile_service.get_or_none(db, project_id, profile_id)
    if row is None:
        raise _AUTH_PROFILE_NOT_FOUND
    return ScanAuthProfileRead.model_validate(row)
