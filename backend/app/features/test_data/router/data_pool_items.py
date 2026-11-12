"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.features.test_data.schemas import DataPoolItemResponse, DataPoolItemUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.test_data.router.dependencies import _POOL


router = APIRouter()


@router.patch("/data-pool-items/{item_id}", response_model=DataPoolItemResponse)
def update_pool_item(
    item_id: int,
    body: DataPoolItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolItemResponse:
    """更新连接池条目。"""
    return _POOL.update_item(db, item_id, body, actor=user)


@router.post("/data-pool-items/{item_id}/release", response_model=DataPoolItemResponse)
def release_pool_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolItemResponse:
    """释放连接池条目。"""
    return _POOL.release_item(db, item_id, actor=user)


@router.delete("/data-pool-items/{item_id}", status_code=204)
def delete_pool_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除连接池条目。"""
    _POOL.delete_item(db, item_id, actor=user)
