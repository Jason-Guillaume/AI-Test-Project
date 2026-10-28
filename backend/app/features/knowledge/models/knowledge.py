"""项目知识库数据模型。

文档逻辑身份、不可变版本、可定位分块和持久化解析作业分开保存；
原始文件只通过随机存储键定位，不使用用户提供的路径。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class KnowledgeBase(Base):
    """每个项目默认一个知识库。"""

    __tablename__ = "knowledge_base"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_knowledge_base_project"),
        {"comment": "项目业务知识库"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False, default="项目知识库", server_default=text("'项目知识库'"))
    description = Column(String(500), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class KnowledgeDocument(Base):
    """项目内文档身份及当前可用于新任务的版本。"""

    __tablename__ = "knowledge_document"
    __table_args__ = (
        Index("ix_knowledge_document_base_status", "knowledge_base_id", "status"),
        {"comment": "项目知识文档逻辑身份"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    category = Column(String(32), nullable=False)
    status = Column(String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"))
    active_version_id = Column(Integer, nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class KnowledgeDocumentVersion(Base):
    """原始文件的不可变版本与解析状态。"""

    __tablename__ = "knowledge_document_version"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_knowledge_document_version_number"),
        Index("ix_knowledge_document_version_status", "parse_status", "created_at"),
        {"comment": "项目知识文档版本"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("knowledge_document.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    file_name = Column(String(255), nullable=False)
    media_type = Column(String(120), nullable=False)
    file_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_key = Column(String(80), nullable=True)
    parser_version = Column(String(40), nullable=True)
    parse_status = Column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    parse_error = Column(String(1000), nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    parsed_at = Column(DateTime, nullable=True)


class KnowledgeChunk(Base):
    """保留标题层级与页码或段落位置的可检索正文块。"""

    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal", name="uq_knowledge_chunk_ordinal"),
        Index("ix_knowledge_chunk_version_heading", "document_version_id", "heading_path"),
        {"comment": "项目知识文档正文分块"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_version_id = Column(Integer, ForeignKey("knowledge_document_version.id", ondelete="CASCADE"), nullable=False)
    ordinal = Column(Integer, nullable=False)
    heading_path = Column(String(1000), nullable=True)
    locator = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    search_text = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class KnowledgeParseJob(Base):
    """文档解析队列项；应用重启后可从 PENDING 或过期租约恢复。"""

    __tablename__ = "knowledge_parse_job"
    __table_args__ = (
        Index("ix_knowledge_parse_job_queue", "status", "available_at", "id"),
        {"comment": "项目知识文档持久化解析作业"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_version_id = Column(Integer, ForeignKey("knowledge_document_version.id", ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    attempt_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    available_at = Column(DateTime, nullable=False, server_default=func.now())
    claimed_at = Column(DateTime, nullable=True)
    error_message = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
