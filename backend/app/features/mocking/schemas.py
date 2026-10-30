"""Mock Management 契约定义（Pydantic v2）。

只放请求 / 响应模型与字面量；service 与 router 共用本文件作为两层接口契约。
枚举在数据库层是 String，合法取值由 Literal + 服务层校验决定（与 test_data 一致）。

安全约定（§五十）：
- MockService 响应只暴露 ``runtime_token_set``（布尔），绝不回显 token_hash。
- 明文 token 仅在创建 / 重置时一次性返回（``runtime_token`` 字段）。
- 快照在进入响应模型前已由 SensitiveDataMasker 脱敏。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SERVICE_KEY_PATTERN = r"^[A-Z][A-Z0-9_]{0,99}$"
SCENARIO_KEY_PATTERN = r"^[A-Z][A-Z0-9_]{0,99}$"

# --------------------------------------------------------------------------- 枚举字面量

MOCK_BEHAVIOR_TYPES = ("STATIC_RESPONSE", "DELAY_RESPONSE", "TIMEOUT", "EMPTY_RESPONSE")
MockBehaviorType = Literal["STATIC_RESPONSE", "DELAY_RESPONSE", "TIMEOUT", "EMPTY_RESPONSE"]

MOCK_MATCHER_SOURCES = ("METHOD", "PATH", "QUERY", "HEADER", "BODY")
MockMatcherSource = Literal["METHOD", "PATH", "QUERY", "HEADER", "BODY"]

MOCK_MATCHER_OPERATORS = (
    "EQ", "NE", "EXISTS", "NOT_EXISTS", "CONTAINS", "IN",
    "JSON_PATH_EQ", "JSON_PATH_EXISTS",
)
MockMatcherOperator = Literal[
    "EQ", "NE", "EXISTS", "NOT_EXISTS", "CONTAINS", "IN",
    "JSON_PATH_EQ", "JSON_PATH_EXISTS",
]

MOCK_CONTEXT_STATUSES = ("ACTIVE", "CLOSED", "EXPIRED")
MockContextStatus = Literal["ACTIVE", "CLOSED", "EXPIRED"]

MOCK_SCOPES = ("SETUP", "EXECUTION", "BOTH")
MockScope = Literal["SETUP", "EXECUTION", "BOTH"]

# API Catalog 推荐场景模板（§二十一）：前端快速创建，最终仍落成 MockScenario。
API_MOCK_TEMPLATES = (
    "NORMAL", "BAD_REQUEST_400", "UNAUTHORIZED_401", "FORBIDDEN_403",
    "NOT_FOUND_404", "SERVER_ERROR_500", "EMPTY_DATA", "DELAY", "TIMEOUT",
)


class _ORM(BaseModel):
    """从 ORM 实体构造响应的基类。"""

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 模拟服务 MockService


class MockServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    service_key: str = Field(..., pattern=SERVICE_KEY_PATTERN)
    base_path: str | None = Field(None, max_length=500)
    enabled: bool = True
    public_runtime: bool = False
    # 创建时可选传明文 token；不传则自动生成。明文只在响应里返回一次。
    runtime_token: str | None = Field(None, min_length=8, max_length=200)


class MockServiceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    base_path: str | None = Field(None, max_length=500)
    enabled: bool | None = None
    public_runtime: bool | None = None
    default_scenario_id: int | None = None
    revision: int = Field(..., description="乐观锁版本号，不匹配返回 409")


class MockServiceResponse(BaseModel):
    """MockService 响应。由 service 显式构造（含派生字段，不直接 from_attributes）。"""

    id: int
    project_id: int
    name: str
    description: str | None
    service_key: str
    base_path: str | None
    enabled: bool
    default_scenario_id: int | None
    public_runtime: bool
    runtime_token_set: bool
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    revision: int
    # 运行时 URL（§十六）与计数：service 填充。
    runtime_url: str | None = None
    endpoint_count: int = 0
    scenario_count: int = 0


class MockServiceCreateResponse(BaseModel):
    """创建 / 重置 token 的响应：明文 token 只在这里返回一次（§五十）。"""

    service: MockServiceResponse
    runtime_token: str


class MockServiceListResponse(BaseModel):
    items: list[MockServiceResponse]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- 模拟接口 MockEndpoint


class MockEndpointCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    method: str = Field(..., min_length=1, max_length=10)
    path: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=1000)
    api_id: int | None = None
    enabled: bool = True


class MockEndpointUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    method: str | None = Field(None, min_length=1, max_length=10)
    path: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(None, max_length=1000)
    enabled: bool | None = None
    revision: int = Field(..., description="乐观锁版本号")


class MockEndpointResponse(_ORM):
    id: int
    project_id: int
    mock_service_id: int
    api_id: int | None
    name: str
    method: str
    path: str
    description: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    revision: int
    scenario_count: int = 0


class MockEndpointListResponse(BaseModel):
    items: list[MockEndpointResponse]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- 模拟场景 MockScenario


class MockScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    scenario_key: str = Field(..., pattern=SCENARIO_KEY_PATTERN)
    description: str | None = Field(None, max_length=1000)
    enabled: bool = True
    is_default: bool = False
    priority: int = 0
    behavior_type: MockBehaviorType = "STATIC_RESPONSE"
    delay_ms: int | None = Field(None, ge=0, le=60000)
    status_code: int = Field(200, ge=100, le=599)
    response_headers: dict[str, str] | None = None
    response_body: Any = None
    response_template: Any = None
    matchers: list["MockMatcherCreate"] = Field(default_factory=list)


class MockScenarioUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    enabled: bool | None = None
    is_default: bool | None = None
    priority: int | None = Field(None, ge=0)
    behavior_type: MockBehaviorType | None = None
    delay_ms: int | None = Field(None, ge=0, le=60000)
    status_code: int | None = Field(None, ge=100, le=599)
    response_headers: dict[str, str] | None = None
    response_body: Any = None
    response_template: Any = None
    revision: int = Field(..., description="乐观锁版本号")


class MockScenarioResponse(_ORM):
    id: int
    project_id: int
    mock_endpoint_id: int
    name: str
    scenario_key: str
    description: str | None
    enabled: bool
    is_default: bool
    priority: int
    behavior_type: str
    delay_ms: int | None
    status_code: int
    response_headers: dict[str, str] | None
    response_body: Any
    response_template: Any
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    revision: int
    matchers: list["MockMatcherResponse"] = Field(default_factory=list)
    call_count: int = 0


class MockScenarioListResponse(BaseModel):
    items: list[MockScenarioResponse]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- 模拟匹配规则 MockMatcher


class MockMatcherCreate(BaseModel):
    source: MockMatcherSource
    field: str = Field(..., min_length=1, max_length=200)
    operator: MockMatcherOperator
    expected_value: Any = None
    priority: int = 0
    enabled: bool = True


class MockMatcherResponse(_ORM):
    id: int
    scenario_id: int
    source: str
    field: str
    operator: str
    expected_value: Any
    priority: int
    enabled: bool
    created_at: datetime


class MockMatchersReplace(BaseModel):
    """整体替换一个 Scenario 的 Matcher 列表（重建，与 Fixture steps 同款语义）。

    ``revision`` 可选：传入时做乐观锁校验，与 PATCH 场景一致。matcher 是重建式
    写入，不加校验的话两个会话会互相覆盖、最后写入者静默吃掉对方的规则集。
    """

    matchers: list[MockMatcherCreate] = Field(default_factory=list)
    revision: int | None = None


# --------------------------------------------------------------------------- 模拟执行记录 MockExecution


class MockExecutionResponse(_ORM):
    id: int
    project_id: int
    mock_service_id: int | None
    mock_endpoint_id: int | None
    mock_scenario_id: int | None
    request_id: str | None
    method: str
    path: str
    query_snapshot: Any
    header_snapshot: Any
    body_snapshot: Any
    response_status: int | None
    response_header_snapshot: Any
    response_body_snapshot: Any
    matched: bool
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    test_run_id: int | None
    case_execution_id: int | None
    mock_context_id: str | None
    created_at: datetime
    # 冗余展示字段（service join 填充）。
    service_key: str | None = None
    service_name: str | None = None
    endpoint_path: str | None = None
    scenario_key: str | None = None


class MockExecutionListResponse(BaseModel):
    items: list[MockExecutionResponse]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- Scenario test（§三十三）


class ScenarioTestRequest(BaseModel):
    """模拟一个请求，测试 Matcher + Response Builder，不真实调用被测系统。"""

    method: str = "GET"
    path: str = "/"
    query: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None


class ScenarioTestResponse(BaseModel):
    matched: bool
    scenario_id: int | None = None
    scenario_key: str | None = None
    status_code: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    duration_ms: int
    delay_ms: int = 0


# --------------------------------------------------------------------------- 模拟上下文 MockContext


class MockContextResponse(_ORM):
    id: int
    context_id: str
    project_id: int
    test_run_id: int | None
    case_execution_id: int | None
    scenario_overrides: Any
    status: str
    expires_at: datetime
    created_at: datetime
    closed_at: datetime | None


# --------------------------------------------------------------------------- TestCase Mock（§二十二）


class TestCaseMockCreate(BaseModel):
    mock_service_id: int
    mock_endpoint_id: int
    mock_scenario_id: int
    scope: MockScope = "EXECUTION"
    sort: int = 0


class TestCaseMockResponse(_ORM):
    id: int
    test_case_id: int
    mock_service_id: int
    mock_endpoint_id: int
    mock_scenario_id: int
    scope: str
    sort: int
    created_at: datetime
    # 冗余展示字段（service join 填充）。
    service_key: str | None = None
    service_name: str | None = None
    endpoint_path: str | None = None
    endpoint_method: str | None = None
    scenario_key: str | None = None
    scenario_name: str | None = None


class TestCaseMocksReplace(BaseModel):
    """整体替换用例的 required_mocks（重建）。"""

    mocks: list[TestCaseMockCreate] = Field(default_factory=list)


# --------------------------------------------------------------------------- API 接口 Catalog 创建 Mock（§二十）


class CreateMockFromApiRequest(BaseModel):
    """从 API Catalog 创建 Mock Service + Endpoint + 推荐场景（§二十 / §二十一）。"""

    service_key: str = Field(..., pattern=SERVICE_KEY_PATTERN)
    service_name: str | None = Field(None, max_length=200)
    endpoint_name: str | None = None
    templates: list[str] = Field(
        default_factory=lambda: ["NORMAL"],
        description="推荐场景模板，见 API_MOCK_TEMPLATES",
    )
    public_runtime: bool = False
    runtime_token: str | None = Field(None, min_length=8, max_length=200)


class CreateMockFromApiResponse(BaseModel):
    """从 API 创建 Mock 的结果：service + endpoint + 创建的场景 ID。"""

    service: "MockServiceResponse"
    endpoint_id: int
    scenario_ids: list[int]
    runtime_token: str | None = None


# 前向引用补全（MockScenarioCreate 引用 MockMatcherCreate，MockScenarioResponse 引用 MockMatcherResponse，
# CreateMockFromApiResponse 引用 MockServiceResponse）。
MockScenarioCreate.model_rebuild()
MockScenarioResponse.model_rebuild()
CreateMockFromApiResponse.model_rebuild()


__all__ = [
    "API_MOCK_TEMPLATES",
    "CreateMockFromApiRequest",
    "CreateMockFromApiResponse",
    "MOCK_BEHAVIOR_TYPES",
    "MOCK_CONTEXT_STATUSES",
    "MOCK_MATCHER_OPERATORS",
    "MOCK_MATCHER_SOURCES",
    "MOCK_SCOPES",
    "MockBehaviorType",
    "MockContextResponse",
    "MockContextStatus",
    "MockEndpointCreate",
    "MockEndpointListResponse",
    "MockEndpointResponse",
    "MockEndpointUpdate",
    "MockExecutionListResponse",
    "MockExecutionResponse",
    "MockMatcherCreate",
    "MockMatcherOperator",
    "MockMatcherResponse",
    "MockMatcherSource",
    "MockMatchersReplace",
    "MockScope",
    "MockScenarioCreate",
    "MockScenarioListResponse",
    "MockScenarioResponse",
    "MockScenarioUpdate",
    "MockServiceCreate",
    "MockServiceCreateResponse",
    "MockServiceListResponse",
    "MockServiceResponse",
    "MockServiceUpdate",
    "ScenarioTestRequest",
    "ScenarioTestResponse",
    "TestCaseMockCreate",
    "TestCaseMockResponse",
    "TestCaseMocksReplace",
]
