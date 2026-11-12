"""test_management 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.test_management.schemas.common import TestStrategyCategory


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
