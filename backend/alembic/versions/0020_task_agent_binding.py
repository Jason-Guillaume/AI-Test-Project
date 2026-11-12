"""将 Agent 配置绑定到任务。"""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    """处理`upgrade`相关逻辑。"""
    with op.batch_alter_table("task") as batch:
        batch.add_column(sa.Column("agent_definition_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_task_agent_definition_id_agent_definition",
            "agent_definition",
            ["agent_definition_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_task_agent_definition_id", ["agent_definition_id"])


def downgrade():
    """处理`downgrade`相关逻辑。"""
    with op.batch_alter_table("task") as batch:
        batch.drop_index("ix_task_agent_definition_id")
        batch.drop_constraint("fk_task_agent_definition_id_agent_definition", type_="foreignkey")
        batch.drop_column("agent_definition_id")
