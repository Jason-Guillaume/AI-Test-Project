"""security_plan：人工确认前的安全计划。"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class SecurityPlan(Base):
    """一份安全测试计划（预览快照）。

    不是第二套 TestRun：``preview_json`` 只是「预计会生成哪些用例」的快照，
    真正落库要等 ``POST /security-plans/{id}/confirm`` 之后由
    ``case_service`` 写入 test_case + security_case。

    ``strategy_ids`` 记录本次选中的策略；``estimated_count`` 是预览条数
    （单次 preview 硬上限 50，超出截断并标记 truncated）。
    """

    __tablename__ = "security_plan"
    __table_args__ = (
        Index("ix_security_plan_project_status", "project_id", "status", "created_at"),
        {"comment": "人工确认前的安全计划：preview_json 快照 + estimated_count"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属平台项目ID",
    )
    name = Column(String(200), nullable=False, comment="计划名称")
    target_type = Column(
        String(20), nullable=False, comment="目标类型：API / TEST_CASE / BUSINESS_ACTION",
    )
    api_id = Column(
        Integer, ForeignKey("api_interface.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="目标接口ID（target_type=API 时必填）",
    )
    baseline_case_id = Column(
        Integer, ForeignKey("test_case.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="基线用例ID（优先）",
    )
    business_action_id = Column(
        Integer, ForeignKey("business_action.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="目标业务动作ID（target_type=BUSINESS_ACTION 时）",
    )
    strategy_ids = Column(JSON, nullable=True, comment="选中的策略 ID 列表")
    status = Column(
        String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"),
        comment="计划状态：DRAFT / CONFIRMED / DISCARDED",
    )
    preview_json = Column(
        JSON, nullable=True, comment="预览快照：预计用例清单、缺哪种 Fixture、是否截断",
    )
    estimated_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="预计生成的安全用例条数",
    )
    environment_id = Column(
        Integer, ForeignKey("environment.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="执行环境（可空，执行时再选）",
    )
    created_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人",
    )
    confirmed_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="确认人",
    )
    confirmed_at = Column(DateTime, nullable=True, comment="确认时间")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
        comment="更新时间",
    )
    revision = Column(Integer, nullable=False, server_default=text("1"), comment="乐观锁版本号")
