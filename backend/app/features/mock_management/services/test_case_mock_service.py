"""TestCaseMock 服务层：用例声明的 required_mocks（§二十二）。

整体替换语义（与 Fixture steps / Scenario matchers 一致）：
``PUT /test-cases/{id}/mocks`` 重建整张声明表。校验 service / endpoint / scenario
存在且同属一个项目（与用例项目一致），跨项目引用 404。

唯一约束：一个用例对一个 scenario 只声明一次（uq_test_case_mock_case_scenario）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.mock_management.models import (
    MockEndpoint,
    MockScenario,
    MockService,
    TestCaseMock,
)
from app.features.mock_management.schemas import (
    TestCaseMockCreate,
    TestCaseMockResponse,
    TestCaseMocksReplace,
)
from app.features.mock_management.services._response import case_mock_response
from app.features.test_management.models.test_case import TestCase
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found


class TestCaseMockService:
    """用例 Mock 声明 CRUD。无状态，路由层复用单例。"""

    def list_case_mocks(
        self, db: Session, test_case_id: int, user: User,
    ) -> list[TestCaseMockResponse]:
        """列出用例`mocks`。"""
        case = self._get_case_or_404(db, test_case_id, user)
        rows = (
            db.query(TestCaseMock)
            .filter(TestCaseMock.test_case_id == case.id)
            .order_by(TestCaseMock.sort.asc(), TestCaseMock.id.asc())
            .all()
        )
        return [case_mock_response(db, r) for r in rows]

    def replace_case_mocks(
        self, db: Session, test_case_id: int, body: TestCaseMocksReplace, *, actor: User,
    ) -> list[TestCaseMockResponse]:
        """替换用例`mocks`。"""
        case = self._get_case_writable(db, test_case_id, actor)

        # 先校验全部声明合法（service/endpoint/scenario 同项目 + 归属一致 + 唯一 scenario）。
        seen_scenarios: set[int] = set()
        validated: list[tuple[TestCaseMockCreate, int]] = []  # 已校验映射项及其所属项目标识：（m, project_id）。
        for m in body.mocks:
            service = db.get(MockService, m.mock_service_id)
            if service is None or service.project_id != case.project_id:
                raise not_found(f"Mock 服务 {m.mock_service_id} 不存在或不属于本项目")
            endpoint = db.get(MockEndpoint, m.mock_endpoint_id)
            if endpoint is None or endpoint.project_id != case.project_id:
                raise not_found(f"Mock 接口 {m.mock_endpoint_id} 不存在或不属于本项目")
            if endpoint.mock_service_id != service.id:
                raise bad_request(f"Mock 接口 {endpoint.id} 不属于服务 {service.service_key}")
            scenario = db.get(MockScenario, m.mock_scenario_id)
            if scenario is None or scenario.project_id != case.project_id:
                raise not_found(f"Mock 场景 {m.mock_scenario_id} 不存在或不属于本项目")
            if scenario.mock_endpoint_id != endpoint.id:
                raise bad_request(f"Mock 场景 {scenario.id} 不属于接口 {endpoint.id}")
            if m.scope not in ("SETUP", "EXECUTION", "BOTH"):
                raise bad_request(f"scope 取值非法：{m.scope}")
            if scenario.id in seen_scenarios:
                raise conflict("同一场景不能在一个用例里声明两次")
            seen_scenarios.add(scenario.id)
            validated.append((m, case.project_id))

        # 重建。
        db.query(TestCaseMock).filter(TestCaseMock.test_case_id == case.id).delete(
            synchronize_session=False
        )
        db.flush()
        for m, project_id in validated:
            db.add(TestCaseMock(
                test_case_id=case.id,
                mock_service_id=m.mock_service_id,
                mock_endpoint_id=m.mock_endpoint_id,
                mock_scenario_id=m.mock_scenario_id,
                scope=m.scope,
                sort=m.sort,
            ))
        db.commit()
        rows = (
            db.query(TestCaseMock)
            .filter(TestCaseMock.test_case_id == case.id)
            .order_by(TestCaseMock.sort.asc(), TestCaseMock.id.asc())
            .all()
        )
        return [case_mock_response(db, r) for r in rows]

    # ---------------------------------------------------------------- 内部

    def _get_case_or_404(self, db: Session, test_case_id: int, user: User) -> TestCase:
        """获取用例或。"""
        from app.features.test_management.services._access import get_project_or_404

        case = db.get(TestCase, test_case_id)
        if case is None:
            raise not_found("测试用例不存在")
        get_project_or_404(db, case.project_id, user)
        return case

    def _get_case_writable(self, db: Session, test_case_id: int, actor: User) -> TestCase:
        """获取用例可写。"""
        from app.features.test_management.services._access import (
            require_writable_project,
            resolve_case_project_id,
        )

        case = db.get(TestCase, test_case_id)
        if case is None:
            raise not_found("测试用例不存在")
        require_writable_project(db, resolve_case_project_id(db, test_case_id), actor)
        return case


__all__ = ["TestCaseMockService"]
