"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.test_management.router.dependencies import _SUITE


router = APIRouter()


@router.delete("/test-suite-cases/{suite_case_id}", status_code=status.HTTP_204_NO_CONTENT, summary="从套件移除用例")
def remove_suite_case(suite_case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """移除套件用例。"""
    _SUITE.remove_suite_case(db, suite_case_id, actor=user)
    return None
