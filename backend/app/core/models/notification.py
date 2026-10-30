"""用户通知收件箱。

旧项目只有通知模板 / 配置 / 订阅，没有收件箱表，因此个人通知列表页面无法落地。
这里补齐最小收件箱模型，保留项目作用域与已读状态。
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class Notification(Base):
    """发送给单个用户的平台通知。"""

    __tablename__ = "notification"
    __table_args__ = (
        Index("ix_notification_user_read_created", "user_id", "is_read", "created_at"),
        {"comment": "用户通知收件箱"},
    )
    # (user_id, is_read, created_at) 复合索引就是收件箱列表的主查询形状：
    # 先按收件人取、再区分已读/未读、最后按时间倒序分页。

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    # 收件人维度：一行只发给一个人；删除用户时连带清掉其收件箱（CASCADE）。
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=True, index=True)
    organization_id = Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=True, index=True)
    # 两个作用域都可为空：为空表示平台级通知（不归属任何项目/组织）；
    # 按项目或按组织筛选时，这两列就是可见性边界的一部分。
    event_type = Column(String(100), nullable=False, index=True, comment="事件类型")
    title = Column(String(200), nullable=False, comment="标题")
    body = Column(Text, nullable=True, comment="正文")
    payload = Column(JSON, nullable=True, comment="结构化上下文")
    is_read = Column(Boolean, nullable=False, default=False, server_default=text("false"), index=True,
                     comment="是否已读")
    # 已读状态由 is_read 与 read_at 成对维护：标记已读时应同时写入 read_at，
    # 恢复未读时应清空 read_at，避免两列不一致。
    read_at = Column(DateTime, nullable=True, comment="已读时间")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
