"""为现有任务补充执行根、Trace、截止时间及 Agent 修订引用，不新建任务体系。"""
import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade():
    """扩展可空字段，按已有批次证据回填分组；历史 Trace 和会话不伪造。"""
    op.add_column("task_run", sa.Column("execution_root_run_id", sa.Integer(), nullable=True))
    op.add_column("task_run", sa.Column("trace_id", sa.String(32), nullable=True))
    op.add_column("task_run", sa.Column("deadline_at", sa.DateTime(), nullable=True))
    op.create_unique_constraint("uq_task_run_id_task", "task_run", ["id", "task_id"])
    # 复合外键禁止跨任务拼接执行根，延迟检查允许原项目整体级联删除。
    op.create_foreign_key("fk_task_run_execution_root", "task_run", "task_run",
                          ["execution_root_run_id", "task_id"], ["id", "task_id"],
                          deferrable=True, initially="DEFERRED")
    op.create_index("ix_task_run_execution_root_run_id", "task_run", ["execution_root_run_id"])
    op.create_index("ix_task_run_trace_id", "task_run", ["trace_id"])
    op.add_column("task_attempt", sa.Column("deadline_at", sa.DateTime(), nullable=True))
    op.add_column("task_agent_instance", sa.Column("agent_definition_revision_id", sa.Integer(), nullable=True))
    op.add_column("task_agent_instance", sa.Column("parent_agent_instance_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_task_agent_revision", "task_agent_instance", "agent_definition_revision",
                          ["agent_definition_revision_id"], ["id"], deferrable=True, initially="DEFERRED")
    op.create_foreign_key("fk_task_agent_parent", "task_agent_instance", "task_agent_instance",
                          ["parent_agent_instance_id"], ["id"], ondelete="SET NULL")
    op.execute("""UPDATE task_run AS branch SET execution_root_run_id = root.id
        FROM case_generation_batch AS batch JOIN task_run AS root ON root.id = batch.task_run_id
        WHERE branch.task_id = root.task_id AND (
            SELECT count(*) FROM case_generation_batch AS b
            JOIN task_run AS r ON r.id = b.task_run_id WHERE r.task_id = root.task_id
        ) = 1""")


def downgrade():
    """仅移除新增关联，不删除原任务、生成草稿、会话或审核数据。"""
    op.drop_constraint("fk_task_agent_parent", "task_agent_instance", type_="foreignkey")
    op.drop_constraint("fk_task_agent_revision", "task_agent_instance", type_="foreignkey")
    op.drop_column("task_agent_instance", "parent_agent_instance_id")
    op.drop_column("task_agent_instance", "agent_definition_revision_id")
    op.drop_column("task_attempt", "deadline_at")
    op.drop_index("ix_task_run_trace_id", table_name="task_run")
    op.drop_index("ix_task_run_execution_root_run_id", table_name="task_run")
    op.drop_constraint("fk_task_run_execution_root", "task_run", type_="foreignkey")
    op.drop_constraint("uq_task_run_id_task", "task_run", type_="unique")
    for name in ("deadline_at", "trace_id", "execution_root_run_id"):
        op.drop_column("task_run", name)
