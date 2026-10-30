"""业务规则（Business Rule）ORM 模型。

允许给项目、业务流程或业务动作配置业务规则（如「一条任务只有 CREATED 状态才能执行」
「同一个项目最多运行5个任务」）。第一阶段主要用于人工维护业务知识，暂时不需要自动执行。

规则可挂在三个层级：project_id 必填；flow_id / action_id 可选（为空表示项目级规则）。
feature-local 表，由迁移 0004 建立。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class BusinessRule(Base):
    """业务规则：项目/流程/动作级业务知识配置。"""

    __tablename__ = "business_rule"
    __table_args__ = ({"comment": "业务规则：项目/流程/动作级业务知识配置"},)
    # project_id / flow_id / action_id 均在列定义上带 index=True（单列索引足够），
    # 不再额外声明同名显式 Index，避免与 index=True 产生重复索引。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID（规则至少属于一个项目）",
    )
    flow_id = Column(
        Integer,
        ForeignKey("business_flow.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属业务流程ID；为空表示项目级规则",
    )
    action_id = Column(
        Integer,
        ForeignKey("business_action.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属业务动作ID；为空表示流程/项目级规则",
    )
    name = Column(String(200), nullable=False, comment="规则名称")
    description = Column(String(1000), nullable=True, comment="规则描述")
    rule_type = Column(
        String(30), nullable=False, default="GENERAL", server_default=text("'GENERAL'"),
        comment="规则类型，如 GENERAL/CONSTRAINT/PRECONDITION",
    )
    expression = Column(
        Text, nullable=True,
        comment="规则表达式（第一阶段仅人工维护，不自动执行）",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
