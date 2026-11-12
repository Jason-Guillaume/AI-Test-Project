"""test_data 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.features.test_data.schemas.common import FIXTURE_KEY_PATTERN
from app.features.test_data.schemas.common import FixtureScope
from app.features.test_data.schemas.common import PoolItemStatus
from app.features.test_data.schemas.common import PoolStatus


class DataPoolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    pool_key: str = Field(..., min_length=1, max_length=100)
    asset_id: int | None = None
    scope: FixtureScope = "PROJECT"
    max_concurrency: int = Field(default=1, ge=1, le=1000)
    lease_ttl_seconds: int = Field(default=1800, ge=1, le=86400)
    status: PoolStatus = "ACTIVE"

    @field_validator("pool_key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        """检查键。"""
        import re

        if not re.fullmatch(FIXTURE_KEY_PATTERN, v):
            raise ValueError("pool_key 必须匹配 " + FIXTURE_KEY_PATTERN)
        return v

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        """检查名称。"""
        return v.strip()


class DataPoolUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    max_concurrency: int | None = Field(None, ge=1, le=1000)
    lease_ttl_seconds: int | None = Field(None, ge=1, le=86400)
    status: PoolStatus | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        """检查名称。"""
        return v.strip() if v is not None else v


class DataPoolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    asset_id: int | None = None
    pool_key: str
    name: str
    scope: str
    max_concurrency: int
    lease_ttl_seconds: int
    status: str
    item_count: int = 0
    available_count: int = 0
    active_lease_count: int = 0
    created_at: datetime
    updated_at: datetime


class DataPoolItemCreate(BaseModel):
    payload_json: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    status: PoolItemStatus = "AVAILABLE"


class DataPoolItemUpdate(BaseModel):
    status: PoolItemStatus | None = None
    payload_json: dict[str, Any] | None = None
    expires_at: datetime | None = None


class DataPoolItemResponse(BaseModel):
    """payload_json 已脱敏。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pool_id: int
    status: str
    payload_json: dict[str, Any]
    occupied_count: int
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DataPoolLeaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    project_id: int
    test_run_id: int | None = None
    case_execution_id: int | None = None
    status: str
    leased_at: datetime | None = None
    released_at: datetime | None = None
    expires_at: datetime | None = None


class DataPoolListResponse(BaseModel):
    items: list[DataPoolResponse]
    page: int
    page_size: int
    total: int


class DataPoolItemListResponse(BaseModel):
    items: list[DataPoolItemResponse]
    page: int
    page_size: int
    total: int


class DataPoolLeaseListResponse(BaseModel):
    items: list[DataPoolLeaseResponse]
    page: int
    page_size: int
    total: int
