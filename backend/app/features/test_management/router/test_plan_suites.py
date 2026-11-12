"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.test_management.router.dependencies import _PLAN


router = APIRouter()


@router.delete("/test-plan-suites/{plan_suite_id}", status_code=status.HTTP_204_NO_CONTENT, summary="从计划移除套件")
def remove_plan_suite(plan_suite_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """移除计划套件。"""
    _PLAN.remove_plan_suite(db, plan_suite_id, actor=user)
    return None
