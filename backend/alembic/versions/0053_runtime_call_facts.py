"""增加不复制 Trace 正文的模型调用、Token 与时延事实表。"""

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade():
    """新增可按项目、运行、模型与时间聚合的调用事实。"""
    op.create_table(
        "runtime_call_fact",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("call_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("task_run_id", sa.Integer(), nullable=False),
        sa.Column("execution_root_run_id", sa.Integer(), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("agent_instance_id", sa.Integer(), nullable=True),
        sa.Column("agent_definition_id", sa.Integer(), nullable=True),
        sa.Column("agent_definition_revision_id", sa.Integer(), nullable=True),
        sa.Column("model_config_id", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("model_revision", sa.String(length=80), nullable=True),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("span_id", sa.String(length=64), nullable=True),
        sa.Column("request_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("usage_status", sa.String(length=20), server_default=sa.text("'UNKNOWN'"), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("cost_currency", sa.String(length=3), nullable=True),
        sa.Column("pricing_revision", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_run_id", "task_id"], ["task_run.id", "task_run.task_id"],
                                name="fk_runtime_call_fact_run_task", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_root_run_id", "task_id"], ["task_run.id", "task_run.task_id"],
                                name="fk_runtime_call_fact_root_task", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["task_work_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["task_attempt.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_instance_id"], ["task_agent_instance.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_definition_id"], ["agent_definition.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_definition_revision_id"], ["agent_definition_revision.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_config_id"], ["model_configuration.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id", name="uq_runtime_call_fact_call_id"),
        comment="模型调用数值事实与任务/Trace/Agent 关联",
    )
    op.create_index("ix_runtime_call_fact_project_created", "runtime_call_fact", ["project_id", "created_at"])
    op.create_index("ix_runtime_call_fact_run_created", "runtime_call_fact", ["task_run_id", "created_at"])
    op.create_index("ix_runtime_call_fact_root", "runtime_call_fact", ["execution_root_run_id"])
    op.create_index("ix_runtime_call_fact_model_created", "runtime_call_fact", ["model_config_id", "created_at"])
    op.create_index("ix_runtime_call_fact_trace_id", "runtime_call_fact", ["trace_id"])


def downgrade():
    """删除派生用量事实表，不修改原任务、Trace、模型或业务数据。"""
    op.drop_index("ix_runtime_call_fact_trace_id", table_name="runtime_call_fact")
    op.drop_index("ix_runtime_call_fact_model_created", table_name="runtime_call_fact")
    op.drop_index("ix_runtime_call_fact_root", table_name="runtime_call_fact")
    op.drop_index("ix_runtime_call_fact_run_created", table_name="runtime_call_fact")
    op.drop_index("ix_runtime_call_fact_project_created", table_name="runtime_call_fact")
    op.drop_table("runtime_call_fact")
