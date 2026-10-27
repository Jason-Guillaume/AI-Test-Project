"""测试策略服务层（CRUD）。

权限：读 viewer+、写 member+、越权与不存在共用 404。service owns commit。
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.test_management.models.test_strategy import TestStrategy
from app.features.test_management.schemas import (
    TEST_STRATEGY_CATEGORIES,
    TestStrategyCreate,
    TestStrategyListResponse,
    TestStrategyResponse,
    TestStrategyUpdate,
)
from app.features.test_management.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_strategy_project_id,
)
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found
from app.shared.notify import notify
from app.shared.pagination import DEFAULT_PAGE_SIZE


def _response(s: TestStrategy) -> TestStrategyResponse:
    """构造接口响应数据。"""
    return TestStrategyResponse.model_validate(s)


def _ensure_unique_name(db: Session, project_id: int, name: str, *, exclude_id: int | None = None) -> None:
    """确保`unique`名称。"""
    q = db.query(TestStrategy).filter(TestStrategy.project_id == project_id, TestStrategy.name == name)
    if exclude_id is not None:
        q = q.filter(TestStrategy.id != exclude_id)
    if q.first() is not None:
        raise conflict("测试策略名称已存在")


class StrategyService:
    """测试策略服务。无状态，路由层复用单例。"""

    def list_strategies(
        self, db: Session, project_id: int, user: User, *,
        category: str | None = None, keyword: str | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TestStrategyListResponse:
        """列出`strategies`。"""
        get_project_or_404(db, project_id, user)
        q = db.query(TestStrategy).filter(TestStrategy.project_id == project_id)
        if category:
            if category not in TEST_STRATEGY_CATEGORIES:
                raise bad_request("策略类别取值非法")
            q = q.filter(TestStrategy.category == category)
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(or_(TestStrategy.name.ilike(f"%{kw}%"), TestStrategy.description.ilike(f"%{kw}%")))
        total = int(q.count())
        items = q.order_by(TestStrategy.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return TestStrategyListResponse(items=[_response(s) for s in items], total=total, page=page, page_size=page_size)

    def create_strategy(
        self, db: Session, project_id: int, body: TestStrategyCreate, *, actor: User,
    ) -> TestStrategyResponse:
        """创建策略。"""
        project = require_writable_project(db, project_id, actor)
        name = body.name.strip()
        if not name:
            raise bad_request("策略名称不能为空")
        _ensure_unique_name(db, project_id, name)
        strategy = TestStrategy(
            project_id=project_id, name=name,
            description=(body.description or "").strip() or None,
            category=body.category, enabled=body.enabled,
        )
        db.add(strategy)
        db.flush()
        notify(db, user_id=actor.id, event_type="test.strategy.created",
               title=f"你已创建测试策略「{strategy.name}」", project_id=project_id,
               actor_id=actor.id, actor_username=actor.username,
               detail={"strategy_id": strategy.id})
        db.commit()
        db.refresh(strategy)
        return _response(strategy)

    def get_strategy(self, db: Session, strategy_id: int, user: User) -> TestStrategyResponse:
        """获取策略。"""
        return _response(self._get_or_404(db, strategy_id, user))

    def update_strategy(
        self, db: Session, strategy_id: int, body: TestStrategyUpdate, *, actor: User,
    ) -> TestStrategyResponse:
        """更新策略。"""
        strategy = self._get_writable_or_404(db, strategy_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _response(strategy)
        if "name" in data and data["name"] is not None:
            new_name = data["name"].strip()
            if not new_name:
                raise bad_request("策略名称不能为空")
            if new_name != strategy.name:
                _ensure_unique_name(db, strategy.project_id, new_name, exclude_id=strategy.id)
                strategy.name = new_name
        for field in ("description", "category", "enabled"):
            if field in data and data[field] is not None:
                if field == "category" and data[field] not in TEST_STRATEGY_CATEGORIES:
                    raise bad_request("策略类别取值非法")
                setattr(strategy, field, data[field])
        if "description" in data:
            strategy.description = data["description"]
        if "enabled" in data:
            strategy.enabled = data["enabled"]
        db.flush()
        db.commit()
        db.refresh(strategy)
        return _response(strategy)

    def delete_strategy(self, db: Session, strategy_id: int, *, actor: User) -> None:
        """删除策略。"""
        strategy = self._get_writable_or_404(db, strategy_id, actor)
        db.delete(strategy)
        db.commit()

    def _get_or_404(self, db: Session, strategy_id: int, user: User) -> TestStrategy:
        """获取或。"""
        s = db.get(TestStrategy, strategy_id)
        if s is None:
            raise not_found("测试策略不存在")
        get_project_or_404(db, s.project_id, user)
        return s

    def _get_writable_or_404(self, db: Session, strategy_id: int, actor: User) -> TestStrategy:
        """获取可写或。"""
        s = db.get(TestStrategy, strategy_id)
        if s is None:
            raise not_found("测试策略不存在")
        require_writable_project(db, resolve_strategy_project_id(db, strategy_id), actor)
        return s
