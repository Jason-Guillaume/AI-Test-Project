"""项目级执行环境配置。"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class ProjectEnvironment(Base):
    """项目与环境模板之间的绑定；目标地址与默认请求头由项目独立维护。"""

    __tablename__ = "project_environment"
    __table_args__ = (
        UniqueConstraint("project_id", "environment_id", name="uq_project_environment_project_env"),
        Index("ix_project_environment_project_active", "project_id", "is_active"),
        {"comment": "项目级执行环境及其目标服务配置"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environment.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name = Column(String(100), nullable=False, default="", server_default=text("''"))
    base_url = Column(String(500), nullable=False, default="", server_default=text("''"))
    gateway_prefix = Column(String(200), nullable=False, default="", server_default=text("''"))
    default_headers = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False, server_default=text("false"), index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"), index=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
