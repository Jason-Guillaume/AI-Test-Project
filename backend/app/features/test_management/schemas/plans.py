"""test_management 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.test_management.schemas.common import TestExecutionMode
from app.features.test_management.schemas.common import TestPlanStatus


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
