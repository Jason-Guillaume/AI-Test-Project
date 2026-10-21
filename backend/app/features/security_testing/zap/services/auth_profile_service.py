"""认证配置（SecurityScanAuthProfile）业务服务（§十一 / §十二 / §十三）。

凭据处理规则（§十一 禁止清单）：
- 只存 Fernet 密文（encrypt_secret），任何响应不回显明文；
- 指纹用 sha256 前 12 位，用于判断「凭据是否被换过」；
- 凭据不进入日志、事件表、Agent Prompt 与普通 API 响应。
- 列表页只给 has_credential / token_fingerprint / credential_updated_at。

MANUAL（飞书 SSO）模式不存任何凭据：飞书账号密码不捕获不保存（§十三），
该模式下 credential 字段必须为空，否则拒绝。
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.orm import Session

from app.features.security_testing.zap.contracts import AUTH_MODE_MANUAL
from app.features.security_testing.zap.models.auth_profile import SecurityScanAuthProfile
from app.features.security_testing.zap.schemas import (
    ScanAuthProfileCreate,
    ScanAuthProfileListResponse,
    ScanAuthProfileRead,
    ScanAuthProfileUpdate,
)
from app.features.security_testing.zap.services import _access
from app.models.identity import User
from app.shared.crypto import decrypt_secret, encrypt_secret
from app.shared.errors import AppError, CODE_SECURITY_SCAN_AUTH_PROFILE_NOT_FOUND
from app.shared.pagination import paginate

_NOT_FOUND = AppError(
    "认证配置不存在", status_code=404, code=CODE_SECURITY_SCAN_AUTH_PROFILE_NOT_FOUND,
)


def fingerprint_of(credential: str) -> str:
    """凭据指纹：sha256 前 12 位，只用于比对，不用于反推凭据。"""
    if not credential:
        return ""
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()[:12]


def _get(db: Session, project_id: int, profile_id: int) -> SecurityScanAuthProfile:
    row = (
        db.query(SecurityScanAuthProfile)
        .filter(
            SecurityScanAuthProfile.id == profile_id,
            SecurityScanAuthProfile.project_id == project_id,
        )
        .first()
    )
    if row is None:
        raise _NOT_FOUND
    return row


def create(db: Session, project_id: int, user: User, payload: ScanAuthProfileCreate) -> SecurityScanAuthProfile:
    """创建认证配置：editor+（认证配置属于项目级敏感配置）。"""
    _access.require_admin_project(db, project_id, user)
    if payload.auth_mode == AUTH_MODE_MANUAL and payload.credential:
        raise AppError("人工扫码登录模式不允许保存任何凭据", status_code=400)
    credential = (payload.credential or "").strip()
    row = SecurityScanAuthProfile(
        project_id=project_id,
        name=payload.name.strip(),
        auth_mode=payload.auth_mode,
        session_method=payload.session_method,
        session_header=payload.session_header,
        session_name=payload.session_name,
        credential_encrypted=encrypt_secret(credential) if credential else None,
        token_fingerprint=fingerprint_of(credential) if credential else None,
        has_credential=bool(credential),
        credential_updated_at=datetime.now() if credential else None,
        authentication_check_url=payload.authentication_check_url,
        logged_in_indicator=payload.logged_in_indicator,
        logged_out_indicator=payload.logged_out_indicator,
        expected_user_id=payload.expected_user_id,
        auth_expiry_policy=payload.auth_expiry_policy or "UNKNOWN",
        credential_expires_at=payload.credential_expires_at,
        description=payload.description,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update(
    db: Session, project_id: int, user: User, profile_id: int, payload: ScanAuthProfileUpdate,
) -> SecurityScanAuthProfile:
    """修改认证配置：editor+。

    credential 传新值 → 更新密文与指纹；remove_credential=True → 清除凭据。
    两种操作都会留一条审计字段（credential_updated_at）。
    """
    _access.require_admin_project(db, project_id, user)
    row = _get(db, project_id, profile_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return row

    new_mode = data.get("auth_mode", row.auth_mode)
    if new_mode == AUTH_MODE_MANUAL and data.get("credential"):
        raise AppError("人工扫码登录模式不允许保存任何凭据", status_code=400)

    if data.get("remove_credential"):
        row.credential_encrypted = None
        row.token_fingerprint = None
        row.has_credential = False
        row.credential_updated_at = datetime.now()
        data.pop("remove_credential", None)
        data.pop("credential", None)
    elif data.get("credential"):
        credential = str(data["credential"]).strip()
        row.credential_encrypted = encrypt_secret(credential)
        row.token_fingerprint = fingerprint_of(credential)
        row.has_credential = True
        row.credential_updated_at = datetime.now()
        data.pop("credential", None)

    for key in ("name", "auth_mode", "enabled", "session_method", "session_header", "session_name",
                "authentication_check_url", "logged_in_indicator", "logged_out_indicator",
                "expected_user_id", "auth_expiry_policy", "credential_expires_at", "description"):
        if key in data and data[key] is not None:
            setattr(row, key, data[key])
    row.updated_by = user.id
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, project_id: int, user: User, profile_id: int) -> None:
    """删除认证配置：editor+。被策略引用时不解引用（外键 SET NULL 自动置空）。"""
    _access.require_admin_project(db, project_id, user)
    row = _get(db, project_id, profile_id)
    db.delete(row)
    db.commit()


def get_or_none(db: Session, project_id: int, profile_id: int) -> SecurityScanAuthProfile | None:
    """不抛错的取值（供 Worker 与扫描计划使用）。"""
    return (
        db.query(SecurityScanAuthProfile)
        .filter(
            SecurityScanAuthProfile.id == profile_id,
            SecurityScanAuthProfile.project_id == project_id,
        )
        .first()
    )


def decrypt_credential(row: SecurityScanAuthProfile) -> str:
    """解密凭据（Worker 配置 ZAP 时用一次，用完即弃，不落任何记录）。"""
    return decrypt_secret(row.credential_encrypted) if row.credential_encrypted else ""


def list_profiles(
    db: Session, project_id: int, user: User, page: int, page_size: int, enabled: bool | None = None,
) -> ScanAuthProfileListResponse:
    """列出认证配置（viewer+）；响应不含任何凭据明文。"""
    _access.get_project_or_404(db, project_id, user)
    query = db.query(SecurityScanAuthProfile).filter(
        SecurityScanAuthProfile.project_id == project_id,
    )
    if enabled is not None:
        query = query.filter(SecurityScanAuthProfile.enabled == enabled)
    query = query.order_by(SecurityScanAuthProfile.id.desc())
    result = paginate(query, page, page_size)
    return ScanAuthProfileListResponse(
        items=[ScanAuthProfileRead.model_validate(row) for row in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
    )
