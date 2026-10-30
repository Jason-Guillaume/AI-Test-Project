"""外发通知渠道 ORM 模型（NotificationChannel）。

一个渠道 = 一个项目的某个外发目标（Phase 2 第一阶段仅 FEISHU_WEBHOOK）。
config_json 存渠道配置：webhook_url 与 secret **加密后**入库（Fernet，见
app/shared/crypto.py），keyword / mention_all / notify_condition 为明文配置项。

安全约束（§十五、§三十四）：
- webhook_url / secret 不得进入 Agent Prompt、Report、前端普通响应；
- 读取时只在 FeishuNotificationService 发送瞬间解密，绝不记日志 / 不入 NotificationRecord；
- 对外响应只回脱敏形式（configured=true 或 https://open.feishu.cn/...****）。

notify_condition ∈ {ALWAYS, ONLY_FAILED, ONLY_HIGH_RISK}（§十七），存于 config_json。

feature-local 表，由迁移 0008 显式建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Boolean
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class NotificationChannel(Base):
    """外发通知渠道（如飞书 Webhook 机器人），按项目隔离。"""

    __tablename__ = "notification_channel"
    # 索引由下方 Column(index=True) 生成，命名与迁移 0008 的 ix_notification_channel_* 一致，
    # 不再显式声明 Index（否则 ORM 元数据会多出重复索引名，与迁移产物不一致）。
    __table_args__ = ({"comment": "外发通知渠道（飞书 Webhook 等）：webhook/secret 加密存储"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    name = Column(String(100), nullable=False, comment="渠道名称（如「测试群机器人」）")
    channel_type = Column(
        String(30), nullable=False, default="FEISHU_WEBHOOK",
        server_default=text("'FEISHU_WEBHOOK'"), comment="渠道类型：FEISHU_WEBHOOK",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用",
    )
    config_json = Column(
        # webhook_url/secret 加密后存此 JSON；keyword/mention_all/notify_condition 明文。
        JSON, nullable=True, comment="渠道配置（webhook_url/secret 加密，其余明文）",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人ID")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
