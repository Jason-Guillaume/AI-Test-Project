"""为现有知识绑定增加兼容默认的 Agent 访问模式。"""

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade():
    """旧绑定全部保留项目共享语义，严格 Agent 范围需显式启用。"""
    op.add_column(
        "project_agent_knowledge_binding",
        sa.Column("access_mode", sa.String(length=24), nullable=False,
                  server_default=sa.text("'PROJECT_SHARED'")),
    )


def downgrade():
    """移除访问模式字段；旧版服务按原项目共享语义继续工作。"""
    op.drop_column("project_agent_knowledge_binding", "access_mode")
