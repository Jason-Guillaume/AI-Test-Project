"""Web UI 自动化一期：独立扩展表，不修改已有测试执行和安全模块表结构。

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    """显式建表并支持 seed_admin 的 stamp base + upgrade head 幂等重跑。"""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("web_page_object"):
        op.create_table("web_page_object",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False), sa.Column("path", sa.String(2000), nullable=False),
            sa.Column("elements", sa.JSON(), nullable=False), sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("project_id", "name", name="uq_web_page_project_name"))
        op.create_index("ix_web_page_object_project_id", "web_page_object", ["project_id"])
    if not inspector.has_table("web_auth_profile"):
        op.create_table("web_auth_profile",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
            sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False), sa.Column("secret_encrypted", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        op.create_index("ix_web_auth_profile_project_id", "web_auth_profile", ["project_id"])
    if not inspector.has_table("web_case"):
        op.create_table("web_case",
            sa.Column("test_case_id", sa.Integer(), sa.ForeignKey("test_case.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("auth_profile_id", sa.Integer(), sa.ForeignKey("web_auth_profile.id", ondelete="SET NULL")),
            sa.Column("timeout_ms", sa.Integer(), nullable=False, server_default="30000"),
            sa.Column("total_timeout_ms", sa.Integer(), nullable=False, server_default="120000"),
            sa.Column("confirmed_digest", sa.String(64)),
            sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")))
    if not inspector.has_table("web_artifact"):
        op.create_table("web_artifact",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
            sa.Column("test_case_id", sa.Integer(), sa.ForeignKey("test_case.id", ondelete="SET NULL")),
            sa.Column("case_execution_id", sa.Integer(), sa.ForeignKey("case_execution.id", ondelete="CASCADE")),
            sa.Column("kind", sa.String(20), nullable=False), sa.Column("content_encrypted", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        op.create_index("ix_web_artifact_project_id", "web_artifact", ["project_id"])
        op.create_index("ix_web_artifact_case_execution_id", "web_artifact", ["case_execution_id"])


def downgrade():
    """仅删除 Web UI 扩展；既有用例、执行、报告和安全数据保留。"""
    for table in ("web_artifact", "web_case", "web_auth_profile", "web_page_object"):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
