"""通知路由。

路径前缀 /api/v1/notifications。只读当前用户自己的收件箱，
不暴露任何他人通知，也不提供通知模板/渠道配置（旧项目那部分属于通知引擎，
第一阶段只保留收件箱与已读状态）。

响应约定：列表接口返回 {items, total, page, page_size, unread_total}。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.notifications.schemas import (
    EventCatalogItem,
    NotificationListResponse,
    NotificationReadRequest,
    NotificationResponse,
    NotificationSummaryResponse,
)
from app.models.identity import User
from app.models.notification import Notification
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.errors import not_found
from app.shared.notify import EVENT_LABELS
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.shared.roles import accessible_organization_ids, accessible_project_ids, is_platform_admin

router = APIRouter(prefix="/notifications", tags=["通知"])


def _visible_in_scope(
    db: Session,
    user: User,
    *,
    project_id: int | None = None,
    organization_id: int | None = None,
    ids: list[int] | None = None,
) -> "object":
    """构造「对当前用户可见」的通知查询。

    可见规则：通知按 user_id 归属；若带 project/organization 作用域，
    则对应资源仍需在当前用户可见集合内（资源被删除或成员被移除后通知隐藏）。
    """
    # 通知严格按 user_id 归属：本接口从构造查询起就排除他人通知。
    query = db.query(Notification).filter(Notification.user_id == user.id)
    # 三个过滤参数都是「可选收窄」：传了就追加条件，不传不加，避免误伤未归属作用域的通知。
    if ids is not None:
        query = query.filter(Notification.id.in_(ids))
    if project_id is not None:
        query = query.filter(Notification.project_id == project_id)
    if organization_id is not None:
        query = query.filter(Notification.organization_id == organization_id)

    # 平台管理员不做作用域过滤：收件箱仍只限于自己的 user_id。
    if is_platform_admin(user):
        return query

    # 非管理员：项目/组织作用域必须落在可见集合内，否则资源删除或成员被移除后通知不再可见。
    project_ids = accessible_project_ids(db, user) or []
    org_ids = accessible_organization_ids(db, user) or []

    # 三类可见通知：完全无作用域的；或项目归属落在可见项目集合内；
    # 同时 organization_id 为空也要放行——「项目不存在」不等于「组织越权」。
    no_scope = (
        Notification.project_id.is_(None) & Notification.organization_id.is_(None)
    )
    in_project = Notification.project_id.is_(None) | Notification.project_id.in_(project_ids or [-1])
    in_org = Notification.organization_id.is_(None) | Notification.organization_id.in_(org_ids or [-1])
    # 可见集合为空时用 [-1] 造一个必然不命中的条件，避免空 IN () 退化成「全部可见」。
    return query.filter(no_scope | (in_project & in_org))


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
    """分页列出当前用户可见的通知，默认按创建时间倒序。

    计数与列表始终使用同一可见性子查询，避免出现「可见条目数 < 返回 total」
    的前后端不一致。
    """
    query = _visible_in_scope(db, user, project_id=project_id, organization_id=organization_id)
    # 未读数统计同范围下的未读，不受 is_read 筛选本身影响。
    unread_total = int(query.filter(Notification.is_read.is_(False)).count())

    if event_type:
        query = query.filter(Notification.event_type == event_type)
    if is_read is not None:
        query = query.filter(Notification.is_read.is_(is_read))

    total = int(query.count())
    rows = (
        # 双键倒序：先按创建时间再按 ID，保证翻页稳定不重不漏。
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [NotificationResponse.model_validate(row) for row in rows]
    return NotificationListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        unread_total=unread_total,
    )


@router.get("/summary", response_model=NotificationSummaryResponse)
def notification_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回通知总数与未读数，用于顶部铃铛角标。

    只统计当前用户可见作用域内的通知；作用域资源被移除后不再计入角标。
    """
    query = _visible_in_scope(db, user)
    return NotificationSummaryResponse(
        total=int(query.count()),
        unread_total=int(query.filter(Notification.is_read.is_(False)).count()),
    )


@router.get("/events", response_model=list[EventCatalogItem])
def list_event_types():
    """事件类型目录，供前端渲染中文文案与图标。"""
    return [EventCatalogItem(value=key, label=value) for key, value in EVENT_LABELS.items()]


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把单条通知标记为已读；作用域不可见时按不存在处理。"""
    row = _owned_or_404(db, notification_id, user)
    # 二次作用域校验：通知本身属于自己，但其作用域资源可能已被删除/移除，此时按不存在处理。
    if _visible_in_scope(db, user, ids=[row.id]).filter(Notification.id == row.id).first() is None:
        raise not_found("通知不存在")
    if not row.is_read:
        # 幂等保护：已是已读时不重复写库，直接返回现有记录。
        row.is_read = True
        row.read_at = datetime.now()
        db.commit()
        db.refresh(row)
    return NotificationResponse.model_validate(row)


@router.post("/read-all", response_model=NotificationListResponse)
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    body: NotificationReadRequest | None = Body(default=None),
):
    """批量标记已读；不传 ids 或 ids 为空时标记全部为已读。"""
    # body 可空：不传 body 或 ids 为空都表示「全部标记已读」，两种写法等价。
    ids = [int(item) for item in (body.ids if body else [])]
    # user_id 过滤先生效，ids 里混入他人通知 ID 也不会越权标记。
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if ids:
        query = query.filter(Notification.id.in_(ids))
    rows = query.all()
    now = datetime.now()
    # changed 只统计本次真正发生状态变化的行数，用于回写响应的 unread_total。
    changed = 0
    for row in rows:
        if not row.is_read:
            row.is_read = True
            row.read_at = now
            changed += 1
    db.commit()
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(row) for row in rows],
        total=len(rows),
        page=1,
        page_size=max(len(rows), 1),
        unread_total=changed,
    )


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除单条通知。"""
    # 先做归属校验再删：他人通知一律按 404 处理，不暴露通知是否存在。
    row = _owned_or_404(db, notification_id, user)
    db.delete(row)
    db.commit()
    return None


def _owned_or_404(db: Session, notification_id: int, user: User) -> Notification:
    """取出通知并校验归属，不存在或不属于当前用户时抛 404。

    Args:
        db: 数据库会话。
        notification_id: 通知 ID（来自路径参数）。
        user: 当前请求用户，用于比对通知的 user_id。

    Returns:
        Notification: 归属于当前用户的通知实体。

    Raises:
        HTTPException: 通知不存在或不属于当前用户时抛 404（ERR_NOT_FOUND）。
    """
    row = db.get(Notification, notification_id)
    # 越权与不存在共用同一 404 文案，避免攻击者通过差异判断通知是否存在。
    if row is None or row.user_id != user.id:
        raise not_found("通知不存在")
    return row
