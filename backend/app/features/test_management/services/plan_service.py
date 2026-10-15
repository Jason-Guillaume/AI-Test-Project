"""测试计划服务层（CRUD + 计划-套件关联）。

权限：读 viewer+、写 member+、越权与不存在共用 404。service owns commit。
environment 为全局资源（无 project_id），不强校验归属（与业务执行一致）。
关联表 TestPlanSuite：CASCADE 删除（计划删则关联删，套件保留）。
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.configuration import Environment
from app.features.test_management.models.test_plan import TestPlan, TestPlanSuite
from app.features.test_management.models.test_suite import TestSuite
from app.features.test_management.schemas import (
    TEST_EXECUTION_MODES,
    TEST_PLAN_STATUSES,
    TestPlanCreate,
    TestPlanListResponse,
    TestPlanResponse,
    TestPlanSuiteAdd,
    TestPlanSuiteResponse,
    TestPlanUpdate,
)
from app.features.test_management.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_plan_project_id,
    resolve_suite_project_id,
)
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found
from app.shared.notify import notify
from app.shared.pagination import DEFAULT_PAGE_SIZE


def _response(p: TestPlan) -> TestPlanResponse:
    return TestPlanResponse.model_validate(p)


def _ensure_unique_name(db: Session, project_id: int, name: str, *, exclude_id: int | None = None) -> None:
    q = db.query(TestPlan).filter(TestPlan.project_id == project_id, TestPlan.name == name)
    if exclude_id is not None:
        q = q.filter(TestPlan.id != exclude_id)
    if q.first() is not None:
        raise conflict("测试计划名称已存在")


class PlanService:
    """测试计划服务。无状态，路由层复用单例。"""

    def list_plans(
        self, db: Session, project_id: int, user: User, *,
        status: str | None = None, keyword: str | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TestPlanListResponse:
        get_project_or_404(db, project_id, user)
        q = db.query(TestPlan).filter(TestPlan.project_id == project_id)
        if status:
            if status not in TEST_PLAN_STATUSES:
                raise bad_request("计划状态取值非法")
            q = q.filter(TestPlan.status == status)
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(or_(TestPlan.name.ilike(f"%{kw}%"), TestPlan.description.ilike(f"%{kw}%")))
        total = int(q.count())
        items = q.order_by(TestPlan.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return TestPlanListResponse(items=[_response(p) for p in items], total=total, page=page, page_size=page_size)

    def create_plan(
        self, db: Session, project_id: int, body: TestPlanCreate, *, actor: User,
    ) -> TestPlanResponse:
        project = require_writable_project(db, project_id, actor)
        name = body.name.strip()
        if not name:
            raise bad_request("计划名称不能为空")
        if body.status not in TEST_PLAN_STATUSES:
            raise bad_request("计划状态取值非法")
        if body.execution_mode not in TEST_EXECUTION_MODES:
            raise bad_request("执行模式取值非法")
        if body.environment_id is not None:
            env = db.get(Environment, body.environment_id)
            if env is None or not env.is_active:
                raise not_found("环境不存在或已停用")
        _ensure_unique_name(db, project_id, name)
        plan = TestPlan(
            project_id=project_id, name=name,
            description=(body.description or "").strip() or None,
            environment_id=body.environment_id, status=body.status,
            execution_mode=body.execution_mode,
        )
        db.add(plan)
        db.flush()
        notify(db, user_id=actor.id, event_type="test.plan.created",
               title=f"你已创建测试计划「{plan.name}」", project_id=project_id,
               actor_id=actor.id, actor_username=actor.username,
               detail={"plan_id": plan.id})
        db.commit()
        db.refresh(plan)
        return _response(plan)

    def get_plan(self, db: Session, plan_id: int, user: User) -> TestPlanResponse:
        return _response(self._get_or_404(db, plan_id, user))

    def update_plan(
        self, db: Session, plan_id: int, body: TestPlanUpdate, *, actor: User,
    ) -> TestPlanResponse:
        plan = self._get_writable_or_404(db, plan_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _response(plan)
        if "name" in data and data["name"] is not None:
            new_name = data["name"].strip()
            if not new_name:
                raise bad_request("计划名称不能为空")
            if new_name != plan.name:
                _ensure_unique_name(db, plan.project_id, new_name, exclude_id=plan.id)
                plan.name = new_name
        if "status" in data and data["status"] is not None and data["status"] not in TEST_PLAN_STATUSES:
            raise bad_request("计划状态取值非法")
        if "execution_mode" in data and data["execution_mode"] is not None and data["execution_mode"] not in TEST_EXECUTION_MODES:
            raise bad_request("执行模式取值非法")
        if "environment_id" in data and data["environment_id"] is not None:
            env = db.get(Environment, data["environment_id"])
            if env is None or not env.is_active:
                raise not_found("环境不存在或已停用")
        for field in ("description", "environment_id", "status", "execution_mode"):
            if field in data and data[field] is not None:
                setattr(plan, field, data[field])
        if "description" in data:
            plan.description = data["description"]
        db.flush()
        db.commit()
        db.refresh(plan)
        return _response(plan)

    def delete_plan(self, db: Session, plan_id: int, *, actor: User) -> None:
        plan = self._get_writable_or_404(db, plan_id, actor)
        db.delete(plan)
        db.commit()

    # -------------------------------------------------------------- 计划-套件关联

    def list_plan_suites(self, db: Session, plan_id: int, user: User) -> list[TestPlanSuiteResponse]:
        self._get_or_404(db, plan_id, user)
        rows = (
            db.query(TestPlanSuite).filter(TestPlanSuite.plan_id == plan_id)
            .order_by(TestPlanSuite.sort.asc(), TestPlanSuite.id.asc()).all()
        )
        return [TestPlanSuiteResponse.model_validate(r) for r in rows]

    def add_plan_suite(
        self, db: Session, plan_id: int, body: TestPlanSuiteAdd, *, actor: User,
    ) -> TestPlanSuiteResponse:
        plan = self._get_writable_or_404(db, plan_id, actor)
        suite = db.get(TestSuite, body.suite_id)
        if suite is None or suite.project_id != plan.project_id:
            raise not_found("测试套件不存在")
        existing = (
            db.query(TestPlanSuite).filter(
                TestPlanSuite.plan_id == plan_id, TestPlanSuite.suite_id == body.suite_id,
            ).first()
        )
        if existing is not None:
            raise conflict("套件已在计划中")
        row = TestPlanSuite(plan_id=plan_id, suite_id=body.suite_id, sort=body.sort)
        db.add(row)
        db.flush()
        db.commit()
        db.refresh(row)
        return TestPlanSuiteResponse.model_validate(row)

    def remove_plan_suite(self, db: Session, plan_suite_id: int, *, actor: User) -> None:
        row = db.get(TestPlanSuite, plan_suite_id)
        if row is None:
            raise not_found("计划套件关联不存在")
        require_writable_project(db, resolve_plan_project_id(db, row.plan_id), actor)
        db.delete(row)
        db.commit()

    def _get_or_404(self, db: Session, plan_id: int, user: User) -> TestPlan:
        p = db.get(TestPlan, plan_id)
        if p is None:
            raise not_found("测试计划不存在")
        get_project_or_404(db, p.project_id, user)
        return p

    def _get_writable_or_404(self, db: Session, plan_id: int, actor: User) -> TestPlan:
        p = db.get(TestPlan, plan_id)
        if p is None:
            raise not_found("测试计划不存在")
        require_writable_project(db, resolve_plan_project_id(db, plan_id), actor)
        return p
