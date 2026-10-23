"""UI 智能体二轮：受控浏览器会话与已执行步骤留痕表，不改既有用例/执行表。

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    """显式建表并兼容 seed_admin 的 stamp base + upgrade head 幂等重跑。"""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("web_agent_session"):
        op.create_table("web_agent_session",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
            sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id", ondelete="CASCADE"), nullable=False),
            sa.Column("auth_profile_id", sa.Integer(), sa.ForeignKey("web_auth_profile.id", ondelete="SET NULL")),
            sa.Column("base_url", sa.String(2000), nullable=False),
            sa.Column("target_page_path", sa.String(2000), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("step_budget", sa.Integer(), nullable=False, server_default="20"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("closed_at", sa.DateTime()))
        op.create_index("ix_web_agent_session_project_id", "web_agent_session", ["project_id"])
    if not inspector.has_table("web_agent_step"):
        op.create_table("web_agent_step",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("web_agent_session.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("step_encrypted", sa.Text(), nullable=False),
            sa.Column("observation_encrypted", sa.Text()),
            sa.Column("status", sa.String(16), nullable=False, server_default="PROPOSED"),
            sa.Column("source", sa.String(8), nullable=False, server_default="AI"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        op.create_index("ix_web_agent_step_session_id", "web_agent_step", ["session_id"])


def downgrade():
    """仅删除智能体会话与步骤留痕；既有 Web 用例、执行与报告数据保留。"""
    for table in ("web_agent_step", "web_agent_session"):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
