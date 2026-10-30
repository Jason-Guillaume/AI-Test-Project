"""业务动作输入/输出变量（Business Variable）ORM 模型。

每个 Business Action 可声明业务输入与输出变量。这些变量后续用于不同 Action 之间的
数据传递（通过 business_variable_ref 建立引用）。

direction ∈ {INPUT, OUTPUT}；data_type ∈ {STRING, INTEGER, NUMBER, BOOLEAN, OBJECT, ARRAY}。
第一阶段只做配置与展示，不执行真正的数据传递。

feature-local 表，由迁移 0004 建立。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class BusinessVariable(Base):
    """业务动作输入/输出变量。"""

    __tablename__ = "business_variable"
    __table_args__ = (
        UniqueConstraint("action_id", "direction", "name", name="uq_business_variable_action_dir_name"),
        Index("ix_business_variable_action_direction", "action_id", "direction"),
        {"comment": "业务动作输入/输出变量"},
    )
    # 唯一约束 (action_id, direction, name)：同一动作同方向下变量名不重复。
    # (action_id, direction) 索引服务于按动作列出输入/输出变量。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    action_id = Column(
        Integer,
        ForeignKey("business_action.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属业务动作ID",
    )
    direction = Column(
        String(10), nullable=False,
        comment="方向：INPUT/OUTPUT",
    )
    name = Column(String(100), nullable=False, comment="变量名，如 project_id / task_id")
    data_type = Column(
        String(20), nullable=False, default="STRING", server_default=text("'STRING'"),
        comment="数据类型：STRING/INTEGER/NUMBER/BOOLEAN/OBJECT/ARRAY",
    )
    required = Column(
        Boolean, nullable=False, default=False, server_default=text("false"), comment="是否必填",
    )
    description = Column(String(500), nullable=True, comment="变量说明")
    sort = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="排序值",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
