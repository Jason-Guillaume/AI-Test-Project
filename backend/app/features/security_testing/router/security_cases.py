"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.security_testing.schemas import (
    SecurityCaseDetail,
    SecurityCaseListResponse,
    SecurityCaseRead,
    SecurityCaseUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.security_testing.router.dependencies import _CASE


router = APIRouter()


@router.get(
    "/projects/{project_id}/security-cases", response_model=SecurityCaseListResponse,
)
def list_security_cases(
    project_id: int,
    api_id: int | None = Query(None),
    strategy_id: int | None = Query(None),
    mutation_type: str | None = Query(None),
    enabled: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityCaseListResponse:
    """列出安全`cases`。"""
    return _CASE.list_cases(
        db, project_id, user=user, api_id=api_id, strategy_id=strategy_id,
        mutation_type=mutation_type, enabled=enabled, page=page, page_size=page_size,
    )


@router.get("/security-cases/{security_case_id}", response_model=SecurityCaseDetail)
def get_security_case(
    security_case_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityCaseDetail:
    """获取安全用例。"""
    return _CASE.get_case(db, security_case_id, user=user)


@router.patch("/security-cases/{security_case_id}", response_model=SecurityCaseRead)
def update_security_case(
    security_case_id: int,
    body: SecurityCaseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityCaseRead:
    """只允许改启用状态；扩展行没有 enabled 列，事实来源是 test_case。"""
    return _CASE.update_case(db, security_case_id, body, actor=user)


@router.post(
    "/security-cases/{security_case_id}/confirm-risk", response_model=SecurityCaseRead,
)
def confirm_security_risk(
    security_case_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityCaseRead:
    """高风险确认只能人工走这个端点；Agent 工具不调用它。"""
    return _CASE.confirm_risk(db, security_case_id, actor=user)
