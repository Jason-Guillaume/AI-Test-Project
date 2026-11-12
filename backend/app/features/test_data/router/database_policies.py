"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.test_data.schemas import (
    DatabasePolicyListResponse,
    DatabasePolicyResponse,
    DatabasePolicyUpsert,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_data.router.dependencies import _POLICY


router = APIRouter()


@router.get(
    "/projects/{project_id}/database-policies", response_model=DatabasePolicyListResponse,
)
def list_database_policies(
    project_id: int,
    environment_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatabasePolicyListResponse:
    """列出数据库`policies`。"""
    return _POLICY.list_policies(
        db, project_id, user,
        environment_id=environment_id, page=page, page_size=page_size,
    )


@router.put(
    "/projects/{project_id}/database-policies/{environment_id}",
    response_model=DatabasePolicyResponse,
)
def upsert_database_policy(
    project_id: int,
    environment_id: int,
    body: DatabasePolicyUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatabasePolicyResponse:
    """新增或更新数据库策略。"""
    return _POLICY.upsert_policy(
        db, project_id, environment_id, body, actor=user,
    )
