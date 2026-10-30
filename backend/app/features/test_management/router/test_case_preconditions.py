"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.test_management.schemas import TestCasePreconditionUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.test_management.router.dependencies import _CASE


router = APIRouter()


@router.patch("/test-case-preconditions/{precondition_id}", summary="编辑前置条件")
def update_precondition(
    precondition_id: int, body: TestCasePreconditionUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新前置条件。"""
    return _CASE.update_precondition(db, precondition_id, body, actor=user)


@router.delete("/test-case-preconditions/{precondition_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除前置条件")
def delete_precondition(precondition_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除前置条件。"""
    _CASE.delete_precondition(db, precondition_id, actor=user)
    return None
