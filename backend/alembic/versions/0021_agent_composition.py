"""支持受控子 Agent 组合。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    """给 Agent 定义增加最多一层的子 Agent 引用。"""
    op.add_column(
        "agent_definition",
        sa.Column("child_agent_ids", sa.JSON(), server_default=text("'[]'"), nullable=False),
    )


def downgrade():
    """处理`downgrade`相关逻辑。"""
    op.drop_column("agent_definition", "child_agent_ids")
