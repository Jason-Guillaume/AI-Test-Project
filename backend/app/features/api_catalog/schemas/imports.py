"""api_catalog 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from app.features.api_catalog.schemas.common import ApiSourceType
from app.features.api_catalog.schemas.common import ImportClassification
from app.features.api_catalog.schemas.internal import InternalApiSchema


class ImportPreviewRequest(BaseModel):
    """导入预览请求。content 为 cURL、OpenAPI/Swagger 或 Postman 文本。"""

    source_type: ApiSourceType
    content: str = Field(..., min_length=1)
    file_name: str | None = None
    user_module_id: int | None = Field(default=None, gt=0)
    tag_to_module_map: dict[str, int] | None = None


class ImportPreviewItem(BaseModel):
    """单条导入预览项。"""

    classification: ImportClassification
    schema: InternalApiSchema
    proposed_module_id: int | None = None
    proposed_module_name: str
    existing_interface_id: int | None = None
    diff_summary: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class ImportPreviewResponse(BaseModel):
    """导入预览响应（不入库）。"""

    project_id: int
    source_type: ApiSourceType
    source_hash: str | None = None
    total: int
    new_count: int
    existing_count: int
    changed_count: int
    unchanged_count: int
    items: list[ImportPreviewItem]


class ImportConfirmRequest(BaseModel):
    """导入确认请求。重新解析+去重+入库（幂等，不信任预览缓存）。"""

    source_type: ApiSourceType
    content: str = Field(..., min_length=1)
    file_name: str | None = None
    user_module_id: int | None = Field(default=None, gt=0)
    tag_to_module_map: dict[str, int] | None = None
    # selected_items：选中的预览项序号（0-based）；None 表示全部 NEW+CHANGED 项。
    selected_items: list[int] | None = None
    overwrite_changed: bool = True


class ImportConfirmResponse(BaseModel):
    """导入确认响应。"""

    record_id: int
    total: int
    created_count: int
    updated_count: int
    skipped_count: int
    source_hash: str | None = None


class ApiImportRecordResponse(BaseModel):
    """导入记录响应。"""

    id: int
    project_id: int
    source_type: ApiSourceType
    file_name: str | None = None
    source_hash: str | None = None
    total: int
    created_count: int
    updated_count: int
    skipped_count: int
    created_by: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiImportRecordListResponse(BaseModel):
    """导入记录列表响应。"""

    items: list[ApiImportRecordResponse]
    total: int
