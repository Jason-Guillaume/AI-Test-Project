"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.business.schemas import (
    BusinessActionResponse,
    BusinessActionUpdate,
    BusinessBindingCreate,
    BusinessBindingDetailResponse,
    BusinessPreconditionCreate,
    BusinessPreconditionResponse,
    BusinessStateCreate,
    BusinessStateResponse,
    BusinessVariableCreate,
    BusinessVariableResponse,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.business.router.dependencies import _BINDING
from app.features.business.router.dependencies import _CONFIG
from app.features.business.router.dependencies import _FLOW


router = APIRouter()


@router.patch("/business-actions/{action_id}", response_model=BusinessActionResponse, summary="编辑业务动作")
def update_action(
    action_id: int,
    body: BusinessActionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新动作。"""
    return _FLOW.update_action(db, action_id, body, actor=user)


@router.delete(
    "/business-actions/{action_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务动作（级联清理子配置与绑定）",
)
def delete_action(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除动作。"""
    _FLOW.delete_action(db, action_id, actor=user)
    return None


@router.get(
    "/business-actions/{action_id}/preconditions",
    response_model=list[BusinessPreconditionResponse],
    summary="前置条件列表",
)
def list_preconditions(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`preconditions`。"""
    return _CONFIG.list_preconditions(db, action_id, user)


@router.post(
    "/business-actions/{action_id}/preconditions",
    response_model=BusinessPreconditionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增前置条件",
)
def create_precondition(
    action_id: int,
    body: BusinessPreconditionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建前置条件。"""
    return _CONFIG.create_precondition(db, action_id, body, actor=user)


@router.get(
    "/business-actions/{action_id}/variables",
    response_model=list[BusinessVariableResponse],
    summary="业务变量列表（INPUT/OUTPUT 混排）",
)
def list_variables(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`variables`。"""
    return _CONFIG.list_variables(db, action_id, user)


@router.post(
    "/business-actions/{action_id}/variables",
    response_model=BusinessVariableResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增业务变量",
)
def create_variable(
    action_id: int,
    body: BusinessVariableCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建变量。"""
    return _CONFIG.create_variable(db, action_id, body, actor=user)


@router.get(
    "/business-actions/{action_id}/states",
    response_model=list[BusinessStateResponse],
    summary="业务状态列表",
)
def list_states(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`states`。"""
    return _CONFIG.list_states(db, action_id, user)


@router.post(
    "/business-actions/{action_id}/states",
    response_model=BusinessStateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增业务状态（每动作每实体一组 Pre/Post）",
)
def create_state(
    action_id: int,
    body: BusinessStateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建状态。"""
    return _CONFIG.create_state(db, action_id, body, actor=user)


@router.get(
    "/business-actions/{action_id}/bindings",
    response_model=list[BusinessBindingDetailResponse],
    summary="业务绑定列表（含失效判定与映射）",
)
def list_bindings(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`bindings`。"""
    return _BINDING.list_bindings(db, action_id, user)


@router.post(
    "/business-actions/{action_id}/bindings",
    response_model=BusinessBindingDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增业务绑定（第一阶段仅 API 通道）",
)
def create_binding(
    action_id: int,
    body: BusinessBindingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建绑定。"""
    return _BINDING.create_binding(db, action_id, body, actor=user)
