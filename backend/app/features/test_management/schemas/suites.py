"""test_management 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.test_management.schemas.common import TestSuiteType


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
