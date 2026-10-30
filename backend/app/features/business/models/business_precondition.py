"""业务动作前置条件（Business Precondition）ORM 模型。

每个 Business Action 可定义多个前置条件，用于声明执行该动作前需满足的业务前提。
第一阶段以结构化 + 文本方式保存（type/target/operator/expected_value）。

type ∈ {VARIABLE, STATE, BUSINESS, TEXT}：
- VARIABLE：某变量需满足条件
- STATE：某实体状态需满足（如 task.status = CREATED）
- BUSINESS：业务级前提（文本描述）
- TEXT：纯文本补充说明

feature-local 表，由迁移 0004 建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class BusinessPrecondition(Base):
    """业务动作前置条件：执行动作前需满足的业务前提。"""

    __tablename__ = "business_precondition"
    __table_args__ = (
        Index("ix_business_precondition_action_sort", "action_id", "sort"),
        {"comment": "业务动作前置条件"},
    )
    # (action_id, sort) 索引服务于按动作列出有序前置条件。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    action_id = Column(
        Integer,
        ForeignKey("business_action.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属业务动作ID",
    )
    type = Column(
        String(20), nullable=False,
        comment="前提类型：VARIABLE/STATE/BUSINESS/TEXT",
    )
    target = Column(
        String(200), nullable=False,
        comment="判断目标，如 task.status / project.id",
    )
    operator = Column(
        String(20), nullable=False, default="EQ", server_default=text("'EQ'"),
        comment="比较符：EQ/NE/IN/CONTAINS 等",
    )
    expected_value = Column(
        String(500), nullable=True,
        comment="期望值，如 CREATED；多值用逗号分隔",
    )
    description = Column(String(500), nullable=True, comment="前提说明")
    sort = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="排序值",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
