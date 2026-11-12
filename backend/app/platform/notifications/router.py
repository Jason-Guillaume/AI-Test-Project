"""通知收件箱 HTTP 适配器。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.orm import Session

from app.platform.notifications.schemas import (
    EventCatalogItem, NotificationListResponse, NotificationReadRequest,
    NotificationResponse, NotificationSummaryResponse,
)
from app.platform.notifications.services import inbox_service as _inbox
from app.core.models.identity import User
from app.core.database.session import get_db
from app.core.security.auth import get_current_user
from app.core.notifications.notify import EVENT_LABELS
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/notifications", tags=["通知"])

@router.get("", response_model=NotificationListResponse)
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    event_type: str | None = None,
    is_read: bool | None = None,
    organization_id: int | None = Query(None, ge=1),
    project_id: int | None = Query(None, ge=1),
):
    '分页列出当前用户可见的通知，默认按创建时间倒序。\n\n    计数与列表始终使用同一可见性子查询，避免出现「可见条目数 < 返回 total」\n    的前后端不一致。\n    '
    return _inbox.list_notifications(db=db, user=user, page=page, page_size=page_size, event_type=event_type, is_read=is_read, organization_id=organization_id, project_id=project_id)


@router.get("/summary", response_model=NotificationSummaryResponse)
def notification_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '返回通知总数与未读数，用于顶部铃铛角标。\n\n    只统计当前用户可见作用域内的通知；作用域资源被移除后不再计入角标。\n    '
    return _inbox.notification_summary(db=db, user=user)


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '把单条通知标记为已读；作用域不可见时按不存在处理。'
    return _inbox.mark_read(notification_id=notification_id, db=db, user=user)


@router.post("/read-all", response_model=NotificationListResponse)
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    body: NotificationReadRequest | None = Body(default=None),
):
    '批量标记已读；不传 ids 或 ids 为空时标记全部为已读。'
    return _inbox.mark_all_read(db=db, user=user, body=body)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '删除单条通知。'
    return _inbox.delete_notification(notification_id=notification_id, db=db, user=user)


@router.get("/events", response_model=list[EventCatalogItem])
def list_event_types():
    """返回事件类型目录，供前端渲染文案与图标。"""
    return [EventCatalogItem(value=key, label=value) for key, value in EVENT_LABELS.items()]
