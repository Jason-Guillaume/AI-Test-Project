"""Security Testing 管理面路由（开发计划 §16.1，Phase A）。

单 APIRouter（无自身前缀），挂在 /api/v1 下。路径分两类：
- 项目资源：/projects/{project_id}/security-setting、/projects/{project_id}/security-strategies
- 全局资源：/security-strategies/{id}(+/rules)、/security-rules/{id}

权限口径：读 viewer+；策略与规则写 editor+；系统内置策略/规则不可改（403）也不可删。
跨平台项目统一 404（隐藏存在性），项目可见但角色不足 403。
端点统一 sync def；service owns commit，本层不做 commit。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.security_testing.models import SecurityStrategy
from app.features.security_testing.schemas import (
    MutationRuleCreate,
    MutationRuleResponse,
    MutationRuleUpdate,
    RESERVED_CATEGORIES,
    SecuritySettingRead,
    SecuritySettingUpdate,
    SecurityStrategyCreate,
    SecurityStrategyListResponse,
    SecurityStrategyResponse,
    SecurityStrategyUpdate,
)
from app.features.security_testing.services.rule_service import (
    SecurityRuleService,
    get_manageable_rule,
)
from app.features.security_testing.services.setting_service import SecuritySettingService
from app.features.security_testing.services.strategy_service import (
    SecurityStrategyService,
)
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["Security 管理"])

# 服务无状态，路由层复用单例。
_SETTING = SecuritySettingService()
_STRATEGY = SecurityStrategyService()
_RULE = SecurityRuleService()


# --------------------------------------------------------------------------- 项目设置


@router.get("/projects/{project_id}/security-setting", response_model=SecuritySettingRead)
def get_security_setting(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecuritySettingRead:
    return _SETTING.get_setting(db, project_id, user)


@router.put("/projects/{project_id}/security-setting", response_model=SecuritySettingRead)
def update_security_setting(
    project_id: int,
    body: SecuritySettingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecuritySettingRead:
    return _SETTING.update_setting(db, project_id, body, actor=user)


# --------------------------------------------------------------------------- 策略


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
    return _STRATEGY.create_strategy(db, project_id, body, actor=user)


@router.get("/security-strategies/{strategy_id}", response_model=SecurityStrategyResponse)
def get_security_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyResponse:
    return _STRATEGY.get_strategy(db, strategy_id, actor=user)


@router.patch("/security-strategies/{strategy_id}", response_model=SecurityStrategyResponse)
def update_security_strategy(
    strategy_id: int,
    body: SecurityStrategyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SecurityStrategyResponse:
    return _STRATEGY.update_strategy(db, strategy_id, body, actor=user)


@router.delete("/security-strategies/{strategy_id}", status_code=204)
def delete_security_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _STRATEGY.delete_strategy(db, strategy_id, actor=user)


# --------------------------------------------------------------------------- 变异规则


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


@router.patch("/security-rules/{rule_id}", response_model=MutationRuleResponse)
def update_mutation_rule(
    rule_id: int,
    body: MutationRuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MutationRuleResponse:
    rule = get_manageable_rule(db, rule_id, actor=user)
    # 规则已校验过 editor+；这里只取策略行判断预留类别。
    strategy = db.get(SecurityStrategy, rule.strategy_id)
    return _RULE.update_rule(db, rule_id, body, actor=user, strategy=strategy)


@router.delete("/security-rules/{rule_id}", status_code=204)
def delete_mutation_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _RULE.delete_rule(db, rule_id, actor=user)
