"""Mock Management 响应装配：派生字段与 join 冗余展示。

集中放置跨 service 共用的响应构造，避免 N+1：
- ``service_response``：MockServiceResponse（派生 runtime_token_set / runtime_url /
  endpoint_count / scenario_count，不直接 from_attributes，§五十 不回显 token_hash）。
- ``endpoint_response``：补 scenario_count。
- ``scenario_response``：补 matchers + call_count。
- ``execution_response``：join service_key / endpoint_path / scenario_key 等冗余展示。
- ``case_mock_response``：join service / endpoint / scenario 展示字段。

所有计数 / join 都走批量查询（in_ + 一次扫描），列表与详情复用同一份装配。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.mock_management.models import (
    MockEndpoint,
    MockExecution,
    MockMatcher,
    MockScenario,
    MockService,
    TestCaseMock,
)
from app.features.mock_management.schemas import (
    MockEndpointResponse,
    MockExecutionResponse,
    MockMatcherResponse,
    MockScenarioResponse,
    MockServiceResponse,
    TestCaseMockResponse,
)

# Runtime URL 前缀：执行面路由挂在 /api/v1/mock 下（§十六）。
RUNTIME_URL_PREFIX = "/api/v1/mock"


def service_response(db: Session, service: MockService) -> MockServiceResponse:
    """构造 MockServiceResponse（含派生字段，不回显 token_hash，§五十）。"""
    endpoint_count = int(
        db.query(MockEndpoint.id)
        .filter(MockEndpoint.mock_service_id == service.id)
        .count()
    )
    scenario_count = int(
        db.query(MockScenario.id)
        .join(MockEndpoint, MockEndpoint.id == MockScenario.mock_endpoint_id)
        .filter(MockEndpoint.mock_service_id == service.id)
        .count()
    )
    return MockServiceResponse(
        id=service.id,
        project_id=service.project_id,
        name=service.name,
        description=service.description,
        service_key=service.service_key,
        base_path=service.base_path,
        enabled=service.enabled,
        default_scenario_id=service.default_scenario_id,
        public_runtime=service.public_runtime,
        runtime_token_set=bool(service.runtime_token_hash),
        created_by=service.created_by,
        created_at=service.created_at,
        updated_at=service.updated_at,
        revision=service.revision,
        runtime_url=f"{RUNTIME_URL_PREFIX}/{service.project_id}/{service.service_key}",
        endpoint_count=endpoint_count,
        scenario_count=scenario_count,
    )


def endpoint_response(db: Session, endpoint: MockEndpoint) -> MockEndpointResponse:
    """构造 MockEndpointResponse（补 scenario_count）。"""
    scenario_count = int(
        db.query(MockScenario.id)
        .filter(MockScenario.mock_endpoint_id == endpoint.id)
        .count()
    )
    resp = MockEndpointResponse.model_validate(endpoint)
    resp.scenario_count = scenario_count
    return resp


def _matchers_for(db: Session, scenario_ids: list[int]) -> dict[int, list[MockMatcher]]:
    """批量取多个 Scenario 的 Matcher（priority ASC, id ASC）。"""
    out: dict[int, list[MockMatcher]] = {}
    if not scenario_ids:
        return out
    rows = (
        db.query(MockMatcher)
        .filter(MockMatcher.scenario_id.in_(scenario_ids))
        .order_by(MockMatcher.priority.asc(), MockMatcher.id.asc())
        .all()
    )
    for m in rows:
        out.setdefault(m.scenario_id, []).append(m)
    return out


def _call_counts(db: Session, scenario_ids: list[int]) -> dict[int, int]:
    """批量取 Scenario 的命中调用次数（matched=true）。"""
    if not scenario_ids:
        return {}
    counts: dict[int, int] = {sid: 0 for sid in scenario_ids}
    for sid, cnt in (
        db.query(MockExecution.mock_scenario_id, MockExecution.id)
        .filter(
            MockExecution.mock_scenario_id.in_(scenario_ids),
            MockExecution.matched.is_(True),
        )
        .all()
    ):
        # 上面 select 的是 (scenario_id, execution_id)，按行计数即可。
        counts[sid] = counts.get(sid, 0) + 1
    return counts


def scenario_response(db: Session, scenario: MockScenario) -> MockScenarioResponse:
    """构造 MockScenarioResponse（补 matchers + call_count）。"""
    matchers = _matchers_for(db, [scenario.id]).get(scenario.id, [])
    call_count = _call_counts(db, [scenario.id]).get(scenario.id, 0)
    resp = MockScenarioResponse.model_validate(scenario)
    resp.matchers = [MockMatcherResponse.model_validate(m) for m in matchers]
    resp.call_count = call_count
    return resp


def scenarios_response(db: Session, scenarios: list[MockScenario]) -> list[MockScenarioResponse]:
    """批量构造 MockScenarioResponse（matchers + call_count 一次扫描，避免 N+1）。"""
    ids = [s.id for s in scenarios]
    matchers_by = _matchers_for(db, ids)
    calls_by = _call_counts(db, ids)
    out: list[MockScenarioResponse] = []
    for s in scenarios:
        resp = MockScenarioResponse.model_validate(s)
        resp.matchers = [MockMatcherResponse.model_validate(m) for m in matchers_by.get(s.id, [])]
        resp.call_count = calls_by.get(s.id, 0)
        out.append(resp)
    return out


def execution_response(db: Session, execution: MockExecution) -> MockExecutionResponse:
    """构造 MockExecutionResponse（join 冗余展示字段）。"""
    resp = MockExecutionResponse.model_validate(execution)
    if execution.mock_service_id is not None:
        svc = db.get(MockService, execution.mock_service_id)
        if svc is not None:
            resp.service_key = svc.service_key
            resp.service_name = svc.name
    if execution.mock_endpoint_id is not None:
        ep = db.get(MockEndpoint, execution.mock_endpoint_id)
        if ep is not None:
            resp.endpoint_path = ep.path
    if execution.mock_scenario_id is not None:
        sc = db.get(MockScenario, execution.mock_scenario_id)
        if sc is not None:
            resp.scenario_key = sc.scenario_key
    return resp


def case_mock_response(db: Session, tcm: TestCaseMock) -> TestCaseMockResponse:
    """构造 TestCaseMockResponse（join service / endpoint / scenario 展示字段）。"""
    resp = TestCaseMockResponse.model_validate(tcm)
    svc = db.get(MockService, tcm.mock_service_id)
    if svc is not None:
        resp.service_key = svc.service_key
        resp.service_name = svc.name
    ep = db.get(MockEndpoint, tcm.mock_endpoint_id)
    if ep is not None:
        resp.endpoint_path = ep.path
        resp.endpoint_method = ep.method
    sc = db.get(MockScenario, tcm.mock_scenario_id)
    if sc is not None:
        resp.scenario_key = sc.scenario_key
        resp.scenario_name = sc.name
    return resp


__all__ = [
    "RUNTIME_URL_PREFIX",
    "case_mock_response",
    "endpoint_response",
    "execution_response",
    "scenario_response",
    "scenarios_response",
    "service_response",
]
