"""扫描目标（SecurityScanTarget）业务服务（§四）。

所有写入路径都过 scope_guard：base_url / allowed_hosts 创建与修改时都会重新校验
协议、主机白名单、端口与解析 IP。校验放在服务层而不是只在路由层，
这样 Worker 重试、Agent 调用、脚本导入都不能绕过（§三十四 第 5 条）。
"""

from __future__ import annotations

from app.platform.projects.services.access_service import get_project_or_404

from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.features.security_testing.zap import scope_guard
from app.features.security_testing.zap.contracts import JOB_INFLIGHT_STATUSES
from app.features.security_testing.zap.models.job import SecurityScanJob
from app.features.security_testing.zap.models.target import SecurityScanTarget
from app.features.security_testing.zap.schemas import (
    ScanTargetCreate,
    ScanTargetListResponse,
    ScanTargetRead,
    ScanTargetUpdate,
)
from app.features.security_testing.zap.services import _access
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.errors import AppError, CODE_SECURITY_SCAN_TARGET_NOT_FOUND
from app.core.http.pagination import paginate

_TARGET_NOT_FOUND = AppError(
    "扫描目标不存在", status_code=404, code=CODE_SECURITY_SCAN_TARGET_NOT_FOUND,
)


def _get(db: Session, project_id: int, target_id: int) -> SecurityScanTarget:
    """获取对应数据。"""
    row = (
        db.query(SecurityScanTarget)
        .filter(SecurityScanTarget.id == target_id, SecurityScanTarget.project_id == project_id)
        .first()
    )
    if row is None:
        raise _TARGET_NOT_FOUND
    return row


def _netloc(url: str) -> str:
    """解析 URL 的网络位置，包括主机和端口。"""
    return (urlsplit(url or "").netloc or "").lower()


def _derive_hosts(base_url: str, allowed_hosts: list[str]) -> list[str]:
    """白名单为空时只放行扫描根本身（含端口）。

    空白名单不能让校验整体短路：否则管理员只想扫 8443，
    结果同一主机上任何端口都会被拿去扫（§三十四 第 5 条）。
    """
    hosts = [str(h).strip().lower() for h in (allowed_hosts or []) if str(h).strip()]
    if hosts:
        return hosts
    parts = urlsplit((base_url or "").strip())
    host = (parts.hostname or "").lower()
    if not host:
        return hosts
    entry = f"[{host}]" if host.count(":") > 0 else host
    if parts.port is not None:
        entry = f"{entry}:{parts.port}"
    return [entry]


def _validate_base_and_entry(
    base_url: str, entry_url: str | None, allowed_hosts: list[str],
) -> tuple[str, str | None, list[str]]:
    """校验扫描根与入口地址，并保证两者属于同一个主机；返回实际生效的白名单。"""
    hosts = _derive_hosts(base_url, allowed_hosts)
    scope_guard.validate_allowed_hosts(hosts)
    base = scope_guard.validate_target_url(base_url, allowed_hosts=hosts or None)
    if entry_url:
        entry = scope_guard.validate_target_url(entry_url, allowed_hosts=hosts or None)
        if _netloc(entry) != _netloc(base):
            raise scope_guard.scope_violation("入口地址必须与扫描根地址属于同一个主机")
        return base, entry, hosts
    return base, None, hosts


def create(db: Session, project_id: int, user: User, payload: ScanTargetCreate) -> SecurityScanTarget:
    """创建扫描目标：editor+ 才能建（目标是项目级配置，不是任务级数据）。"""
    _access.require_admin_project(db, project_id, user)
    requested_hosts = [str(h).strip() for h in (payload.allowed_hosts or []) if str(h).strip()]
    base, entry, allowed_hosts = _validate_base_and_entry(
        payload.base_url, payload.entry_url, requested_hosts,
    )
    _check_environment(db, project_id, payload.environment_id)
    row = SecurityScanTarget(
        project_id=project_id,
        name=payload.name.strip(),
        target_type=payload.target_type,
        base_url=base,
        entry_url=entry,
        environment_id=payload.environment_id,
        enabled=bool(payload.enabled),
        authorization_status=payload.authorization_status,
        authorization_note=payload.authorization_note,
        active_scan_allowed=bool(payload.active_scan_allowed),
        allowed_hosts=allowed_hosts,
        include_paths=[str(p).strip() for p in (payload.include_paths or []) if str(p).strip()],
        exclude_paths=[str(p).strip() for p in (payload.exclude_paths or []) if str(p).strip()],
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update(
    db: Session, project_id: int, user: User, target_id: int, payload: ScanTargetUpdate,
) -> SecurityScanTarget:
    """修改扫描目标：editor+；base_url / allowed_hosts 变更会重新过 scope_guard。"""
    _access.require_admin_project(db, project_id, user)
    row = _get(db, project_id, target_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return row

    base = data.get("base_url") or row.base_url
    entry = data.get("entry_url", row.entry_url)
    requested_hosts = data.get("allowed_hosts", row.allowed_hosts or [])
    validated_base, validated_entry, validated_hosts = _validate_base_and_entry(
        base, entry, [str(h).strip() for h in (requested_hosts or []) if str(h).strip()],
    )
    data["base_url"] = validated_base
    data["entry_url"] = validated_entry
    data["allowed_hosts"] = validated_hosts
    if "environment_id" in data:
        _check_environment(db, project_id, data["environment_id"])

    for key in ("include_paths", "exclude_paths"):
        if key in data and data[key] is not None:
            data[key] = [str(p).strip() for p in data[key] if str(p).strip()]

    data.pop("id", None)
    for key, value in data.items():
        setattr(row, key, value)
    row.updated_by = user.id
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, project_id: int, user: User, target_id: int) -> None:
    """删除扫描目标：editor+；有未结束任务时禁止删除（避免任务指向空目标）。"""
    _access.require_admin_project(db, project_id, user)
    row = _get(db, project_id, target_id)
    running = (
        db.query(SecurityScanJob)
        .filter(
            SecurityScanJob.target_id == row.id,
            SecurityScanJob.status.in_(JOB_INFLIGHT_STATUSES),
        )
        .count()
    )
    if running:
        raise AppError("该目标下有未结束的扫描任务，无法删除", status_code=409)
    db.delete(row)
    db.commit()


def get_or_none(db: Session, project_id: int, target_id: int) -> SecurityScanTarget | None:
    """不抛错的取值（供扫描计划与 Worker 使用）。"""
    return (
        db.query(SecurityScanTarget)
        .filter(SecurityScanTarget.id == target_id, SecurityScanTarget.project_id == project_id)
        .first()
    )


def list_targets(
    db: Session, project_id: int, user: User, page: int, page_size: int, enabled: bool | None = None,
) -> ScanTargetListResponse:
    """列出项目下的扫描目标（viewer+）。"""
    get_project_or_404(db, project_id, user)
    query = db.query(SecurityScanTarget).filter(SecurityScanTarget.project_id == project_id)
    if enabled is not None:
        query = query.filter(SecurityScanTarget.enabled == enabled)
    query = query.order_by(SecurityScanTarget.id.desc())
    result = paginate(query, page, page_size)
    return ScanTargetListResponse(
        items=[to_read(db, row) for row in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
    )


def to_read(db: Session, row: SecurityScanTarget) -> ScanTargetRead:
    """ORM → 响应；补 is_production 判定（前端据此禁用主动扫描入口）。"""
    environment = db.get(Environment, row.environment_id) if row.environment_id else None
    environment_name = str(getattr(environment, "name", "") or "")
    base = ScanTargetRead.model_validate(row)
    base.is_production = scope_guard.is_production_environment(environment_name)
    base.allowed_hosts = list(row.allowed_hosts or [])
    base.include_paths = list(row.include_paths or [])
    base.exclude_paths = list(row.exclude_paths or [])
    return base


def _check_environment(db: Session, project_id: int, environment_id: int | None) -> None:
    """校验扫描目标引用当前项目已关联且启用的环境。"""
    if not environment_id:
        return
    resolve_project_environment(db, project_id, environment_id)
