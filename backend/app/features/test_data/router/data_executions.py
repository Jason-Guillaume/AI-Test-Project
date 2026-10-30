"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.test_data.schemas import DataExecutionDetailResponse, DataExecutionListResponse
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_data.router.dependencies import _EXECUTION


router = APIRouter()


@router.get(
    "/projects/{project_id}/data-executions", response_model=DataExecutionListResponse,
)
def list_data_executions(
    project_id: int,
    status: str | None = Query(None),
    test_run_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionListResponse:
    """列出数据`executions`。"""
    return _EXECUTION.list_executions(
        db, project_id, user, status=status, test_run_id=test_run_id,
        page=page, page_size=page_size,
    )


@router.get(
    "/data-executions/{data_execution_id}", response_model=DataExecutionDetailResponse,
)
def get_data_execution(
    data_execution_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionDetailResponse:
    """获取数据执行记录。"""
    return _EXECUTION.get_execution(db, data_execution_id, user)
