"""统一任务、角色会话、持久化调度与业务资源回链。

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    """显式增量建表；重复 stamp base 后重跑时跳过已存在的结构。"""
    inspector = sa.inspect(op.get_bind())

    def create_table_if_missing(name, *columns, **kwargs):
        """只在表缺失时建表，兼容 seed_admin 的 stamp base + upgrade head。"""
        if not inspector.has_table(name):
            op.create_table(name, *columns, **kwargs)

    create_table_if_missing(
        "task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id", ondelete="SET NULL")),
        sa.Column("input_case_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("request_key", sa.String(100)),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("created_by", "request_key", name="uq_task_creator_request_key"),
        comment="统一工作任务；原有测试资产继续由各业务表持有",
    )
    create_table_if_missing(
        "task_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("stage", sa.String(40), nullable=False, server_default="PLANNING"),
        sa.Column("goal_snapshot", sa.Text(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("current_plan_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "run_number", name="uq_task_run_number"),
        comment="统一任务运行与恢复状态",
    )
    create_table_if_missing(
        "task_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PROPOSED"),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("accepted_at", sa.DateTime()),
        sa.UniqueConstraint("task_run_id", "version", name="uq_task_plan_run_version"),
        comment="统一任务的版本化编排方案",
    )
    create_table_if_missing(
        "task_agent_instance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instance_key", sa.String(80), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="READY"),
        sa.Column("model_config_id", sa.Integer(), sa.ForeignKey("model_configuration.id", ondelete="SET NULL")),
        sa.Column("config_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("skills_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("tool_allowlist_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_run_id", "instance_key", name="uq_task_agent_run_key"),
        comment="任务运行内的 Agent 实例及会话配置",
    )
    create_table_if_missing(
        "task_work_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_instance_id", sa.Integer(), sa.ForeignKey("task_agent_instance.id", ondelete="SET NULL")),
        sa.Column("work_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("input_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("output_json", sa.JSON()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("claimed_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_run_id", "work_key", name="uq_task_work_run_key"),
        comment="统一任务调度工作项",
    )
    create_table_if_missing(
        "task_work_item_dependency",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_item_id", sa.Integer(), sa.ForeignKey("task_work_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("depends_on_id", sa.Integer(), sa.ForeignKey("task_work_item.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("work_item_id", "depends_on_id", name="uq_task_work_dependency"),
        comment="统一任务工作项依赖关系",
    )
    create_table_if_missing(
        "task_attempt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_item_id", sa.Integer(), sa.ForeignKey("task_work_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("owner", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="RUNNING"),
        sa.Column("checkpoint_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint("work_item_id", "attempt_number", name="uq_task_attempt_number"),
        comment="统一任务工作项执行尝试",
    )
    create_table_if_missing(
        "task_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_instance_id", sa.Integer(), sa.ForeignKey("task_agent_instance.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_type", sa.String(16), nullable=False),
        sa.Column("sender_user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("sender_instance_id", sa.Integer(), sa.ForeignKey("task_agent_instance.id", ondelete="SET NULL")),
        sa.Column("message_type", sa.String(24), nullable=False, server_default="TEXT"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(20), nullable=False, server_default="RECEIVED"),
        sa.Column("client_message_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime()),
        sa.UniqueConstraint("task_run_id", "client_message_id", name="uq_task_message_client_id"),
        comment="任务内独立参与者会话消息",
    )
    create_table_if_missing(
        "task_command",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("command_type", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACCEPTED"),
        sa.Column("response_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime()),
        sa.UniqueConstraint("task_run_id", "idempotency_key", name="uq_task_command_idempotency"),
        comment="统一任务可靠命令",
    )
    create_table_if_missing(
        "task_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("agent_instance_id", sa.Integer(), sa.ForeignKey("task_agent_instance.id", ondelete="SET NULL")),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_run_id", "event_seq", name="uq_task_event_sequence"),
        comment="统一任务持久化事件游标",
    )
    create_table_if_missing(
        "task_resource_ref",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_instance_id", sa.Integer(), sa.ForeignKey("task_agent_instance.id", ondelete="SET NULL")),
        sa.Column("direction", sa.String(12), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("version", sa.String(80)),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        comment="任务与原有业务资源的双向引用",
    )
    create_table_if_missing(
        "task_tool_invocation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("work_item_id", sa.Integer(), sa.ForeignKey("task_work_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_instance_id", sa.Integer(), sa.ForeignKey("task_agent_instance.id", ondelete="SET NULL")),
        sa.Column("invocation_key", sa.String(160), nullable=False),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="STARTED"),
        sa.Column("input_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint("task_run_id", "invocation_key", name="uq_task_tool_invocation_key"),
        comment="任务工具调用幂等回执与恢复边界",
    )
    create_table_if_missing(
        "task_scheduler_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("max_concurrent_runs", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        comment="统一任务调度全局并发控制",
    )

    indexes = (
        ("ix_task_project_id", "task", ["project_id"]),
        ("ix_task_created_by", "task", ["created_by"]),
        ("ix_task_project_status_created", "task", ["project_id", "status", "created_at"]),
        ("ix_task_run_task_id", "task_run", ["task_id"]),
        ("ix_task_run_status_lease", "task_run", ["status", "lease_expires_at"]),
        ("ix_task_plan_task_run_id", "task_plan", ["task_run_id"]),
        ("ix_task_agent_instance_task_run_id", "task_agent_instance", ["task_run_id"]),
        ("ix_task_agent_run_role", "task_agent_instance", ["task_run_id", "role"]),
        ("ix_task_work_item_task_run_id", "task_work_item", ["task_run_id"]),
        ("ix_task_work_status_created", "task_work_item", ["status", "created_at"]),
        ("ix_task_work_item_dependency_work_item_id", "task_work_item_dependency", ["work_item_id"]),
        ("ix_task_work_item_dependency_depends_on_id", "task_work_item_dependency", ["depends_on_id"]),
        ("ix_task_attempt_work_item_id", "task_attempt", ["work_item_id"]),
        ("ix_task_attempt_status_heartbeat", "task_attempt", ["status", "heartbeat_at"]),
        ("ix_task_message_task_run_id", "task_message", ["task_run_id"]),
        ("ix_task_message_instance_status", "task_message", ["agent_instance_id", "status", "id"]),
        ("ix_task_command_task_run_id", "task_command", ["task_run_id"]),
        ("ix_task_event_task_run_id", "task_event", ["task_run_id"]),
        ("ix_task_event_run_created", "task_event", ["task_run_id", "created_at"]),
        ("ix_task_resource_ref_task_run_id", "task_resource_ref", ["task_run_id"]),
        ("ix_task_resource_business_ref", "task_resource_ref", ["resource_type", "resource_id"]),
        ("ix_task_resource_run_kind", "task_resource_ref", ["task_run_id", "direction", "resource_type"]),
        ("ix_task_tool_invocation_task_run_id", "task_tool_invocation", ["task_run_id"]),
        ("ix_task_tool_invocation_work_item_id", "task_tool_invocation", ["work_item_id"]),
    )
    existing_indexes = {idx["name"] for table in inspector.get_table_names() for idx in inspector.get_indexes(table)}
    for name, table, columns in indexes:
        if inspector.has_table(table) and name not in existing_indexes:
            op.create_index(name, table, columns, unique=False)

    # 控制行保证多个 API 进程也会先串行判断并发，再领取一个工作项。
    op.get_bind().execute(
        sa.text("INSERT INTO task_scheduler_control (id, max_concurrent_runs) VALUES (1, 1) ON CONFLICT (id) DO NOTHING")
    )


def downgrade():
    """按外键依赖逆序删除本迁移新增的任务表。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in (
        "task_tool_invocation", "task_resource_ref", "task_event", "task_command",
        "task_message", "task_attempt", "task_work_item_dependency", "task_work_item",
        "task_agent_instance", "task_plan", "task_run", "task", "task_scheduler_control",
    ):
        if inspector.has_table(table):
            op.drop_table(table)
