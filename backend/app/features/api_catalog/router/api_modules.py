"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.features.api_catalog.schemas import (
    ApiModuleCreate,
    ApiModuleMove,
    ApiModuleResponse,
    ApiModuleUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.api_catalog.router.dependencies import _API


router = APIRouter()


@router.get(
    "/projects/{project_id}/api-modules",
    response_model=list[ApiModuleResponse],
    summary="模块树（含未分类）",
)
def list_modules(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`modules`。"""
    return _API.list_modules(db, project_id, user)


@router.post(
    "/projects/{project_id}/api-modules",
    response_model=ApiModuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建模块（≤2级）",
)
def create_module(
    project_id: int,
    body: ApiModuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建`module`。"""
    return _API.create_module(db, project_id, body, actor=user)


@router.patch("/api-modules/{module_id}", response_model=ApiModuleResponse, summary="编辑模块")
def update_module(
    module_id: int,
    body: ApiModuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新`module`。"""
    return _API.update_module(db, module_id, body, actor=user)


@router.patch("/api-modules/{module_id}/move", response_model=ApiModuleResponse, summary="移动模块")
def move_module(
    module_id: int,
    body: ApiModuleMove,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """移动模块。"""
    return _API.move_module(db, module_id, body, actor=user)


@router.delete(
    "/api-modules/{module_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除模块（未分类不可删；子接口归未分类）",
)
def delete_module(
    module_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除`module`。"""
    _API.delete_module(db, module_id, actor=user)
    return None
