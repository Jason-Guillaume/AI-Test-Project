"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.test_data.schemas import (
    TargetDbConnectionCreate,
    TargetDbConnectionListResponse,
    TargetDbConnectionResponse,
    TargetDbConnectionUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_data.router.dependencies import _CONNECTION


router = APIRouter()


@router.get(
    "/projects/{project_id}/target-databases", response_model=TargetDbConnectionListResponse,
)
def list_target_databases(
    project_id: int,
    environment_id: int | None = Query(None),
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetDbConnectionListResponse:
    """列出目标`databases`。"""
    return _CONNECTION.list_connections(
        db, project_id, user,
        environment_id=environment_id, keyword=keyword, page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/target-databases",
    response_model=TargetDbConnectionResponse, status_code=201,
)
def create_target_database(
    project_id: int,
    body: TargetDbConnectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetDbConnectionResponse:
    """创建目标数据库。"""
    return _CONNECTION.create_connection(db, project_id, body, actor=user)


@router.get(
    "/target-databases/{connection_id}", response_model=TargetDbConnectionResponse,
)
def get_target_database(
    connection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetDbConnectionResponse:
    """获取目标数据库。"""
    return _CONNECTION.get_connection(db, connection_id, user)


@router.patch(
    "/target-databases/{connection_id}", response_model=TargetDbConnectionResponse,
)
def update_target_database(
    connection_id: int,
    body: TargetDbConnectionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetDbConnectionResponse:
    """更新目标数据库。"""
    return _CONNECTION.update_connection(db, connection_id, body, actor=user)


@router.delete("/target-databases/{connection_id}", status_code=204)
def delete_target_database(
    connection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除目标数据库。"""
    _CONNECTION.delete_connection(db, connection_id, actor=user)


@router.post("/target-databases/{connection_id}/ping")
def ping_target_database(
    connection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """检查连通性`target`数据库。"""
    return _CONNECTION.ping(db, connection_id, user)
