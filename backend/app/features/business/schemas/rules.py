"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.business.schemas.common import BusinessRuleType


class BusinessRuleBase(BaseModel):
    """业务规则共有字段。"""

    name: str = Field(..., min_length=1, max_length=200, description="规则名称")
    description: str | None = Field(None, max_length=1000, description="规则描述")
    rule_type: BusinessRuleType = Field(default="GENERAL", description="规则类型：GENERAL/CONSTRAINT/PRECONDITION")
    expression: str | None = Field(None, description="规则表达式（第一阶段仅人工维护，不自动执行）")
    enabled: bool = Field(default=True, description="是否启用")


class BusinessRuleCreate(BusinessRuleBase):
    """新增业务规则入参（project_id 由路径提供；flow_id/action_id 可选，为空表示项目级规则）。"""

    flow_id: int | None = Field(None, gt=0, description="所属业务流程ID；为空表示项目级规则")
    action_id: int | None = Field(None, gt=0, description="所属业务动作ID；为空表示流程/项目级规则")


class BusinessRuleUpdate(BaseModel):
    """修改业务规则入参（局部）。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    rule_type: BusinessRuleType | None = None
    expression: str | None = None
    enabled: bool | None = None


class BusinessRuleResponse(BaseModel):
    """业务规则响应。"""

    id: int
    project_id: int
    flow_id: int | None = None
    action_id: int | None = None
    name: str
    description: str | None = None
    rule_type: str
    expression: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessRuleListResponse(BaseModel):
    """业务规则列表响应。"""

    items: list[BusinessRuleResponse]
    total: int
    page: int = 1
    page_size: int = 20
