"""测试套件服务层（CRUD + 套件-用例关联）。

权限：读 viewer+、写 member+、越权与不存在共用 404。service owns commit。
关联表 TestSuiteCase：CASCADE 删除（套件删则关联删，用例保留）。
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_suite import TestSuite, TestSuiteCase
from app.features.test_management.schemas import (
    TEST_SUITE_TYPES,
    TestSuiteCaseAdd,
    TestSuiteCaseResponse,
    TestSuiteCreate,
    TestSuiteListResponse,
    TestSuiteResponse,
    TestSuiteUpdate,
)
from app.features.test_management.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_case_project_id,
    resolve_suite_project_id,
)
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found
from app.shared.notify import notify
from app.shared.pagination import DEFAULT_PAGE_SIZE


def _response(s: TestSuite) -> TestSuiteResponse:
    return TestSuiteResponse.model_validate(s)


def _ensure_unique_name(db: Session, project_id: int, name: str, *, exclude_id: int | None = None) -> None:
    q = db.query(TestSuite).filter(TestSuite.project_id == project_id, TestSuite.name == name)
    if exclude_id is not None:
        q = q.filter(TestSuite.id != exclude_id)
    if q.first() is not None:
        raise conflict("测试套件名称已存在")


class SuiteService:
    """测试套件服务。无状态，路由层复用单例。"""

    def list_suites(
        self, db: Session, project_id: int, user: User, *,
        suite_type: str | None = None, keyword: str | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TestSuiteListResponse:
        get_project_or_404(db, project_id, user)
        q = db.query(TestSuite).filter(TestSuite.project_id == project_id)
        if suite_type:
            if suite_type not in TEST_SUITE_TYPES:
                raise bad_request("套件类型取值非法")
            q = q.filter(TestSuite.suite_type == suite_type)
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(or_(TestSuite.name.ilike(f"%{kw}%"), TestSuite.description.ilike(f"%{kw}%")))
        total = int(q.count())
        items = q.order_by(TestSuite.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return TestSuiteListResponse(items=[_response(s) for s in items], total=total, page=page, page_size=page_size)

    def create_suite(
        self, db: Session, project_id: int, body: TestSuiteCreate, *, actor: User,
    ) -> TestSuiteResponse:
        project = require_writable_project(db, project_id, actor)
        name = body.name.strip()
        if not name:
            raise bad_request("套件名称不能为空")
        if body.suite_type not in TEST_SUITE_TYPES:
            raise bad_request("套件类型取值非法")
        _ensure_unique_name(db, project_id, name)
        suite = TestSuite(
            project_id=project_id, name=name,
            description=(body.description or "").strip() or None,
            suite_type=body.suite_type, enabled=body.enabled,
        )
        db.add(suite)
        db.flush()
        notify(db, user_id=actor.id, event_type="test.suite.created",
               title=f"你已创建测试套件「{suite.name}」", project_id=project_id,
               actor_id=actor.id, actor_username=actor.username,
               detail={"suite_id": suite.id})
        db.commit()
        db.refresh(suite)
        return _response(suite)

    def get_suite(self, db: Session, suite_id: int, user: User) -> TestSuiteResponse:
        return _response(self._get_or_404(db, suite_id, user))

    def update_suite(
        self, db: Session, suite_id: int, body: TestSuiteUpdate, *, actor: User,
    ) -> TestSuiteResponse:
        suite = self._get_writable_or_404(db, suite_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _response(suite)
        if "name" in data and data["name"] is not None:
            new_name = data["name"].strip()
            if not new_name:
                raise bad_request("套件名称不能为空")
            if new_name != suite.name:
                _ensure_unique_name(db, suite.project_id, new_name, exclude_id=suite.id)
                suite.name = new_name
        if "suite_type" in data and data["suite_type"] is not None and data["suite_type"] not in TEST_SUITE_TYPES:
            raise bad_request("套件类型取值非法")
        for field in ("description", "suite_type", "enabled"):
            if field in data and data[field] is not None:
                setattr(suite, field, data[field])
        if "description" in data:
            suite.description = data["description"]
        if "enabled" in data:
            suite.enabled = data["enabled"]
        db.flush()
        db.commit()
        db.refresh(suite)
        return _response(suite)

    def delete_suite(self, db: Session, suite_id: int, *, actor: User) -> None:
        suite = self._get_writable_or_404(db, suite_id, actor)
        db.delete(suite)
        db.commit()

    # -------------------------------------------------------------- 套件-用例关联

    def list_suite_cases(self, db: Session, suite_id: int, user: User) -> list[TestSuiteCaseResponse]:
        self._get_or_404(db, suite_id, user)
        rows = (
            db.query(TestSuiteCase).filter(TestSuiteCase.suite_id == suite_id)
            .order_by(TestSuiteCase.sort.asc(), TestSuiteCase.id.asc()).all()
        )
        return [TestSuiteCaseResponse.model_validate(r) for r in rows]

    def add_suite_case(
        self, db: Session, suite_id: int, body: TestSuiteCaseAdd, *, actor: User,
    ) -> TestSuiteCaseResponse:
        suite = self._get_writable_or_404(db, suite_id, actor)
        case = db.get(TestCase, body.test_case_id)
        if case is None or case.project_id != suite.project_id:
            raise not_found("测试用例不存在")
        existing = (
            db.query(TestSuiteCase).filter(
                TestSuiteCase.suite_id == suite_id, TestSuiteCase.test_case_id == body.test_case_id,
            ).first()
        )
        if existing is not None:
            raise conflict("用例已在套件中")
        row = TestSuiteCase(
            suite_id=suite_id, test_case_id=body.test_case_id,
            sort=body.sort, enabled=body.enabled,
        )
        db.add(row)
        db.flush()
        db.commit()
        db.refresh(row)
        return TestSuiteCaseResponse.model_validate(row)

    def remove_suite_case(self, db: Session, suite_case_id: int, *, actor: User) -> None:
        row = db.get(TestSuiteCase, suite_case_id)
        if row is None:
            raise not_found("套件用例关联不存在")
        require_writable_project(db, resolve_suite_project_id(db, row.suite_id), actor)
        db.delete(row)
        db.commit()

    def _get_or_404(self, db: Session, suite_id: int, user: User) -> TestSuite:
        s = db.get(TestSuite, suite_id)
        if s is None:
            raise not_found("测试套件不存在")
        get_project_or_404(db, s.project_id, user)
        return s

    def _get_writable_or_404(self, db: Session, suite_id: int, actor: User) -> TestSuite:
        s = db.get(TestSuite, suite_id)
        if s is None:
            raise not_found("测试套件不存在")
        require_writable_project(db, resolve_suite_project_id(db, suite_id), actor)
        return s
