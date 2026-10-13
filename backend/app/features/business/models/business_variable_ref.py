"""业务变量引用关系（Business Variable Ref）ORM 模型。

在业务流程内建立不同 Business Action 之间的变量引用：一个动作的输出变量，
可作为另一个动作输入变量的来源。第一阶段只做配置与展示，不执行真正的数据传递。

source_action_id / target_action_id 都带 ondelete=CASCADE：任一动作被删除时，
引用它的关系一并清理，避免残留指向已删除动作的关系。flow_id 冗余存储便于按流程
整树查询。feature-local 表，由迁移 0004 建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.shared.database import Base


class BusinessVariableRef(Base):
    """业务动作之间的变量引用关系（一个动作输出 → 另一动作输入）。"""

    __tablename__ = "business_variable_ref"
    __table_args__ = ({"comment": "业务动作之间的变量引用关系"},)
    # flow_id / source_action_id / target_action_id 均在列定义上带 index=True（单列索引），
    # 不再额外声明同名显式 Index，保持与 bug / api_interface 等模型一致的索引风格。

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    flow_id = Column(
        Integer,
        ForeignKey("business_flow.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属业务流程ID",
    )
    # flow_id 冗余：两个动作必须同属一个流程（服务层校验），冗余 flow_id 便于按流程整树查询。
    source_action_id = Column(
        Integer,
        ForeignKey("business_action.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="来源动作ID（输出方）",
    )
    source_variable = Column(
        String(100), nullable=False, comment="来源动作输出变量名",
    )
    source_variable_id = Column(
        Integer,
        ForeignKey("business_variable.id", ondelete="SET NULL"),
        nullable=True,
        comment="来源变量ID（FK → business_variable）",
    )
    target_action_id = Column(
        Integer,
        ForeignKey("business_action.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="目标动作ID（输入方）",
    )
    target_variable = Column(
        String(100), nullable=False, comment="目标动作输入变量名",
    )
    target_variable_id = Column(
        Integer,
        ForeignKey("business_variable.id", ondelete="SET NULL"),
        nullable=True,
        comment="目标变量ID（FK → business_variable）",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
