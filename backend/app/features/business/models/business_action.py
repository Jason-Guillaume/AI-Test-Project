"""业务动作（Business Action）ORM 模型。

业务动作是业务管理的核心：一个不可分割的业务步骤（如「登录」「创建任务」「执行任务」）。
action_key 是稳定业务标识（LOGIN/CREATE_TASK 等），不依赖具体接口 ID——这是业务层与
执行方式解耦的关键：同一个 action 将来可绑定 API 或 Web 通道。

sort 决定在流程中的顺序；当前执行器只支持普通顺序动作。feature-local 表，由迁移 0004 建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class BusinessAction(Base):
    """业务动作：业务流程中一个不可分割的业务步骤。"""

    __tablename__ = "business_action"
    __table_args__ = (
        UniqueConstraint("flow_id", "action_key", name="uq_business_action_flow_key"),
        Index("ix_business_action_flow_sort", "flow_id", "sort"),
        {"comment": "业务动作：业务流程中一个不可分割的业务步骤"},
    )
    # 唯一约束 (flow_id, action_key)：同一流程内 action_key 唯一，作为稳定业务标识。
    # (flow_id, sort) 索引服务于按流程列出有序步骤。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    flow_id = Column(
        Integer,
        ForeignKey("business_flow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属业务流程ID",
    )
    # flow_id 带 ondelete=CASCADE：流程被删除时其下动作及子配置一并清理。
    name = Column(String(200), nullable=False, comment="动作名称")
    description = Column(String(1000), nullable=True, comment="动作描述")
    action_key = Column(
        String(100), nullable=False, index=True,
        comment="稳定业务标识，如 LOGIN/CREATE_TASK/RUN_TASK，不依赖接口ID",
    )
    sort = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="步骤顺序，越小越靠前",
    )
    action_type = Column(
        String(30), nullable=False, default="NORMAL", server_default=text("'NORMAL'"),
        comment="动作类型：当前仅支持 NORMAL；通道类型由 Binding 承载",
    )
    revision = Column(Integer, nullable=False, server_default=text("1"), comment="乐观锁版本号")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
