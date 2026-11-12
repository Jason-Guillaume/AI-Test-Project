"""Mapped base and query filtering for resources that support recovery."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database.base import Base


class SoftDeleteBase(Base):
    """Abstract base for individually audited, recoverable business resources."""

    __abstract__ = True

    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")
    deleted_by = Column(Integer, ForeignKey("user.id", name="fk_soft_delete_deleted_by_user", ondelete="SET NULL"), nullable=True,
                         comment="删除操作人")
    deletion_reason = Column(String(500), nullable=True, comment="删除原因")
    deletion_batch_id = Column(String(36), nullable=True, comment="删除批次 ID")
