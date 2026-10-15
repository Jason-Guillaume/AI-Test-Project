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

路由层编排多个 service（reports.ChannelService / ReportService / FeishuNotificationService），
不违反「feature 间不互 import service」红线——红线约束 service 之间，路由层是编排者。
权限：读 viewer+、写 member+、越权与不存在共用 404。端点统一 sync def；service owns commit。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.notifications.schemas_channel import (
    ChannelCreateRequest,
    ChannelListResponse,
    ChannelResponse,
    ChannelUpdateRequest,
    NotificationRecordListResponse,
    NotifyReportRequest,
    SendResultResponse,
)
from app.features.notifications.services import ChannelService, FeishuNotificationService
from app.features.reports.services import ReportService
from app.features.test_management.services._access import require_writable_project
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["通知渠道"])

# 服务无状态，路由层复用单例。
_CHANNEL = ChannelService()
_REPORT = ReportService()
_FEISHU = FeishuNotificationService()


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
    return _CHANNEL.list_channels(db, project_id, user, page=page, page_size=page_size)


@router.get("/notification-channels/{channel_id}", response_model=ChannelResponse, summary="通知渠道详情")
def get_channel(channel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _CHANNEL.get_channel(db, channel_id, user)


@router.patch("/notification-channels/{channel_id}", response_model=ChannelResponse, summary="编辑通知渠道")
def update_channel(
    channel_id: int, body: ChannelUpdateRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return _CHANNEL.update_channel(db, channel_id, body, actor=user)


@router.delete(
    "/notification-channels/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除通知渠道",
)
def delete_channel(channel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _CHANNEL.delete_channel(db, channel_id, user)
    return None


# --------------------------------------------------------------------------- 连通性测试 / 手动触发


@router.post(
    "/notification-channels/{channel_id}/test",
    response_model=SendResultResponse,
    summary="通知渠道连通性测试（发送测试卡片）",
)
def test_channel(channel_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
    # 路由层编排：报告 viewer+（get_report_orm）→ 触发外发升级 member+ → 渠道解析 → 发送。
    report = _REPORT.get_report_orm(db, report_id, user)
    require_writable_project(db, report.project_id, user)
    channel = _CHANNEL.resolve_channel(db, report.project_id, user, channel_id=body.channel_id)
    if channel is None:
        # 无启用渠道 → 跳过而非失败（与 Agent 路径同口径）。
        return SendResultResponse(
            record_id=None, status="SUCCESS",
            error_message="未配置启用的通知渠道，已跳过", skipped=True,
        )
    # 直接调 FeishuNotificationService（接收已加载 ORM 对象，不跨 feature import service）。
    record = _FEISHU.send_report_notification(db, channel, report, actor_id=user.id)
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
    # 报告 viewer+ 鉴权后取 project_id，再按报告维度查发送记录。
    report = _REPORT.get_report_orm(db, report_id, user)
    return _CHANNEL.list_records_for_report(
        db, report.project_id, report.id, page=page, page_size=page_size,
    )
