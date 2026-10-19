"""安全策略服务：系统模板只读 + 项目自定义 CRUD。

- 系统模板（scope=SYSTEM、builtin=true、project_id 为空）对所有人只读，
  修改规则体 403，不能删除。项目若不想用，生成计划时不勾选即可——
  不做一套「项目屏蔽系统模板」的隐藏配置。
- 项目自定义策略只允许 scope=PROJECT 且必须带 project_id。
- 预留攻击类（INJECTION / RATE_LIMIT / UPLOAD / SSRF）允许保存，
  但 enabled 强制 false，规则也全部停用，执行时仍会直接拒绝。
- 跨平台项目统一 404（隐藏存在性）；项目可见但角色不足时 403。
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.identity import User
from app.models.project import Project
from app.shared.errors import (
    CODE_SECURITY_STRATEGY_NOT_FOUND,
    AppError,
    conflict,
    forbidden,
    not_found,
)
from app.shared.pagination import paginate
from app.shared.roles import (
    PROJECT_ROLE_VIEWER,
    has_project_role,
    project_role_for,
)

from app.features.security_testing.models import SecurityMutationRule, SecurityStrategy
from app.features.security_testing.schemas import (
    RESERVED_CATEGORIES,
    SecurityStrategyCreate,
    SecurityStrategyListResponse,
    SecurityStrategyResponse,
    SecurityStrategyUpdate,
)
from app.features.security_testing.services._access import (
    get_project_or_404,
    require_manage_project,
)
from app.features.security_testing.services.rule_service import (
    SecurityRuleService,
    apply_rule_payload,
)


class SecurityStrategyService:
    """策略服务。所有 commit 都在这里发生。"""

    def __init__(self) -> None:
        self._rules = SecurityRuleService()

    # ---------------------------------------------------------------- 查询

    def list_strategies(
        self,
        db: Session,
        project_id: int,
        *,
        actor: User,
        category: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SecurityStrategyListResponse:
        """系统模板 + 本项目策略；支持按类别与启用状态筛选。"""
        get_project_or_404(db, project_id, actor)
        query = db.query(SecurityStrategy).filter(
            (SecurityStrategy.project_id.is_(None))
            | (SecurityStrategy.project_id == project_id)
        )
        if category is not None:
            query = query.filter(SecurityStrategy.category == category)
        if enabled is not None:
            query = query.filter(SecurityStrategy.enabled.is_(enabled))
        query = query.order_by(
            SecurityStrategy.project_id.is_(None).desc(),
            SecurityStrategy.category,
            SecurityStrategy.strategy_key,
        )
        result = paginate(query, page, page_size)
        return SecurityStrategyListResponse(
            items=[
                self._to_response(db, row, with_rules=True) for row in result["items"]
            ],
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
        )

    def get_strategy(self, db: Session, strategy_id: int, *, actor: User) -> SecurityStrategyResponse:
        """取单条策略（含规则列表）。系统模板对所有人只读可见。"""
        strategy = self._get_or_404(db, strategy_id)
        if strategy.project_id is not None:
            self._assert_readable(db, strategy.project_id, actor)
        return self._to_response(db, strategy, with_rules=True)

    # ---------------------------------------------------------------- 写入

    def create_strategy(
        self,
        db: Session,
        project_id: int,
        payload: SecurityStrategyCreate,
        *,
        actor: User,
    ) -> SecurityStrategyResponse:
        """创建项目自定义策略（只创建 scope=PROJECT）。"""
        project = require_manage_project(db, project_id, actor)
        reserved = payload.category in RESERVED_CATEGORIES

        strategy = SecurityStrategy(
            project_id=project.id,
            scope="PROJECT",
            name=payload.name.strip(),
            strategy_key=payload.strategy_key,
            category=payload.category,
            description=(payload.description or None),
            # 预留攻击类可以保存，但永远不允许启用。
            enabled=False if reserved else bool(payload.enabled),
            risk_level=payload.risk_level,
            builtin=False,
            created_by=actor.id,
        )
        db.add(strategy)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise conflict("同项目内已存在相同 strategy_key 的策略")

        for rule_payload in payload.rules:
            db.add(
                apply_rule_payload(
                    SecurityMutationRule(), strategy, rule_payload,
                    force_disabled=reserved,
                )
            )
        db.commit()
        db.refresh(strategy)
        return self._to_response(db, strategy, with_rules=True)

    def update_strategy(
        self,
        db: Session,
        strategy_id: int,
        payload: SecurityStrategyUpdate,
        *,
        actor: User,
    ) -> SecurityStrategyResponse:
        """修改策略。系统模板 403；预留类别不能重新启用。"""
        strategy = self._get_manageable(db, strategy_id, actor)
        data = payload.model_dump(exclude_unset=True, exclude_none=True)
        if data.get("revision") == strategy.revision:
            data.pop("revision", None)
        elif "revision" in data:
            raise conflict("策略已被他人修改，请刷新后重试")

        if "enabled" in data and strategy.category in RESERVED_CATEGORIES and data["enabled"]:
            raise forbidden("未开放的攻击类策略不能启用")
        if not data:
            return self._to_response(db, strategy, with_rules=True)

        if "name" in data:
            data["name"] = data["name"].strip()
        for key, value in data.items():
            setattr(strategy, key, bool(value) if isinstance(value, bool) else value)
        strategy.revision = (strategy.revision or 0) + 1
        db.commit()
        db.refresh(strategy)
        return self._to_response(db, strategy, with_rules=True)

    def delete_strategy(self, db: Session, strategy_id: int, *, actor: User) -> None:
        """删除项目自定义策略；系统模板禁止删除。规则随外键级联删除。"""
        strategy = self._get_manageable(db, strategy_id, actor)
        db.delete(strategy)
        db.commit()

    def get_manageable_strategy(self, db: Session, strategy_id: int, *, actor: User) -> SecurityStrategy:
        """取策略实体并校验管理权限（editor+），供规则写入判断预留类别使用。"""
        return self._get_manageable(db, strategy_id, actor)

    # ---------------------------------------------------------------- 内部

    @staticmethod
    def _get_or_404(db: Session, strategy_id: int) -> SecurityStrategy:
        strategy = db.get(SecurityStrategy, strategy_id)
        if strategy is None:
            raise AppError(
                "安全策略不存在", status_code=404, code=CODE_SECURITY_STRATEGY_NOT_FOUND,
            )
        return strategy

    @staticmethod
    def _assert_readable(db: Session, project_id: int, actor: User) -> None:
        """读权限校验：viewer+，跨项目与不可见统一 404。"""
        project = db.get(Project, project_id)
        if project is None:
            raise not_found("项目不存在")
        if not has_project_role(project_role_for(db, project, actor), PROJECT_ROLE_VIEWER):
            raise not_found("安全策略不存在")

    @classmethod
    def _get_manageable(cls, db: Session, strategy_id: int, actor: User) -> SecurityStrategy:
        """取策略并校验管理权限（editor+）；系统模板 403，跨项目 404。"""
        strategy = cls._get_or_404(db, strategy_id)
        if strategy.project_id is None:
            raise forbidden("系统内置策略不可修改")
        project = db.get(Project, strategy.project_id)
        if project is None:
            raise not_found("安全策略不存在")
        require_manage_project(db, project.id, actor)
        return strategy

    @staticmethod
    def _to_response(
        db: Session, strategy: SecurityStrategy, *, with_rules: bool = False,
    ) -> SecurityStrategyResponse:
        response = SecurityStrategyResponse.model_validate(strategy)
        if with_rules:
            response.rules = SecurityRuleService().list_rules(db, strategy)
        return response
