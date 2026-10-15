"""Mock Management 管理面路由（§三十四，需平台 JWT）。

单 APIRouter（无自身前缀），挂在 /api/v1 下。资源级路径：
- /projects/{project_id}/(mock-services|mock-executions|mock-contexts|mock-from-api/{api_id})
- /mock-services/{id}(/endpoints|/reset-token)
- /mock-endpoints/{id}(/scenarios)
- /mock-scenarios/{id}(/matchers|/set-default|/duplicate|/test)
- /mock-contexts/{context_id}(/close)
- /mock-executions/{id}
- /test-cases/{id}/mocks

权限：读 viewer+、写 member+；MockService 创建/删除/重置 Token 需 editor+。
执行面（runtime_router.py）不在此处，单独挂载且不要求 JWT（§十四）。
端点统一 sync def；service owns commit。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.mock_management.schemas import (
    CreateMockFromApiRequest,
    CreateMockFromApiResponse,
    MockContextResponse,
    MockEndpointCreate,
    MockEndpointListResponse,
    MockEndpointResponse,
    MockEndpointUpdate,
    MockExecutionListResponse,
    MockExecutionResponse,
    MockMatchersReplace,
    MockScenarioCreate,
    MockScenarioListResponse,
    MockScenarioResponse,
    MockScenarioUpdate,
    MockServiceCreate,
    MockServiceCreateResponse,
    MockServiceListResponse,
    MockServiceResponse,
    MockServiceUpdate,
    ScenarioTestRequest,
    ScenarioTestResponse,
    TestCaseMockResponse,
    TestCaseMocksReplace,
)
from app.features.mock_management.services.api_mock_integration_service import (
    ApiMockIntegrationService,
)
from app.features.mock_management.services.mock_context_service import (
    MockContextService,
)
from app.features.mock_management.services.mock_endpoint_service import (
    MockEndpointService,
)
from app.features.mock_management.services.mock_execution_query_service import (
    MockExecutionQueryService,
)
from app.features.mock_management.services.mock_scenario_service import (
    MockScenarioService,
)
from app.features.mock_management.services.mock_service_service import (
    MockServiceService,
)
from app.features.mock_management.services.test_case_mock_service import (
    TestCaseMockService,
)
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["Mock 管理"])

# 服务无状态，路由层复用单例。
_SERVICE = MockServiceService()
_ENDPOINT = MockEndpointService()
_SCENARIO = MockScenarioService()
_EXECUTION = MockExecutionQueryService()
_CONTEXT = MockContextService()
_INTEGRATION = ApiMockIntegrationService()
_CASE_MOCK = TestCaseMockService()


# --------------------------------------------------------------------------- MockService


@router.get("/projects/{project_id}/mock-services", response_model=MockServiceListResponse)
def list_mock_services(
    project_id: int,
    keyword: str | None = Query(None),
    enabled: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockServiceListResponse:
    return _SERVICE.list_services(
        db, project_id, user, keyword=keyword, enabled=enabled, page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/mock-services",
    response_model=MockServiceCreateResponse, status_code=201,
)
def create_mock_service(
    project_id: int,
    body: MockServiceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockServiceCreateResponse:
    return _SERVICE.create_service(db, project_id, body, actor=user)


@router.get("/mock-services/{service_id}", response_model=MockServiceResponse)
def get_mock_service(
    service_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockServiceResponse:
    return _SERVICE.get_service(db, service_id, user)


@router.patch("/mock-services/{service_id}", response_model=MockServiceResponse)
def update_mock_service(
    service_id: int,
    body: MockServiceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockServiceResponse:
    return _SERVICE.update_service(db, service_id, body, actor=user)


@router.delete("/mock-services/{service_id}", status_code=204)
def delete_mock_service(
    service_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _SERVICE.delete_service(db, service_id, actor=user)


@router.post("/mock-services/{service_id}/reset-token", response_model=MockServiceCreateResponse)
def reset_mock_token(
    service_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockServiceCreateResponse:
    """重置 Runtime Token：旧 token 立即失效，新明文只返回一次（§五十）。"""
    return _SERVICE.reset_token(db, service_id, actor=user)


# --------------------------------------------------------------------------- MockEndpoint


@router.get(
    "/mock-services/{service_id}/endpoints", response_model=MockEndpointListResponse,
)
def list_mock_endpoints(
    service_id: int,
    keyword: str | None = Query(None),
    enabled: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockEndpointListResponse:
    return _ENDPOINT.list_endpoints(
        db, service_id, user, keyword=keyword, enabled=enabled, page=page, page_size=page_size,
    )


@router.post(
    "/mock-services/{service_id}/endpoints",
    response_model=MockEndpointResponse, status_code=201,
)
def create_mock_endpoint(
    service_id: int,
    body: MockEndpointCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockEndpointResponse:
    return _ENDPOINT.create_endpoint(db, service_id, body, actor=user)


@router.get("/mock-endpoints/{endpoint_id}", response_model=MockEndpointResponse)
def get_mock_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockEndpointResponse:
    return _ENDPOINT.get_endpoint(db, endpoint_id, user)


@router.patch("/mock-endpoints/{endpoint_id}", response_model=MockEndpointResponse)
def update_mock_endpoint(
    endpoint_id: int,
    body: MockEndpointUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockEndpointResponse:
    return _ENDPOINT.update_endpoint(db, endpoint_id, body, actor=user)


@router.delete("/mock-endpoints/{endpoint_id}", status_code=204)
def delete_mock_endpoint(
    endpoint_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _ENDPOINT.delete_endpoint(db, endpoint_id, actor=user)


# --------------------------------------------------------------------------- MockScenario


@router.get(
    "/mock-endpoints/{endpoint_id}/scenarios", response_model=MockScenarioListResponse,
)
def list_mock_scenarios(
    endpoint_id: int,
    keyword: str | None = Query(None),
    enabled: bool | None = Query(None),
    is_default: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockScenarioListResponse:
    return _SCENARIO.list_scenarios(
        db, endpoint_id, user, keyword=keyword, enabled=enabled,
        is_default=is_default, page=page, page_size=page_size,
    )


@router.post(
    "/mock-endpoints/{endpoint_id}/scenarios",
    response_model=MockScenarioResponse, status_code=201,
)
def create_mock_scenario(
    endpoint_id: int,
    body: MockScenarioCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockScenarioResponse:
    return _SCENARIO.create_scenario(db, endpoint_id, body, actor=user)


@router.get("/mock-scenarios/{scenario_id}", response_model=MockScenarioResponse)
def get_mock_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockScenarioResponse:
    return _SCENARIO.get_scenario(db, scenario_id, user)


@router.patch("/mock-scenarios/{scenario_id}", response_model=MockScenarioResponse)
def update_mock_scenario(
    scenario_id: int,
    body: MockScenarioUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockScenarioResponse:
    return _SCENARIO.update_scenario(db, scenario_id, body, actor=user)


@router.delete("/mock-scenarios/{scenario_id}", status_code=204)
def delete_mock_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _SCENARIO.delete_scenario(db, scenario_id, actor=user)


@router.put("/mock-scenarios/{scenario_id}/matchers", response_model=MockScenarioResponse)
def replace_mock_matchers(
    scenario_id: int,
    body: MockMatchersReplace,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockScenarioResponse:
    return _SCENARIO.replace_matchers(db, scenario_id, body, actor=user)


@router.post("/mock-scenarios/{scenario_id}/set-default", response_model=MockScenarioResponse)
def set_default_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockScenarioResponse:
    return _SCENARIO.set_default(db, scenario_id, actor=user)


@router.post("/mock-scenarios/{scenario_id}/duplicate", response_model=MockScenarioResponse)
def duplicate_scenario(
    scenario_id: int,
    new_key: str = Query(..., description="新 scenario_key，须同接口唯一"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockScenarioResponse:
    return _SCENARIO.duplicate(db, scenario_id, new_key, actor=user)


@router.post("/mock-scenarios/{scenario_id}/test", response_model=ScenarioTestResponse)
def test_scenario(
    scenario_id: int,
    body: ScenarioTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScenarioTestResponse:
    """模拟一个请求，试跑 Matcher + Response Builder，不调用被测系统（§三十三）。"""
    return _SCENARIO.test_scenario(db, scenario_id, body, user)


# --------------------------------------------------------------------------- 调用记录 + 作用域


@router.get(
    "/projects/{project_id}/mock-executions", response_model=MockExecutionListResponse,
)
def list_mock_executions(
    project_id: int,
    test_run_id: int | None = Query(None),
    case_execution_id: int | None = Query(None),
    service_id: int | None = Query(None),
    matched: bool | None = Query(None),
    context_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockExecutionListResponse:
    return _EXECUTION.list_executions(
        db, project_id, user, test_run_id=test_run_id, case_execution_id=case_execution_id,
        service_id=service_id, matched=matched, context_id=context_id,
        page=page, page_size=page_size,
    )


@router.get("/mock-executions/{execution_id}", response_model=MockExecutionResponse)
def get_mock_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockExecutionResponse:
    return _EXECUTION.get_execution(db, execution_id, user)


@router.get(
    "/projects/{project_id}/mock-contexts", response_model=list[MockContextResponse],
)
def list_mock_contexts(
    project_id: int,
    status: str | None = Query(None),
    test_run_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MockContextResponse]:
    return _CONTEXT.list_contexts(
        db, project_id, user, status=status, test_run_id=test_run_id,
        page=page, page_size=page_size,
    )


@router.get("/mock-contexts/{context_id}", response_model=MockContextResponse)
def get_mock_context(
    context_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockContextResponse:
    return _CONTEXT.get_context(db, context_id, user)


@router.post("/mock-contexts/{context_id}/close", response_model=MockContextResponse)
def close_mock_context(
    context_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MockContextResponse:
    return _CONTEXT.close_context(db, context_id, actor=user)


# --------------------------------------------------------------------------- API 一键创建 + 用例 Mock 声明


@router.post(
    "/projects/{project_id}/mock-from-api/{api_id}",
    response_model=CreateMockFromApiResponse, status_code=201,
)
def create_mock_from_api(
    project_id: int,
    api_id: int,
    body: CreateMockFromApiRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CreateMockFromApiResponse:
    """从 API Catalog 一键创建 Mock Service + Endpoint + 推荐场景（§二十 / §二十一）。"""
    return _INTEGRATION.create_from_api(db, project_id, api_id, body, actor=user)


@router.get(
    "/test-cases/{test_case_id}/mocks", response_model=list[TestCaseMockResponse],
)
def list_case_mocks(
    test_case_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TestCaseMockResponse]:
    return _CASE_MOCK.list_case_mocks(db, test_case_id, user)


@router.put(
    "/test-cases/{test_case_id}/mocks", response_model=list[TestCaseMockResponse],
)
def replace_case_mocks(
    test_case_id: int,
    body: TestCaseMocksReplace,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TestCaseMockResponse]:
    """整体替换用例的 required_mocks（重建）。"""
    return _CASE_MOCK.replace_case_mocks(db, test_case_id, body, actor=user)
