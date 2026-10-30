"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.security_testing.schemas import (
    SecurityFindingListResponse,
    SecurityFindingRead,
    SecurityFindingUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.security_testing.router.dependencies import _FINDING


router = APIRouter()


@router.get(
    "/projects/{project_id}/security-findings", response_model=SecurityFindingListResponse,
)
def list_security_findings(
    project_id: int,
    severity: str | None = Query(None),
    status: str | None = Query(None),
    api_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityFindingListResponse:
    """列出安全`findings`。"""
    return _FINDING.list_findings(
        db, project_id, user=user, severity=severity, status=status,
        api_id=api_id, page=page, page_size=page_size,
    )


@router.get("/security-findings/{finding_id}", response_model=SecurityFindingRead)
def get_security_finding(
    finding_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityFindingRead:
    """获取安全发现项。"""
    return _FINDING.get_finding(db, finding_id, user=user)


@router.patch("/security-findings/{finding_id}", response_model=SecurityFindingRead)
def update_security_finding(
    finding_id: int,
    body: SecurityFindingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityFindingRead:
    """只允许改状态；非法迁移 400。改状态需要 editor+。"""
    return _FINDING.update_status(db, finding_id, body, actor=user)
