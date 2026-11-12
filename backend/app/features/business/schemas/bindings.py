"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from app.features.business.schemas.common import BusinessApiLocation
from app.features.business.schemas.common import BusinessApiMappingDirection
from app.features.business.schemas.common import BusinessBindingType


class BusinessBindingCreate(BaseModel):
    """新增业务绑定入参（action_id 由路径提供）。"""

    binding_type: BusinessBindingType = Field(default="API", description="绑定通道：API/WEB")
    api_id: int | None = Field(None, gt=0, description="绑定的接口ID（api_catalog.ApiInterface）")
    name: str | None = Field(None, max_length=200, description="绑定名称（如 API v1）")
    is_default: bool = Field(default=True, description="是否为默认绑定（执行时使用）")
    sort: int = Field(default=0, ge=0, description="绑定排序值")
    config_json: dict[str, Any] | None = Field(None, description="通道相关配置")
    enabled: bool = Field(default=True, description="是否启用该绑定")


class BusinessBindingUpdate(BaseModel):
    """修改业务绑定入参（局部）。"""

    binding_type: BusinessBindingType | None = None
    api_id: int | None = Field(None, gt=0)
    name: str | None = Field(None, max_length=200)
    is_default: bool | None = None
    sort: int | None = Field(None, ge=0)
    config_json: dict[str, Any] | None = None
    enabled: bool | None = None


class BusinessBindingResponse(BaseModel):
    """业务绑定响应（基本信息，不含失效判定与映射）。"""

    id: int
    action_id: int
    binding_type: str
    api_id: int | None = None
    name: str | None = None
    is_default: bool = True
    sort: int = 0
    config_json: dict[str, Any] | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessApiMappingCreate(BaseModel):
    """新增业务变量 ↔ 接口参数映射入参（binding_id 由路径提供）。"""

    direction: BusinessApiMappingDirection = Field(..., description="方向：INPUT/OUTPUT")
    business_variable: str = Field(..., min_length=1, max_length=100, description="业务变量名")
    api_location: BusinessApiLocation = Field(
        ..., description="接口位置：INPUT 用 BODY/HEADER/QUERY/PATH；OUTPUT 用 RESPONSE",
    )
    api_field: str | None = Field(None, max_length=300, description="接口字段路径，如 body.project_id")
    expression: str | None = Field(None, max_length=500, description="OUTPUT 时 JSONPath 表达式，如 $.data.id")


class BusinessApiMappingUpdate(BaseModel):
    """修改业务 API 映射入参（局部）。"""

    direction: BusinessApiMappingDirection | None = None
    business_variable: str | None = Field(None, min_length=1, max_length=100)
    api_location: BusinessApiLocation | None = None
    api_field: str | None = Field(None, max_length=300)
    expression: str | None = Field(None, max_length=500)


class BusinessApiMappingResponse(BaseModel):
    """业务 API 映射响应。"""

    id: int
    binding_id: int
    direction: str
    business_variable: str
    api_location: str
    api_field: str | None = None
    expression: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessBindingDetailResponse(BusinessBindingResponse):
    """业务绑定详情：基本信息 + 失效判定 + 输入/输出映射。"""

    valid: bool = Field(..., description="绑定是否有效（接口存在且未废弃）")
    invalid_reason: str | None = Field(None, description="失效原因；valid=True 时为 None")
    api_name: str | None = Field(None, description="绑定接口名称（失效时为 None）")
    api_method: str | None = Field(None, description="绑定接口 HTTP 方法")
    api_path: str | None = Field(None, description="绑定接口路径")
    api_status: str | None = Field(None, description="绑定接口状态")
    input_mappings: list[BusinessApiMappingResponse] = Field(default_factory=list)
    output_mappings: list[BusinessApiMappingResponse] = Field(default_factory=list)
