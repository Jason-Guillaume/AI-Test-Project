"""持久化带来源校验的 Agent 会话摘要。"""

import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_session_summary",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("summary_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("summary_kind", sa.String(length=24), nullable=False, server_default="EXTRACTIVE"),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("source_through_message_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["session_id"], ["agent_session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
        comment="Agent 会话提取式摘要索引，原始消息保留为事实来源",
    )


def downgrade():
    op.drop_table("agent_session_summary")
