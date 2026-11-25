from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text
from app.core.database.base import Base
from app.core.database.soft_delete import SoftDeleteBase

class KnowledgeBase(SoftDeleteBase):
    __tablename__ = 'knowledge_base'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('project.id'), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)

class KnowledgeDocument(SoftDeleteBase):
    __tablename__ = 'knowledge_document'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('project.id'), nullable=False, index=True)
    base_id = Column(Integer, ForeignKey('knowledge_base.id'), nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False, default='')
    enabled = Column(Boolean, nullable=False, default=True)
    current_version_id = Column(Integer)

class KnowledgeVersion(Base):
    __tablename__ = 'knowledge_document_version'
    __table_args__ = (UniqueConstraint('document_id', 'version'),)
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('knowledge_document.id'), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    digest = Column(String(64), nullable=False)
    filename = Column(String(255), nullable=False)
    content = Column(LargeBinary, nullable=False)
    status = Column(String(20), nullable=False, default='QUEUED')
    error = Column(String(500))
    attempts = Column(Integer, nullable=False, default=0)
    queued_at = Column(DateTime(timezone=True), server_default=func.now())
    chunking_version = Column(String(40))

class KnowledgeChunk(Base):
    __tablename__ = 'knowledge_chunk'
    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey('knowledge_document_version.id'), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    page = Column(Integer)
    text = Column(Text, nullable=False)

class KnowledgeBinding(Base):
    __tablename__ = 'project_agent_knowledge_binding'
    __table_args__ = (UniqueConstraint('project_id', 'agent_id'),)
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('project.id'), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey('agent_definition.id'), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    required = Column(Boolean, nullable=False, default=False)
    access_mode = Column(String(24), nullable=False, default='PROJECT_SHARED', server_default=text("'PROJECT_SHARED'"))
    revision = Column(Integer, nullable=False, default=1)
    scopes = Column(JSON, nullable=False, default=list)

# Index generations are immutable encoding spaces. A project points to one active
# generation; a second generation can be built without changing query behaviour.
from pgvector.sqlalchemy import Vector


class KnowledgeRetrievalConfig(Base):
    __tablename__ = 'knowledge_retrieval_config'
    project_id = Column(Integer, ForeignKey('project.id', ondelete='CASCADE'), primary_key=True)
    active_generation_id = Column(Integer, ForeignKey('knowledge_index_generation.id', ondelete='SET NULL'))
    rerank_revision_id = Column(Integer, ForeignKey('model_revision.id', ondelete='RESTRICT'))
    enabled = Column(Boolean, nullable=False, default=False, server_default=text('false'))
    bm25_candidates = Column(Integer, nullable=False, default=50, server_default=text('50'))
    vector_candidates = Column(Integer, nullable=False, default=50, server_default=text('50'))
    rerank_window = Column(Integer, nullable=False, default=30, server_default=text('30'))
    default_top_k = Column(Integer, nullable=False, default=8, server_default=text('8'))
    timeout_seconds = Column(Integer, nullable=False, default=10, server_default=text('10'))
    fusion_min_score = Column(Float)
    rerank_min_score = Column(Float)


class KnowledgeIndexGeneration(Base):
    __tablename__ = 'knowledge_index_generation'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('project.id', ondelete='CASCADE'), nullable=False, index=True)
    embedding_revision_id = Column(Integer, ForeignKey('model_revision.id', ondelete='RESTRICT'), nullable=False)
    dimension = Column(Integer, nullable=False)
    distance = Column(String(16), nullable=False)
    encoding_version = Column(String(200), nullable=False)
    document_input_type = Column(String(100))
    query_input_type = Column(String(100))
    state = Column(String(20), nullable=False, default='BUILDING', server_default=text("'BUILDING'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class KnowledgeVector(Base):
    __tablename__ = 'knowledge_vector'
    __table_args__ = (UniqueConstraint('generation_id', 'chunk_id', name='uq_knowledge_vector_generation_chunk'),)
    id = Column(Integer, primary_key=True)
    generation_id = Column(Integer, ForeignKey('knowledge_index_generation.id', ondelete='CASCADE'), nullable=False, index=True)
    chunk_id = Column(Integer, ForeignKey('knowledge_chunk.id', ondelete='CASCADE'), nullable=False, index=True)
    embedding = Column(Vector().with_variant(JSON(), 'sqlite'), nullable=False)


class KnowledgeIndexJob(Base):
    __tablename__ = 'knowledge_index_job'
    __table_args__ = (UniqueConstraint('generation_id', 'chunk_id', name='uq_knowledge_index_job_generation_chunk'),)
    id = Column(Integer, primary_key=True)
    generation_id = Column(Integer, ForeignKey('knowledge_index_generation.id', ondelete='CASCADE'), nullable=False, index=True)
    chunk_id = Column(Integer, ForeignKey('knowledge_chunk.id', ondelete='CASCADE'), nullable=False, index=True)
    status = Column(String(20), nullable=False, default='QUEUED', server_default=text("'QUEUED'"), index=True)
    attempts = Column(Integer, nullable=False, default=0, server_default=text('0'))
    next_attempt_at = Column(DateTime(timezone=True))
    lease_token = Column(String(64))
    lease_until = Column(DateTime(timezone=True))
    error = Column(String(200))
    queued_at = Column(DateTime(timezone=True), server_default=func.now())
