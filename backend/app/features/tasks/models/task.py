"""统一任务与可恢复运行的 ORM 结构。

本模块导出任务、运行、计划、参与者、工作项、尝试、消息、命令、事件、产物引用、工具回执和调度配额模型。
它们由 tasks 服务与运行时协作；所有新表由 Alembic 0015 显式建表，运行时不依赖 create_all。
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.shared.database import Base


class Task(Base):
    """跨管理页面的统一工作任务；项目与发起人是权限事实来源。"""

    __tablename__ = "task"
    __table_args__ = (
        UniqueConstraint("created_by", "request_key", name="uq_task_creator_request_key"),
        Index("ix_task_project_status_created", "project_id", "status", "created_at"),
        {"comment": "统一工作任务；原有测试资产继续由各业务表持有"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    goal = Column(Text, nullable=False)
    environment_id = Column(Integer, ForeignKey("environment.id", ondelete="SET NULL"), nullable=True)
    input_case_ids = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    security_scan_json = Column(JSON, nullable=True, comment="可选 ZAP 扫描目标与策略；批准说明只在确认命令中提交")
    request_key = Column(String(100), nullable=True)
    status = Column(String(32), nullable=False, default="QUEUED", server_default=text("'QUEUED'"))
    archived = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class TaskRun(Base):
    """任务运行版本；保存状态机、输入快照、租约与事件游标。"""

    __tablename__ = "task_run"
    __table_args__ = (
        UniqueConstraint("task_id", "run_number", name="uq_task_run_number"),
        Index("ix_task_run_status_lease", "status", "lease_expires_at"),
        {"comment": "统一任务运行与恢复状态"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True)
    run_number = Column(Integer, nullable=False)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(32), nullable=False, default="QUEUED", server_default=text("'QUEUED'"))
    stage = Column(String(40), nullable=False, default="PLANNING", server_default=text("'PLANNING'"))
    goal_snapshot = Column(Text, nullable=False)
    input_snapshot = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    current_plan_version = Column(Integer, nullable=False, default=0, server_default=text("0"))
    event_seq = Column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_owner = Column(String(160), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class TaskPlan(Base):
    """不可变的编排方案版本；人工确认只改变状态，不覆盖方案内容。"""

    __tablename__ = "task_plan"
    __table_args__ = (
        UniqueConstraint("task_run_id", "version", name="uq_task_plan_run_version"),
        {"comment": "统一任务的版本化编排方案"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="PROPOSED", server_default=text("'PROPOSED'"))
    plan_json = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    accepted_at = Column(DateTime, nullable=True)


class TaskAgentInstance(Base):
    """某个运行内的独立参与者会话与不可变角色配置快照。"""

    __tablename__ = "task_agent_instance"
    __table_args__ = (
        UniqueConstraint("task_run_id", "instance_key", name="uq_task_agent_run_key"),
        Index("ix_task_agent_run_role", "task_run_id", "role"),
        {"comment": "任务运行内的 Agent 实例及会话配置"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    instance_key = Column(String(80), nullable=False)
    role = Column(String(32), nullable=False)
    display_name = Column(String(120), nullable=False)
    status = Column(String(24), nullable=False, default="READY", server_default=text("'READY'"))
    model_config_id = Column(Integer, ForeignKey("model_configuration.id", ondelete="SET NULL"), nullable=True)
    config_snapshot = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    skills_json = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    tool_allowlist_json = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class TaskWorkItem(Base):
    """可单独领取、依赖、重试和审计的工作单元。"""

    __tablename__ = "task_work_item"
    __table_args__ = (
        UniqueConstraint("task_run_id", "work_key", name="uq_task_work_run_key"),
        Index("ix_task_work_status_created", "status", "created_at"),
        {"comment": "统一任務调度工作项"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_instance_id = Column(Integer, ForeignKey("task_agent_instance.id", ondelete="SET NULL"), nullable=True)
    work_key = Column(String(100), nullable=False)
    kind = Column(String(32), nullable=False)
    sequence = Column(Integer, nullable=False, default=0, server_default=text("0"))
    status = Column(String(24), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    input_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    output_json = Column(JSON, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    max_attempts = Column(Integer, nullable=False, default=3, server_default=text("3"))
    idempotency_key = Column(String(160), nullable=False)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    available_at = Column(DateTime, nullable=True, index=True, comment="外部任务轮询或延迟重试的最早领取时间")
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class TaskWorkItemDependency(Base):
    """工作项依赖边；服务端在领取前验证依赖已成功。"""

    __tablename__ = "task_work_item_dependency"
    __table_args__ = (
        UniqueConstraint("work_item_id", "depends_on_id", name="uq_task_work_dependency"),
        {"comment": "统一任务工作项依赖关系"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_item_id = Column(Integer, ForeignKey("task_work_item.id", ondelete="CASCADE"), nullable=False, index=True)
    depends_on_id = Column(Integer, ForeignKey("task_work_item.id", ondelete="CASCADE"), nullable=False, index=True)


class TaskAttempt(Base):
    """某工作项的一次执行尝试、所有者租约、检查点与失败原因。"""

    __tablename__ = "task_attempt"
    __table_args__ = (
        UniqueConstraint("work_item_id", "attempt_number", name="uq_task_attempt_number"),
        Index("ix_task_attempt_status_heartbeat", "status", "heartbeat_at"),
        {"comment": "统一任务工作项执行尝试"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_item_id = Column(Integer, ForeignKey("task_work_item.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    lease_generation = Column(Integer, nullable=False, default=1, server_default=text("1"))
    owner = Column(String(160), nullable=False)
    status = Column(String(24), nullable=False, default="RUNNING", server_default=text("'RUNNING'"))
    checkpoint_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    heartbeat_at = Column(DateTime, nullable=False, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)


class TaskMessage(Base):
    """参与者邮箱消息；接收、处理状态按任务运行与实例隔离。"""

    __tablename__ = "task_message"
    __table_args__ = (
        UniqueConstraint("task_run_id", "client_message_id", name="uq_task_message_client_id"),
        Index("ix_task_message_instance_status", "agent_instance_id", "status", "id"),
        {"comment": "任务内独立参与者会话消息"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_instance_id = Column(Integer, ForeignKey("task_agent_instance.id", ondelete="CASCADE"), nullable=False)
    sender_type = Column(String(16), nullable=False)
    sender_user_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    sender_instance_id = Column(Integer, ForeignKey("task_agent_instance.id", ondelete="SET NULL"), nullable=True)
    message_type = Column(String(24), nullable=False, default="TEXT", server_default=text("'TEXT'"))
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    status = Column(String(20), nullable=False, default="RECEIVED", server_default=text("'RECEIVED'"))
    client_message_id = Column(String(100), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)


class TaskCommand(Base):
    """暂停、继续、取消、确认与重试等显式幂等命令。"""

    __tablename__ = "task_command"
    __table_args__ = (
        UniqueConstraint("task_run_id", "idempotency_key", name="uq_task_command_idempotency"),
        {"comment": "统一任务可靠命令"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    command_type = Column(String(32), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    status = Column(String(20), nullable=False, default="ACCEPTED", server_default=text("'ACCEPTED'"))
    response_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)


class TaskEvent(Base):
    """已提交事实的递增游标事件，不承载模型隐藏推理。"""

    __tablename__ = "task_event"
    __table_args__ = (
        UniqueConstraint("task_run_id", "event_seq", name="uq_task_event_sequence"),
        Index("ix_task_event_run_created", "task_run_id", "created_at"),
        {"comment": "统一任务持久化事件游标"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    event_seq = Column(Integer, nullable=False)
    event_type = Column(String(60), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    agent_instance_id = Column(Integer, ForeignKey("task_agent_instance.id", ondelete="SET NULL"), nullable=True)
    payload = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class TaskResourceRef(Base):
    """统一任务输入与产物引用；业务数据仍由原业务模块持有。"""

    __tablename__ = "task_resource_ref"
    __table_args__ = (
        Index("ix_task_resource_business_ref", "resource_type", "resource_id"),
        Index("ix_task_resource_run_kind", "task_run_id", "direction", "resource_type"),
        {"comment": "任务与原有业务资源的双向引用"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_instance_id = Column(Integer, ForeignKey("task_agent_instance.id", ondelete="SET NULL"), nullable=True)
    direction = Column(String(12), nullable=False)
    resource_type = Column(String(40), nullable=False)
    resource_id = Column(String(64), nullable=False)
    version = Column(String(80), nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class TaskToolInvocation(Base):
    """有副作用工具的幂等回执；STARTED 中断后必须核对，禁止盲目重放。"""

    __tablename__ = "task_tool_invocation"
    __table_args__ = (
        UniqueConstraint("task_run_id", "invocation_key", name="uq_task_tool_invocation_key"),
        {"comment": "任务工具调用幂等回执与恢复边界"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    work_item_id = Column(Integer, ForeignKey("task_work_item.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_instance_id = Column(Integer, ForeignKey("task_agent_instance.id", ondelete="SET NULL"), nullable=True)
    invocation_key = Column(String(160), nullable=False)
    tool_name = Column(String(80), nullable=False)
    status = Column(String(24), nullable=False, default="STARTED", server_default=text("'STARTED'"))
    input_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    result_json = Column(JSON, nullable=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)


class TaskSchedulerControl(Base):
    """数据库级调度闸门，串行化领取并约束全局运行并发。"""

    __tablename__ = "task_scheduler_control"
    __table_args__ = {"comment": "统一任务调度全局并发控制"}

    id = Column(Integer, primary_key=True)
    max_concurrent_runs = Column(Integer, nullable=False, default=1, server_default=text("1"))
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
