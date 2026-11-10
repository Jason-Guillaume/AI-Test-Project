from sqlalchemy import Boolean, Column, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from app.core.database.base import Base

class KnowledgeBase(Base):
    __tablename__ = 'knowledge_base'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('project.id'), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)

class KnowledgeDocument(Base):
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
    revision = Column(Integer, nullable=False, default=1)
    scopes = Column(JSON, nullable=False, default=list)
