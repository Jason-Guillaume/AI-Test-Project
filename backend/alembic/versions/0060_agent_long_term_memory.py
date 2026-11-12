"""新增按项目和 Agent 版本化的长期记忆。"""

import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_long_term_memory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("agent_definition_id", sa.Integer(), nullable=False),
        sa.Column("memory_key", sa.String(length=160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_definition_id"], ["agent_definition.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["agent_long_term_memory.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "agent_definition_id", "memory_key", "version",
                            name="uq_agent_memory_key_version"),
        comment="隔离的 Agent 长期记忆版本及原始来源指纹",
    )
    op.create_index(
        "ix_agent_memory_scope_status", "agent_long_term_memory",
        ["project_id", "agent_definition_id", "status"],
    )


def downgrade():
    op.drop_index("ix_agent_memory_scope_status", table_name="agent_long_term_memory")
    op.drop_table("agent_long_term_memory")
