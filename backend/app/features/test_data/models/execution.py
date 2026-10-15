"""造数执行记录 ORM 模型：总记录、Fixture 执行、Provider 执行、缓存。

快照（input_snapshot / output_snapshot / output_json）写入前必须调用
`SensitiveDataMasker.mask_body`。禁止把 password_encrypted、解密后的口令、
Authorization 写入快照。

provider_execution.output_snapshot 的保留键 `_cleanup` 存结构化 cleanup_handle，
不进 Fixture 契约输出。

模型 feature-local，不进 app/models/__init__.py；由 alembic 0009 显式建表。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.sql import func, text

from app.shared.database import Base


class DataExecution(Base):
    """一次造数总记录：一条用例、一次 Run 级准备、或一次手工试跑。"""

    __tablename__ = "data_execution"
    __table_args__ = (
        Index("ix_data_execution_project_created", "project_id", "created_at"),
        {"comment": "造数总记录：一次用例/Run 级准备/手工试跑"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="消费方项目ID",
    )
    test_run_id = Column(
        Integer, ForeignKey("test_run.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联 TestRun ID",
    )
    case_execution_id = Column(
        Integer, ForeignKey("case_execution.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联 CaseExecution ID",
    )
    environment_id = Column(
        Integer, ForeignKey("environment.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="执行环境ID",
    )
    status = Column(
        String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"),
        comment="状态：PENDING/GENERATING/READY/FAILED/EXPIRED/DIRTY/CLEANING/CLEANED",
    )
    scope = Column(String(20), nullable=True, comment="作用域：CASE/RUN/PROJECT/GLOBAL/MANUAL")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration_ms = Column(Integer, nullable=True, comment="耗时（毫秒）")
    error_code = Column(String(50), nullable=True, comment="错误码（无前缀，见 shared.errors 常量）")
    error_message = Column(Text, nullable=True, comment="错误信息")
    cleanup_status = Column(
        String(20), nullable=True, comment="清理状态：PENDING/SUCCESS/FAILED/SKIPPED",
    )
    cleanup_error_code = Column(String(50), nullable=True, comment="清理失败错误码")
    cleanup_error_message = Column(Text, nullable=True, comment="清理失败原因（截断 2000 字）")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")


class FixtureExecution(Base):
    """Fixture 单次执行记录。"""

    __tablename__ = "fixture_execution"
    __table_args__ = ({"comment": "Fixture 单次执行：输入输出快照已脱敏"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    data_execution_id = Column(
        Integer, ForeignKey("data_execution.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属总记录ID",
    )
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="消费方项目ID",
    )
    fixture_id = Column(
        Integer, ForeignKey("fixture.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Fixture ID（删除后记录仍可读，fixture_key 为快照）",
    )
    fixture_key = Column(
        String(100), nullable=False, index=True,
        comment="执行时的 fixture_key 快照",
    )
    status = Column(
        String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"),
        comment="状态：同 data_execution",
    )
    scope = Column(
        String(20), nullable=False, default="CASE", server_default=text("'CASE'"),
        comment="实际生效的作用域（取依赖 Fixture 自己的 scope）",
    )
    cache_hit = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否命中缓存",
    )
    input_snapshot = Column(JSON, nullable=True, comment="输入快照（脱敏后）")
    output_snapshot = Column(JSON, nullable=True, comment="输出快照（脱敏后，含 _cleanup 保留键）")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration_ms = Column(Integer, nullable=True, comment="耗时（毫秒）")
    error_code = Column(String(50), nullable=True, comment="错误码")
    error_message = Column(Text, nullable=True, comment="错误信息")
    cleanup_status = Column(String(20), nullable=True, comment="清理状态")
    cleanup_error_code = Column(String(50), nullable=True, comment="清理失败错误码")
    cleanup_error_message = Column(Text, nullable=True, comment="清理失败原因")


class ProviderExecution(Base):
    """Provider 单步执行记录。手工试跑 Provider 时两个上级 ID 都可空。"""

    __tablename__ = "provider_execution"
    __table_args__ = ({"comment": "Provider 单步执行：input/output 快照已脱敏，_cleanup 存句柄"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    fixture_execution_id = Column(
        Integer, ForeignKey("fixture_execution.id", ondelete="CASCADE"),
        nullable=True, index=True,
        comment="所属 Fixture 执行ID（手工试跑可空）",
    )
    data_execution_id = Column(
        Integer, ForeignKey("data_execution.id", ondelete="CASCADE"),
        nullable=True, index=True, comment="所属总记录ID",
    )
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    provider_id = Column(
        Integer, ForeignKey("data_provider.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Provider ID（删除后记录保留）",
    )
    provider_type = Column(
        String(30), nullable=False, index=True,
        comment="Provider 类型快照",
    )
    step_id = Column(
        Integer, nullable=True, comment="步骤 ID（不建 FK，步骤删除后记录保留）",
    )
    status = Column(
        String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"),
        comment="状态：PENDING/RUNNING/SUCCESS/FAILED/SKIPPED",
    )
    input_snapshot = Column(JSON, nullable=True, comment="输入快照（脱敏后）")
    output_snapshot = Column(JSON, nullable=True, comment="输出快照（脱敏后）")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration_ms = Column(Integer, nullable=True, comment="耗时（毫秒）")
    error_code = Column(String(50), nullable=True, comment="错误码")
    error_message = Column(Text, nullable=True, comment="错误信息")
    cleanup_status = Column(String(20), nullable=True, comment="清理状态")


class FixtureCache(Base):
    """按 scope 共享的 Fixture 输出缓存。

    scope_key：CASE=`case_execution:{id}`，RUN=`test_run:{id}`，
    PROJECT=`project:{id}`，GLOBAL=`global`。
    DIRTY 不可复用：Cleanup 失败把缓存标 DIRTY，下次必须重造或报错。
    """

    __tablename__ = "fixture_cache"
    __table_args__ = (
        Index("uq_fixture_cache_scope", "project_id", "fixture_id", "scope", "scope_key", unique=True),
        {"comment": "Fixture 输出缓存：按 scope 共享，DIRTY 不可复用"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID（消费方）",
    )
    fixture_id = Column(
        Integer, ForeignKey("fixture.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="Fixture ID",
    )
    scope = Column(
        String(20), nullable=False, default="CASE", server_default=text("'CASE'"),
        comment="作用域：CASE/RUN/PROJECT/GLOBAL",
    )
    scope_key = Column(String(64), nullable=False, comment="作用域键：case_execution:{id} 等")
    status = Column(
        String(20), nullable=False, default="READY", server_default=text("'READY'"),
        comment="状态：READY/DIRTY/EXPIRED",
    )
    output_json = Column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
        comment="脱敏后的契约输出",
    )
    ref_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="引用计数",
    )
    data_execution_id = Column(
        Integer, ForeignKey("data_execution.id", ondelete="SET NULL"),
        nullable=True, comment="首次生成该缓存的总记录ID",
    )
    expires_at = Column(DateTime, nullable=True, index=True, comment="过期时间")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
