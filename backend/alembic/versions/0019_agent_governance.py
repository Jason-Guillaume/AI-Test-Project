"""新增 Agent、Skill 与 MCP 管理配置。

Revision ID: 0019
Revises: 0018
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func, text

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    """创建管理配置表；所有凭据只保存密文，工具发现结果默认不授权。"""
    op.create_table(
        "agent_definition",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(36), nullable=False, comment="后端生成的稳定引用键"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), server_default=text("''"), nullable=False),
        sa.Column("workflow_template", sa.String(40), nullable=False),
        sa.Column("instruction", sa.Text(), server_default=text("''"), nullable=False),
        sa.Column("model_config_id", sa.Integer(), nullable=True),
        sa.Column("skill_keys", sa.JSON(), server_default=text("'[]'"), nullable=False),
        sa.Column("tool_keys", sa.JSON(), server_default=text("'[]'"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=text("false"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=text("1"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["model_config_id"], ["model_configuration.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="受控工作流 Agent 定义",
    )
    op.create_index("ix_agent_definition_key", "agent_definition", ["key"], unique=True)
    op.create_index("ix_agent_definition_is_enabled", "agent_definition", ["is_enabled"])

    op.create_table(
        "skill_definition",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(36), nullable=False, comment="后端生成的稳定引用键"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), server_default=text("''"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=text("false"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=text("1"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="可复用 Agent Skill 内容",
    )
    op.create_index("ix_skill_definition_key", "skill_definition", ["key"], unique=True)
    op.create_index("ix_skill_definition_is_enabled", "skill_definition", ["is_enabled"])

    op.create_table(
        "agent_definition_revision",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_definition_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agent_definition_id"], ["agent_definition.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_definition_id", "version", name="uq_agent_definition_revision_version"),
        comment="Agent 不可变配置版本快照",
    )
    op.create_index("ix_agent_definition_revision_agent_definition_id", "agent_definition_revision", ["agent_definition_id"])

    op.create_table(
        "skill_definition_revision",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("skill_definition_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["skill_definition_id"], ["skill_definition.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_definition_id", "version", name="uq_skill_definition_revision_version"),
        comment="Skill 不可变内容版本快照",
    )
    op.create_index("ix_skill_definition_revision_skill_definition_id", "skill_definition_revision", ["skill_definition_id"])

    op.create_table(
        "mcp_server",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("endpoint", sa.String(1000), nullable=False),
        sa.Column("auth_type", sa.String(20), server_default=text("'none'"), nullable=False),
        sa.Column("auth_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=text("false"), nullable=False),
        sa.Column("connection_status", sa.String(20), server_default=text("'unknown'"), nullable=False),
        sa.Column("discovered_tools_json", sa.JSON(), server_default=text("'[]'"), nullable=False),
        sa.Column("approved_tools_json", sa.JSON(), server_default=text("'[]'"), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="MCP 服务端点与只读发现状态",
    )
    op.create_index("ix_mcp_server_is_enabled", "mcp_server", ["is_enabled"])


def downgrade():
    """处理`downgrade`相关逻辑。"""
    op.drop_index("ix_skill_definition_revision_skill_definition_id", table_name="skill_definition_revision")
    op.drop_table("skill_definition_revision")
    op.drop_index("ix_agent_definition_revision_agent_definition_id", table_name="agent_definition_revision")
    op.drop_table("agent_definition_revision")
    op.drop_index("ix_mcp_server_is_enabled", table_name="mcp_server")
    op.drop_table("mcp_server")
    op.drop_index("ix_skill_definition_is_enabled", table_name="skill_definition")
    op.drop_index("ix_skill_definition_key", table_name="skill_definition")
    op.drop_table("skill_definition")
    op.drop_index("ix_agent_definition_is_enabled", table_name="agent_definition")
    op.drop_index("ix_agent_definition_key", table_name="agent_definition")
    op.drop_table("agent_definition")
