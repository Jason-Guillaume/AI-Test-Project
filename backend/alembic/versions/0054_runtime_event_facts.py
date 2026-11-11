"""增加不复制 Trace 正文的工具、检索与上下文事件索引。"""

import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade():
    """为项目级运行质量统计增加可关联事件事实。"""
    op.create_table(
        "runtime_event_fact",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("task_run_id", sa.Integer(), nullable=True),
        sa.Column("execution_root_run_id", sa.Integer(), nullable=True),
        sa.Column("work_item_id", sa.Integer(), nullable=True),
        sa.Column("attempt_id", sa.Integer(), nullable=True),
        sa.Column("agent_instance_id", sa.Integer(), nullable=True),
        sa.Column("agent_definition_id", sa.Integer(), nullable=True),
        sa.Column("agent_definition_revision_id", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("span_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("event_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("event_metadata", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_run_id", "task_id"], ["task_run.id", "task_run.task_id"],
                                name="fk_runtime_event_fact_run_task", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_root_run_id", "task_id"], ["task_run.id", "task_run.task_id"],
                                name="fk_runtime_event_fact_root_task", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["task_work_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["task_attempt.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_instance_id"], ["task_agent_instance.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_definition_id"], ["agent_definition.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_definition_revision_id"], ["agent_definition_revision.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_runtime_event_fact_event_id"),
        comment="工具调用、检索与上下文事件索引，不复制 Langfuse Trace 正文",
    )
    op.create_index("ix_runtime_event_fact_project_time", "runtime_event_fact", ["project_id", "occurred_at"])
    op.create_index("ix_runtime_event_fact_run_time", "runtime_event_fact", ["task_run_id", "occurred_at"])
    op.create_index("ix_runtime_event_fact_root_time", "runtime_event_fact", ["execution_root_run_id", "occurred_at"])
    op.create_index("ix_runtime_event_fact_type_time", "runtime_event_fact", ["event_type", "occurred_at"])
    op.create_index("ix_runtime_event_fact_trace_id", "runtime_event_fact", ["trace_id"])


def downgrade():
    """移除只读派生事件索引，不变更 Langfuse Trace 或任务数据。"""
    op.drop_index("ix_runtime_event_fact_trace_id", table_name="runtime_event_fact")
    op.drop_index("ix_runtime_event_fact_type_time", table_name="runtime_event_fact")
    op.drop_index("ix_runtime_event_fact_root_time", table_name="runtime_event_fact")
    op.drop_index("ix_runtime_event_fact_run_time", table_name="runtime_event_fact")
    op.drop_index("ix_runtime_event_fact_project_time", table_name="runtime_event_fact")
    op.drop_table("runtime_event_fact")
