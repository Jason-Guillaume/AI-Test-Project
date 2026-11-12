"""api_catalog 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.features.api_catalog.schemas.requests import ApiBodyIn
from app.features.api_catalog.schemas.requests import ApiParameterIn
from app.features.api_catalog.schemas.requests import ApiParameterResponse
from app.features.api_catalog.schemas.requests import ApiRequestBodyResponse
from app.features.api_catalog.schemas.requests import ApiResponseIn
from app.features.api_catalog.schemas.requests import ApiResponseResponse
from app.features.api_catalog.schemas.common import ApiSourceType
from app.features.api_catalog.schemas.common import ApiStatus


class ApiInterfaceCreate(BaseModel):
    """手工创建接口。"""

    module_id: int | None = Field(default=None, gt=0)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    method: str
    path: str = Field(..., min_length=1, max_length=500)
    auth_type: str = "none"
    content_type: str = "application/json"
    status: ApiStatus = "DRAFT"
    parameters: list[ApiParameterIn] = Field(default_factory=list)
    body: ApiBodyIn = Field(default_factory=ApiBodyIn)
    responses: list[ApiResponseIn] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: Any) -> str:
        """清理名称。"""
        return str(v or "").strip()

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, v: Any) -> str:
        """规范化方法。"""
        return str(v or "").upper()


class ApiInterfaceUpdate(BaseModel):
    """更新接口基本信息（局部）。"""

    module_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    method: str | None = None
    path: str | None = Field(default=None, min_length=1, max_length=500)
    auth_type: str | None = None
    content_type: str | None = None
    status: ApiStatus | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: Any) -> Any:
        """清理名称。"""
        return str(v).strip() if v is not None else None

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, v: Any) -> Any:
        """规范化方法。"""
        return str(v).upper() if v is not None else None


class ApiInterfaceMove(BaseModel):
    """移动接口到指定模块。"""

    module_id: int | None = Field(default=None, gt=0)


class ApiInterfaceResponse(BaseModel):
    """接口列表/详情响应（基本信息）。"""

    id: int
    project_id: int
    module_id: int | None = None
    module_name: str | None = None
    name: str
    description: str | None = None
    method: str
    path: str
    auth_type: str
    content_type: str
    status: ApiStatus
    source_type: ApiSourceType
    version: int
    source_hash: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiInterfaceDetailResponse(ApiInterfaceResponse):
    """接口详情：附带参数、body、响应概要。"""

    parameters: list[ApiParameterResponse] = Field(default_factory=list)
    body: ApiRequestBodyResponse | None = None
    responses: list[ApiResponseResponse] = Field(default_factory=list)


class ApiInterfaceListResponse(BaseModel):
    """接口列表分页响应。"""

    items: list[ApiInterfaceResponse]
    total: int
    page: int = 1
    page_size: int = 20
