"""缺陷免登录分享与外部处理记录。

对外只暴露不可猜测的 share_id。访问凭证的明文不入库，只保存 SHA-256。
分享行记录推送时允许公开的字段快照；外部处理行记录免登录提交的修复说明。
本模块不替代缺陷状态服务，状态变更仍由 DefectService 完成。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class DefectShareLink(Base):
    """一条独立的缺陷分享。不同群聊即使指向同一缺陷，也各自持有凭证。"""

    __tablename__ = "defect_share_link"
    __table_args__ = (
        UniqueConstraint("share_id", name="uq_defect_share_link_share_id"),
        UniqueConstraint("token_hash", name="uq_defect_share_link_token_hash"),
        Index("uq_defect_share_link_request_key", "request_key", unique=True),
        {"comment": "缺陷免登录分享：只保存访问凭证哈希"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    share_id = Column(String(64), nullable=False, comment="公开标识，不能当作访问凭证")
    bug_id = Column(Integer, ForeignKey("bug.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(
        Integer, ForeignKey("notification_channel.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="推送时选择的飞书渠道；渠道删除后分享仍保留",
    )
    token_hash = Column(String(64), nullable=False, comment="访问凭证的 SHA-256，十六进制")
    batch_id = Column(Integer, ForeignKey("defect_share_batch.id", ondelete="SET NULL"), nullable=True, index=True)
    request_key = Column(String(100), nullable=True, comment="创建确认请求幂等键")
    payload_hash = Column(String(64), nullable=True, comment="幂等请求载荷摘要")
    allow_view = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    allow_resolve = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    visible_fields = Column(JSON, nullable=False, comment="本次允许公开的字段名")
    content_snapshot = Column(JSON, nullable=False, comment="推送时已脱敏的公开内容快照")
    expires_at = Column(DateTime, nullable=True, index=True, comment="空表示永久有效")
    revoked_at = Column(DateTime, nullable=True, comment="撤销时间")
    archived_at = Column(DateTime, nullable=True, comment="过期后的归档时间")
    pushed_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    pushed_at = Column(DateTime, nullable=False, server_default=func.now())
    retry_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    view_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    last_viewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class DefectShareBatch(Base):
    """一次多缺陷分享入口与一次飞书投递。"""

    __tablename__ = "defect_share_batch"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_defect_share_batch_public_id"),
        UniqueConstraint("token_hash", name="uq_defect_share_batch_token_hash"),
        UniqueConstraint("request_key", name="uq_defect_share_batch_request_key"),
        {"comment": "多缺陷免登录分享批次"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(64), nullable=False)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(Integer, ForeignKey("notification_channel.id", ondelete="SET NULL"), nullable=True, index=True)
    token_hash = Column(String(64), nullable=False)
    request_key = Column(String(100), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    allow_view = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    allow_resolve = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    expires_at = Column(DateTime, nullable=True, index=True)
    revoked_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    pushed_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    pushed_at = Column(DateTime, nullable=False, server_default=func.now())
    delivery_status = Column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    retry_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class DefectExternalAction(Base):
    """免登录分享提交的修复记录。actor_id 故意不存在，避免伪造内部用户。"""

    __tablename__ = "defect_external_action"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_defect_external_action_idempotency"),
        {"comment": "免登录分享产生的缺陷处理记录"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bug_id = Column(Integer, ForeignKey("bug.id", ondelete="CASCADE"), nullable=False, index=True)
    share_link_id = Column(
        Integer, ForeignKey("defect_share_link.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    action_type = Column(String(32), nullable=False, comment="目前仅 RESOLVE")
    old_status = Column(String(20), nullable=False)
    new_status = Column(String(20), nullable=False)
    actor_type = Column(String(32), nullable=False, comment="固定 EXTERNAL_SHARE")
    actor_display_name = Column(String(40), nullable=True, comment="开发人员自报姓名，未经认证")
    repair_description = Column(Text, nullable=False)
    fix_version = Column(String(80), nullable=True)
    commit_sha = Column(String(64), nullable=True)
    idempotency_key = Column(String(120), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
