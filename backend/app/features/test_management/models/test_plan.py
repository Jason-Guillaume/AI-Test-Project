"""测试计划（Test Plan）ORM 模型。

测试计划组织「何时、以何环境、跑哪些套件」。一个计划关联一个环境（可选）
和若干套件（TestPlanSuite）。计划触发后生成一次 TestRun。

environment 用 SET NULL：环境删除时计划保留、环境置空。
status ∈ {DRAFT, ACTIVE, DISABLED}。
execution_mode ∈ {MANUAL, SCHEDULED, CI}（本阶段仅 MANUAL，其余预留）。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class TestPlan(Base):
    """测试计划：组织套件与环境的执行单元。"""

    __tablename__ = "test_plan"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_plan_project_name"),
        Index("ix_test_plan_project_status", "project_id", "status"),
        {"comment": "测试计划：组织套件与环境的执行单元"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    name = Column(String(200), nullable=False, comment="计划名")
    description = Column(String(1000), nullable=True, comment="计划描述")
    environment_id = Column(
        Integer,
        ForeignKey("environment.id", ondelete="SET NULL"),
        nullable=True,
        comment="执行环境ID（可空）",
    )
    status = Column(
        String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"),
        index=True, comment="状态：DRAFT/ACTIVE/DISABLED",
    )
    execution_mode = Column(
        String(20), nullable=False, default="MANUAL", server_default=text("'MANUAL'"),
        comment="执行模式：MANUAL/SCHEDULED/CI",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )


class TestPlanSuite(Base):
    """计划-套件关联。"""

    __tablename__ = "test_plan_suite"
    __table_args__ = (
        UniqueConstraint("plan_id", "suite_id", name="uq_test_plan_suite_plan_suite"),
        Index("ix_test_plan_suite_plan_sort", "plan_id", "sort"),
        {"comment": "计划-套件关联"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    plan_id = Column(
        Integer,
        ForeignKey("test_plan.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属计划ID",
    )
    suite_id = Column(
        Integer,
        ForeignKey("test_suite.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="套件ID",
    )
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
