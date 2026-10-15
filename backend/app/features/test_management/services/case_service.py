"""测试用例服务层（CRUD + 子实体 + 聚合详情）。

TestCase.revision 乐观锁：更新时校验 revision，不匹配 → 409 CONFLICT
（消息含「已被其他用户修改」，前端据此提示「当前测试用例已被其他用户修改」）。

子实体（前置条件 / 测试数据 / 步骤 / 断言）均挂载在 test_case 下，CASCADE 删除。
聚合详情 TestCaseDetailResponse 一次性返回用例 + 全部子实体，供前端用例编辑器渲染。

权限：读 viewer+、写 member+、越权与不存在共用 404。service owns commit。
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.test_data.models.case_fixture import TestCaseFixture
from app.features.test_data.models.fixture import Fixture, FixtureOutput
from app.features.test_management.models.test_assertion import TestAssertion
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_case_data import TestCaseData
from app.features.test_management.models.test_case_precondition import TestCasePrecondition
from app.features.test_management.models.test_point import TestPoint
from app.features.test_management.models.test_step import TestStep
from app.features.test_management.schemas import (
    TEST_CASE_TYPES,
    TEST_PRIORITIES,
    TEST_STATUSES,
    TEST_TARGET_TYPES,
    TestCaseCreate,
    TestCaseDataCreate,
    TestCaseDataResponse,
    TestCaseDataUpdate,
    TestCaseDetailResponse,
    TestCaseFixtureReplace,
    TestCaseFixtureResponse,
    TestCaseListResponse,
    TestCasePreconditionCreate,
    TestCasePreconditionResponse,
    TestCasePreconditionUpdate,
    TestCaseResponse,
    TestCaseUpdate,
    TestAssertionCreate,
    TestAssertionResponse,
    TestAssertionUpdate,
    TestStepCreate,
    TestStepResponse,
    TestStepUpdate,
)
from app.features.test_management.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_case_project_id,
)
from app.models.identity import User
from app.shared.errors import (
    CODE_FIXTURE_DISABLED,
    CODE_FIXTURE_NOT_FOUND,
    AppError,
    bad_request,
    conflict,
    not_found,
)
from app.shared.notify import notify
from app.shared.pagination import DEFAULT_PAGE_SIZE


def _response(c: TestCase) -> TestCaseResponse:
    return TestCaseResponse.model_validate(c)


def _ensure_unique_name(db: Session, project_id: int, name: str, *, exclude_id: int | None = None) -> None:
    q = db.query(TestCase).filter(TestCase.project_id == project_id, TestCase.name == name)
    if exclude_id is not None:
        q = q.filter(TestCase.id != exclude_id)
    if q.first() is not None:
        raise conflict("测试用例名称已存在")


class CaseService:
    """测试用例服务。无状态，路由层复用单例。"""

    # -------------------------------------------------------------- 用例

    def list_cases(
        self, db: Session, project_id: int, user: User, *,
        test_point_id: int | None = None, target_type: str | None = None,
        status: str | None = None, keyword: str | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TestCaseListResponse:
        get_project_or_404(db, project_id, user)
        q = db.query(TestCase).filter(TestCase.project_id == project_id)
        if test_point_id is not None:
            q = q.filter(TestCase.test_point_id == test_point_id)
        if target_type:
            if target_type not in TEST_TARGET_TYPES:
                raise bad_request("被测对象类型取值非法")
            q = q.filter(TestCase.target_type == target_type)
        if status:
            if status not in TEST_STATUSES:
                raise bad_request("状态取值非法")
            q = q.filter(TestCase.status == status)
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(or_(TestCase.name.ilike(f"%{kw}%"), TestCase.description.ilike(f"%{kw}%")))
        total = int(q.count())
        items = q.order_by(TestCase.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return TestCaseListResponse(items=[_response(c) for c in items], total=total, page=page, page_size=page_size)

    def create_case(
        self, db: Session, project_id: int, body: TestCaseCreate, *, actor: User,
    ) -> TestCaseResponse:
        project = require_writable_project(db, project_id, actor)
        name = body.name.strip()
        if not name:
            raise bad_request("测试用例名称不能为空")
        if body.priority not in TEST_PRIORITIES:
            raise bad_request("优先级取值非法")
        if body.case_type not in TEST_CASE_TYPES:
            raise bad_request("用例类型取值非法")
        if body.target_type not in TEST_TARGET_TYPES:
            raise bad_request("被测对象类型取值非法")
        if body.status not in TEST_STATUSES:
            raise bad_request("状态取值非法")
        if body.test_point_id is not None:
            point = db.get(TestPoint, body.test_point_id)
            if point is None or point.project_id != project.id:
                raise not_found("测试点不存在")
        _ensure_unique_name(db, project_id, name)
        case = TestCase(
            project_id=project_id, name=name,
            description=(body.description or "").strip() or None,
            priority=body.priority, case_type=body.case_type, target_type=body.target_type,
            test_point_id=body.test_point_id, api_id=body.api_id,
            business_flow_id=body.business_flow_id, business_action_id=body.business_action_id,
            status=body.status, enabled=body.enabled, source_type=body.source_type,
            agent_session_id=body.agent_session_id, generation_version=body.generation_version,
        )
        db.add(case)
        db.flush()
        notify(db, user_id=actor.id, event_type="test.case.created",
               title=f"你已创建测试用例「{case.name}」", project_id=project_id,
               actor_id=actor.id, actor_username=actor.username,
               detail={"case_id": case.id})
        db.commit()
        db.refresh(case)
        return _response(case)

    def get_case(self, db: Session, case_id: int, user: User) -> TestCaseResponse:
        return _response(self._get_or_404(db, case_id, user))

    def get_case_detail(self, db: Session, case_id: int, user: User) -> TestCaseDetailResponse:
        case = self._get_or_404(db, case_id, user)
        preconditions = (
            db.query(TestCasePrecondition).filter(TestCasePrecondition.test_case_id == case_id)
            .order_by(TestCasePrecondition.sort.asc(), TestCasePrecondition.id.asc()).all()
        )
        data = (
            db.query(TestCaseData).filter(TestCaseData.test_case_id == case_id)
            .order_by(TestCaseData.sort.asc(), TestCaseData.id.asc()).all()
        )
        steps = (
            db.query(TestStep).filter(TestStep.test_case_id == case_id)
            .order_by(TestStep.sort.asc(), TestStep.id.asc()).all()
        )
        assertions = (
            db.query(TestAssertion).filter(TestAssertion.test_case_id == case_id)
            .order_by(TestAssertion.sort.asc(), TestAssertion.id.asc()).all()
        )
        return TestCaseDetailResponse(
            **_response(case).model_dump(),
            preconditions=[TestCasePreconditionResponse.model_validate(p) for p in preconditions],
            test_data=[TestCaseDataResponse.model_validate(d) for d in data],
            steps=[TestStepResponse.model_validate(s) for s in steps],
            assertions=[TestAssertionResponse.model_validate(a) for a in assertions],
            fixtures=self._fixture_rows(db, case_id),
        )

    def update_case(
        self, db: Session, case_id: int, body: TestCaseUpdate, *, actor: User,
    ) -> TestCaseResponse:
        case = self._get_writable_or_404(db, case_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _response(case)
        # 乐观锁校验（§26）：revision 不匹配 → 409。
        if "revision" in data and data["revision"] is not None and data["revision"] != case.revision:
            raise conflict("当前测试用例已被其他用户修改，请刷新后重试")
        if "name" in data and data["name"] is not None:
            new_name = data["name"].strip()
            if not new_name:
                raise bad_request("测试用例名称不能为空")
            if new_name != case.name:
                _ensure_unique_name(db, case.project_id, new_name, exclude_id=case.id)
                case.name = new_name
        if "priority" in data and data["priority"] is not None and data["priority"] not in TEST_PRIORITIES:
            raise bad_request("优先级取值非法")
        if "case_type" in data and data["case_type"] is not None and data["case_type"] not in TEST_CASE_TYPES:
            raise bad_request("用例类型取值非法")
        if "target_type" in data and data["target_type"] is not None and data["target_type"] not in TEST_TARGET_TYPES:
            raise bad_request("被测对象类型取值非法")
        if "status" in data and data["status"] is not None and data["status"] not in TEST_STATUSES:
            raise bad_request("状态取值非法")
        if "test_point_id" in data and data["test_point_id"] is not None:
            point = db.get(TestPoint, data["test_point_id"])
            if point is None or point.project_id != case.project_id:
                raise not_found("测试点不存在")
        for field in ("description", "priority", "case_type", "target_type", "test_point_id",
                       "api_id", "business_flow_id", "business_action_id", "status", "enabled"):
            if field in data and data[field] is not None:
                setattr(case, field, data[field])
        if "description" in data:
            case.description = data["description"]
        if "enabled" in data:
            case.enabled = data["enabled"]
        case.revision = (case.revision or 0) + 1
        db.flush()
        db.commit()
        db.refresh(case)
        return _response(case)

    def delete_case(self, db: Session, case_id: int, *, actor: User) -> None:
        case = self._get_writable_or_404(db, case_id, actor)
        db.delete(case)
        db.commit()

    # -------------------------------------------------------------- 前置条件

    def list_preconditions(self, db: Session, case_id: int, user: User) -> list[TestCasePreconditionResponse]:
        self._get_or_404(db, case_id, user)
        rows = (
            db.query(TestCasePrecondition).filter(TestCasePrecondition.test_case_id == case_id)
            .order_by(TestCasePrecondition.sort.asc(), TestCasePrecondition.id.asc()).all()
        )
        return [TestCasePreconditionResponse.model_validate(r) for r in rows]

    def create_precondition(
        self, db: Session, case_id: int, body: TestCasePreconditionCreate, *, actor: User,
    ) -> TestCasePreconditionResponse:
        self._get_writable_or_404(db, case_id, actor)
        row = TestCasePrecondition(
            test_case_id=case_id, type=body.type, target=body.target, operator=body.operator,
            expected_value=body.expected_value, description=body.description,
            config_json=body.config_json, sort=body.sort,
        )
        db.add(row)
        db.flush()
        db.commit()
        db.refresh(row)
        return TestCasePreconditionResponse.model_validate(row)

    def update_precondition(
        self, db: Session, precondition_id: int, body: TestCasePreconditionUpdate, *, actor: User,
    ) -> TestCasePreconditionResponse:
        row = self._get_writable_sub_or_404(db, precondition_id, TestCasePrecondition, "前置条件", actor)
        data = body.model_dump(exclude_unset=True)
        for field in ("type", "target", "operator", "expected_value", "description", "config_json", "sort"):
            if field in data and data[field] is not None:
                setattr(row, field, data[field])
        if "expected_value" in data:
            row.expected_value = data["expected_value"]
        db.flush()
        db.commit()
        db.refresh(row)
        return TestCasePreconditionResponse.model_validate(row)

    def delete_precondition(self, db: Session, precondition_id: int, *, actor: User) -> None:
        row = self._get_writable_sub_or_404(db, precondition_id, TestCasePrecondition, "前置条件", actor)
        db.delete(row)
        db.commit()

    # -------------------------------------------------------------- 测试数据

    def list_data(self, db: Session, case_id: int, user: User) -> list[TestCaseDataResponse]:
        self._get_or_404(db, case_id, user)
        rows = (
            db.query(TestCaseData).filter(TestCaseData.test_case_id == case_id)
            .order_by(TestCaseData.sort.asc(), TestCaseData.id.asc()).all()
        )
        return [TestCaseDataResponse.model_validate(r) for r in rows]

    def create_data(
        self, db: Session, case_id: int, body: TestCaseDataCreate, *, actor: User,
    ) -> TestCaseDataResponse:
        self._get_writable_or_404(db, case_id, actor)
        name = (body.name or "").strip()
        if not name:
            raise bad_request("测试数据名称不能为空")
        # 同一用例下数据项名唯一（uq_test_case_data_case_name）；先于 INSERT 校验，
        # 把唯一约束违例转成 409 而非 500。
        if db.query(TestCaseData).filter(
            TestCaseData.test_case_id == case_id, TestCaseData.name == name,
        ).first() is not None:
            raise conflict("测试数据名称已存在")
        row = TestCaseData(
            test_case_id=case_id, name=name, value_type=body.value_type, value=body.value,
            source_type=body.source_type, required=body.required, description=body.description,
            config_json=body.config_json, sort=body.sort,
        )
        self._validate_fixture_data(db, case_id, row)
        db.add(row)
        db.flush()
        db.commit()
        db.refresh(row)
        return TestCaseDataResponse.model_validate(row)

    def update_data(
        self, db: Session, data_id: int, body: TestCaseDataUpdate, *, actor: User,
    ) -> TestCaseDataResponse:
        row = self._get_writable_sub_or_404(db, data_id, TestCaseData, "测试数据", actor)
        data = body.model_dump(exclude_unset=True)
        for field in ("value_type", "value", "source_type", "required", "description", "config_json", "sort"):
            if field in data and data[field] is not None:
                setattr(row, field, data[field])
        if "value" in data:
            row.value = data["value"]
        if "required" in data:
            row.required = data["required"]
        self._validate_fixture_data(db, row.test_case_id, row)
        db.flush()
        db.commit()
        db.refresh(row)
        return TestCaseDataResponse.model_validate(row)

    def delete_data(self, db: Session, data_id: int, *, actor: User) -> None:
        row = self._get_writable_sub_or_404(db, data_id, TestCaseData, "测试数据", actor)
        db.delete(row)
        db.commit()

    # -------------------------------------------------------------- 所需 Fixture

    def list_fixtures(self, db: Session, case_id: int, user: User) -> list[TestCaseFixtureResponse]:
        self._get_or_404(db, case_id, user)
        return self._fixture_rows(db, case_id)

    def replace_fixtures(
        self, db: Session, case_id: int, body: TestCaseFixtureReplace, *, actor: User,
    ) -> list[TestCaseFixtureResponse]:
        """整体替换用例所需 Fixture。用例只声明 fixture_key，运行时值由 Data Factory 注入。

        key 不存在或不可见 → FIXTURE_NOT_FOUND；不是 ACTIVE → FIXTURE_DISABLED。
        任一 key 校验失败整条不保存（与子实体「失败即不落库」的粒度一致）。
        """
        case = self._get_writable_or_404(db, case_id, actor)

        seen: set[str] = set()
        resolved: list[tuple[Fixture, int]] = []
        for item in body.fixtures:
            key = item.fixture_key.strip()
            if key in seen:
                raise conflict(f"所需 Fixture 重复：{key}")
            seen.add(key)
            resolved.append((self._load_visible_fixture(db, case.project_id, key), item.sort))

        for row in db.query(TestCaseFixture).filter(TestCaseFixture.test_case_id == case_id).all():
            db.delete(row)
        db.flush()

        for sort, (fixture, _ignored) in enumerate(resolved):
            db.add(TestCaseFixture(test_case_id=case_id, fixture_id=fixture.id, sort=sort))
        db.commit()
        return self._fixture_rows(db, case_id)

    @staticmethod
    def _fixture_rows(db: Session, case_id: int) -> list[TestCaseFixtureResponse]:
        rows = (
            db.query(TestCaseFixture).filter(TestCaseFixture.test_case_id == case_id)
            .order_by(TestCaseFixture.sort.asc(), TestCaseFixture.id.asc()).all()
        )
        if not rows:
            return []
        fixture_ids = [row.fixture_id for row in rows]
        fixtures = {
            f.id: f for f in db.query(Fixture).filter(Fixture.id.in_(fixture_ids)).all()
        }
        output_names: dict[int, list[str]] = defaultdict(list)
        for fx_id, name in (
            db.query(FixtureOutput.fixture_id, FixtureOutput.name)
            .filter(FixtureOutput.fixture_id.in_(fixture_ids))
            .order_by(FixtureOutput.sort.asc(), FixtureOutput.id.asc())
            .all()
        ):
            output_names[fx_id].append(name)

        result: list[TestCaseFixtureResponse] = []
        for row in rows:
            fixture = fixtures.get(row.fixture_id)
            result.append(TestCaseFixtureResponse(
                id=row.id,
                test_case_id=row.test_case_id,
                fixture_id=row.fixture_id,
                fixture_key=fixture.fixture_key if fixture else "",
                name=fixture.name if fixture else None,
                entity_type=fixture.entity_type if fixture else None,
                scope=fixture.scope if fixture else None,
                status=fixture.status if fixture else None,
                outputs=output_names.get(row.fixture_id, []),
                sort=row.sort,
            ))
        return result

    @staticmethod
    def _load_visible_fixture(db: Session, project_id: int, fixture_key: str) -> Fixture:
        """按 key 加载可见 Fixture：本项目，或 GLOBAL 且 ACTIVE（与 Data Factory 同口径）。"""
        key = (fixture_key or "").strip()
        if not key:
            raise bad_request("fixture_key 不能为空")
        fixture = (
            db.query(Fixture).filter(Fixture.project_id == project_id, Fixture.fixture_key == key).first()
        )
        if fixture is None:
            fixture = (
                db.query(Fixture)
                .filter(Fixture.fixture_key == key, Fixture.scope == "GLOBAL", Fixture.status == "ACTIVE")
                .first()
            )
        if fixture is None:
            raise AppError(f"Fixture {key} 不存在", status_code=404, code=CODE_FIXTURE_NOT_FOUND)
        if fixture.project_id == project_id and fixture.status != "ACTIVE":
            raise AppError(
                f"Fixture {key} 状态为 {fixture.status}，只有 ACTIVE 可被用例引用",
                status_code=400,
                code=CODE_FIXTURE_DISABLED,
            )
        return fixture

    def _validate_fixture_data(self, db: Session, case_id: int, row: TestCaseData) -> None:
        """FIXTURE 数据项：config_json 必须指向已声明的 Fixture 及其输出契约。

        校验通过时服务端写入 ``value = ${fixture.<KEY>.<output>}``，用例上永远不出现
        真实 ID（§12.4）。
        """
        if (row.source_type or "").upper() != "FIXTURE":
            return
        cfg = row.config_json if isinstance(row.config_json, dict) else {}
        key = str(cfg.get("fixture_key") or "").strip()
        output = str(cfg.get("output") or "").strip()
        if not key or not output:
            raise bad_request(f"测试数据 {row.name} 的 FIXTURE 配置需要 fixture_key 与 output")

        declared_ids = [
            fixture_id
            for (fixture_id,) in db.query(TestCaseFixture.fixture_id).filter(
                TestCaseFixture.test_case_id == case_id,
            ).all()
        ]
        if not declared_ids:
            raise bad_request(f"测试数据 {row.name} 引用 Fixture {key}，但该用例未声明所需 Fixture")
        fixture = (
            db.query(Fixture).filter(Fixture.id.in_(declared_ids), Fixture.fixture_key == key).first()
        )
        if fixture is None:
            raise bad_request(f"测试数据 {row.name} 引用的 Fixture {key} 未在该用例声明")
        names = [
            o.name for o in db.query(FixtureOutput).filter(FixtureOutput.fixture_id == fixture.id).all()
        ]
        if output not in names:
            raise bad_request(f"测试数据 {row.name} 引用的输出 {output} 不在 Fixture {key} 的输出契约里")
        row.value = f"${{fixture.{key}.{output}}}"
        row.config_json = {**cfg, "variable": row.name}

    # -------------------------------------------------------------- 步骤

    def list_steps(self, db: Session, case_id: int, user: User) -> list[TestStepResponse]:
        self._get_or_404(db, case_id, user)
        rows = (
            db.query(TestStep).filter(TestStep.test_case_id == case_id)
            .order_by(TestStep.sort.asc(), TestStep.id.asc()).all()
        )
        return [TestStepResponse.model_validate(r) for r in rows]

    def create_step(
        self, db: Session, case_id: int, body: TestStepCreate, *, actor: User,
    ) -> TestStepResponse:
        self._get_writable_or_404(db, case_id, actor)
        row = TestStep(
            test_case_id=case_id, name=body.name, step_type=body.step_type,
            target_type=body.target_type, target_id=body.target_id,
            sort=body.sort, config_json=body.config_json,
        )
        db.add(row)
        db.flush()
        db.commit()
        db.refresh(row)
        return TestStepResponse.model_validate(row)

    def update_step(
        self, db: Session, step_id: int, body: TestStepUpdate, *, actor: User,
    ) -> TestStepResponse:
        row = self._get_writable_sub_or_404(db, step_id, TestStep, "测试步骤", actor)
        data = body.model_dump(exclude_unset=True)
        for field in ("name", "step_type", "target_type", "target_id", "sort", "config_json"):
            if field in data and data[field] is not None:
                setattr(row, field, data[field])
        db.flush()
        db.commit()
        db.refresh(row)
        return TestStepResponse.model_validate(row)

    def delete_step(self, db: Session, step_id: int, *, actor: User) -> None:
        row = self._get_writable_sub_or_404(db, step_id, TestStep, "测试步骤", actor)
        db.delete(row)
        db.commit()

    # -------------------------------------------------------------- 断言

    def list_assertions(self, db: Session, case_id: int, user: User) -> list[TestAssertionResponse]:
        self._get_or_404(db, case_id, user)
        rows = (
            db.query(TestAssertion).filter(TestAssertion.test_case_id == case_id)
            .order_by(TestAssertion.sort.asc(), TestAssertion.id.asc()).all()
        )
        return [TestAssertionResponse.model_validate(r) for r in rows]

    def create_assertion(
        self, db: Session, case_id: int, body: TestAssertionCreate, *, actor: User,
    ) -> TestAssertionResponse:
        self._get_writable_or_404(db, case_id, actor)
        if body.step_id is not None:
            step = db.get(TestStep, body.step_id)
            if step is None or step.test_case_id != case_id:
                raise not_found("测试步骤不存在")
        row = TestAssertion(
            test_case_id=case_id, step_id=body.step_id, assertion_type=body.assertion_type,
            source=body.source, path=body.path, operator=body.operator,
            expected_value=body.expected_value, required=body.required, sort=body.sort,
        )
        db.add(row)
        db.flush()
        db.commit()
        db.refresh(row)
        return TestAssertionResponse.model_validate(row)

    def update_assertion(
        self, db: Session, assertion_id: int, body: TestAssertionUpdate, *, actor: User,
    ) -> TestAssertionResponse:
        row = self._get_writable_sub_or_404(db, assertion_id, TestAssertion, "断言", actor)
        data = body.model_dump(exclude_unset=True)
        if "step_id" in data and data["step_id"] is not None:
            step = db.get(TestStep, data["step_id"])
            if step is None or step.test_case_id != row.test_case_id:
                raise not_found("测试步骤不存在")
        for field in ("assertion_type", "source", "path", "operator", "expected_value",
                       "required", "step_id", "sort"):
            if field in data and data[field] is not None:
                setattr(row, field, data[field])
        if "expected_value" in data:
            row.expected_value = data["expected_value"]
        if "required" in data:
            row.required = data["required"]
        db.flush()
        db.commit()
        db.refresh(row)
        return TestAssertionResponse.model_validate(row)

    def delete_assertion(self, db: Session, assertion_id: int, *, actor: User) -> None:
        row = self._get_writable_sub_or_404(db, assertion_id, TestAssertion, "断言", actor)
        db.delete(row)
        db.commit()

    # -------------------------------------------------------------- 取实体

    def _get_or_404(self, db: Session, case_id: int, user: User) -> TestCase:
        c = db.get(TestCase, case_id)
        if c is None:
            raise not_found("测试用例不存在")
        get_project_or_404(db, c.project_id, user)
        return c

    def _get_writable_or_404(self, db: Session, case_id: int, actor: User) -> TestCase:
        c = db.get(TestCase, case_id)
        if c is None:
            raise not_found("测试用例不存在")
        require_writable_project(db, resolve_case_project_id(db, case_id), actor)
        return c

    def _get_writable_sub_or_404(
        self, db: Session, sub_id: int, model_cls, label: str, actor: User,
    ):
        """取子实体并校验所属用例可写。子实体不存在 → 404。"""
        row = db.get(model_cls, sub_id)
        if row is None:
            raise not_found(f"{label}不存在")
        require_writable_project(db, resolve_case_project_id(db, row.test_case_id), actor)
        return row
