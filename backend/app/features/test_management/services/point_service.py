"""测试点服务层（CRUD）。

权限：读 viewer+、写 member+、越权与不存在共用 404。service owns commit。
strategy_id 为空表示独立测试点；非空时校验策略属于本项目（跨资源 → 404）。
api_id / business_flow_id / business_action_id 用 SET NULL，不强校验存在性（失效由前端展示）。
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.test_management.models.test_point import TestPoint
from app.features.test_management.models.test_strategy import TestStrategy
from app.features.test_management.schemas import (
    TEST_PRIORITIES,
    TEST_STATUSES,
    TEST_TARGET_TYPES,
    TestPointCreate,
    TestPointListResponse,
    TestPointResponse,
    TestPointUpdate,
)
from app.features.test_management.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_point_project_id,
    resolve_strategy_project_id,
)
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found
from app.shared.notify import notify
from app.shared.pagination import DEFAULT_PAGE_SIZE


def _response(p: TestPoint) -> TestPointResponse:
    return TestPointResponse.model_validate(p)


def _ensure_unique_name(db: Session, project_id: int, name: str, *, exclude_id: int | None = None) -> None:
    q = db.query(TestPoint).filter(TestPoint.project_id == project_id, TestPoint.name == name)
    if exclude_id is not None:
        q = q.filter(TestPoint.id != exclude_id)
    if q.first() is not None:
        raise conflict("测试点名称已存在")


class PointService:
    """测试点服务。无状态，路由层复用单例。"""

    def list_points(
        self, db: Session, project_id: int, user: User, *,
        strategy_id: int | None = None, target_type: str | None = None,
        status: str | None = None, keyword: str | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TestPointListResponse:
        get_project_or_404(db, project_id, user)
        q = db.query(TestPoint).filter(TestPoint.project_id == project_id)
        if strategy_id is not None:
            q = q.filter(TestPoint.strategy_id == strategy_id)
        if target_type:
            if target_type not in TEST_TARGET_TYPES:
                raise bad_request("被测对象类型取值非法")
            q = q.filter(TestPoint.target_type == target_type)
        if status:
            if status not in TEST_STATUSES:
                raise bad_request("状态取值非法")
            q = q.filter(TestPoint.status == status)
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(or_(TestPoint.name.ilike(f"%{kw}%"), TestPoint.description.ilike(f"%{kw}%")))
        total = int(q.count())
        items = q.order_by(TestPoint.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return TestPointListResponse(items=[_response(p) for p in items], total=total, page=page, page_size=page_size)

    def create_point(
        self, db: Session, project_id: int, body: TestPointCreate, *, actor: User,
    ) -> TestPointResponse:
        project = require_writable_project(db, project_id, actor)
        name = body.name.strip()
        if not name:
            raise bad_request("测试点名称不能为空")
        if body.priority not in TEST_PRIORITIES:
            raise bad_request("优先级取值非法")
        if body.target_type not in TEST_TARGET_TYPES:
            raise bad_request("被测对象类型取值非法")
        if body.strategy_id is not None:
            strategy = db.get(TestStrategy, body.strategy_id)
            if strategy is None or strategy.project_id != project.id:
                raise not_found("测试策略不存在")
        _ensure_unique_name(db, project_id, name)
        point = TestPoint(
            project_id=project_id, name=name,
            description=(body.description or "").strip() or None,
            priority=body.priority, target_type=body.target_type,
            strategy_id=body.strategy_id, api_id=body.api_id,
            business_flow_id=body.business_flow_id, business_action_id=body.business_action_id,
            status=body.status, source_type=body.source_type,
            agent_session_id=body.agent_session_id, generation_version=body.generation_version,
        )
        db.add(point)
        db.flush()
        notify(db, user_id=actor.id, event_type="test.point.created",
               title=f"你已创建测试点「{point.name}」", project_id=project_id,
               actor_id=actor.id, actor_username=actor.username,
               detail={"point_id": point.id})
        db.commit()
        db.refresh(point)
        return _response(point)

    def get_point(self, db: Session, point_id: int, user: User) -> TestPointResponse:
        return _response(self._get_or_404(db, point_id, user))

    def update_point(
        self, db: Session, point_id: int, body: TestPointUpdate, *, actor: User,
    ) -> TestPointResponse:
        point = self._get_writable_or_404(db, point_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _response(point)
        if "name" in data and data["name"] is not None:
            new_name = data["name"].strip()
            if not new_name:
                raise bad_request("测试点名称不能为空")
            if new_name != point.name:
                _ensure_unique_name(db, point.project_id, new_name, exclude_id=point.id)
                point.name = new_name
        if "priority" in data and data["priority"] is not None and data["priority"] not in TEST_PRIORITIES:
            raise bad_request("优先级取值非法")
        if "target_type" in data and data["target_type"] is not None and data["target_type"] not in TEST_TARGET_TYPES:
            raise bad_request("被测对象类型取值非法")
        if "status" in data and data["status"] is not None and data["status"] not in TEST_STATUSES:
            raise bad_request("状态取值非法")
        if "strategy_id" in data and data["strategy_id"] is not None:
            strategy = db.get(TestStrategy, data["strategy_id"])
            if strategy is None or strategy.project_id != point.project_id:
                raise not_found("测试策略不存在")
        for field in ("description", "priority", "target_type", "strategy_id", "api_id",
                       "business_flow_id", "business_action_id", "status"):
            if field in data and data[field] is not None:
                setattr(point, field, data[field])
        db.flush()
        db.commit()
        db.refresh(point)
        return _response(point)

    def delete_point(self, db: Session, point_id: int, *, actor: User) -> None:
        point = self._get_writable_or_404(db, point_id, actor)
        db.delete(point)
        db.commit()

    def _get_or_404(self, db: Session, point_id: int, user: User) -> TestPoint:
        p = db.get(TestPoint, point_id)
        if p is None:
            raise not_found("测试点不存在")
        get_project_or_404(db, p.project_id, user)
        return p

    def _get_writable_or_404(self, db: Session, point_id: int, actor: User) -> TestPoint:
        p = db.get(TestPoint, point_id)
        if p is None:
            raise not_found("测试点不存在")
        require_writable_project(db, resolve_point_project_id(db, point_id), actor)
        return p
