"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.business.schemas import BusinessApiMappingResponse, BusinessApiMappingUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.business.router.dependencies import _BINDING


router = APIRouter()


@router.patch(
    "/business-api-mappings/{mapping_id}",
    response_model=BusinessApiMappingResponse,
    summary="编辑映射",
)
def update_mapping(
    mapping_id: int,
    body: BusinessApiMappingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新映射。"""
    return _BINDING.update_mapping(db, mapping_id, body, actor=user)


@router.delete(
    "/business-api-mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除映射",
)
def delete_mapping(mapping_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除映射。"""
    _BINDING.delete_mapping(db, mapping_id, actor=user)
    return None
