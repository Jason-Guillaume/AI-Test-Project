"""业务状态定义（Business State）ORM 模型。

第一阶段提供基础 Business State 配置：每个 Business Action 可对一个业务实体定义
前置状态（Pre State）与后置状态（Post State），为后续 Agent 生成状态测试用例提供数据基础。

例如「执行任务」动作：Pre=CREATED，Post=RUNNING。
第一阶段只做配置、保存与展示，不实现完整状态机引擎。

feature-local 表，由迁移 0004 建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.shared.database import Base


class BusinessState(Base):
    """业务动作对某实体的前置/后置状态定义。"""

    __tablename__ = "business_state"
    __table_args__ = (
        UniqueConstraint("action_id", "entity", name="uq_business_state_action_entity"),
        {"comment": "业务动作对某实体的前置/后置状态定义"},
    )
    # 唯一约束 (action_id, entity)：同一动作对同一实体只定义一组 Pre/Post 状态。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    action_id = Column(
        Integer,
        ForeignKey("business_action.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属业务动作ID",
    )
    entity = Column(
        String(100), nullable=False,
        comment="状态所属实体，如 task / project",
    )
    pre_state = Column(
        String(50), nullable=True,
        comment="前置状态，如 CREATED；为空表示无前置约束",
    )
    post_state = Column(
        String(50), nullable=True,
        comment="后置状态，如 RUNNING；为空表示无后置转换",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
