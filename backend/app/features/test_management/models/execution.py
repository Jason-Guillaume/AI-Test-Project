"""测试执行记录 ORM 模型。

TestRun 代表一次测试计划执行；CaseExecution 代表其中某个用例的执行。
与业务执行记录（flow_execution/action_execution）结构对称，但归属测试域。

context_json 存放运行时上下文（变量键值对），与配置表分离。
request_snapshot/response_snapshot/assertion_results 均为脱敏后的快照。
status 字段为 String（不设 sa.Enum），合法取值由服务层校验。

TestRun.status ∈ {PENDING, RUNNING, SUCCESS, FAILED, CANCELLED}
CaseExecution.status ∈ {PENDING, RUNNING, PASSED, FAILED, SKIPPED, ERROR}
CaseExecution.executor_type ∈ {API, BUSINESS_FLOW, BUSINESS_ACTION}
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func, text

from app.shared.database import Base


class TestRun(Base):
    """测试计划执行记录。"""

    __tablename__ = "test_run"
    __table_args__ = ({"comment": "测试计划执行记录"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    plan_id = Column(
        Integer,
        ForeignKey("test_plan.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联计划ID",
    )
    environment_id = Column(
        Integer,
        ForeignKey("environment.id", ondelete="SET NULL"),
        nullable=True,
        comment="执行环境ID",
    )
    status = Column(
        String(20), nullable=False, server_default=text("'PENDING'"), index=True,
        comment="执行状态：PENDING/RUNNING/SUCCESS/FAILED/CANCELLED",
    )
    total = Column(Integer, nullable=False, server_default=text("0"), comment="用例总数")
    passed = Column(Integer, nullable=False, server_default=text("0"), comment="通过数")
    failed = Column(Integer, nullable=False, server_default=text("0"), comment="失败数")
    skipped = Column(Integer, nullable=False, server_default=text("0"), comment="跳过数")
    error = Column(Integer, nullable=False, server_default=text("0"), comment="错误数（执行异常）")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="触发人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )


class CaseExecution(Base):
    """用例执行记录。"""

    __tablename__ = "case_execution"
    __table_args__ = ({"comment": "用例执行记录"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    test_run_id = Column(
        Integer,
        ForeignKey("test_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属测试执行ID",
    )
    test_case_id = Column(
        Integer,
        ForeignKey("test_case.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="用例ID",
    )
    status = Column(
        String(20), nullable=False, server_default=text("'PENDING'"), index=True,
        comment="执行状态：PENDING/RUNNING/PASSED/FAILED/SKIPPED/ERROR",
    )
    executor_type = Column(String(20), nullable=True, comment="执行器类型：API/BUSINESS_FLOW/BUSINESS_ACTION")
    request_snapshot = Column(JSON, nullable=True, comment="请求快照（脱敏后）")
    response_snapshot = Column(JSON, nullable=True, comment="响应快照（脱敏后）")
    assertion_results = Column(JSON, nullable=True, comment="断言结果列表")
    context_json = Column(JSON, nullable=True, comment="运行时上下文")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration_ms = Column(Integer, nullable=True, comment="执行耗时（毫秒）")
    error_code = Column(String(50), nullable=True, comment="标准化错误代码")
    error_message = Column(Text, nullable=True, comment="错误信息")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
