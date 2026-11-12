"""HTTP contracts for batched deletion and recycle-bin operations."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BatchDeleteRequest(BaseModel):
    project_id: int | None = Field(default=None, gt=0)
    ids: list[int] = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=500)


class BatchRestoreRequest(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=100)


class PurgeRequest(BaseModel):
    confirmation: str
    reason: str = Field(min_length=1, max_length=500)


class BatchItemReceipt(BaseModel):
    id: int
    succeeded: bool
    recycle_bin_item_id: int | None = None
    already_done: bool = False
    error_code: str | None = None
    error: str | None = None
    meta: dict[str, Any] | None = None


class BatchReceipt(BaseModel):
    succeeded: int
    failed: int
    items: list[BatchItemReceipt]


class RecycleBinItemResponse(BaseModel):
    id: int
    resource_type: str
    resource_id: str
    display_name: str
    project_id: int | None
    organization_id: int | None
    deleted_by: int | None
    deleted_by_name: str | None
    deleted_at: datetime
    deletion_reason: str | None
    deletion_batch_id: str
    deletion_status: str
    can_restore: bool
    restore_conflict: str | None = None
    last_restore_error: str | None = None
    metadata: dict[str, Any]


class RecycleBinListResponse(BaseModel):
    items: list[RecycleBinItemResponse]
    total: int
    page: int
    page_size: int


class RecycleBinDetailResponse(RecycleBinItemResponse):
    resource_data: dict[str, Any] | None


class LifecycleAuditResponse(BaseModel):
    id: int
    event_type: str
    result: str
    resource_type: str
    resource_id: str
    project_id: int | None
    actor_id: int | None
    deletion_batch_id: str | None
    reason: str | None
    detail: dict[str, Any]
    created_at: datetime
