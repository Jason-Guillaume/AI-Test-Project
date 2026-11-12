"""Unified recycle-bin and domain-policy-routed batch deletion endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.models.identity import User
from app.core.security.auth import get_current_user, require_platform_admin
from app.lifecycle.schemas import (
    BatchDeleteRequest,
    BatchRestoreRequest,
    PurgeRequest,
    RecycleBinDetailResponse,
    RecycleBinListResponse,
)
from app.lifecycle import service


router = APIRouter(tags=["数据生命周期"])


@router.post("/resources/{resource_type}/batch-delete", summary="按领域策略批量软删除")
def batch_delete(
    resource_type: str,
    body: BatchDeleteRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return service.batch_delete(
        db, resource_type, body.project_id, body.ids, actor=actor, reason=body.reason,
    )


@router.get("/recycle-bin", response_model=RecycleBinListResponse, summary="回收站列表")
def list_recycle_bin(
    project_id: int | None = Query(None, ge=1),
    organization_id: int | None = Query(None, ge=1),
    resource_type: str | None = Query(None, max_length=80),
    deleted_by: int | None = Query(None, ge=1),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    keyword: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = Query("deleted_at"),
    order: str = Query("desc"),
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return service.list_recycle_bin(
        db, actor, project_id=project_id, organization_id=organization_id,
        resource_type=resource_type, deleted_by=deleted_by,
        date_from=date_from, date_to=date_to, keyword=keyword,
        page=page, page_size=page_size, sort=sort, order=order,
    )


@router.get("/recycle-bin/{item_id}", response_model=RecycleBinDetailResponse, summary="回收站详情")
def get_recycle_item(
    item_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return service.get_recycle_item(db, item_id, actor)


@router.post("/recycle-bin/{item_id}/restore", summary="恢复单条数据")
def restore_recycle_item(
    item_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return service.restore_recycle_item(db, item_id, actor)


@router.post("/recycle-bin/batch-restore", summary="批量恢复数据")
def batch_restore(
    body: BatchRestoreRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return service.batch_restore(db, body.item_ids, actor)


@router.get("/recycle-bin/{item_id}/audit", summary="删除与恢复审计记录")
def list_lifecycle_audit(
    item_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return service.list_lifecycle_audit(db, item_id, actor)


@router.get("/recycle-bin/{item_id}/purge-preview", summary="永久清理影响范围预览")
def purge_preview(
    item_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    return service.purge_preview(db, item_id, actor)


@router.delete(
    "/recycle-bin/{item_id}/permanent",
    status_code=status.HTTP_200_OK,
    summary="管理员永久清理（不可逆）",
)
def purge_recycle_item(
    item_id: int,
    body: PurgeRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    return service.purge_recycle_item(
        db, item_id, actor, confirmation=body.confirmation, reason=body.reason,
    )
