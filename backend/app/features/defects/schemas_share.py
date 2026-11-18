"""缺陷分享的请求和响应契约。

公开响应只包含分享时授权的内容。内部响应可以包含快照和发送审计，
但仍然不返回访问凭证明文；明文只出现在创建或重新签发的响应里。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ShareOptions(BaseModel):
    """创建、预览和批量推送共用的展示选项。"""

    channel_id: int = Field(gt=0)
    visible_fields: list[str] | None = None
    expires_in_days: Literal[7, 30, 90] | None = 7
    permanent: bool = False
    allow_view: bool = True
    allow_resolve: bool = True
    request_key: str | None = Field(default=None, min_length=8, max_length=100)


class SharePreviewRequest(ShareOptions):
    """推送前预览。不创建分享，也不调用飞书。"""

    bug_ids: list[int] = Field(min_length=1, max_length=30)


class BatchShareRequest(ShareOptions):
    """同一项目内的批量推送。每条缺陷仍会生成独立凭证。"""

    bug_ids: list[int] = Field(min_length=1, max_length=30)


class ShareRetryRequest(BaseModel):
    """重新推送。携带原凭证时不轮换；不携带时签发新凭证并使旧凭证失效。"""

    access_token: str | None = Field(default=None, max_length=200)
    confirm_uncertain: bool = False


class RevokeItem(BaseModel):
    """批量撤销中的一条分享。"""

    bug_id: int = Field(gt=0)
    share_id: str = Field(min_length=8, max_length=64)


class RevokeBatchRequest(BaseModel):
    """批量撤销。调用方需要先完成二次确认。"""

    items: list[RevokeItem] = Field(min_length=1, max_length=50)


class SharePushResponse(BaseModel):
    """创建或重试的结果。share_url 只在这次响应中出现。"""

    share_id: str
    share_url: str | None
    url_is_absolute: bool
    bug_id: int
    bug_no: str
    channel_id: int | None
    channel_name: str
    allow_view: bool
    allow_resolve: bool
    expires_at: datetime | None
    visible_fields: list[str]
    notification_status: str
    error_message: str | None = None
    retry_count: int = 0


class BatchShareResponse(BaseModel):
    """批量推送结果。页面入口和投递状态按本批次返回。"""

    batch_share_id: str | None = None
    batch_share_url: str | None = None
    url_is_absolute: bool = True
    items: list["BatchShareItemResponse"]
    card_count: int = 1
    notification_status: str = "PENDING"
    error_message: str | None = None
    retry_count: int = 0
    duplicate_request: bool = False


class BatchShareItemResponse(BaseModel):
    """批次内单条分享历史；公开凭证只在批次入口中使用。"""

    share_id: str
    bug_id: int
    bug_no: str
    notification_status: str


class SharePreviewResponse(BaseModel):
    """推送确认框使用的预览，不含访问凭证。"""

    defect_count: int
    channel_name: str
    channel_enabled: bool
    webhook_configured: bool
    expires_label: str
    allow_resolve: bool
    visible_fields: list[str]
    message_preview: str
    public_url_valid: bool = True
    public_url_error: str | None = None


class ExternalActionResponse(BaseModel):
    """外部修复记录。姓名明确标记为自报。"""

    action_type: str
    old_status: str
    new_status: str
    actor_type: str
    actor_display_name: str | None
    repair_description: str
    fix_version: str | None
    commit_sha: str | None
    created_at: datetime
    identity_note: str


class ShareNotificationResponse(BaseModel):
    """某次飞书投递的结果，不包含 Webhook 地址。"""

    id: int
    status: str
    error_message: str | None
    retry_count: int
    sent_at: datetime | None
    created_at: datetime


class ShareSummaryResponse(BaseModel):
    """分享历史列表项。不包含可再次打开页面的凭证。"""

    share_id: str
    bug_id: int
    channel_id: int | None
    channel_name: str
    pushed_by_username: str | None
    pushed_at: datetime
    expires_at: datetime | None
    expires_label: str
    share_status: str
    allow_view: bool
    allow_resolve: bool
    view_count: int
    last_viewed_at: datetime | None
    resolution_status: str
    latest_resolution: ExternalActionResponse | None = None
    notification_status: str | None
    error_message: str | None
    retry_count: int
    batch_share_id: str | None = None


class ShareDetailResponse(ShareSummaryResponse):
    """单条分享详情，含推送快照、外部处理和投递记录。"""

    visible_fields: list[str]
    content_snapshot: dict[str, Any]
    external_actions: list[ExternalActionResponse]
    notifications: list[ShareNotificationResponse]


class ShareListResponse(BaseModel):
    """一个缺陷的分享历史。"""

    items: list[ShareSummaryResponse]


class PublicResolutionResponse(BaseModel):
    """公开页面上的修复结果。"""

    repair_description: str
    fix_version: str | None
    commit_sha: str | None
    actor_display_name: str | None
    actor_type: str
    old_status: str
    new_status: str
    submitted_at: datetime
    identity_note: str


class PublicDefectResponse(BaseModel):
    """公开缺陷详情。content 只含本次授权字段，live_status 始终是当前状态。"""

    share_state: Literal["active"] = "active"
    live_status: str
    allow_resolve: bool
    can_submit: bool
    expires_at: datetime | None
    content: dict[str, Any]
    resolution: PublicResolutionResponse | None = None
    identity_note: str


class PublicBatchItemResponse(BaseModel):
    share_id: str
    bug_no: str
    title: str | None
    severity_label: str | None
    status: str | None


class PublicBatchResponse(BaseModel):
    batch_state: Literal["active"] = "active"
    expires_at: datetime | None
    items: list[PublicBatchItemResponse]


class PublicResolveRequest(BaseModel):
    """开发人员提交已解决。姓名不是经过认证的身份。"""

    repair_description: str = Field(min_length=1, max_length=2000)
    fix_version: str | None = Field(default=None, max_length=80)
    commit_sha: str | None = Field(default=None, max_length=64)
    reporter_name: str | None = Field(default=None, max_length=40)


class PublicResolveResponse(BaseModel):
    """提交结果。重复提交不会再次改变状态。"""

    live_status: str
    idempotent: bool
    message: str
    repair_description: str | None
    submitted_at: datetime | None
    actor_display_name: str | None


class ArchiveExpiredResponse(BaseModel):
    """过期分享归档数量。"""

    archived: int
