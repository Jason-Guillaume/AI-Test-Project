"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.features.test_management.schemas import TestStrategyCreate, TestStrategyUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_management.router.dependencies import _STRATEGY


router = APIRouter()


@router.get("/projects/{project_id}/test-strategies", response_model=list, summary="测试策略列表")
def list_strategies(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    category: str | None = Query(None),
    keyword: str | None = Query(None),
):
    """列出`strategies`。"""
    # response_model=list 时返回 items；前端按需改用 ListResponse。
    return _STRATEGY.list_strategies(
        db, project_id, user, category=category, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post(
    "/projects/{project_id}/test-strategies",
    status_code=status.HTTP_201_CREATED,
    summary="新建测试策略",
)
def create_strategy(
    project_id: int,
    body: TestStrategyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建策略。"""
    return _STRATEGY.create_strategy(db, project_id, body, actor=user)


@router.get("/test-strategies/{strategy_id}", summary="测试策略详情")
def get_strategy(strategy_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取策略。"""
    return _STRATEGY.get_strategy(db, strategy_id, user)


@router.patch("/test-strategies/{strategy_id}", summary="编辑测试策略")
def update_strategy(
    strategy_id: int,
    body: TestStrategyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新策略。"""
    return _STRATEGY.update_strategy(db, strategy_id, body, actor=user)


@router.delete("/test-strategies/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试策略")
def delete_strategy(strategy_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除策略。"""
    _STRATEGY.delete_strategy(db, strategy_id, actor=user)
    return None
