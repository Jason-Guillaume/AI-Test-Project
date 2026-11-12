"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.features.security_testing.schemas import (
    PlanConfirmRequest,
    PlanConfirmResponse,
    PlanPreviewRequest,
    PlanPreviewResponse,
    SecurityPlanRead,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.security_testing.router.dependencies import _PLAN


router = APIRouter()


@router.post(
    "/projects/{project_id}/security-plans/preview",
    response_model=PlanPreviewResponse,
)
def preview_security_plan(
    project_id: int,
    body: PlanPreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanPreviewResponse:
    """只算一遍，不写 TestCase。落库的 security_plan 是未确认快照。"""
    return _PLAN.preview(db, project_id, body, actor=user)


@router.post(
    "/security-plans/{plan_id}/confirm",
    response_model=PlanConfirmResponse,
)
def confirm_security_plan(
    plan_id: int,
    body: PlanConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanConfirmResponse:
    """把选中的预览项写成 case_type='SECURITY' 的用例 + security_case 扩展行。"""
    return _PLAN.confirm(db, plan_id, body, actor=user)


@router.post("/security-plans/{plan_id}/discard", response_model=SecurityPlanRead)
def discard_security_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityPlanRead:
    """放弃安全计划。"""
    return _PLAN.discard(db, plan_id, actor=user)
