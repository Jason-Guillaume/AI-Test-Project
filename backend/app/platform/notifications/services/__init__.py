"""通知服务层。

- channel_service.ChannelService：渠道 CRUD（webhook/secret 加密存储、响应脱敏）+ 连通性测试；
- feishu_service.FeishuNotificationService：飞书卡片构造 / 签名 / httpx 发送 / 发送记录审计。

发送失败只记 NotificationRecord(status=FAILED)，不改 TestRun / Report 状态（§二十八 三者独立）。
"""
from app.platform.notifications.services.channel_service import ChannelService
from app.platform.notifications.services.feishu_service import FeishuNotificationService

__all__ = ["ChannelService", "FeishuNotificationService"]
