"""security_execution：一次 CaseExecution 的安全细结果。"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database.base import Base


class SecurityExecution(Base):
    """一次 ``CaseExecution`` 至多一行。

    安全结论不进 ``case_execution.status`` 枚举（报告、前端、计数器都写死六态），
    这里保存细结果，再映射成现有四态：
    PASS→PASSED、POTENTIAL_ISSUE→FAILED、FAILED_EXECUTION→ERROR、
    INCONCLUSIVE/SKIPPED→SKIPPED。

    ``mutation_trace`` 与 ``evidence`` 在落库前必须经 ``SensitiveDataMasker`` 脱敏；
    内存中的真实 Token 不入库。
    """

    __tablename__ = "security_execution"
    __table_args__ = (
        UniqueConstraint("case_execution_id", name="uq_security_execution_case"),
        Index("ix_security_execution_project_result", "project_id", "security_result"),
        Index("ix_security_execution_run", "test_run_id"),
        {"comment": "安全细结果：基线结论 + 变异 trace（脱敏）+ 五态结论"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属平台项目ID",
    )
    test_run_id = Column(
        Integer, ForeignKey("test_run.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属测试运行ID",
    )
    # 不单独建 ix：已被 uq_security_execution_case 唯一索引覆盖，一对一语义已包含可查性。
    case_execution_id = Column(
        Integer, ForeignKey("case_execution.id", ondelete="CASCADE"),
        nullable=False, comment="对应的用例执行记录ID（一对一）",
    )
    security_case_id = Column(
        Integer, ForeignKey("security_case.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="安全用例ID",
    )
    environment_id = Column(
        Integer, ForeignKey("environment.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="执行环境ID",
    )
    actor_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="执行人",
    )
    baseline_status = Column(
        String(20), nullable=True, comment="基线结论：PASSED / FAILED",
    )
    baseline_http_status = Column(
        Integer, nullable=True, comment="基线请求的实际 HTTP 状态码",
    )
    security_result = Column(
        String(30), nullable=False,
        comment="安全结论：PASS / POTENTIAL_ISSUE / FAILED_EXECUTION / "
                "INCONCLUSIVE / SKIPPED",
    )
    classification = Column(
        String(40), nullable=True,
        comment="结论分类：EXPECTED_DENY_MET / EXPECTED_VALIDATION_MET / "
                "EXPECTED_IDEMPOTENT_MET / POTENTIAL_ISSUE / UNEXPECTED_SERVER_ERROR / "
                "BASELINE_FAILED / FIXTURE_REQUIRED / CONFIRMATION_REQUIRED / "
                "TARGET_BLOCKED / TRANSPORT_ERROR",
    )
    mutation_trace = Column(
        JSON, nullable=True, comment="脱敏后的变异前后对比（before/after）",
    )
    replay_count = Column(
        Integer, nullable=True, comment="重放实际次数（最大 3）",
    )
    actual_status_codes = Column(
        JSON, nullable=True, comment="实际状态码；重放时为整数数组",
    )
    evidence = Column(
        JSON, nullable=True,
        comment="脱敏后的对比摘要与基线快照，不含原始 Token；"
                "重复命中时 repeat_count 在此累加",
    )
    error_code = Column(
        String(50), nullable=True,
        comment="执行期错误码（SECURITY_BASELINE_FAILED / SECURITY_FIXTURE_REQUIRED / "
                "SECURITY_CONFIRMATION_REQUIRED / SECURITY_PRODUCTION_FORBIDDEN 等）",
    )
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
