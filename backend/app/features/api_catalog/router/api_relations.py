"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.api_catalog.router.dependencies import _API


router = APIRouter()


@router.delete(
    "/api-relations/{relation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除关联",
)
def delete_relation(
    relation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除`relation`。"""
    _API.delete_relation(db, relation_id, actor=user)
    return None
