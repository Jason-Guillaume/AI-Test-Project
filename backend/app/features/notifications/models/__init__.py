"""外发通知渠道与发送记录 ORM 模型集合（feature-local）。

与站内信 inbox（app/models/notification.py + shared/notify.py）区分：
- 站内信是面向用户的入站消息（user_id 维度）；
- NotificationChannel / NotificationRecord 是**外发**渠道配置与发送审计
 （project 维度，Feishu Webhook 等）。

由迁移 0008 显式建表，**不**加入 app/models/__init__.py（红线 17）。
"""
from app.features.notifications.models.channel import NotificationChannel
from app.features.notifications.models.notification_record import NotificationRecord

__all__ = ["NotificationChannel", "NotificationRecord"]
