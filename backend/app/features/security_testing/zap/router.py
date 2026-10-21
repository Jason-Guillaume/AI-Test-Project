"""ZAP 安全扫描管理面路由（§三十二）。

单 APIRouter（无自身前缀），挂在 /api/v1 下。路径分两类：

- 全局资源：/security/zap/health、/security/zap/capabilities —— 基础设施可观测性，
  按 §三十三 归平台管理员；响应不含任何密钥，也不暴露 ZAP 管理 API。
- 项目资源：/projects/{project_id}/security/scan-targets、/scan-auth-profiles、
  /scan-profiles、/scan-jobs —— 走 §三十三 的项目角色口径。

端点统一 sync def；service owns commit，本层不做 commit（§八）。
Router 不拼 ZAP API 请求（§六）：本层只做参数收敛与 service 分发。
跨平台项目统一 404（隐藏存在性），项目可见但角色不足 403（铁律 7）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.security_testing.zap.schemas import (
    CoverageRead,
    ScanAlertListResponse,
    ScanAuthProfileCreate,
    ScanAuthProfileListResponse,
    ScanAuthProfileRead,
    ScanAuthProfileUpdate,
    ScanEventListResponse,
    ScanFindingListResponse,
    ScanJobCreate,
    ScanJobListResponse,
    ScanJobProgressRead,
    ScanJobRead,
    ScanPlanRead,
    ScanProfileCreate,
    ScanProfileListResponse,
    ScanProfileRead,
    ScanProfileUpdate,
    ScanReportRead,
    ScanTargetCreate,
    ScanTargetListResponse,
    ScanTargetRead,
    ScanTargetUpdate,
    ZapHealthRead,
)
from app.features.security_testing.zap.services import (
    _access,
    auth_profile_service,
    job_service,
    profile_service,
    target_service,
)
from app.models.identity import User
from app.shared.auth import get_current_user, require_platform_admin
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["安全扫描"])

_TARGETS = target_service
_PROFILES = profile_service
_AUTH_PROFILES = auth_profile_service
_JOBS = job_service

_PAGE = Query(1, ge=1)
_PAGE_SIZE = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


# --------------------------------------------------------------------------- ZAP 服务


@router.get("/security/zap/health", response_model=ZapHealthRead)
def get_zap_health(user: User = Depends(require_platform_admin)) -> ZapHealthRead:
    """ZAP 服务健康状态：只读配置，不含密钥，也不发起网络请求。"""
    return _JOBS.health()


@router.get("/security/zap/capabilities")
def get_zap_capabilities(user: User = Depends(require_platform_admin)) -> dict:
    """ZAP 能力清单：只用 about / list 等只读端点探测，服务不可达时返回 available=false。"""
    return _JOBS.capabilities()


# --------------------------------------------------------------------------- 扫描目标


@router.get(
    "/projects/{project_id}/security/scan-targets", response_model=ScanTargetListResponse,
)
def list_scan_targets(
    project_id: int,
    enabled: bool | None = Query(None),
    page: int = _PAGE,
    page_size: int = _PAGE_SIZE,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanTargetListResponse:
    return _TARGETS.list_targets(db, project_id, user, page, page_size, enabled=enabled)


@router.post(
    "/projects/{project_id}/security/scan-targets",
    response_model=ScanTargetRead, status_code=201,
)
def create_scan_target(
    project_id: int,
    body: ScanTargetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanTargetRead:
    return _TARGETS.to_read(db, _TARGETS.create(db, project_id, user, body))


@router.get(
    "/projects/{project_id}/security/scan-targets/{target_id}", response_model=ScanTargetRead,
)
def get_scan_target(
    project_id: int,
    target_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanTargetRead:
    _access.get_project_or_404(db, project_id, user)
    row = _TARGETS.get_or_none(db, project_id, target_id)
    if row is None:
        raise _access.target_forbidden()
    return _TARGETS.to_read(db, row)


@router.patch(
    "/projects/{project_id}/security/scan-targets/{target_id}", response_model=ScanTargetRead,
)
def update_scan_target(
    project_id: int,
    target_id: int,
    body: ScanTargetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanTargetRead:
    return _TARGETS.to_read(db, _TARGETS.update(db, project_id, user, target_id, body))


@router.delete(
    "/projects/{project_id}/security/scan-targets/{target_id}", status_code=204,
)
def delete_scan_target(
    project_id: int,
    target_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _TARGETS.delete(db, project_id, user, target_id)


# --------------------------------------------------------------------------- 扫描策略


@router.get(
    "/projects/{project_id}/security/scan-profiles", response_model=ScanProfileListResponse,
)
def list_scan_profiles(
    project_id: int,
    enabled: bool | None = Query(None),
    is_builtin: bool | None = Query(None),
    page: int = _PAGE,
    page_size: int = _PAGE_SIZE,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanProfileListResponse:
    return _PROFILES.list_profiles(
        db, project_id, user, page, page_size, enabled=enabled, is_builtin=is_builtin,
    )


@router.post(
    "/projects/{project_id}/security/scan-profiles",
    response_model=ScanProfileRead, status_code=201,
)
def create_scan_profile(
    project_id: int,
    body: ScanProfileCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanProfileRead:
    return _PROFILES.to_read(_PROFILES.create(db, project_id, user, body))


@router.get(
    "/projects/{project_id}/security/scan-profiles/{profile_id}", response_model=ScanProfileRead,
)
def get_scan_profile(
    project_id: int,
    profile_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanProfileRead:
    _access.get_project_or_404(db, project_id, user)
    row = _PROFILES.get_or_none(db, project_id, profile_id)
    if row is None:
        raise _access.profile_not_found()
    return _PROFILES.to_read(row)


@router.patch(
    "/projects/{project_id}/security/scan-profiles/{profile_id}", response_model=ScanProfileRead,
)
def update_scan_profile(
    project_id: int,
    profile_id: int,
    body: ScanProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanProfileRead:
    return _PROFILES.to_read(_PROFILES.update(db, project_id, user, profile_id, body))


@router.delete(
    "/projects/{project_id}/security/scan-profiles/{profile_id}", status_code=204,
)
def delete_scan_profile(
    project_id: int,
    profile_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _PROFILES.delete(db, project_id, user, profile_id)


# --------------------------------------------------------------------------- 认证配置


@router.get(
    "/projects/{project_id}/security/scan-auth-profiles",
    response_model=ScanAuthProfileListResponse,
)
def list_scan_auth_profiles(
    project_id: int,
    enabled: bool | None = Query(None),
    page: int = _PAGE,
    page_size: int = _PAGE_SIZE,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanAuthProfileListResponse:
    return _AUTH_PROFILES.list_profiles(db, project_id, user, page, page_size, enabled=enabled)


@router.post(
    "/projects/{project_id}/security/scan-auth-profiles",
    response_model=ScanAuthProfileRead, status_code=201,
)
def create_scan_auth_profile(
    project_id: int,
    body: ScanAuthProfileCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanAuthProfileRead:
    """新增认证配置。凭据加密入库，响应只回掩码字段（§十一）。"""
    return ScanAuthProfileRead.model_validate(
        _AUTH_PROFILES.create(db, project_id, user, body)
    )


@router.get(
    "/projects/{project_id}/security/scan-auth-profiles/{profile_id}",
    response_model=ScanAuthProfileRead,
)
def get_scan_auth_profile(
    project_id: int,
    profile_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanAuthProfileRead:
    return _JOBS.get_auth_profile(db, project_id, user, profile_id)


@router.patch(
    "/projects/{project_id}/security/scan-auth-profiles/{profile_id}",
    response_model=ScanAuthProfileRead,
)
def update_scan_auth_profile(
    project_id: int,
    profile_id: int,
    body: ScanAuthProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanAuthProfileRead:
    return ScanAuthProfileRead.model_validate(
        _AUTH_PROFILES.update(db, project_id, user, profile_id, body)
    )


@router.delete(
    "/projects/{project_id}/security/scan-auth-profiles/{profile_id}", status_code=204,
)
def delete_scan_auth_profile(
    project_id: int,
    profile_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _AUTH_PROFILES.delete(db, project_id, user, profile_id)


# --------------------------------------------------------------------------- 扫描任务


@router.post(
    "/projects/{project_id}/security/scan-jobs/plan", response_model=ScanPlanRead,
)
def plan_scan_job(
    project_id: int,
    body: ScanJobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanPlanRead:
    """扫描计划预览：纯读取，不写库、不发 ZAP 请求（§二十二）。"""
    return _JOBS.plan(db, project_id, user, body)


@router.post(
    "/projects/{project_id}/security/scan-jobs", response_model=ScanJobRead, status_code=202,
)
def create_scan_job(
    project_id: int,
    body: ScanJobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanJobRead:
    """登记扫描任务并立即返回；真正执行由后台任务完成（§八）。"""
    return _JOBS.to_read(db, _JOBS.create(db, project_id, user, body))


@router.get(
    "/projects/{project_id}/security/scan-jobs", response_model=ScanJobListResponse,
)
def list_scan_jobs(
    project_id: int,
    status: str | None = Query(None),
    target_id: int | None = Query(None),
    page: int = _PAGE,
    page_size: int = _PAGE_SIZE,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanJobListResponse:
    return _JOBS.list_jobs(
        db, project_id, user, page, page_size, status=status, target_id=target_id,
    )


@router.get(
    "/projects/{project_id}/security/scan-jobs/{job_id}", response_model=ScanJobRead,
)
def get_scan_job(
    project_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanJobRead:
    return _JOBS.get_job(db, project_id, user, job_id)


@router.post(
    "/projects/{project_id}/security/scan-jobs/{job_id}/cancel", response_model=ScanJobRead,
)
def cancel_scan_job(
    project_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanJobRead:
    """请求取消：只置持久化取消位，由 Worker 在下一个检查点真正停止。"""
    return _JOBS.to_read(db, _JOBS.cancel(db, project_id, user, job_id))


@router.get(
    "/projects/{project_id}/security/scan-jobs/{job_id}/progress",
    response_model=ScanJobProgressRead,
)
def get_scan_progress(
    project_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanJobProgressRead:
    return _JOBS.progress(db, project_id, user, job_id)


@router.get(
    "/projects/{project_id}/security/scan-jobs/{job_id}/events",
    response_model=ScanEventListResponse,
)
def list_scan_events(
    project_id: int,
    job_id: int,
    event_type: str | None = Query(None),
    page: int = _PAGE,
    page_size: int = _PAGE_SIZE,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanEventListResponse:
    return _JOBS.events(
        db, project_id, user, job_id, page, page_size, event_type=event_type,
    )


@router.get(
    "/projects/{project_id}/security/scan-jobs/{job_id}/alerts",
    response_model=ScanAlertListResponse,
)
def list_scan_alerts(
    project_id: int,
    job_id: int,
    rule_id: str | None = Query(None),
    severity: str | None = Query(None),
    page: int = _PAGE,
    page_size: int = _PAGE_SIZE,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanAlertListResponse:
    return _JOBS.alerts(
        db, project_id, user, job_id, page, page_size, rule_id=rule_id, severity=severity,
    )


@router.get(
    "/projects/{project_id}/security/scan-jobs/{job_id}/findings",
    response_model=ScanFindingListResponse,
)
def list_scan_findings(
    project_id: int,
    job_id: int,
    source_rule_id: str | None = Query(None),
    page: int = _PAGE,
    page_size: int = _PAGE_SIZE,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanFindingListResponse:
    return _JOBS.findings(
        db, project_id, user, job_id, page, page_size, source_rule_id=source_rule_id,
    )


@router.get(
    "/projects/{project_id}/security/scan-jobs/{job_id}/coverage", response_model=CoverageRead,
)
def get_scan_coverage(
    project_id: int,
    job_id: int,
    page: int = _PAGE,
    page_size: int = _PAGE_SIZE,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CoverageRead:
    return _JOBS.coverage(db, project_id, user, job_id, page, page_size)


@router.get(
    "/projects/{project_id}/security/scan-jobs/{job_id}/report", response_model=ScanReportRead,
)
def get_scan_report(
    project_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScanReportRead:
    """独立安全扫描报告：所有数字来自任务记录本身，不重新扫描（§二十五）。"""
    return _JOBS.report(db, project_id, user, job_id)
