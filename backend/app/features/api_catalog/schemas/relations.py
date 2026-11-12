"""api_catalog 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.api_catalog.schemas.common import RelationType


class ApiRelationCreate(BaseModel):
    """新增接口关联。"""

    source_api_id: int = Field(..., gt=0)
    target_api_id: int = Field(..., gt=0)
    relation_type: RelationType
    variable_name: str | None = Field(default=None, max_length=100)
    extract_path: str | None = Field(default=None, max_length=500)


class ApiRelationResponse(BaseModel):
    """关联响应。"""

    id: int
    project_id: int
    source_api_id: int
    target_api_id: int
    source_api_name: str | None = None
    target_api_name: str | None = None
    relation_type: RelationType
    variable_name: str | None = None
    extract_path: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiRelationListResponse(BaseModel):
    """关联列表响应。"""

    items: list[ApiRelationResponse]
    total: int
