"""归属当前能力包的唯一 ORM 模型定义。"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class MCPServer(Base):
    """MCP 服务登记；仅缓存发现结果，不自动授予工具执行权限。"""

    __tablename__ = "mcp_server"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    endpoint = Column(String(1000), nullable=False)
    auth_type = Column(String(20), nullable=False, default="none", server_default=text("'none'"))
    auth_secret_encrypted = Column(Text, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"), index=True)
    connection_status = Column(String(20), nullable=False, default="unknown", server_default=text("'unknown'"))
    discovered_tools_json = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    approved_tools_json = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    last_checked_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
