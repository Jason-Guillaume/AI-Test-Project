"""外发通知发送记录 ORM 模型（NotificationRecord）。

记录每一次外发（飞书等）的投递审计：状态独立于 TestRun / TestReport（§二十八
「通知失败不能影响测试执行」）——例如 TestRun SUCCESS、Report COMPLETED、
Notification FAILED 三者互不影响。

status 常用值为 PENDING/SENDING/SUCCESS/FAILED，缺陷分享超时另标记 UNCERTAIN。
request_snapshot / response_snapshot 均为**脱敏后**的内容（§二十：消息进 Feishu
Service 前必须经 SensitiveDataMasker；webhook URL 本身绝不入此两字段）。

feature-local 表，由迁移 0008 显式建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class NotificationRecord(Base):
    """外发通知发送审计记录。"""

    __tablename__ = "notification_record"
    # 索引由下方 Column(index=True) 生成，命名与迁移 0008 的 ix_notification_record_* 一致，
    # 不再显式声明 Index（否则 ORM 元数据会多出重复索引名，与迁移产物不一致）。
    __table_args__ = ({"comment": "外发通知发送记录：状态独立于 TestRun/Report"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    channel_id = Column(
        # 渠道删除连带删发送记录（审计随渠道生命周期）。
        Integer,
        ForeignKey("notification_channel.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="发送渠道ID",
    )
    report_id = Column(
        # 报告删除不连带删发送记录（保留投递审计）；置空即可。
        Integer,
        ForeignKey("test_report.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联报告ID",
    )
    status = Column(
        String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"),
        index=True, comment="发送状态：PENDING/SUCCESS/FAILED",
    )
    request_snapshot = Column(JSON, nullable=True, comment="发送内容快照（脱敏后，不含 webhook URL）")
    response_snapshot = Column(JSON, nullable=True, comment="飞书响应快照")
    error_message = Column(Text, nullable=True, comment="失败原因")
    sent_at = Column(DateTime, nullable=True, comment="发送时间")
    # 缺陷分享复用同一条发送审计，报告通知这些列保持为空。
    bug_id = Column(
        Integer, ForeignKey("bug.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="关联缺陷ID",
    )
    share_link_id = Column(
        Integer, ForeignKey("defect_share_link.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="关联缺陷分享ID",
    )
    share_batch_id = Column(
        Integer, ForeignKey("defect_share_batch.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="关联多缺陷分享批次",
    )
    event_type = Column(String(40), nullable=True, comment="业务事件：defect.share 等")
    idempotency_key = Column(String(120), nullable=True, unique=True, comment="同一次投递的幂等键")
    retry_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="同一分享的重试次数",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
