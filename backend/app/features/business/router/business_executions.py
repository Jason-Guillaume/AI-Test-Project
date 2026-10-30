"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.features.business.schemas import FlowExecutionActionListResponse, FlowExecutionResponse
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.business.router.dependencies import _EXECUTION


router = APIRouter()


@router.get(
    "/business-executions/{execution_id}",
    response_model=FlowExecutionResponse,
    summary="执行记录详情",
)
def get_execution(execution_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取执行记录。"""
    return _EXECUTION.get_execution(db, execution_id, user)


@router.get(
    "/business-executions/{execution_id}/actions",
    response_model=FlowExecutionActionListResponse,
    summary="执行记录的步骤执行列表",
)
def list_execution_actions(execution_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出执行记录`actions`。"""
    return _EXECUTION.list_execution_actions(db, execution_id, user)
