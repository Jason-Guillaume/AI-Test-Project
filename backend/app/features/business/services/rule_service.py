"""业务规则服务层。

规则挂在三个层级：project_id 必填（由路径提供），flow_id / action_id 可选
（为空表示项目级规则）。第一阶段主要用于人工维护业务知识，expression 不自动执行。

权限：读 viewer+、写 member+、越权与不存在共用 404。service owns commit。
创建时校验：flow_id（若有）须属于本项目；action_id（若有）须属于本项目某流程。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_flow import BusinessFlow
from app.features.business.models.business_rule import BusinessRule
from app.features.business.schemas import (
    BusinessRuleCreate,
    BusinessRuleListResponse,
    BusinessRuleResponse,
    BusinessRuleUpdate,
)
from app.features.business.services._access import (
    get_project_or_404,
    require_writable_project,
)
from app.models.identity import User
from app.shared.errors import bad_request, not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE


def _rule_response(rule: BusinessRule) -> BusinessRuleResponse:
    """构造规则响应数据。"""
    return BusinessRuleResponse.model_validate(rule)


class RuleService:
    """业务规则服务。无状态，路由层复用单例。"""

    def list_rules(
        self,
        db: Session,
        project_id: int,
        user: User,
        *,
        flow_id: int | None = None,
        action_id: int | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> BusinessRuleListResponse:
        """列出`rules`。"""
        get_project_or_404(db, project_id, user)
        query = db.query(BusinessRule).filter(BusinessRule.project_id == project_id)
        if flow_id is not None:
            query = query.filter(BusinessRule.flow_id == flow_id)
        if action_id is not None:
            query = query.filter(BusinessRule.action_id == action_id)
        total = int(query.count())
        items = (
            query.order_by(BusinessRule.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return BusinessRuleListResponse(
            items=[_rule_response(r) for r in items], total=total, page=page, page_size=page_size
        )

    def create_rule(
        self, db: Session, project_id: int, body: BusinessRuleCreate, *, actor: User
    ) -> BusinessRuleResponse:
        """创建规则。"""
        project = require_writable_project(db, project_id, actor)
        # flow_id / action_id 若指定，须属于本项目（跨资源不一致 → 400）。
        flow: BusinessFlow | None = None
        if body.flow_id is not None:
            flow = db.get(BusinessFlow, body.flow_id)
            if flow is None or flow.project_id != project.id:
                raise bad_request("业务流程不存在或不属于当前项目")
        if body.action_id is not None:
            action = db.get(BusinessAction, body.action_id)
            if action is None:
                raise bad_request("业务动作不存在")
            action_flow = db.get(BusinessFlow, action.flow_id)
            if action_flow is None or action_flow.project_id != project.id:
                raise bad_request("业务动作不属于当前项目")
            # action_id 须属于 flow_id 对应的流程，避免悬挂引用
            if body.flow_id is not None and action.flow_id != body.flow_id:
                raise bad_request("业务动作不属于指定的业务流程")
        name = body.name.strip()
        if not name:
            raise bad_request("规则名称不能为空")
        rule = BusinessRule(
            project_id=project_id,
            flow_id=body.flow_id,
            action_id=body.action_id,
            name=name,
            description=body.description,
            rule_type=body.rule_type,
            expression=body.expression,
            enabled=body.enabled,
        )
        db.add(rule)
        db.flush()
        db.commit()
        db.refresh(rule)
        return _rule_response(rule)

    def update_rule(
        self, db: Session, rule_id: int, body: BusinessRuleUpdate, *, actor: User
    ) -> BusinessRuleResponse:
        """更新规则。"""
        rule = self._get_writable_rule_or_404(db, rule_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _rule_response(rule)
        if "name" in data and data["name"] is not None:
            data["name"] = data["name"].strip()
            if not data["name"]:
                raise bad_request("规则名称不能为空")
        for field, value in data.items():
            setattr(rule, field, value)
        db.flush()
        db.commit()
        db.refresh(rule)
        return _rule_response(rule)

    def delete_rule(self, db: Session, rule_id: int, *, actor: User) -> None:
        """删除规则。"""
        rule = self._get_writable_rule_or_404(db, rule_id, actor)
        db.delete(rule)
        db.commit()

    def _get_writable_rule_or_404(
        self, db: Session, rule_id: int, actor: User
    ) -> BusinessRule:
        """获取可写规则或。"""
        rule = db.get(BusinessRule, rule_id)
        if rule is None:
            raise not_found("业务规则不存在")
        require_writable_project(db, rule.project_id, actor)
        return rule
