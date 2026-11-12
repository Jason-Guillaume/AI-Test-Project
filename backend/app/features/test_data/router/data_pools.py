"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.test_data.schemas import (
    DataPoolCreate,
    DataPoolItemListResponse,
    DataPoolItemCreate,
    DataPoolItemResponse,
    DataPoolLeaseListResponse,
    DataPoolListResponse,
    DataPoolResponse,
    DataPoolUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_data.router.dependencies import _POOL


router = APIRouter()


@router.get("/projects/{project_id}/data-pools", response_model=DataPoolListResponse)
def list_pools(
    project_id: int,
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolListResponse:
    """列出`pools`。"""
    return _POOL.list_pools(
        db, project_id, user, keyword=keyword, status=status, page=page, page_size=page_size,
    )


@router.post("/projects/{project_id}/data-pools", response_model=DataPoolResponse, status_code=201)
def create_pool(
    project_id: int,
    body: DataPoolCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolResponse:
    """创建连接池。"""
    return _POOL.create_pool(db, project_id, body, actor=user)


@router.get("/data-pools/{pool_id}", response_model=DataPoolResponse)
def get_pool(
    pool_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolResponse:
    """获取连接池。"""
    return _POOL.get_pool(db, pool_id, user)


@router.patch("/data-pools/{pool_id}", response_model=DataPoolResponse)
def update_pool(
    pool_id: int,
    body: DataPoolUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolResponse:
    """更新连接池。"""
    return _POOL.update_pool(db, pool_id, body, actor=user)


@router.delete("/data-pools/{pool_id}", status_code=204)
def delete_pool(
    pool_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除连接池。"""
    _POOL.delete_pool(db, pool_id, actor=user)


@router.get("/data-pools/{pool_id}/items", response_model=DataPoolItemListResponse)
def list_pool_items(
    pool_id: int,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolItemListResponse:
    """列出连接池条目。"""
    return _POOL.list_items(
        db, pool_id, user, status=status, page=page, page_size=page_size,
    )


@router.post(
    "/data-pools/{pool_id}/items", response_model=DataPoolItemResponse, status_code=201,
)
def create_pool_item(
    pool_id: int,
    body: DataPoolItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolItemResponse:
    """创建连接池条目。"""
    return _POOL.create_item(db, pool_id, body, actor=user)


@router.get("/data-pools/{pool_id}/leases", response_model=DataPoolLeaseListResponse)
def list_pool_leases(
    pool_id: int,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolLeaseListResponse:
    """列出连接池`leases`。"""
    result = _POOL.list_leases(
        db, pool_id, user, status=status, page=page, page_size=page_size,
    )
    return DataPoolLeaseListResponse(**result)
