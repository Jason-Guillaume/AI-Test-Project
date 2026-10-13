"""通知模块：契约定义。

统一分页信封 {items, total, page, page_size}。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# 事件类型：与业务动作对应，便于前端按类型展示图标与文案。
EVENT_TYPE_USER_CREATED = "user.created"
EVENT_TYPE_USER_UPDATED = "user.updated"
EVENT_TYPE_USER_PASSWORD_CHANGED = "user.password_changed"
EVENT_TYPE_ORG_MEMBER_INVITED = "organization.member.invited"
EVENT_TYPE_PROJECT_MEMBER_INVITED = "project.member.invited"
EVENT_TYPE_PROJECT_OWNER_CHANGED = "project.owner_changed"
EVENT_TYPE_DEFECT_CREATED = "defect.created"
EVENT_TYPE_DEFECT_ASSIGNED = "defect.assigned"
EVENT_TYPE_DEFECT_STATUS_CHANGED = "defect.status_changed"

EVENT_TYPES: tuple[str, ...] = (
    EVENT_TYPE_USER_CREATED,
    EVENT_TYPE_USER_UPDATED,
    EVENT_TYPE_USER_PASSWORD_CHANGED,
    EVENT_TYPE_ORG_MEMBER_INVITED,
    EVENT_TYPE_PROJECT_MEMBER_INVITED,
    EVENT_TYPE_PROJECT_OWNER_CHANGED,
    EVENT_TYPE_DEFECT_CREATED,
    EVENT_TYPE_DEFECT_ASSIGNED,
    EVENT_TYPE_DEFECT_STATUS_CHANGED,
)


class NotificationResponse(BaseModel):
    """单条通知。"""

    id: int
    event_type: str
    title: str
    body: str | None = None
    payload: dict | None = None
    project_id: int | None = None
    organization_id: int | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """通知列表响应。"""

    items: list[NotificationResponse]
    total: int
    page: int = 1
    page_size: int = 1
    unread_total: int = 0


class NotificationReadRequest(BaseModel):
    """批量标记已读入参。为空表示全部标记为已读。"""

    ids: list[int] = Field(default_factory=list)


class NotificationSummaryResponse(BaseModel):
    """通知概览：用于顶部铃铛与工作台卡片。"""

    total: int
    unread_total: int


class EventCatalogItem(BaseModel):
    """事件目录项，供前端渲染事件类型文案。"""

    value: str
    label: str
