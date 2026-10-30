"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.test_management.schemas import TestAssertionUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.test_management.router.dependencies import _CASE


router = APIRouter()


@router.patch("/test-assertions/{assertion_id}", summary="编辑断言")
def update_assertion(
    assertion_id: int, body: TestAssertionUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新断言。"""
    return _CASE.update_assertion(db, assertion_id, body, actor=user)


@router.delete("/test-assertions/{assertion_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除断言")
def delete_assertion(assertion_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除断言。"""
    _CASE.delete_assertion(db, assertion_id, actor=user)
    return None
