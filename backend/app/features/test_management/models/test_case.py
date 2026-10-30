"""测试用例（Test Case）ORM 模型。

测试用例是测试资产的核心：可执行、可断言、可复用。一个用例由若干前置条件、
测试数据、测试步骤、断言组成（均以子表挂载，CASCADE 删除）。

target_type 决定 TestCaseExecutor 路由：
- API → 复用 ApiRequestExecutor
- BUSINESS_FLOW → 复用 business.executors.business_flow_executor.execute_flow
- BUSINESS_ACTION → 复用业务动作执行能力（绑定 + 映射 + ApiRequestExecutor）

revision 为乐观锁版本号：更新时校验 revision，不匹配返回 409 CONFLICT。
case_type ∈ {FUNCTIONAL, BUSINESS, NEGATIVE, BOUNDARY, PERMISSION, SECURITY, EXCEPTION}。
status ∈ {DRAFT, ACTIVE, DEPRECATED}。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class TestCase(Base):
    """测试用例：可执行、可断言、可复用的测试资产核心实体。"""

    __tablename__ = "test_case"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_case_project_name"),
        Index("ix_test_case_project_status", "project_id", "status"),
        Index("ix_test_case_project_target", "project_id", "target_type"),
        {"comment": "测试用例：可执行、可断言、可复用的测试资产核心实体"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    test_point_id = Column(
        Integer,
        ForeignKey("test_point.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联测试点ID",
    )
    name = Column(String(200), nullable=False, comment="用例名称")
    description = Column(String(1000), nullable=True, comment="用例描述")
    priority = Column(
        String(10), nullable=False, default="P1", server_default=text("'P1'"),
        comment="优先级：P0/P1/P2/P3",
    )
    case_type = Column(
        String(30), nullable=False, default="FUNCTIONAL", server_default=text("'FUNCTIONAL'"),
        comment="用例类型：FUNCTIONAL/BUSINESS/NEGATIVE/BOUNDARY/PERMISSION/SECURITY/EXCEPTION",
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
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用")
    revision = Column(Integer, nullable=False, server_default=text("1"), comment="乐观锁版本号")
    source_type = Column(
        String(20), nullable=False, default="MANUAL", server_default=text("'MANUAL'"),
        comment="来源：MANUAL/AI",
    )
    agent_session_id = Column(
        Integer, ForeignKey("agent_session.id", ondelete="SET NULL"), nullable=True,
        comment="生成该用例的 Agent 会话ID（追溯用，MANUAL 来源为空）",
    )
    generation_version = Column(Integer, nullable=True, comment="Agent 生成版本号（追溯用）")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
