"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.business.router.dependencies import _REF


router = APIRouter()


@router.delete(
    "/business-variable-refs/{ref_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除变量引用",
)
def delete_variable_ref(ref_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除变量`ref`。"""
    _REF.delete_variable_ref(db, ref_id, actor=user)
    return None
