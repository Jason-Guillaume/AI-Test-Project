"""Data Provider ORM 模型：数据工厂的可复用造数配置。

provider_type：STATIC / ENVIRONMENT / FAKER / API_CREATE / BUSINESS_ACTION /
BUSINESS_FLOW / EXISTING_POOL / DATABASE_INSERT / DATABASE_PATCH。

config_json 里的密码字段禁止出现；数据库操作只存 connection_id。
模型 feature-local，不进 app/models/__init__.py；由 alembic 0009 显式建表。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class DataProvider(Base):
    """数据工厂 Provider 配置。"""

    __tablename__ = "data_provider"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_data_provider_project_name"),
        Index("ix_data_provider_project_type", "project_id", "provider_type", "enabled"),
        {"comment": "数据工厂 Provider 配置（config_json 禁止密码，连接只存 connection_id）"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    name = Column(String(200), nullable=False, comment="Provider 名称")
    provider_type = Column(
        String(30), nullable=False,
        comment="STATIC/ENVIRONMENT/FAKER/API_CREATE/BUSINESS_ACTION/BUSINESS_FLOW/"
        "EXISTING_POOL/DATABASE_INSERT/DATABASE_PATCH",
    )
    config_json = Column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
        comment="Provider 配置（Pydantic 按 type 校验，extra=forbid 禁止 sql 等键）",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用",
    )
    risk_level = Column(
        String(20), nullable=False, default="MEDIUM", server_default=text("'MEDIUM'"),
        comment="风险等级：LOW/MEDIUM/HIGH/CRITICAL",
    )
    description = Column(String(1000), nullable=True, comment="描述")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
