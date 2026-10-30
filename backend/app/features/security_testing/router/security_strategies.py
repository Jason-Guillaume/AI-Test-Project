"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.security_testing.schemas import (
    MutationRuleCreate,
    MutationRuleResponse,
    RESERVED_CATEGORIES,
    SecurityStrategyCreate,
    SecurityStrategyListResponse,
    SecurityStrategyResponse,
    SecurityStrategyUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.security_testing.router.dependencies import _RULE
from app.features.security_testing.router.dependencies import _STRATEGY


router = APIRouter()


@router.get(
    "/projects/{project_id}/security-strategies", response_model=SecurityStrategyListResponse,
)
def list_security_strategies(
    project_id: int,
    category: str | None = Query(None),
    enabled: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyListResponse:
    """列出安全`strategies`。"""
    return _STRATEGY.list_strategies(
        db, project_id, actor=user, category=category, enabled=enabled,
        page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/security-strategies",
    response_model=SecurityStrategyResponse, status_code=201,
)
def create_security_strategy(
    project_id: int,
    body: SecurityStrategyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyResponse:
    """创建安全策略。"""
    return _STRATEGY.create_strategy(db, project_id, body, actor=user)


@router.get("/security-strategies/{strategy_id}", response_model=SecurityStrategyResponse)
def get_security_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyResponse:
    """获取安全策略。"""
    return _STRATEGY.get_strategy(db, strategy_id, actor=user)


@router.patch("/security-strategies/{strategy_id}", response_model=SecurityStrategyResponse)
def update_security_strategy(
    strategy_id: int,
    body: SecurityStrategyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyResponse:
    """更新安全策略。"""
    return _STRATEGY.update_strategy(db, strategy_id, body, actor=user)


@router.delete("/security-strategies/{strategy_id}", status_code=204)
def delete_security_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除安全策略。"""
    _STRATEGY.delete_strategy(db, strategy_id, actor=user)


@router.post(
    "/security-strategies/{strategy_id}/rules",
    response_model=MutationRuleResponse, status_code=201,
)
def create_mutation_rule(
    strategy_id: int,
    body: MutationRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MutationRuleResponse:
    """在策略下新增规则。预留攻击类策略下强制停用。"""
    strategy = _STRATEGY.get_manageable_strategy(db, strategy_id, actor=user)
    return _RULE.create_rule(
        db, strategy, body, actor=user,
        force_disabled=strategy.category in RESERVED_CATEGORIES,
    )
