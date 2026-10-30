"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.test_management.schemas import TestStepUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.test_management.router.dependencies import _CASE


router = APIRouter()


@router.patch("/test-steps/{step_id}", summary="编辑测试步骤")
def update_step(
    step_id: int, body: TestStepUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新`step`。"""
    return _CASE.update_step(db, step_id, body, actor=user)


@router.delete("/test-steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试步骤")
def delete_step(step_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除`step`。"""
    _CASE.delete_step(db, step_id, actor=user)
    return None
