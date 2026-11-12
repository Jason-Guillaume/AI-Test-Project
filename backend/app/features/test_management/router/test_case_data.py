"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.test_management.schemas import TestCaseDataUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.test_management.router.dependencies import _CASE


router = APIRouter()


@router.patch("/test-case-data/{data_id}", summary="编辑测试数据")
def update_data(
    data_id: int, body: TestCaseDataUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新数据。"""
    return _CASE.update_data(db, data_id, body, actor=user)


@router.delete("/test-case-data/{data_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试数据")
def delete_data(data_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除数据。"""
    _CASE.delete_data(db, data_id, actor=user)
    return None
