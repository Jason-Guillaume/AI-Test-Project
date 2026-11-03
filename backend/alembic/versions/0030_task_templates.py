"""Add versioned project task templates."""
from alembic import op
import sqlalchemy as sa


revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_template",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        comment="项目共享任务模板，不保存运行状态、消息或临时会话",
    )
    op.create_index("ix_task_template_project_id", "task_template", ["project_id"])
    op.create_index("ix_task_template_project_active_updated", "task_template", ["project_id", "is_active", "updated_at"])


def downgrade():
    op.drop_index("ix_task_template_project_active_updated", table_name="task_template")
    op.drop_index("ix_task_template_project_id", table_name="task_template")
    op.drop_table("task_template")
