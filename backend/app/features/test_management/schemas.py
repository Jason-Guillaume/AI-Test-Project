"""测试管理模块：契约定义（Pydantic v2）。

只放请求/响应模型与字面量类型，不含业务逻辑；service 与 router 共用本文件
作为两层接口契约（与 business / defects / api_catalog 的 schemas 风格一致）。

覆盖：
- 测试资产：TestStrategy / TestPoint / TestCase（含前置条件、测试数据、步骤、断言子实体）
- 测试管理：TestSuite / TestPlan / TestRun / CaseExecution
- 聚合详情：TestCaseDetailResponse（用例 + 前置条件 + 数据 + 步骤 + 断言一次性返回）

TestCase.revision 乐观锁：更新时校验 revision，不匹配 → 409 CONFLICT。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- 枚举字面量

# 各状态/类型字段在数据库层均为 String（不设 sa.Enum / CHECK），
# 合法取值由服务层校验；这里用 Literal 与常量元组双重声明，供路由/前端/文档复用。

TEST_STRATEGY_CATEGORIES = (
    "FUNCTIONAL", "PARAMETER", "BOUNDARY", "AUTH", "PERMISSION",
    "BUSINESS", "EXCEPTION", "IDEMPOTENCY", "SECURITY", "DATA_CONSISTENCY",
)
TestStrategyCategory = Literal[
    "FUNCTIONAL", "PARAMETER", "BOUNDARY", "AUTH", "PERMISSION",
    "BUSINESS", "EXCEPTION", "IDEMPOTENCY", "SECURITY", "DATA_CONSISTENCY",
]

TEST_PRIORITIES = ("P0", "P1", "P2", "P3")
TestPriority = Literal["P0", "P1", "P2", "P3"]

TEST_TARGET_TYPES = ("API", "BUSINESS_FLOW", "BUSINESS_ACTION")
TestTargetType = Literal["API", "BUSINESS_FLOW", "BUSINESS_ACTION"]

TEST_STATUSES = ("DRAFT", "ACTIVE", "DEPRECATED")
TestStatus = Literal["DRAFT", "ACTIVE", "DEPRECATED"]

TEST_SOURCE_TYPES = ("MANUAL", "AI")
TestSourceType = Literal["MANUAL", "AI"]

TEST_CASE_TYPES = (
    "FUNCTIONAL", "BUSINESS", "NEGATIVE", "BOUNDARY", "PERMISSION", "SECURITY", "EXCEPTION",
)
TestCaseType = Literal[
    "FUNCTIONAL", "BUSINESS", "NEGATIVE", "BOUNDARY", "PERMISSION", "SECURITY", "EXCEPTION",
]

TEST_PRECONDITION_TYPES = ("VARIABLE", "TEXT", "FIXTURE", "API", "BUSINESS_ACTION", "BUSINESS_FLOW")
TestPreconditionType = Literal[
    "VARIABLE", "TEXT", "FIXTURE", "API", "BUSINESS_ACTION", "BUSINESS_FLOW"
]

TEST_OPERATORS = ("EQ", "NE", "GT", "GE", "LT", "LE", "IN", "CONTAINS", "EXISTS", "NOT_EXISTS")
TestOperator = Literal["EQ", "NE", "GT", "GE", "LT", "LE", "IN", "CONTAINS", "EXISTS", "NOT_EXISTS"]

TEST_VALUE_TYPES = ("STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY")
TestValueType = Literal["STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY"]

TEST_DATA_SOURCE_TYPES = ("STATIC", "ENVIRONMENT", "VARIABLE", "RUNTIME", "FAKER", "FIXTURE")
TestDataSourceType = Literal["STATIC", "ENVIRONMENT", "VARIABLE", "RUNTIME", "FAKER", "FIXTURE"]

TEST_STEP_TYPES = ("SETUP", "ACTION", "ASSERT", "CLEANUP")
TestStepType = Literal["SETUP", "ACTION", "ASSERT", "CLEANUP"]

TEST_ASSERTION_TYPES = (
    "STATUS_CODE", "JSON_PATH", "HEADER", "RESPONSE_TIME", "CONTAINS", "NOT_CONTAINS",
)
TestAssertionType = Literal[
    "STATUS_CODE", "JSON_PATH", "HEADER", "RESPONSE_TIME", "CONTAINS", "NOT_CONTAINS"
]

TEST_SUITE_TYPES = ("SMOKE", "REGRESSION", "BUSINESS", "CUSTOM")
TestSuiteType = Literal["SMOKE", "REGRESSION", "BUSINESS", "CUSTOM"]

TEST_PLAN_STATUSES = ("DRAFT", "ACTIVE", "DISABLED")
TestPlanStatus = Literal["DRAFT", "ACTIVE", "DISABLED"]

TEST_EXECUTION_MODES = ("MANUAL", "SCHEDULED", "CI")
TestExecutionMode = Literal["MANUAL", "SCHEDULED", "CI"]

TEST_RUN_STATUSES = ("PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED")
TestRunStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED"]

CASE_EXECUTION_STATUSES = ("PENDING", "RUNNING", "PASSED", "FAILED", "SKIPPED", "ERROR")
CaseExecutionStatus = Literal["PENDING", "RUNNING", "PASSED", "FAILED", "SKIPPED", "ERROR"]

CASE_EXECUTOR_TYPES = ("API", "BUSINESS_FLOW", "BUSINESS_ACTION")
CaseExecutorType = Literal["API", "BUSINESS_FLOW", "BUSINESS_ACTION"]


# --------------------------------------------------------------------------- 测试策略


class TestStrategyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="策略名称")
    description: str | None = Field(None, max_length=1000, description="策略描述")
    category: TestStrategyCategory = Field(default="FUNCTIONAL", description="策略类别")
    enabled: bool = Field(default=True, description="是否启用")


class TestStrategyCreate(TestStrategyBase):
    """新增测试策略入参（project_id 由路径提供）。"""


class TestStrategyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    category: TestStrategyCategory | None = None
    enabled: bool | None = None


class TestStrategyResponse(BaseModel):
    id: int
    project_id: int
    name: str
    description: str | None = None
    category: str
    enabled: bool
    source_type: str
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestStrategyListResponse(BaseModel):
    items: list[TestStrategyResponse]
    total: int
    page: int = 1
    page_size: int = 20


# --------------------------------------------------------------------------- 测试点


class TestPointBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="测试点名称")
    description: str | None = Field(None, max_length=1000, description="测试点描述")
    priority: TestPriority = Field(default="P1", description="优先级：P0/P1/P2/P3")
    target_type: TestTargetType = Field(default="API", description="被测对象类型")
    strategy_id: int | None = Field(None, gt=0, description="所属测试策略ID")
    api_id: int | None = Field(None, gt=0, description="关联接口ID")
    business_flow_id: int | None = Field(None, gt=0, description="关联业务流程ID")
    business_action_id: int | None = Field(None, gt=0, description="关联业务动作ID")
    status: TestStatus = Field(default="DRAFT", description="状态：DRAFT/ACTIVE/DEPRECATED")


class TestPointCreate(TestPointBase):
    """新增测试点入参（project_id 由路径提供）。"""

    source_type: TestSourceType = Field(default="MANUAL", description="来源：MANUAL/AI")
    agent_session_id: int | None = Field(None, gt=0, description="生成该测试点的 Agent 会话ID（AI 来源追溯，MANUAL 为空）")
    generation_version: int | None = Field(None, ge=1, description="Agent 生成版本号（追溯用）")


class TestPointUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    priority: TestPriority | None = None
    target_type: TestTargetType | None = None
    strategy_id: int | None = Field(None, gt=0)
    api_id: int | None = Field(None, gt=0)
    business_flow_id: int | None = Field(None, gt=0)
    business_action_id: int | None = Field(None, gt=0)
    status: TestStatus | None = None


class TestPointResponse(BaseModel):
    id: int
    project_id: int
    strategy_id: int | None = None
    name: str
    description: str | None = None
    priority: str
    target_type: str
    api_id: int | None = None
    business_flow_id: int | None = None
    business_action_id: int | None = None
    status: str
    source_type: str
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestPointListResponse(BaseModel):
    items: list[TestPointResponse]
    total: int
    page: int = 1
    page_size: int = 20


# --------------------------------------------------------------------------- 测试用例


class TestCaseBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="用例名称")
    description: str | None = Field(None, max_length=1000, description="用例描述")
    priority: TestPriority = Field(default="P1", description="优先级")
    case_type: TestCaseType = Field(default="FUNCTIONAL", description="用例类型")
    target_type: TestTargetType = Field(default="API", description="被测对象类型")
    test_point_id: int | None = Field(None, gt=0, description="关联测试点ID")
    api_id: int | None = Field(None, gt=0, description="关联接口ID")
    business_flow_id: int | None = Field(None, gt=0, description="关联业务流程ID")
    business_action_id: int | None = Field(None, gt=0, description="关联业务动作ID")
    status: TestStatus = Field(default="DRAFT", description="状态：DRAFT/ACTIVE/DEPRECATED")
    enabled: bool = Field(default=True, description="是否启用")


class TestCaseCreate(TestCaseBase):
    """新增测试用例入参（project_id 由路径提供）。"""

    source_type: TestSourceType = Field(default="MANUAL", description="来源：MANUAL/AI")
    agent_session_id: int | None = Field(None, gt=0, description="生成该用例的 Agent 会话ID（AI 来源追溯，MANUAL 为空）")
    generation_version: int | None = Field(None, ge=1, description="Agent 生成版本号（追溯用）")


class TestCaseUpdate(BaseModel):
    """修改测试用例入参（局部）。revision 乐观锁必传以防并发覆盖。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    priority: TestPriority | None = None
    case_type: TestCaseType | None = None
    target_type: TestTargetType | None = None
    test_point_id: int | None = Field(None, gt=0)
    api_id: int | None = Field(None, gt=0)
    business_flow_id: int | None = Field(None, gt=0)
    business_action_id: int | None = Field(None, gt=0)
    status: TestStatus | None = None
    enabled: bool | None = None
    revision: int | None = Field(None, ge=1, description="乐观锁版本号（防并发冲突）")


class TestCaseResponse(BaseModel):
    id: int
    project_id: int
    test_point_id: int | None = None
    name: str
    description: str | None = None
    priority: str
    case_type: str
    target_type: str
    api_id: int | None = None
    business_flow_id: int | None = None
    business_action_id: int | None = None
    status: str
    enabled: bool
    revision: int = 1
    source_type: str
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestCaseListResponse(BaseModel):
    items: list[TestCaseResponse]
    total: int
    page: int = 1
    page_size: int = 20


# --------------------------------------------------------------------------- 测试用例：前置条件


class TestCasePreconditionBase(BaseModel):
    type: TestPreconditionType = Field(default="VARIABLE", description="前置条件类型")
    target: str | None = Field(None, max_length=200, description="目标：变量名/实体/说明")
    operator: TestOperator = Field(default="EQ", description="操作符")
    expected_value: str | None = Field(None, description="期望值")
    description: str | None = Field(None, max_length=500, description="说明")
    config_json: dict[str, Any] | None = Field(None, description="附加配置")
    sort: int = Field(default=0, ge=0, description="排序")


class TestCasePreconditionCreate(TestCasePreconditionBase):
    """新增前置条件入参（test_case_id 由路径提供）。"""


class TestCasePreconditionUpdate(BaseModel):
    type: TestPreconditionType | None = None
    target: str | None = Field(None, max_length=200)
    operator: TestOperator | None = None
    expected_value: str | None = None
    description: str | None = Field(None, max_length=500)
    config_json: dict[str, Any] | None = None
    sort: int | None = Field(None, ge=0)


class TestCasePreconditionResponse(BaseModel):
    id: int
    test_case_id: int
    type: str
    target: str | None = None
    operator: str
    expected_value: str | None = None
    description: str | None = None
    config_json: dict[str, Any] | None = None
    sort: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 测试用例：测试数据


class TestCaseDataBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="数据项名")
    value_type: TestValueType = Field(default="STRING", description="值类型")
    value: str | None = Field(None, description="值或引用标识")
    source_type: TestDataSourceType = Field(default="STATIC", description="来源")
    required: bool = Field(default=False, description="是否必需")
    description: str | None = Field(None, max_length=500, description="说明")
    config_json: dict[str, Any] | None = Field(None, description="附加配置")
    sort: int = Field(default=0, ge=0, description="排序")


class TestCaseDataCreate(TestCaseDataBase):
    """新增测试数据入参（test_case_id 由路径提供）。"""


class TestCaseDataUpdate(BaseModel):
    value_type: TestValueType | None = None
    value: str | None = None
    source_type: TestDataSourceType | None = None
    required: bool | None = None
    description: str | None = Field(None, max_length=500)
    config_json: dict[str, Any] | None = None
    sort: int | None = Field(None, ge=0)


class TestCaseDataResponse(BaseModel):
    id: int
    test_case_id: int
    name: str
    value_type: str
    value: str | None = None
    source_type: str
    required: bool
    description: str | None = None
    config_json: dict[str, Any] | None = None
    sort: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 测试用例：所需 Fixture


class TestCaseFixtureItem(BaseModel):
    """用例声明所需 Fixture 的一项：只引用 fixture_key，不写真实 task_id。"""

    fixture_key: str = Field(
        ..., min_length=1, max_length=100,
        pattern=r"^[A-Z][A-Z0-9_]{0,99}$",
        description="Fixture 引用键（与 fixture.fixture_key 同规则）",
    )
    sort: int = Field(default=0, ge=0, description="排序")


class TestCaseFixtureReplace(BaseModel):
    """整体替换用例所需 Fixture 列表；空列表表示解除全部声明。"""

    fixtures: list[TestCaseFixtureItem] = Field(default_factory=list, max_length=50)


class TestCaseFixtureResponse(BaseModel):
    id: int
    test_case_id: int
    fixture_id: int
    fixture_key: str
    name: str | None = None
    entity_type: str | None = None
    scope: str | None = None
    status: str | None = None
    outputs: list[str] = Field(
        default_factory=list, description="输出契约名：测试数据按 fixture_key + output 绑定",
    )
    sort: int

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 测试用例：步骤


class TestStepBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="步骤名")
    step_type: TestStepType = Field(default="ACTION", description="步骤类型：SETUP/ACTION/ASSERT/CLEANUP")
    target_type: TestTargetType | None = Field(None, description="被测对象类型")
    target_id: int | None = Field(None, gt=0, description="被测对象ID")
    sort: int = Field(default=0, ge=0, description="排序")
    config_json: dict[str, Any] | None = Field(None, description="步骤配置")


class TestStepCreate(TestStepBase):
    """新增测试步骤入参（test_case_id 由路径提供）。"""


class TestStepUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    step_type: TestStepType | None = None
    target_type: TestTargetType | None = None
    target_id: int | None = Field(None, gt=0)
    sort: int | None = Field(None, ge=0)
    config_json: dict[str, Any] | None = None


class TestStepResponse(BaseModel):
    id: int
    test_case_id: int
    name: str
    step_type: str
    target_type: str | None = None
    target_id: int | None = None
    sort: int
    config_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 测试用例：断言


class TestAssertionBase(BaseModel):
    assertion_type: TestAssertionType = Field(
        default="STATUS_CODE", description="断言类型：STATUS_CODE/JSON_PATH/HEADER/RESPONSE_TIME/CONTAINS/NOT_CONTAINS",
    )
    source: str | None = Field(None, max_length=100, description="来源标识：HEADER名/CONTEXT作用域")
    path: str | None = Field(None, max_length=500, description="JSONPath 或字段路径")
    operator: TestOperator = Field(default="EQ", description="操作符")
    expected_value: str | None = Field(None, description="期望值")
    required: bool = Field(default=True, description="是否必需（软断言=False）")
    step_id: int | None = Field(None, ge=0, description="关联步骤ID")
    sort: int = Field(default=0, ge=0, description="排序")


class TestAssertionCreate(TestAssertionBase):
    """新增断言入参（test_case_id 由路径提供）。"""


class TestAssertionUpdate(BaseModel):
    assertion_type: TestAssertionType | None = None
    source: str | None = Field(None, max_length=100)
    path: str | None = Field(None, max_length=500)
    operator: TestOperator | None = None
    expected_value: str | None = None
    required: bool | None = None
    step_id: int | None = Field(None, ge=0)
    sort: int | None = Field(None, ge=0)


class TestAssertionResponse(BaseModel):
    id: int
    test_case_id: int
    step_id: int | None = None
    assertion_type: str
    source: str | None = None
    path: str | None = None
    operator: str
    expected_value: str | None = None
    required: bool
    sort: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 测试用例：聚合详情


class TestCaseDetailResponse(TestCaseResponse):
    """测试用例聚合详情：基本信息 + 前置条件 + 测试数据 + 步骤 + 断言。

    前端「用例编辑器」一次性拉取该结构，减少往返。
    """

    preconditions: list[TestCasePreconditionResponse] = Field(default_factory=list)
    test_data: list[TestCaseDataResponse] = Field(default_factory=list)
    steps: list[TestStepResponse] = Field(default_factory=list)
    assertions: list[TestAssertionResponse] = Field(default_factory=list)
    fixtures: list[TestCaseFixtureResponse] = Field(
        default_factory=list, description="所需 Fixture（执行前由 Data Factory 生成并注入）",
    )


# --------------------------------------------------------------------------- 测试套件


class TestSuiteBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="套件名")
    description: str | None = Field(None, max_length=1000, description="套件描述")
    suite_type: TestSuiteType = Field(default="REGRESSION", description="套件类型")
    enabled: bool = Field(default=True, description="是否启用")


class TestSuiteCreate(TestSuiteBase):
    """新增测试套件入参（project_id 由路径提供）。"""


class TestSuiteUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    suite_type: TestSuiteType | None = None
    enabled: bool | None = None


class TestSuiteResponse(BaseModel):
    id: int
    project_id: int
    name: str
    description: str | None = None
    suite_type: str
    enabled: bool
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestSuiteListResponse(BaseModel):
    items: list[TestSuiteResponse]
    total: int
    page: int = 1
    page_size: int = 20


# --------------------------------------------------------------------------- 套件-用例关联


class TestSuiteCaseAdd(BaseModel):
    """把用例加入套件。"""

    test_case_id: int = Field(..., gt=0, description="用例ID")
    sort: int = Field(default=0, ge=0, description="排序")
    enabled: bool = Field(default=True, description="是否启用")


class TestSuiteCaseResponse(BaseModel):
    id: int
    suite_id: int
    test_case_id: int
    sort: int
    enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 测试计划


class TestPlanBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="计划名")
    description: str | None = Field(None, max_length=1000, description="计划描述")
    environment_id: int | None = Field(None, gt=0, description="执行环境ID")
    status: TestPlanStatus = Field(default="DRAFT", description="状态")
    execution_mode: TestExecutionMode = Field(default="MANUAL", description="执行模式")


class TestPlanCreate(TestPlanBase):
    """新增测试计划入参（project_id 由路径提供）。"""


class TestPlanUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    environment_id: int | None = Field(None, gt=0)
    status: TestPlanStatus | None = None
    execution_mode: TestExecutionMode | None = None


class TestPlanResponse(BaseModel):
    id: int
    project_id: int
    name: str
    description: str | None = None
    environment_id: int | None = None
    status: str
    execution_mode: str
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestPlanListResponse(BaseModel):
    items: list[TestPlanResponse]
    total: int
    page: int = 1
    page_size: int = 20


# --------------------------------------------------------------------------- 计划-套件关联


class TestPlanSuiteAdd(BaseModel):
    """把套件加入计划。"""

    suite_id: int = Field(..., gt=0, description="套件ID")
    sort: int = Field(default=0, ge=0, description="排序")


class TestPlanSuiteResponse(BaseModel):
    id: int
    plan_id: int
    suite_id: int
    sort: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 测试执行


class TestRunCreateRequest(BaseModel):
    """触发测试计划执行。"""

    environment_id: int | None = Field(None, gt=0, description="执行环境ID（覆盖计划环境；为空用计划环境）")


class TestRunResponse(BaseModel):
    id: int
    project_id: int
    plan_id: int | None = None
    environment_id: int | None = None
    status: str
    total: int
    passed: int
    failed: int
    skipped: int
    error: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestRunListResponse(BaseModel):
    items: list[TestRunResponse]
    total: int
    page: int = 1
    page_size: int = 20


class CaseExecutionResponse(BaseModel):
    id: int
    test_run_id: int
    test_case_id: int | None = None
    status: str
    executor_type: str | None = None
    request_snapshot: dict[str, Any] | None = None
    response_snapshot: dict[str, Any] | None = None
    assertion_results: list[dict[str, Any]] | None = None
    context_json: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    cleanup_status: str | None = Field(
        None, description="清理状态：PENDING/SUCCESS/FAILED/SKIPPED（不覆盖 status 与 error_code）",
    )
    cleanup_error_code: str | None = Field(None, description="清理失败错误码（仅 cleanup_* 字段）")
    cleanup_error_message: str | None = Field(None, description="清理失败原因（截断 2000 字）")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CaseExecutionListResponse(BaseModel):
    items: list[CaseExecutionResponse]
    total: int
    page: int = 1
    page_size: int = 100


__all__ = [
    # 枚举常量
    "CASE_EXECUTION_STATUSES",
    "CASE_EXECUTOR_TYPES",
    "TEST_ASSERTION_TYPES",
    "TEST_CASE_TYPES",
    "TEST_DATA_SOURCE_TYPES",
    "TEST_EXECUTION_MODES",
    "TEST_OPERATORS",
    "TEST_PLAN_STATUSES",
    "TEST_PRIORITIES",
    "TEST_PRECONDITION_TYPES",
    "TEST_RUN_STATUSES",
    "TEST_SOURCE_TYPES",
    "TEST_STATUSES",
    "TEST_STEP_TYPES",
    "TEST_STRATEGY_CATEGORIES",
    "TEST_SUITE_TYPES",
    "TEST_TARGET_TYPES",
    "TEST_VALUE_TYPES",
    # 测试策略
    "TestStrategyBase",
    "TestStrategyCreate",
    "TestStrategyListResponse",
    "TestStrategyResponse",
    "TestStrategyUpdate",
    # 测试点
    "TestPointBase",
    "TestPointCreate",
    "TestPointListResponse",
    "TestPointResponse",
    "TestPointUpdate",
    # 测试用例
    "TestCaseBase",
    "TestCaseCreate",
    "TestCaseDetailResponse",
    "TestCaseListResponse",
    "TestCaseResponse",
    "TestCaseUpdate",
    # 前置条件
    "TestCasePreconditionBase",
    "TestCasePreconditionCreate",
    "TestCasePreconditionResponse",
    "TestCasePreconditionUpdate",
    # 测试数据
    "TestCaseDataBase",
    "TestCaseDataCreate",
    "TestCaseDataResponse",
    "TestCaseDataUpdate",
    "TestCaseFixtureItem",
    "TestCaseFixtureReplace",
    "TestCaseFixtureResponse",
    # 步骤
    "TestStepBase",
    "TestStepCreate",
    "TestStepResponse",
    "TestStepUpdate",
    # 断言
    "TestAssertionBase",
    "TestAssertionCreate",
    "TestAssertionResponse",
    "TestAssertionUpdate",
    # 测试套件
    "TestSuiteBase",
    "TestSuiteCaseAdd",
    "TestSuiteCaseResponse",
    "TestSuiteCreate",
    "TestSuiteListResponse",
    "TestSuiteResponse",
    "TestSuiteUpdate",
    # 测试计划
    "TestPlanBase",
    "TestPlanCreate",
    "TestPlanListResponse",
    "TestPlanResponse",
    "TestPlanSuiteAdd",
    "TestPlanSuiteResponse",
    "TestPlanUpdate",
    # 测试执行
    "TestRunCreateRequest",
    "TestRunListResponse",
    "TestRunResponse",
    "CaseExecutionListResponse",
    "CaseExecutionResponse",
    # Literal 类型
    "CaseExecutionStatus",
    "CaseExecutorType",
    "TestAssertionType",
    "TestCaseType",
    "TestDataSourceType",
    "TestExecutionMode",
    "TestOperator",
    "TestPlanStatus",
    "TestPreconditionType",
    "TestPriority",
    "TestRunStatus",
    "TestSourceType",
    "TestStatus",
    "TestStepType",
    "TestStrategyCategory",
    "TestSuiteType",
    "TestTargetType",
    "TestValueType",
]
