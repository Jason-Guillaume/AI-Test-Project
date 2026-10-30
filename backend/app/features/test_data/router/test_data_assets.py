"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.test_data.schemas import (
    TestDataAssetCreate,
    TestDataAssetListResponse,
    TestDataAssetResponse,
    TestDataAssetUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_data.router.dependencies import _ASSET


router = APIRouter()


@router.get(
    "/projects/{project_id}/test-data-assets", response_model=TestDataAssetListResponse,
)
def list_assets(
    project_id: int,
    keyword: str | None = Query(None),
    entity_type: str | None = Query(None),
    source: str | None = Query(None),
    status: str | None = Query(None),
    scope: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestDataAssetListResponse:
    """列出`assets`。"""
    return _ASSET.list_assets(
        db, project_id, user,
        keyword=keyword, entity_type=entity_type, source=source, status=status, scope=scope,
        page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/test-data-assets",
    response_model=TestDataAssetResponse, status_code=201,
)
def create_asset(
    project_id: int,
    body: TestDataAssetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestDataAssetResponse:
    """创建资产。"""
    return _ASSET.create_asset(db, project_id, body, actor=user)


@router.get("/test-data-assets/{asset_id}", response_model=TestDataAssetResponse)
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestDataAssetResponse:
    """获取资产。"""
    return _ASSET.get_asset(db, asset_id, user)


@router.patch("/test-data-assets/{asset_id}", response_model=TestDataAssetResponse)
def update_asset(
    asset_id: int,
    body: TestDataAssetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestDataAssetResponse:
    """更新资产。"""
    return _ASSET.update_asset(db, asset_id, body, actor=user)


@router.delete("/test-data-assets/{asset_id}", status_code=204)
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除资产。"""
    _ASSET.delete_asset(db, asset_id, actor=user)
