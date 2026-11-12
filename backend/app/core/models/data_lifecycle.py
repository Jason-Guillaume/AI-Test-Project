"""Central recycle-bin catalogue and append-only lifecycle audit facts."""

from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.core.database.base import Base


class RecycleBinItem(Base):
    """One deletion cycle for a soft-deleted domain row; intentionally has no resource FK."""

    __tablename__ = "recycle_bin_item"
    __table_args__ = (
        Index("ix_recycle_bin_scope_deleted", "project_id", "deletion_status", "deleted_at"),
        Index("ix_recycle_bin_resource", "resource_type", "resource_id"),
        {"comment": "统一回收站目录；保留原业务表主键，不建立跨域资源外键"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_type = Column(String(80), nullable=False, index=True)
    resource_id = Column(String(64), nullable=False)
    display_name = Column(String(500), nullable=False)
    project_id = Column(Integer, nullable=True, index=True)
    organization_id = Column(Integer, nullable=True, index=True)
    deleted_by = Column(Integer, nullable=True, index=True)
    deleted_by_name = Column(String(100), nullable=True)
    deleted_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    deletion_reason = Column(String(500), nullable=True)
    deletion_batch_id = Column(String(36), nullable=False, index=True)
    deletion_status = Column(String(20), nullable=False, server_default="ACTIVE", index=True)
    metadata_json = Column(JSON, nullable=False, default=dict, server_default="{}")
    restored_by = Column(Integer, nullable=True)
    restored_at = Column(DateTime, nullable=True)
    last_restore_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class LifecycleAuditEvent(Base):
    """Append-only event row; actor and resource references intentionally survive deletion."""

    __tablename__ = "data_lifecycle_audit_event"
    __table_args__ = (
        Index("ix_lifecycle_audit_resource", "resource_type", "resource_id", "created_at"),
        Index("ix_lifecycle_audit_batch", "deletion_batch_id", "created_at"),
        {"comment": "数据删除、恢复与物理清理的不可变审计事件"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(20), nullable=False)
    result = Column(String(20), nullable=False, server_default="SUCCEEDED")
    resource_type = Column(String(80), nullable=False)
    resource_id = Column(String(64), nullable=False)
    recycle_bin_item_id = Column(Integer, nullable=True)
    project_id = Column(Integer, nullable=True)
    organization_id = Column(Integer, nullable=True)
    actor_id = Column(Integer, nullable=True)
    deletion_batch_id = Column(String(36), nullable=True)
    reason = Column(String(500), nullable=True)
    detail = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
