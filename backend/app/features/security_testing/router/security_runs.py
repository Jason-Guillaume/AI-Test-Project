"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.features.security_testing.schemas import SecurityRunRequest
from app.features.test_management.schemas import TestRunResponse
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.security_testing.router.dependencies import _CASE


router = APIRouter()


@router.post("/projects/{project_id}/security-runs", response_model=TestRunResponse)
def run_security_cases(
    project_id: int,
    body: SecurityRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestRunResponse:
    """唯一的批量执行入口：内部临时 TestPlan + Suite，复用既有 RunService。"""
    return _CASE.run_security_cases(db, project_id, body, actor=user)
