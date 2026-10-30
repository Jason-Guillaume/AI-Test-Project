"""扫描策略（SecurityScanProfile）业务服务（§十六）。

内置策略（project_id 为空、is_builtin=True）：
- 禁止删除，禁止改 code；
- 禁止绑定项目级认证配置（内置策略全项目共享，绑定会把某个项目的凭据配置
  变成其它项目也能用的入口，属于跨项目泄露）；
- 限额类字段可以调，但 Worker 侧仍会再套一次硬上限。

自定义策略（project_id 非空、code 为空）：只能在所属项目内使用。
"""

from __future__ import annotations

from app.platform.projects.services.access_service import get_project_or_404

from sqlalchemy.orm import Session

from app.features.security_testing.zap.contracts import ACTIVE_SCAN_MODES, is_active_scan
from app.features.security_testing.zap.models.profile import SecurityScanProfile
from app.features.security_testing.zap.schemas import (
    ScanProfileCreate,
    ScanProfileListResponse,
    ScanProfileRead,
    ScanProfileUpdate,
)
from app.features.security_testing.zap.services import _access, auth_profile_service
from app.core.models.identity import User
from app.core.http.errors import AppError, CODE_SECURITY_SCAN_PROFILE_INVALID, CODE_SECURITY_SCAN_PROFILE_NOT_FOUND
from app.core.http.pagination import paginate

_NOT_FOUND = AppError(
    "扫描策略不存在", status_code=404, code=CODE_SECURITY_SCAN_PROFILE_NOT_FOUND,
)

# 策略上允许直接更新的标量字段（JSON 字段单独清洗）。
_SCALAR_FIELDS = (
    "name", "scan_mode", "spider_enabled", "client_spider_enabled", "passive_enabled",
    "active_enabled", "authentication_profile_id", "max_duration", "max_depth",
    "max_concurrency", "request_delay", "max_alerts_per_rule", "max_request_budget",
    "enabled", "description",
)
_JSON_FIELDS = ("include_paths", "exclude_paths", "selected_rule_ids")


def _get(db: Session, profile_id: int) -> SecurityScanProfile:
    """按 ID 取策略（内置策略与项目策略通用）；不存在 404。"""
    row = db.query(SecurityScanProfile).filter(SecurityScanProfile.id == profile_id).first()
    if row is None:
        raise _NOT_FOUND
    return row


def _accessible(db: Session, project_id: int, profile_id: int) -> SecurityScanProfile:
    """取项目内可见的策略：内置 + 本项目自定义；越界统一 404（不返回 403）。"""
    row = db.query(SecurityScanProfile).filter(
        SecurityScanProfile.id == profile_id,
        SecurityScanProfile.project_id == project_id,
    ).first()
    if row is None:
        row = _get(db, profile_id)
        if not row.is_builtin or row.project_id is not None:
            raise _NOT_FOUND
    return row


def _check_auth_binding(db: Session, project_id: int | None, auth_profile_id: int | None, is_builtin: bool) -> None:
    """校验认证配置绑定：内置策略禁止绑定；绑定必须属于同一项目。"""
    if not auth_profile_id:
        return
    if is_builtin:
        raise AppError(
            "平台内置策略不能绑定项目认证配置", status_code=400, code=CODE_SECURITY_SCAN_PROFILE_INVALID,
        )
    if project_id is None:
        raise AppError("扫描策略缺少项目归属", status_code=400, code=CODE_SECURITY_SCAN_PROFILE_INVALID)
    if auth_profile_service.get_or_none(db, project_id, auth_profile_id) is None:
        raise AppError(
            "关联的认证配置不存在", status_code=400, code=CODE_SECURITY_SCAN_PROFILE_INVALID,
        )


def _check_mode_flags(mode: str, active_enabled: bool) -> None:
    """模式与开关的一致性：勾选主动扫描必须选择主动扫描模式。"""
    if active_enabled and mode not in ACTIVE_SCAN_MODES:
        raise AppError(
            "当前扫描模式不支持主动扫描，请先切换到主动扫描模式",
            status_code=400,
            code=CODE_SECURITY_SCAN_PROFILE_INVALID,
        )


def create(db: Session, project_id: int, user: User, payload: ScanProfileCreate) -> SecurityScanProfile:
    """创建项目自定义策略：editor+。"""
    _access.require_admin_project(db, project_id, user)
    _check_mode_flags(payload.scan_mode, payload.active_enabled)
    _check_auth_binding(db, project_id, payload.authentication_profile_id, is_builtin=False)
    row = SecurityScanProfile(
        project_id=project_id,
        code=None,
        is_builtin=False,
        name=payload.name.strip(),
        scan_mode=payload.scan_mode,
        spider_enabled=bool(payload.spider_enabled),
        client_spider_enabled=bool(payload.client_spider_enabled),
        passive_enabled=bool(payload.passive_enabled),
        active_enabled=bool(payload.active_enabled),
        authentication_profile_id=payload.authentication_profile_id,
        max_duration=int(payload.max_duration),
        max_depth=int(payload.max_depth),
        max_concurrency=int(payload.max_concurrency),
        request_delay=int(payload.request_delay),
        max_alerts_per_rule=payload.max_alerts_per_rule,
        max_request_budget=payload.max_request_budget,
        include_paths=list(payload.include_paths or []),
        exclude_paths=list(payload.exclude_paths or []),
        selected_rule_ids=list(payload.selected_rule_ids or []),
        enabled=bool(payload.enabled),
        description=payload.description,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update(
    db: Session, project_id: int, user: User, profile_id: int, payload: ScanProfileUpdate,
) -> SecurityScanProfile:
    """修改策略：editor+。全局内置策略只有平台管理员能改，项目内只能改自定义策略。"""
    _access.require_admin_project(db, project_id, user)
    row = _accessible(db, project_id, profile_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return row

    if row.is_builtin and "code" in data and data["code"] != row.code:
        raise AppError(
            "平台内置策略代号不可修改", status_code=400, code=CODE_SECURITY_SCAN_PROFILE_INVALID,
        )
    if row.is_builtin and row.project_id is None and not _access.is_platform_admin(user):
        # 全局内置模板被所有项目共享：任何项目的 editor 都能调低它的默认扫描强度
        # （关掉被动扫描、放开 exclude_paths、打开主动扫描），影响范围是全部项目。
        # 项目级调整应该复制成自定义策略，而不是改平台默认。
        raise AppError(
            "平台内置策略为全项目共享，无法在项目内修改；请复制为自定义策略后再调整",
            status_code=400,
            code=CODE_SECURITY_SCAN_PROFILE_INVALID,
        )
    if row.is_builtin and data.get("authentication_profile_id"):
        raise AppError(
            "平台内置策略不能绑定项目认证配置", status_code=400, code=CODE_SECURITY_SCAN_PROFILE_INVALID,
        )

    mode = data.get("scan_mode", row.scan_mode)
    active_enabled = data.get("active_enabled", row.active_enabled)
    _check_mode_flags(mode, bool(active_enabled))
    auth_id = data.get("authentication_profile_id", row.authentication_profile_id)
    _check_auth_binding(db, row.project_id or project_id, auth_id, row.is_builtin)

    for key in _SCALAR_FIELDS:
        if key in data and data[key] is not None:
            setattr(row, key, data[key])
    for key in _JSON_FIELDS:
        if key in data and data[key] is not None:
            setattr(row, key, list(data[key]))
    row.updated_by = user.id
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, project_id: int, user: User, profile_id: int) -> None:
    """删除策略：editor+；内置策略不可删除。"""
    _access.require_admin_project(db, project_id, user)
    row = _accessible(db, project_id, profile_id)
    if row.is_builtin:
        raise AppError("平台内置策略不可删除", status_code=400, code=CODE_SECURITY_SCAN_PROFILE_INVALID)
    db.delete(row)
    db.commit()


def get_or_none(db: Session, project_id: int, profile_id: int) -> SecurityScanProfile | None:
    """不抛错的取值（供扫描计划与 Worker 使用）。"""
    return (
        db.query(SecurityScanProfile)
        .filter(
            SecurityScanProfile.id == profile_id,
            (SecurityScanProfile.project_id == project_id) | (SecurityScanProfile.is_builtin.is_(True)),
        )
        .first()
    )


def to_read(row: SecurityScanProfile) -> ScanProfileRead:
    """ORM → 响应；补 is_active_scan 与 JSON 列表副本。

    内置策略的行里 include_paths / exclude_paths / selected_rule_ids 是 NULL，
    schema 的 default_factory 只在字段缺失时生效、遇到显式 NULL 会 ValidationError → 500，
    所以必须在校验之前收敛成空列表。
    """
    data = dict(row.__dict__)
    data.pop("_sa_instance_state", None)
    data["include_paths"] = list(row.include_paths or [])
    data["exclude_paths"] = list(row.exclude_paths or [])
    data["selected_rule_ids"] = list(row.selected_rule_ids or [])
    data["is_active_scan"] = is_active_scan(row.scan_mode)
    return ScanProfileRead.model_validate(data)


def list_profiles(
    db: Session,
    project_id: int,
    user: User,
    page: int,
    page_size: int,
    *,
    enabled: bool | None = None,
    is_builtin: bool | None = None,
) -> ScanProfileListResponse:
    """列出可见策略（viewer+）：平台内置 + 本项目自定义。"""
    get_project_or_404(db, project_id, user)
    query = db.query(SecurityScanProfile).filter(
        (SecurityScanProfile.project_id == project_id) | (SecurityScanProfile.is_builtin.is_(True)),
    )
    if enabled is not None:
        query = query.filter(SecurityScanProfile.enabled == enabled)
    if is_builtin is not None:
        query = query.filter(SecurityScanProfile.is_builtin == is_builtin)
    # 内置策略（ID 较小）在前，再按 ID 倒序；便于前端默认选中第一个内置策略。
    query = query.order_by(SecurityScanProfile.is_builtin.desc(), SecurityScanProfile.id.desc())
    result = paginate(query, page, page_size)
    return ScanProfileListResponse(
        items=[to_read(row) for row in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
    )
