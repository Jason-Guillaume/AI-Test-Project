"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.features.security_testing.models import SecurityStrategy
from app.features.security_testing.schemas import MutationRuleResponse, MutationRuleUpdate
from app.features.security_testing.services.rule_service import get_manageable_rule
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.features.security_testing.router.dependencies import _RULE


router = APIRouter()


@router.patch("/security-rules/{rule_id}", response_model=MutationRuleResponse)
def update_mutation_rule(
    rule_id: int,
    body: MutationRuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MutationRuleResponse:
    """更新变异规则。"""
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
    """删除变异规则。"""
    _RULE.delete_rule(db, rule_id, actor=user)
