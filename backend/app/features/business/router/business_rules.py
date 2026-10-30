"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.features.business.schemas import (
    BusinessRuleCreate,
    BusinessRuleListResponse,
    BusinessRuleResponse,
    BusinessRuleUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.business.router.dependencies import _RULE


router = APIRouter()


@router.get(
    "/projects/{project_id}/business-rules",
    response_model=BusinessRuleListResponse,
    summary="业务规则列表（flow_id/action_id 过滤）",
)
def list_rules(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    flow_id: int | None = Query(None, ge=1),
    action_id: int | None = Query(None, ge=1),
):
    """列出`rules`。"""
    return _RULE.list_rules(
        db, project_id, user,
        flow_id=flow_id, action_id=action_id, page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/business-rules",
    response_model=BusinessRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增业务规则",
)
def create_rule(
    project_id: int,
    body: BusinessRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建规则。"""
    return _RULE.create_rule(db, project_id, body, actor=user)


@router.patch("/business-rules/{rule_id}", response_model=BusinessRuleResponse, summary="编辑业务规则")
def update_rule(
    rule_id: int,
    body: BusinessRuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新规则。"""
    return _RULE.update_rule(db, rule_id, body, actor=user)


@router.delete(
    "/business-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务规则",
)
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除规则。"""
    _RULE.delete_rule(db, rule_id, actor=user)
    return None
