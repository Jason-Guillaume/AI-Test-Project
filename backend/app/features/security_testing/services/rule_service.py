"""结构化变异规则 CRUD。

规则挂在策略下面，禁止脚本：mutation_config 出现 script / python / sql / shell /
payload_file / command 任一键直接 400 SECURITY_MUTATION_INVALID。
期望与算子必须匹配（REMOVE_TOKEN 不能配 EXPECTED_IDEMPOTENT）。
系统模板下的规则不允许项目成员修改（403）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.identity import User
from app.shared.errors import (
    CODE_SECURITY_RULE_NOT_FOUND,
    AppError,
    forbidden,
)

from app.features.security_testing.models import SecurityMutationRule, SecurityStrategy
from app.features.security_testing.schemas import (
    MutationRuleCreate,
    MutationRuleResponse,
    MutationRuleUpdate,
    RESERVED_CATEGORIES,
    parse_mutation_config,
    validate_rule_expectation,
)
from app.features.security_testing.services._access import (
    require_manage_project,
    resolve_rule_project_id,
)


def apply_rule_payload(
    rule: SecurityMutationRule,
    strategy: SecurityStrategy,
    payload: MutationRuleCreate,
    *,
    force_disabled: bool = False,
) -> SecurityMutationRule:
    """把创建请求写进规则实体（策略下单独创建与内嵌创建共用）。

    Args:
        force_disabled: 预留攻击类策略下的规则强制停用，不参与计划生成。
    """
    rule.project_id = strategy.project_id
    rule.strategy_id = strategy.id
    rule.name = payload.name.strip()
    rule.mutation_type = payload.mutation_type
    rule.target_location = payload.target_location
    rule.target_field = payload.target_field
    # operator 与 mutation_type 同集，不另写一套算子表。
    rule.operator = payload.operator or payload.mutation_type
    rule.mutation_config = parse_mutation_config(payload.mutation_config)
    rule.expected_security_behavior = validate_rule_expectation(
        payload.mutation_type, payload.expected_security_behavior
    )
    rule.expected_status_codes = payload.expected_status_codes
    rule.severity = payload.severity or "MEDIUM"
    rule.enabled = False if force_disabled else bool(payload.enabled)
    rule.confirmation_required = bool(payload.confirmation_required)
    rule.sort = int(payload.sort or 0)
    return rule


def get_manageable_rule(db: Session, rule_id: int, *, actor: User) -> SecurityMutationRule:
    """取规则并校验管理权限；系统规则返回 403，跨项目或不存在返回 404。"""
    rule = db.get(SecurityMutationRule, rule_id)
    if rule is None:
        raise AppError("变异规则不存在", status_code=404, code=CODE_SECURITY_RULE_NOT_FOUND)
    project_id = resolve_rule_project_id(db, rule_id)
    if project_id is None:
        raise forbidden("系统内置规则不可修改")
    require_manage_project(db, project_id, actor)
    return rule


class SecurityRuleService:
    """变异规则服务。所有 commit 都在这里发生。"""

    def list_rules(self, db: Session, strategy: SecurityStrategy) -> list[MutationRuleResponse]:
        """列出策略下的规则（按 sort 排序）。读取走 viewer+，权限由策略读取接口保证。"""
        return self._to_response(
            db.query(SecurityMutationRule)
            .filter(SecurityMutationRule.strategy_id == strategy.id)
            .order_by(SecurityMutationRule.sort, SecurityMutationRule.id)
            .all()
        )

    def create_rule(
        self,
        db: Session,
        strategy: SecurityStrategy,
        payload: MutationRuleCreate,
        *,
        actor: User,
        force_disabled: bool = False,
    ) -> MutationRuleResponse:
        """在策略下新增一条规则。"""
        rule = apply_rule_payload(
            SecurityMutationRule(), strategy, payload, force_disabled=force_disabled
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return MutationRuleResponse.model_validate(rule)

    def update_rule(
        self,
        db: Session,
        rule_id: int,
        payload: MutationRuleUpdate,
        *,
        actor: User,
        strategy: SecurityStrategy,
    ) -> MutationRuleResponse:
        """修改规则。系统内置规则 403；预留攻击类策略下的规则不允许重新启用。"""
        rule = get_manageable_rule(db, rule_id, actor=actor)
        data = payload.model_dump(exclude_unset=True, exclude_none=True)
        if not data:
            return MutationRuleResponse.model_validate(rule)

        if "mutation_config" in data:
            data["mutation_config"] = parse_mutation_config(data["mutation_config"])
        # 期望校验要看最终生效的 mutation_type。
        final_type = data.get("mutation_type") or rule.mutation_type
        if "expected_security_behavior" in data:
            data["expected_security_behavior"] = validate_rule_expectation(
                final_type, data["expected_security_behavior"]
            )
        if data.get("operator") is None:
            data["operator"] = final_type
        # 预留攻击类只拦「启用」：允许把误配的规则再停用一次。
        if data.get("enabled") and strategy.category in RESERVED_CATEGORIES:
            raise forbidden("未开放的攻击类策略不能启用")

        for key, value in data.items():
            setattr(rule, key, value)
        db.commit()
        db.refresh(rule)
        return MutationRuleResponse.model_validate(rule)

    def delete_rule(self, db: Session, rule_id: int, *, actor: User) -> None:
        """删除规则。"""
        rule = get_manageable_rule(db, rule_id, actor=actor)
        db.delete(rule)
        db.commit()

    @staticmethod
    def _to_response(rows) -> list[MutationRuleResponse]:
        return [MutationRuleResponse.model_validate(r) for r in rows]
