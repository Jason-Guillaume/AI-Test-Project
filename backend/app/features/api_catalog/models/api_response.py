"""接口响应（API Response）ORM 模型。

按 HTTP status_code 保存每个响应：status_code / description / schema_json / example_json。
后续 Agent 会根据这些响应字段自动生成断言。feature-local 表，由迁移 0003 显式建立。
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class ApiResponse(Base):
    """接口响应（按 status_code 保存结构）。"""

    __tablename__ = "api_response"
    __table_args__ = (
        Index("ix_api_response_interface_status", "interface_id", "status_code"),
        {"comment": "接口响应（按 HTTP status_code 保存结构）"},
    )
    # (interface_id, status_code) 复合索引：详情页按状态码定位响应结构。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    interface_id = Column(
        Integer,
        ForeignKey("api_interface.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属接口ID",
    )
    status_code = Column(Integer, nullable=False, comment="HTTP 状态码，如 200/400/500")
    description = Column(String(500), nullable=True, comment="响应描述")
    schema_json = Column(JSON, nullable=True, comment="响应 JSON Schema 结构")
    example_json = Column(Text, nullable=True, comment="响应示例 JSON 文本")
    sort = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="排序"
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )
