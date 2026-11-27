"""缺陷积压提醒去重记录。

同一项目、同一收件人、同一提醒类型、同一业务日只允许一条记录；
唯一约束是跨进程并发扫描的最终防线。业务日按北京时间（UTC+8）计算，
具体换算集中在 reminder_worker 中。
"""

from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func

from app.core.database.base import Base


class DefectReminderDispatch(Base):
    """一次已经成功写入通知的提醒投递；与收件箱通知同事务提交。"""

    __tablename__ = "defect_reminder_dispatch"
    __table_args__ = (
        # 项目 + 收件人 + 类型 + 业务日：同日重复扫描或多实例并发只会留下一条。
        Index(
            "uq_defect_reminder_dispatch_day",
            "project_id", "recipient_id", "reminder_type", "business_date",
            unique=True,
        ),
        Index(
            "ix_defect_reminder_dispatch_project_date",
            "project_id", "business_date",
        ),
        {"comment": "缺陷积压提醒去重：项目/收件人/类型/业务日唯一"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="项目ID",
    )
    recipient_id = Column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="收件人ID；用户删除时一并清理",
    )
    reminder_type = Column(
        String(30), nullable=False, default="STALE_BACKLOG",
        comment="提醒类型，当前仅 STALE_BACKLOG",
    )
    business_date = Column(
        Date, nullable=False, comment="业务日（北京时间 UTC+8）",
    )
    notification_id = Column(
        Integer, ForeignKey("notification.id", ondelete="SET NULL"),
        nullable=True, comment="实际写入的站内通知ID，便于回溯",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())