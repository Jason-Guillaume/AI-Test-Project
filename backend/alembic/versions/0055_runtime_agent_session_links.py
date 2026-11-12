"""将调用与运行事件事实关联到既有 AgentSession。"""

import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade():
    """为运行事实补充 AgentSession 外键与查询索引。"""
    op.add_column("runtime_call_fact", sa.Column("agent_session_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_runtime_call_fact_agent_session", "runtime_call_fact", "agent_session",
        ["agent_session_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_runtime_call_fact_agent_session_id", "runtime_call_fact", ["agent_session_id"])
    op.add_column("runtime_event_fact", sa.Column("agent_session_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_runtime_event_fact_agent_session", "runtime_event_fact", "agent_session",
        ["agent_session_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_runtime_event_fact_agent_session_id", "runtime_event_fact", ["agent_session_id"])


def downgrade():
    """移除 AgentSession 关联字段，不删除会话或事实数据。"""
    op.drop_index("ix_runtime_event_fact_agent_session_id", table_name="runtime_event_fact")
    op.drop_constraint("fk_runtime_event_fact_agent_session", "runtime_event_fact", type_="foreignkey")
    op.drop_column("runtime_event_fact", "agent_session_id")
    op.drop_index("ix_runtime_call_fact_agent_session_id", table_name="runtime_call_fact")
    op.drop_constraint("fk_runtime_call_fact_agent_session", "runtime_call_fact", type_="foreignkey")
    op.drop_column("runtime_call_fact", "agent_session_id")
