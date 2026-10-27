"""Add self-designed security assessment inputs to tasks."""

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    """处理`upgrade`相关逻辑。"""
    op.add_column(
        "task",
        sa.Column("security_assessment_json", sa.JSON(), nullable=True),
    )


def downgrade():
    """处理`downgrade`相关逻辑。"""
    op.drop_column("task", "security_assessment_json")
