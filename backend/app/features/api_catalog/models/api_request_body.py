"""接口请求体（API Request Body）ORM 模型。

与接口一对一：``interface_id`` 唯一。body_type ∈ {none, json, form, multipart, raw}。
JSON body 的结构树存 schema_json（JSON Schema 或字段树）；raw 文本存 raw_text。

feature-local 表，由迁移 0003 显式建立；ORM 列类型与迁移保持一致（JSON 列用 sa.JSON），
运行期 SQLAlchemy 据此读写 JSON 列。
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class ApiRequestBody(Base):
    """接口请求体（与接口一对一）。"""

    __tablename__ = "api_request_body"
    __table_args__ = ({"comment": "接口请求体（json/form/multipart/raw）"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    interface_id = Column(
        Integer,
        ForeignKey("api_interface.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="所属接口ID（一对一）",
    )
    # unique=True：一个接口至多一行请求体；接口删除时级联清除。
    body_type = Column(
        String(20), nullable=False, default="none", server_default=text("'none'"),
        comment="body类型：none/json/form/multipart/raw",
    )
    content_type = Column(String(100), nullable=True, comment="实际 Content-Type")
    schema_json = Column(
        JSON, nullable=True, comment="JSON Schema 树或 form/multipart 字段结构"
    )
    raw_text = Column(Text, nullable=True, comment="raw 文本体")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )
