"""通知渠道路由（飞书 Webhook 配置 / 测试 / 手动触发 / 发送审计）。

单 APIRouter（无自身前缀），挂在 /api/v1 下。资源级路径：
- POST   /projects/{project_id}/notification-channels            新建渠道（member+）
- GET    /projects/{project_id}/notification-channels            渠道列表（viewer+）
- GET    /notification-channels/{channel_id}                     渠道详情（viewer+，webhook 脱敏）
- PATCH  /notification-channels/{channel_id}                     编辑渠道（member+）
- DELETE /notification-channels/{channel_id}                     删除渠道（member+）
- POST   /notification-channels/{channel_id}/test                连通性测试（member+）
- POST   /reports/{report_id}/notify                             手动触发报告飞书通知（member+）
- GET    /notification-channels/{channel_id}/records             渠道发送记录（viewer+）
- GET    /reports/{report_id}/notifications                      报告发送记录（viewer+）

渠道 CRUD 交由 ChannelService，报告通知与记录查询交由 report_delivery 应用服务。
权限：读 viewer+、写 member+、越权与不存在共用 404。端点统一 sync def；service owns commit。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.platform.notifications.schemas_channel import (
    ChannelCreateRequest,
    ChannelListResponse,
    ChannelResponse,
    ChannelUpdateRequest,
    NotificationRecordListResponse,
    NotifyReportRequest,
    SendResultResponse,
)
from app.platform.notifications.services import ChannelService
from app.orchestration.report_delivery.service import ReportDeliveryService
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["通知渠道"])

# 服务无状态，路由层复用单例。
_CHANNEL = ChannelService()
_REPORT_DELIVERY = ReportDeliveryService()


# --------------------------------------------------------------------------- 渠道 CRUD


@router.post(
    "/projects/{project_id}/notification-channels",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建飞书通知渠道",
)
def create_channel(
    project_id: int, body: ChannelCreateRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建渠道。"""
    # webhook_url / secret 在 service 内加密入库，响应只回脱敏形式。
    return _CHANNEL.create_channel(db, project_id, body, actor=user)


@router.get(
    "/projects/{project_id}/notification-channels",
    response_model=ChannelListResponse,
    summary="项目通知渠道列表",
)
def list_channels(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """列出`channels`。"""
    return _CHANNEL.list_channels(db, project_id, user, page=page, page_size=page_size)


@router.get("/notification-channels/{channel_id}", response_model=ChannelResponse, summary="通知渠道详情")
def get_channel(channel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取渠道。"""
    return _CHANNEL.get_channel(db, channel_id, user)


@router.patch("/notification-channels/{channel_id}", response_model=ChannelResponse, summary="编辑通知渠道")
def update_channel(
    channel_id: int, body: ChannelUpdateRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新渠道。"""
    return _CHANNEL.update_channel(db, channel_id, body, actor=user)


@router.delete(
    "/notification-channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除通知渠道",
)
def delete_channel(channel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除渠道。"""
    _CHANNEL.delete_channel(db, channel_id, user)
    return None


# --------------------------------------------------------------------------- 连通性测试 / 手动触发


@router.post(
    "/notification-channels/{channel_id}/test",
    response_model=SendResultResponse,
    summary="通知渠道连通性测试（发送测试卡片）",
)
def test_channel(channel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """验证渠道场景及其预期结果。"""
    return _CHANNEL.test_channel(db, channel_id, user)


@router.post(
    "/reports/{report_id}/notify",
    response_model=SendResultResponse,
    summary="手动触发报告飞书通知",
)
def notify_report(
    report_id: int, body: NotifyReportRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """发送通知报告。"""
    record, channel = _REPORT_DELIVERY.deliver(
        db, project_id=None, report_id=report_id, user=user, channel_id=body.channel_id,
    )
    if channel is None:
        # 无启用渠道 → 跳过而非失败（与 Agent 路径同口径）。
        return SendResultResponse(
            record_id=None, status="SUCCESS",
            error_message="未配置启用的通知渠道，已跳过", skipped=True,
        )
    if record is None:
        # 渠道禁用或通知条件不满足 → 跳过，非失败（§十七）。
        return SendResultResponse(record_id=None, status="SUCCESS", error_message=None, skipped=True)
    return SendResultResponse(
        record_id=record.id, status=record.status, error_message=record.error_message, skipped=False,
    )


# --------------------------------------------------------------------------- 发送记录审计


@router.get(
    "/notification-channels/{channel_id}/records",
    response_model=NotificationRecordListResponse,
    summary="渠道的飞书通知发送记录",
)
def list_channel_records(
    channel_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """列出渠道记录。"""
    return _CHANNEL.list_records_by_channel(db, channel_id, user, page=page, page_size=page_size)


@router.get(
    "/reports/{report_id}/notifications",
    response_model=NotificationRecordListResponse,
    summary="报告的飞书通知发送记录",
)
def list_report_notifications(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """列出报告`notifications`。"""
    return _REPORT_DELIVERY.list_records(db, report_id, user, page=page, page_size=page_size)
