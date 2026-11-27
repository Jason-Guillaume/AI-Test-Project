"""缺陷 Excel 导入批次与预览状态模型。

保存预览阶段生成的标准化数据快照、预览标识（preview_token）及确认后的幂等回执。
协作模块：
- ``app.features.defects.services.excel_io_service`` 负责预览落库、行锁确认与重复文件检索；
- ``alembic/versions/0109_defect_import_batch.py`` 负责显式建表（不加入 core 基线模型）。

已知限制：
- 仅保存首版批量新建缺陷的预览与提交记录，不支持按已有缺陷 ID 更新。
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class DefectImportBatch(Base):
    """缺陷 Excel 导入预览与确认回执表。"""

    __tablename__ = "defect_import_batch"
    __table_args__ = (
        UniqueConstraint("preview_token", name="uq_defect_import_preview_token"),
        Index(
            "ix_defect_import_project_digest_status",
            "project_id",
            "content_digest",
            "status",
            "committed_at",
        ),
        Index("ix_defect_import_project_created", "project_id", "created_at"),
        {"comment": "缺陷 Excel 导入预览快照与确认幂等回执"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True, comment="导入批次编号")
    preview_token = Column(String(36), nullable=False, comment="预览标识（UUID），确认提交的唯一幂等键")
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        comment="目标项目ID",
    )
    created_by = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="预览与提交人ID",
    )
    status = Column(
        String(20),
        nullable=False,
        default="PREVIEW",
        server_default=text("'PREVIEW'"),
        comment="批次状态：PREVIEW 待确认 / COMMITTED 已提交",
    )
    file_name = Column(String(255), nullable=False, comment="原始上传文件名")
    file_hash = Column(String(64), nullable=False, comment="原始上传文件 SHA-256 摘要")
    content_digest = Column(String(64), nullable=False, comment="标准化导入数据的 SHA-256 摘要")
    row_count = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="待创建缺陷条数")
    payload_json = Column(JSON, nullable=False, comment="校验通过后的标准化行列表")
    result_json = Column(JSON, nullable=True, comment="确认提交后的幂等回执")
    expires_at = Column(DateTime, nullable=False, comment="预览有效期截止时间")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    committed_at = Column(DateTime, nullable=True, comment="确认提交时间")
