"""为 Dagu 增加已提交后的投递状态，以及执行请求幂等约束。

dispatch_state 让平台先提交执行记录，再调用 Dagu。历史行默认 CONFIRMED，
避免升级后把旧的云效或归档记录重新入队。幂等表用数据库唯一约束挡住并发重复点击。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加投递状态和幂等表。已有执行视为已经确认，不参与补投。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "automation_execution" not in tables:
        return
    columns = {item["name"] for item in inspector.get_columns("automation_execution")}
    if "dispatch_state" not in columns:
        op.add_column(
            "automation_execution",
            sa.Column("dispatch_state", sa.String(20), nullable=False, server_default="CONFIRMED"),
        )
    indexes = {item["name"] for item in inspector.get_indexes("automation_execution")}
    if "ix_automation_execution_dispatch" not in indexes:
        op.create_index(
            "ix_automation_execution_dispatch",
            "automation_execution",
            ["provider_type", "dispatch_state", "status"],
        )
    if "automation_execution_idempotency" not in tables:
        op.create_table(
            "automation_execution_idempotency",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("automation_project_id", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=120), nullable=False),
            sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("execution_id", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(
                ["automation_project_id"], ["automation_project.id"], ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["execution_id"], ["automation_execution.id"], ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "automation_project_id", "idempotency_key", name="uq_automation_execution_idempotency",
            ),
        )
        op.create_index(
            "ix_automation_execution_idempotency_expires",
            "automation_execution_idempotency",
            ["expires_at"],
        )


def downgrade() -> None:
    """去掉幂等表和投递状态。执行记录本身保留。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "automation_execution_idempotency" in tables:
        op.drop_index("ix_automation_execution_idempotency_expires", table_name="automation_execution_idempotency")
        op.drop_table("automation_execution_idempotency")
    if "automation_execution" not in tables:
        return
    indexes = {item["name"] for item in inspector.get_indexes("automation_execution")}
    if "ix_automation_execution_dispatch" in indexes:
        op.drop_index("ix_automation_execution_dispatch", table_name="automation_execution")
    columns = {item["name"] for item in inspector.get_columns("automation_execution")}
    if "dispatch_state" in columns:
        op.drop_column("automation_execution", "dispatch_state")
