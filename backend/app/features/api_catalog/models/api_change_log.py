"""接口变更记录（API Change Log）ORM 模型。

接口创建/更新/导入变更时写日志，供「变更记录」Tab 与后续 Agent 审计。
change_type ∈ {CREATED, UPDATED, PARAM_ADDED, PARAM_REMOVED, PARAM_TYPE_CHANGED,
REQUIRED_CHANGED, RESPONSE_CHANGED, MODULE_CHANGED}。feature-local 表，由迁移 0003 显式建立。
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.shared.database import Base


class ApiChangeLog(Base):
    """接口变更记录。"""

    __tablename__ = "api_change_log"
    __table_args__ = (
        Index("ix_api_change_log_interface_created", "interface_id", "created_at"),
        {"comment": "接口变更记录"},
    )
    # (interface_id, created_at) 复合索引：按接口倒序列变更历史，详情页「变更记录」Tab 主查询。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    interface_id = Column(
        Integer,
        ForeignKey("api_interface.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属接口ID",
    )
    change_type = Column(
        String(30), nullable=False, comment="变更类型：CREATED/UPDATED/PARAM_*/REQUIRED_CHANGED/RESPONSE_CHANGED/MODULE_CHANGED"
    )
    diff_json = Column(JSON, nullable=True, comment="变更明细（字段级 diff）")
    source_hash_before = Column(String(64), nullable=True, comment="变更前 source_hash")
    source_hash_after = Column(String(64), nullable=True, comment="变更后 source_hash")
    summary = Column(Text, nullable=True, comment="人类可读摘要")
    created_by = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="操作人ID",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
