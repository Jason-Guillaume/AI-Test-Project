"""Agent Tool 层：飞书通知（§三二）。

Agent **不写飞书 HTTP 逻辑**（§三二）。`send_report_notification` 调用报告投递应用服务，
通用传输器只接收卡片与通知渠道。通知失败只记 NotificationRecord，**不改
TestRun / Report 状态**（§二十八 三者独立）。

渠道解析：显式 channel_id 优先（同项目校验），否则取项目首个 enabled 渠道；都没有则
跳过（不报错，返回 skipped）——符合「无渠道不发」的安全默认。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.platform.notifications.models.channel import NotificationChannel
from app.platform.notifications.services import ChannelService
from app.orchestration.report_delivery.service import ReportDeliveryService
from app.core.models.identity import User

_CHANNEL = ChannelService()
_REPORT_DELIVERY = ReportDeliveryService()


def resolve_channel(
    db: Session, project_id: int, user: User, *, channel_id: int | None = None,
) -> NotificationChannel | None:
    """解析发送渠道：显式 channel_id 优先（须同项目），否则取项目首个 enabled 渠道。

    实现委托给 notifications 的 ChannelService.resolve_channel，保证 Agent 路径与
    REST 路由 /reports/{report_id}/notify 行为一致。
    """
    return _CHANNEL.resolve_channel(db, project_id, user, channel_id=channel_id)


def send_report_notification(
    db: Session, project_id: int, report_id: int, user: User, *, channel_id: int | None = None,
) -> dict[str, Any]:
    """触发报告飞书通知，返回脱敏结果（不含 webhook/sign）。

    鉴权、通知条件与卡片构建由报告投递应用服务统一负责。
    """
    record, channel = _REPORT_DELIVERY.deliver(
        db, project_id, report_id, user, channel_id=channel_id,
    )
    if channel is None:
        # 无启用渠道：跳过而非失败（安全默认，§二十八）。
        return {
            "record_id": None, "status": "SUCCESS", "error_message": "未配置启用的通知渠道，已跳过",
            "skipped": True, "channel_name": None,
        }
    if record is None:
        # 渠道禁用或通知条件不满足 → 跳过（§十七），非失败。
        return {
            "record_id": None, "status": "SUCCESS",
            "error_message": "通知条件不满足或渠道禁用，已跳过",
            "skipped": True, "channel_name": channel.name,
        }
    return {
        "record_id": record.id, "status": record.status,
        "error_message": record.error_message, "skipped": False, "channel_name": channel.name,
    }


from app.tools.registry import bind_module_handlers

bind_module_handlers(globals(), {
    'resolve_channel': ('runtime.notifications.resolve_channel', 'read'),
    'send_report_notification': ('runtime.notifications.send_report_notification', 'high_risk'),
})
