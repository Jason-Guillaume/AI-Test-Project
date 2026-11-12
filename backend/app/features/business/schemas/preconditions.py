"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.business.schemas.common import BusinessPreconditionOperator
from app.features.business.schemas.common import BusinessPreconditionType


class BusinessPreconditionBase(BaseModel):
    """业务前置条件共有字段。"""

    type: BusinessPreconditionType = Field(..., description="前提类型：VARIABLE/STATE/BUSINESS/TEXT")
    target: str = Field(..., min_length=1, max_length=200, description="判断目标，如 task.status")
    operator: BusinessPreconditionOperator = Field(default="EQ", description="比较符：EQ/NE/IN/CONTAINS")
    expected_value: str | None = Field(None, max_length=500, description="期望值，多值用逗号分隔")
    description: str | None = Field(None, max_length=500, description="前提说明")
    sort: int = Field(default=0, ge=0, description="排序值")


class BusinessPreconditionCreate(BusinessPreconditionBase):
    """新增前置条件入参（action_id 由路径提供）。"""


class BusinessPreconditionUpdate(BaseModel):
    """修改前置条件入参（局部）。"""

    type: BusinessPreconditionType | None = None
    target: str | None = Field(None, min_length=1, max_length=200)
    operator: BusinessPreconditionOperator | None = None
    expected_value: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=500)
    sort: int | None = Field(None, ge=0)


class BusinessPreconditionResponse(BaseModel):
    """业务前置条件响应。"""

    id: int
    action_id: int
    type: str
    target: str
    operator: str
    expected_value: str | None = None
    description: str | None = None
    sort: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
