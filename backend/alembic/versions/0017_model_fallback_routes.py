"""模型配置增加有序备用模型路由。

Revision ID: 0017
Revises: 0016
"""

from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    """为既有模型配置添加空备用链，保持旧配置调用行为不变。"""
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("model_configuration")}
    if "fallback_model_ids" not in columns:
        op.add_column(
            "model_configuration",
            sa.Column("fallback_model_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'"), comment="有序备用模型配置 ID"),
        )


def downgrade():
    """删除备用模型路由字段；任务运行快照仍保留已创建任务的候选顺序。"""
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("model_configuration")}
    if "fallback_model_ids" in columns:
        op.drop_column("model_configuration", "fallback_model_ids")
