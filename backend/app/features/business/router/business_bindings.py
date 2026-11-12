"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.business.schemas import (
    BusinessApiMappingCreate,
    BusinessApiMappingResponse,
    BusinessBindingDetailResponse,
    BusinessBindingUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.business.router.dependencies import _BINDING


router = APIRouter()


@router.get(
    "/business-bindings/{binding_id}",
    response_model=BusinessBindingDetailResponse,
    summary="业务绑定详情（含失效判定与输入/输出映射）",
)
def get_binding(binding_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取绑定。"""
    return _BINDING.get_binding(db, binding_id, user)


@router.patch("/business-bindings/{binding_id}", response_model=BusinessBindingDetailResponse, summary="编辑业务绑定")
def update_binding(
    binding_id: int,
    body: BusinessBindingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新绑定。"""
    return _BINDING.update_binding(db, binding_id, body, actor=user)


@router.delete(
    "/business-bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务绑定（级联清理映射）",
)
def delete_binding(binding_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除绑定。"""
    _BINDING.delete_binding(db, binding_id, actor=user)
    return None


@router.get(
    "/business-bindings/{binding_id}/mappings",
    response_model=list[BusinessApiMappingResponse],
    summary="业务变量 ↔ 接口参数映射列表",
)
def list_mappings(binding_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`mappings`。"""
    return _BINDING.list_mappings(db, binding_id, user)


@router.post(
    "/business-bindings/{binding_id}/mappings",
    response_model=BusinessApiMappingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增映射（project_id→body.project_id / $.data.id→task_id 等）",
)
def create_mapping(
    binding_id: int,
    body: BusinessApiMappingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建映射。"""
    return _BINDING.create_mapping(db, binding_id, body, actor=user)
