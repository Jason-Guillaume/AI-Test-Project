"""将交互式 Web 编写会话真实绑定到任务运行和 UI Worker。"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    """历史任务/会话保留为空绑定；新模式由任务服务显式创建。"""
    op.add_column("task", sa.Column("task_mode", sa.String(32), nullable=False, server_default="TEST_EXECUTION"))
    op.add_column("task", sa.Column("web_authoring_json", sa.JSON(), nullable=True))

    op.add_column("agent_session", sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=True))
    op.add_column("agent_session", sa.Column("task_agent_instance_id", sa.Integer(), sa.ForeignKey("task_agent_instance.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_agent_session_task_run_id", "agent_session", ["task_run_id"])
    op.create_unique_constraint("uq_agent_session_task_run", "agent_session", ["task_run_id"])

    op.add_column("web_agent_session", sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", ondelete="CASCADE"), nullable=True))
    op.add_column("web_agent_session", sa.Column("task_agent_instance_id", sa.Integer(), sa.ForeignKey("task_agent_instance.id", ondelete="SET NULL"), nullable=True))
    op.add_column("web_agent_session", sa.Column("agent_session_id", sa.Integer(), sa.ForeignKey("agent_session.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_web_agent_session_task_run_id", "web_agent_session", ["task_run_id"])
    op.create_index("ix_web_agent_session_agent_session_id", "web_agent_session", ["agent_session_id"])


def downgrade():
    """删除新增关联，不修改旧会话或资产。"""
    op.drop_index("ix_web_agent_session_agent_session_id", table_name="web_agent_session")
    op.drop_index("ix_web_agent_session_task_run_id", table_name="web_agent_session")
    op.drop_column("web_agent_session", "agent_session_id")
    op.drop_column("web_agent_session", "task_agent_instance_id")
    op.drop_column("web_agent_session", "task_run_id")
    op.drop_constraint("uq_agent_session_task_run", "agent_session", type_="unique")
    op.drop_index("ix_agent_session_task_run_id", table_name="agent_session")
    op.drop_column("agent_session", "task_agent_instance_id")
    op.drop_column("agent_session", "task_run_id")
    op.drop_column("task", "web_authoring_json")
    op.drop_column("task", "task_mode")
