"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.business.schemas.common import BusinessDomainStatus


class BusinessDomainBase(BaseModel):
    """业务域共有字段。"""

    name: str = Field(..., min_length=1, max_length=100, description="业务域名称")
    description: str | None = Field(None, max_length=500, description="业务域描述")
    sort: int = Field(default=0, ge=0, description="排序值，越小越靠前")
    status: BusinessDomainStatus = Field(default="ACTIVE", description="状态：ACTIVE/INACTIVE")


class BusinessDomainCreate(BusinessDomainBase):
    """新增业务域入参（project_id 由路径提供，不在此处重复）。"""


class BusinessDomainUpdate(BaseModel):
    """修改业务域入参（局部）。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    sort: int | None = Field(None, ge=0)
    status: BusinessDomainStatus | None = None


class BusinessDomainResponse(BaseModel):
    """业务域响应。"""

    id: int
    project_id: int
    name: str
    description: str | None = None
    sort: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessDomainListResponse(BaseModel):
    """业务域列表响应。"""

    items: list[BusinessDomainResponse]
    total: int
    page: int = 1
    page_size: int = 20
