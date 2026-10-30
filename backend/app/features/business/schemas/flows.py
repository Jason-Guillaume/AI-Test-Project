"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.business.schemas.actions import BusinessActionDetailResponse
from app.features.business.schemas.common import BusinessFlowStatus
from app.features.business.schemas.rules import BusinessRuleResponse
from app.features.business.schemas.references import BusinessVariableRefResponse


class BusinessFlowBase(BaseModel):
    """业务流程共有字段。"""

    name: str = Field(..., min_length=1, max_length=200, description="业务流程名称")
    description: str | None = Field(None, max_length=1000, description="业务流程描述")
    status: BusinessFlowStatus = Field(default="DRAFT", description="状态：DRAFT/ACTIVE/DEPRECATED")


class BusinessFlowCreate(BusinessFlowBase):
    """新增业务流程入参（project_id 由路径提供；domain_id 在请求体中）。"""

    domain_id: int = Field(..., gt=0, description="所属业务域ID")


class BusinessFlowUpdate(BaseModel):
    """修改业务流程入参（局部）。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    status: BusinessFlowStatus | None = None
    revision: int | None = Field(None, ge=1, description="乐观锁版本号（防并发冲突）")


class BusinessFlowResponse(BaseModel):
    """业务流程响应（基本信息）。"""

    id: int
    project_id: int
    domain_id: int
    name: str
    description: str | None = None
    status: str
    version: int
    revision: int = 1
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessFlowListResponse(BaseModel):
    """业务流程列表响应。"""

    items: list[BusinessFlowResponse]
    total: int
    page: int = 1
    page_size: int = 20


class BusinessFlowDetailResponse(BusinessFlowResponse):
    """业务流程聚合详情：流程 + 所属域 + 有序动作（含各自子配置）+ 变量引用 + 规则。

    前端「业务流程详情」右侧面板一次性拉取该结构，4 个 Tab 共享同一份数据，
    避免切 Tab 时各自再请求。动作按 sort 升序返回。
    """

    domain_name: str | None = Field(None, description="所属业务域名称")
    actions: list[BusinessActionDetailResponse] = Field(default_factory=list)
    variable_refs: list[BusinessVariableRefResponse] = Field(default_factory=list)
    rules: list[BusinessRuleResponse] = Field(default_factory=list)
