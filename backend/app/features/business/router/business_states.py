"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.business.schemas import BusinessStateResponse, BusinessStateUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.business.router.dependencies import _CONFIG


router = APIRouter()


@router.patch("/business-states/{state_id}", response_model=BusinessStateResponse, summary="编辑业务状态")
def update_state(
    state_id: int,
    body: BusinessStateUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新状态。"""
    return _CONFIG.update_state(db, state_id, body, actor=user)


@router.delete(
    "/business-states/{state_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务状态",
)
def delete_state(state_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除状态。"""
    _CONFIG.delete_state(db, state_id, actor=user)
    return None
