"""为任务 Agent 实例保存可恢复的成功输出检查点。"""

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade():
    """新增可空检查点列，不回填或改写历史 Agent 运行。"""
    op.add_column(
        "task_agent_instance",
        sa.Column("result_json", sa.JSON(), nullable=True,
                  comment="可恢复子 Agent 的成功输出检查点及输入指纹"),
    )


def downgrade():
    """移除派生检查点列；不影响任务状态、模型调用或 Langfuse Trace。"""
    op.drop_column("task_agent_instance", "result_json")
