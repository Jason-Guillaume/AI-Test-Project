"""security_case：安全用例扩展数据（与 test_case 一对一）。"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class SecurityCase(Base):
    """安全用例的扩展数据。

    安全用例的本体仍是 ``test_case``（case_type='SECURITY'），这样它才能进入套件、
    计划和 TestRun。扩展字段全在这里，不给 test_case 加列。

    ``baseline_case_id`` 是追溯用的 parent：引用基线用例，不复制一整份基线内容。
    ``rule_id`` 记录实例化时用的规则，规则之后再改不影响已生成用例的
    ``mutation_config`` 快照。
    """

    __tablename__ = "security_case"
    __table_args__ = (
        UniqueConstraint("test_case_id", name="uq_security_case_test_case"),
        Index("ix_security_case_project_mutation", "project_id", "mutation_type"),
        Index("ix_security_case_project_strategy", "project_id", "strategy_id"),
        Index("ix_security_case_baseline", "baseline_case_id"),
        {"comment": "安全用例扩展数据：与 test_case 一对一，引用基线不复制基线"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属平台项目ID（必须等于 test_case.project_id）",
    )
    # 不单独建 ix：已被 uq_security_case_test_case 唯一索引覆盖，一对一语义已包含可查性。
    test_case_id = Column(
        Integer, ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False, comment="对应的测试用例ID（一对一）",
    )
    plan_id = Column(
        Integer, ForeignKey("security_plan.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="来源计划ID（手工创建时为空）",
    )
    baseline_case_id = Column(
        Integer, ForeignKey("test_case.id", ondelete="SET NULL"),
        nullable=True, comment="基线用例ID（追溯用 parent）",
    )
    strategy_id = Column(
        Integer, ForeignKey("security_strategy.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="策略ID",
    )
    rule_id = Column(
        Integer, ForeignKey("security_mutation_rule.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="实例化时的规则ID",
    )
    api_id = Column(
        Integer, ForeignKey("api_interface.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="目标接口ID",
    )
    business_action_id = Column(
        Integer, ForeignKey("business_action.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="目标业务动作ID（跳步场景）",
    )
    mutation_type = Column(
        String(40), nullable=False, comment="变异类型（冗余，便于列表筛选）",
    )
    mutation_config = Column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::json"),
        comment="生成时的变异参数快照",
    )
    security_expectation = Column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::json"),
        comment="安全期望：behavior + 状态码 + 说明",
    )
    risk_level = Column(
        String(20), nullable=False, default="MEDIUM", server_default=text("'MEDIUM'"),
        comment="风险级别：INFO/LOW/MEDIUM/HIGH/CRITICAL",
    )
    confirmation_required = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否需要确认高风险",
    )
    confirmed_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, comment="高风险确认人",
    )
    confirmed_at = Column(
        DateTime, nullable=True,
        comment="高风险确认时间；空且 confirmation_required 时禁止真正发变异请求",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
        comment="更新时间",
    )
