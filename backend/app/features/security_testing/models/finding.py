"""security_finding：疑似问题（独立于 bug 表）。"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class SecurityFinding(Base):
    """一条疑似安全问题。

    只有 ``security_result = POTENTIAL_ISSUE`` 才创建或合并 Finding；
    PASS / INCONCLUSIVE / SKIPPED / FAILED_EXECUTION 都不建。

    去重走部分唯一索引 ``uq_security_finding_open_fingerprint``：
    同一接口、同一变异、同一字段上未关闭（OPEN / CONFIRMED）的 Finding 不重复插入，
    只把最新一次的 ``security_execution_id`` 写上并在 ``evidence.repeat_count`` 加一。
    FALSE_POSITIVE / IGNORED / RESOLVED 不占该索引，误报之后允许再开一条新的 OPEN
    （产品上是预期：误报要人再看一次，但不会被一次误点永久屏蔽）。

    ``bug_id`` 故意不加 FK：Phase 1 不自动建缺陷，以后由人工从 CONFIRMED
    调缺陷服务再回填 id，避免现在绑死缺陷模块。
    """

    __tablename__ = "security_finding"
    __table_args__ = (
        Index("ix_security_finding_project_status", "project_id", "status"),
        Index("ix_security_finding_project_severity", "project_id", "severity"),
        Index(
            "uq_security_finding_open_fingerprint", "project_id", "fingerprint", unique=True,
            postgresql_where=text("status IN ('OPEN', 'CONFIRMED')"),
        ),
        {"comment": "疑似问题：fingerprint 去重，独立于 bug 表"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属平台项目ID",
    )
    test_run_id = Column(
        Integer, ForeignKey("test_run.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="产生该 Finding 的测试运行ID",
    )
    case_execution_id = Column(
        Integer, ForeignKey("case_execution.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="用例执行记录ID",
    )
    security_execution_id = Column(
        Integer, ForeignKey("security_execution.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="安全执行记录ID（重复命中时更新为最新一次）",
    )
    api_id = Column(
        Integer, ForeignKey("api_interface.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="接口ID",
    )
    business_action_id = Column(
        Integer, ForeignKey("business_action.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="业务动作ID",
    )
    strategy_id = Column(
        Integer, ForeignKey("security_strategy.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="策略ID",
    )
    security_case_id = Column(
        Integer, ForeignKey("security_case.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="安全用例ID",
    )
    mutation_type = Column(String(40), nullable=False, comment="变异类型")
    severity = Column(
        String(20), nullable=False, default="MEDIUM", server_default=text("'MEDIUM'"),
        comment="严重级别：INFO/LOW/MEDIUM/HIGH/CRITICAL（由规则表计算，不信模型）",
    )
    status = Column(
        String(20), nullable=False, default="OPEN", server_default=text("'OPEN'"),
        comment="状态：OPEN / CONFIRMED / FALSE_POSITIVE / RESOLVED / IGNORED",
    )
    title = Column(String(200), nullable=False, comment="标题（来自规则模板文案，不是 LLM 发挥）")
    description = Column(
        Text, nullable=False,
        comment="详细描述：期望什么、实际什么、为什么是疑似问题",
    )
    evidence = Column(
        JSON, nullable=True,
        comment="脱敏后的证据：基线值、变异值、实际状态码、重复次数、上次人工结论",
    )
    recommendation = Column(
        Text, nullable=True, comment="处理建议（规则模板文案）",
    )
    fingerprint = Column(
        String(64), nullable=False,
        comment="sha256(api_id|mutation_type|target_location|target_field|baseline_case_id)",
    )
    bug_id = Column(
        Integer, nullable=True,
        comment="关联缺陷ID（故意不加 FK；Phase 1 不写 bug 表）",
    )
    created_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="执行人",
    )
    resolved_by = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
        comment="状态变更人",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
        comment="更新时间",
    )
