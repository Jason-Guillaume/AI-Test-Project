"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.features.security_testing.schemas import SecurityExecutionRead
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.security_testing.router.dependencies import _EXECUTION


router = APIRouter()


@router.get(
    "/security-executions/{security_execution_id}", response_model=SecurityExecutionRead,
)
def get_security_execution(
    security_execution_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityExecutionRead:
    """从 test-runs 的 case_execution.context_json.security_execution_id 反查。"""
    return _EXECUTION.get_execution(db, security_execution_id, user=user)
