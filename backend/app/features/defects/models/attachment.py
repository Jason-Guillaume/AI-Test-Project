"""缺陷附件，内容与缺陷一起保存在数据库中。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.sql import func
from app.core.database.base import Base


class BugAttachment(Base):
    __tablename__ = 'bug_attachment'
    id = Column(Integer, primary_key=True)
    bug_id = Column(Integer, ForeignKey('bug.id', ondelete='CASCADE'), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(255), nullable=False)
    content = Column(LargeBinary, nullable=False)
    size = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
