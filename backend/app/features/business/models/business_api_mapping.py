"""API 输入映射（Business API Mapping）ORM 模型。

建立 Business Action 的业务变量与所绑定 API 接口参数之间的映射关系。

INPUT 示例：business.project_id → BODY.project_id；business.token → HEADER.Authorization
OUTPUT 示例：response.data.id（JSONPath $.data.id）→ business.task_id

direction ∈ {INPUT, OUTPUT}；api_location ∈ {BODY, HEADER, QUERY, PATH, RESPONSE}。
第一阶段 OUTPUT 使用 JSONPath 表达式（expression 字段，如 $.data.id）。
feature-local 表，由迁移 0004 建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.shared.database import Base


class BusinessApiMapping(Base):
    """业务变量与绑定 API 接口参数之间的映射。"""

    __tablename__ = "business_api_mapping"
    __table_args__ = (
        UniqueConstraint(
            "binding_id", "direction", "business_variable",
            name="uq_business_api_mapping_binding_dir_var",
        ),
        Index("ix_business_api_mapping_binding_direction", "binding_id", "direction"),
        {"comment": "业务变量与绑定 API 接口参数之间的映射"},
    )
    # 唯一约束 (binding_id, direction, business_variable)：同一绑定同方向下变量只映射一次。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    binding_id = Column(
        Integer,
        ForeignKey("business_binding.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属业务绑定ID",
    )
    direction = Column(
        String(10), nullable=False,
        comment="方向：INPUT/OUTPUT",
    )
    business_variable = Column(
        String(100), nullable=False, comment="业务变量名",
    )
    api_location = Column(
        String(20), nullable=False,
        comment="接口位置：INPUT 用 BODY/HEADER/QUERY/PATH；OUTPUT 用 RESPONSE",
    )
    api_field = Column(
        String(300), nullable=True,
        comment="接口字段路径，如 body.project_id / header.Authorization",
    )
    expression = Column(
        String(500), nullable=True,
        comment="OUTPUT 时使用 JSONPath 表达式，如 $.data.id",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
