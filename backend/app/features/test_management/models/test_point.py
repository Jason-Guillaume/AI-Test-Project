"""测试点（Test Point）ORM 模型。

测试点从测试策略细化而来，描述「需要验证的具体场景」，
并通过 target_type 关联到被测对象（API / 业务流程 / 业务动作）。

target_type ∈ {API, BUSINESS_FLOW, BUSINESS_ACTION}，决定执行时走哪条执行器路由。
api_id / business_flow_id / business_action_id 均用 SET NULL：被测对象删除时测试点保留、
引用置空，由服务层标记失效，而非级联删除测试资产。
priority ∈ {P0, P1, P2, P3}。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class TestPoint(Base):
    """测试点：从策略细化的具体验证场景。"""

    __tablename__ = "test_point"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_point_project_name"),
        Index("ix_test_point_project_status", "project_id", "status"),
        {"comment": "测试点：从策略细化的具体验证场景"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    strategy_id = Column(
        Integer,
        ForeignKey("test_strategy.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属测试策略ID",
    )
    name = Column(String(200), nullable=False, comment="测试点名称")
    description = Column(String(1000), nullable=True, comment="测试点描述")
    priority = Column(
        String(10), nullable=False, default="P1", server_default=text("'P1'"),
        comment="优先级：P0/P1/P2/P3",
    )
    target_type = Column(
        String(20), nullable=False, default="API", server_default=text("'API'"),
        index=True, comment="被测对象类型：API/BUSINESS_FLOW/BUSINESS_ACTION",
    )
    api_id = Column(Integer, ForeignKey("api_interface.id", ondelete="SET NULL"), nullable=True, comment="关联接口ID")
    business_flow_id = Column(Integer, ForeignKey("business_flow.id", ondelete="SET NULL"), nullable=True, comment="关联业务流程ID")
    business_action_id = Column(Integer, ForeignKey("business_action.id", ondelete="SET NULL"), nullable=True, comment="关联业务动作ID")
    status = Column(
        String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"),
        index=True, comment="状态：DRAFT/ACTIVE/DEPRECATED",
    )
    source_type = Column(
        String(20), nullable=False, default="MANUAL", server_default=text("'MANUAL'"),
        comment="来源：MANUAL/AI（预留）",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
