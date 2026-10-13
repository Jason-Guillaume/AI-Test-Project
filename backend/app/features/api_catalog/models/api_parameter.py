"""接口请求参数（API Parameter）ORM 模型。

统一保存 PATH/QUERY/HEADER/COOKIE/BODY 五类参数（BODY 行用于 form/multipart 字段级；
JSON body 结构树见 api_request_body）。每参数带 name/location/type/required/
description/example/default_value/schema_json。

feature-local 表，由迁移 0003 显式建立。
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func, text

from app.shared.database import Base


class ApiParameter(Base):
    """接口请求参数（PATH/QUERY/HEADER/COOKIE/BODY）。"""

    __tablename__ = "api_parameter"
    __table_args__ = (
        Index("ix_api_parameter_interface_location", "interface_id", "location"),
        {"comment": "接口请求参数（PATH/QUERY/HEADER/COOKIE/BODY）"},
    )
    # (interface_id, location) 复合索引：按接口分组、按参数位置过滤是详情页主查询形状。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    interface_id = Column(
        Integer,
        ForeignKey("api_interface.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属接口ID",
    )
    name = Column(String(100), nullable=False, comment="参数名")
    location = Column(
        String(10), nullable=False, comment="位置：PATH/QUERY/HEADER/COOKIE/BODY"
    )
    type = Column(String(30), nullable=False, default="string", server_default=text("'string'"),
                  comment="参数类型")
    required = Column(
        Boolean, nullable=False, default=False, server_default=text("false"), comment="是否必填"
    )
    description = Column(String(500), nullable=True, comment="参数描述")
    example = Column(Text, nullable=True, comment="示例值")
    default_value = Column(Text, nullable=True, comment="默认值")
    schema_json = Column(JSON, nullable=True, comment="参数 schema（含 enum/嵌套结构等）")
    sort = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="同位置内排序"
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
