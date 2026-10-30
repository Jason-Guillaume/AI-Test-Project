"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.business.schemas import BusinessVariableResponse, BusinessVariableUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.business.router.dependencies import _CONFIG


router = APIRouter()


@router.patch("/business-variables/{variable_id}", response_model=BusinessVariableResponse, summary="编辑业务变量")
def update_variable(
    variable_id: int,
    body: BusinessVariableUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新变量。"""
    return _CONFIG.update_variable(db, variable_id, body, actor=user)


@router.delete(
    "/business-variables/{variable_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务变量",
)
def delete_variable(variable_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除变量。"""
    _CONFIG.delete_variable(db, variable_id, actor=user)
    return None
