"""test_data 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.features.test_data.schemas.common import AssetSource
from app.features.test_data.schemas.common import AssetStatus
from app.features.test_data.schemas.common import FixtureScope


class TestDataAssetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    entity_type: str = Field(..., min_length=1, max_length=50)
    source: AssetSource = "STATIC"
    scope: FixtureScope = "PROJECT"
    status: AssetStatus = "ACTIVE"
    fixture_id: int | None = None
    value_json: dict[str, Any] | None = None
    description: str | None = Field(None, max_length=500)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        """检查名称。"""
        return v.strip()


class TestDataAssetUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    entity_type: str | None = Field(None, min_length=1, max_length=50)
    source: AssetSource | None = None
    scope: FixtureScope | None = None
    status: AssetStatus | None = None
    fixture_id: int | None = None
    value_json: dict[str, Any] | None = None
    description: str | None = Field(None, max_length=500)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        """检查名称。"""
        return v.strip() if v is not None else v


class TestDataAssetResponse(BaseModel):
    """响应体的 value_json 已由 service 脱敏；掩码值编辑时留空表示不修改。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    entity_type: str
    source: str
    scope: str
    status: str
    fixture_id: int | None = None
    value_json: dict[str, Any] | None = None
    description: str | None = None
    referenced_count: int = 0
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class TestDataAssetListResponse(BaseModel):
    items: list[TestDataAssetResponse]
    page: int
    page_size: int
    total: int
