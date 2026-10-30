"""api_catalog 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict
from app.features.api_catalog.schemas.common import ChangeType


class ApiChangeLogResponse(BaseModel):
    """变更记录响应。"""

    id: int
    interface_id: int
    change_type: ChangeType
    diff_json: dict[str, Any] | None = None
    source_hash_before: str | None = None
    source_hash_after: str | None = None
    summary: str | None = None
    created_by: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiChangeLogListResponse(BaseModel):
    """变更记录列表响应。"""

    items: list[ApiChangeLogResponse]
    total: int
