"""接口导入记录（API Import Record）ORM 模型。

每次批量导入确认后写一行，用于追踪接口来源。counts 与实际入库行对账。
feature-local 表，由迁移 0003 显式建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class ApiImportRecord(Base):
    """接口导入批次记录。"""

    __tablename__ = "api_import_record"
    __table_args__ = (
        Index("ix_api_import_record_project_created", "project_id", "created_at"),
        {"comment": "接口导入批次记录"},
    )
    # (project_id, created_at) 复合索引：按项目倒序列导入历史。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    source_type = Column(
        String(20), nullable=False, comment="来源：CURL/OPENAPI/SWAGGER/POSTMAN/APIFOX"
    )
    file_name = Column(String(300), nullable=True, comment="源文件名或标识")
    source_hash = Column(
        String(64), nullable=True, index=True, comment="整批内容 sha256，便于去重"
    )
    total = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="解析总条数"
    )
    created_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="新建数"
    )
    updated_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="更新数"
    )
    skipped_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="跳过数（含无变化）"
    )
    created_by = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="导入人ID",
    )
    # SET NULL：导入人账号被删时保留导入记录，只清操作者引用。
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
