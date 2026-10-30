"""test_management 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.test_management.schemas.common import TestPriority
from app.features.test_management.schemas.common import TestSourceType
from app.features.test_management.schemas.common import TestStatus
from app.features.test_management.schemas.common import TestTargetType


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
