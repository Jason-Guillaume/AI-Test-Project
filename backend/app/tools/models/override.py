"""归属当前能力包的唯一 ORM 模型定义。"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class ToolDefinitionOverride(Base):
    """平台内置工具允许管理员维护的说明覆写。"""

    __tablename__ = "agent_tool_definition_override"

    tool_key = Column(String(120), primary_key=True)
    description = Column(Text, nullable=False, default="", server_default=text("''"))
    parameter_overrides_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    is_enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
