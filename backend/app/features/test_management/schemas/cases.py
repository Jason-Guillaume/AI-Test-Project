"""test_management 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.test_management.schemas.case_inputs import TestAssertionResponse
from app.features.test_management.schemas.case_inputs import TestCaseDataResponse
from app.features.test_management.schemas.case_inputs import TestCaseFixtureResponse
from app.features.test_management.schemas.case_inputs import TestCasePreconditionResponse
from app.features.test_management.schemas.common import TestCaseType
from app.features.test_management.schemas.common import TestPriority
from app.features.test_management.schemas.common import TestSourceType
from app.features.test_management.schemas.common import TestStatus
from app.features.test_management.schemas.case_inputs import TestStepResponse
from app.features.test_management.schemas.common import TestTargetType


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
