"""项目级环境绑定与目标配置。

Revision ID: 0018
Revises: 0017
"""

from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    """处理`upgrade`相关逻辑。"""
    op.create_table(
        "project_environment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=100), server_default=sa.text("''"), nullable=False),
        sa.Column("base_url", sa.String(length=500), server_default=sa.text("''"), nullable=False),
        sa.Column("gateway_prefix", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column("default_headers", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "environment_id", name="uq_project_environment_project_env"),
        comment="项目级执行环境及其目标服务配置",
    )
    op.create_index("ix_project_environment_project_id", "project_environment", ["project_id"])
    op.create_index("ix_project_environment_environment_id", "project_environment", ["environment_id"])
    op.create_index("ix_project_environment_is_default", "project_environment", ["is_default"])
    op.create_index("ix_project_environment_is_active", "project_environment", ["is_active"])
    op.create_index(
        "ix_project_environment_project_active", "project_environment", ["project_id", "is_active"]
    )

    # 复制旧全局环境到所有现有项目，保持已有计划引用的 environment_id 不变。
    bind = op.get_bind()
    bind.execute(sa.text("""
        INSERT INTO project_environment (
            project_id, environment_id, display_name, base_url, gateway_prefix,
            default_headers, description, is_default, is_active, created_by,
            updated_by, created_at, updated_at
        )
        SELECT p.id, e.id, e.display_name, e.base_url, e.gateway_prefix,
               e.default_headers, e.description, e.is_default, e.is_active,
               e.created_by, e.updated_by, e.created_at, e.updated_at
        FROM project AS p CROSS JOIN environment AS e
    """))


def downgrade():
    """处理`downgrade`相关逻辑。"""
    op.drop_index("ix_project_environment_project_active", table_name="project_environment")
    op.drop_index("ix_project_environment_is_active", table_name="project_environment")
    op.drop_index("ix_project_environment_is_default", table_name="project_environment")
    op.drop_index("ix_project_environment_environment_id", table_name="project_environment")
    op.drop_index("ix_project_environment_project_id", table_name="project_environment")
    op.drop_table("project_environment")
