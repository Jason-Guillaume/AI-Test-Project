"""增加无正文 Langfuse 投影 Outbox 和状态索引。"""

import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runtime_trace_projection",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("projection_key", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("task_run_id", sa.Integer(), nullable=False),
        sa.Column("execution_root_run_id", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("span_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("projected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_run_id", "task_id"], ["task_run.id", "task_run.task_id"],
            name="fk_runtime_trace_projection_run_task", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("projection_key", name="uq_runtime_trace_projection_key"),
        sa.UniqueConstraint("source_type", "source_key", name="uq_runtime_trace_projection_source"),
        comment="Langfuse 投影 outbox，仅持有业务事实引用及投递状态",
    )
    op.create_index("ix_runtime_trace_projection_trace_id", "runtime_trace_projection", ["trace_id"])
    op.create_index(
        "ix_runtime_trace_projection_due", "runtime_trace_projection",
        ["status", "next_attempt_at", "lease_expires_at"],
    )
    op.create_index("ix_runtime_trace_projection_run", "runtime_trace_projection", ["task_run_id", "created_at"])
    op.execute("""
        INSERT INTO runtime_trace_projection (
            projection_key, source_type, source_key, project_id, task_id, task_run_id,
            execution_root_run_id, trace_id, span_id, status, attempt_count,
            next_attempt_at, created_at, updated_at
        )
        SELECT md5('MODEL_CALL:' || call_id), 'MODEL_CALL', call_id, project_id, task_id,
               task_run_id, execution_root_run_id, trace_id, span_id, 'PENDING', 0,
               now(), now(), now()
          FROM runtime_call_fact WHERE trace_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO runtime_trace_projection (
            projection_key, source_type, source_key, project_id, task_id, task_run_id,
            execution_root_run_id, trace_id, span_id, status, attempt_count,
            next_attempt_at, created_at, updated_at
        )
        SELECT md5('AGENT_ATTEMPT:' || attempt.id::text), 'AGENT_ATTEMPT', attempt.id::text,
               task.project_id, task.id, run.id, COALESCE(run.execution_root_run_id, run.id),
               run.trace_id, attempt.checkpoint_json ->> 'agent_span_id', 'PENDING', 0,
               now(), now(), now()
          FROM task_attempt AS attempt
          JOIN task_work_item AS work ON work.id = attempt.work_item_id
          JOIN task_run AS run ON run.id = work.task_run_id
          JOIN task ON task.id = run.task_id
         WHERE run.trace_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO runtime_trace_projection (
            projection_key, source_type, source_key, project_id, task_id, task_run_id,
            execution_root_run_id, trace_id, span_id, status, attempt_count,
            next_attempt_at, created_at, updated_at
        )
        SELECT md5('RUNTIME_EVENT:' || event_id), 'RUNTIME_EVENT', event_id, project_id, task_id,
               task_run_id, COALESCE(execution_root_run_id, task_run_id), trace_id, span_id,
               'PENDING', 0, now(), now(), now()
          FROM runtime_event_fact WHERE trace_id IS NOT NULL AND task_id IS NOT NULL AND task_run_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    op.drop_index("ix_runtime_trace_projection_run", table_name="runtime_trace_projection")
    op.drop_index("ix_runtime_trace_projection_due", table_name="runtime_trace_projection")
    op.drop_index("ix_runtime_trace_projection_trace_id", table_name="runtime_trace_projection")
    op.drop_table("runtime_trace_projection")
