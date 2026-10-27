"""Agent Tool 层：飞书通知（§三二）。

Agent **不写飞书 HTTP 逻辑**（§三二）。`send_report_notification` 包装
`FeishuNotificationService`（解密 webhook → 卡片 → 签名 → httpx POST → 记录），
渠道加载与鉴权走 `ChannelService`。通知失败只记 NotificationRecord，**不改
TestRun / Report 状态**（§二十八 三者独立）。

渠道解析：显式 channel_id 优先（同项目校验），否则取项目首个 enabled 渠道；都没有则
跳过（不报错，返回 skipped）——符合「无渠道不发」的安全默认。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.features.notifications.models.channel import NotificationChannel
from app.features.notifications.services import ChannelService, FeishuNotificationService
from app.features.reports.services import ReportService
from app.features.test_management.services._access import require_writable_project
from app.models.identity import User
from app.shared.errors import not_found

_CHANNEL = ChannelService()
_REPORT = ReportService()
_FEISHU = FeishuNotificationService()


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

    鉴权：报告 viewer+（get_report_orm）→ 触发外发升级 member+（require_writable_project）。
    """
    report = _REPORT.get_report_orm(db, report_id, user)  # viewer+ 及以上角色无权访问时返回 404
    require_writable_project(db, report.project_id, user)  # member+ 触发外发
    if report.project_id != project_id:
        raise not_found("测试报告不存在")
    channel = resolve_channel(db, report.project_id, user, channel_id=channel_id)
    if channel is None:
        # 无启用渠道：跳过而非失败（安全默认，§二十八）。
        return {
            "record_id": None, "status": "SUCCESS", "error_message": "未配置启用的通知渠道，已跳过",
            "skipped": True, "channel_name": None,
        }
    record = _FEISHU.send_report_notification(db, channel, report, actor_id=user.id)
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
