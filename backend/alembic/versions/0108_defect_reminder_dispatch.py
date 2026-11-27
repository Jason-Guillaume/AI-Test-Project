"""缺陷积压提醒去重表。

按「项目 + 收件人 + 提醒类型 + 业务日」建立唯一索引，保证同一收件人
同一业务日最多收到一条积压提醒；业务日按北京时间（UTC+8）计算。

Revision ID: 0108
Revises: 0107
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0108"
down_revision = "0107"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "defect_reminder_dispatch" not in _tables():
        op.create_table(
            "defect_reminder_dispatch",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "project_id", sa.Integer(),
                sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column(
                "recipient_id", sa.Integer(),
                sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("reminder_type", sa.String(30), nullable=False, server_default=sa.text("'STALE_BACKLOG'")),
            sa.Column("business_date", sa.Date(), nullable=False),
            sa.Column(
                "notification_id", sa.Integer(),
                sa.ForeignKey("notification.id", ondelete="SET NULL"), nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            comment="缺陷积压提醒去重：项目/收件人/类型/业务日唯一",
        )
    if "ix_defect_reminder_dispatch_project_id" not in _indexes("defect_reminder_dispatch"):
        op.create_index("ix_defect_reminder_dispatch_project_id", "defect_reminder_dispatch", ["project_id"])
    if "ix_defect_reminder_dispatch_recipient_id" not in _indexes("defect_reminder_dispatch"):
        op.create_index("ix_defect_reminder_dispatch_recipient_id", "defect_reminder_dispatch", ["recipient_id"])
    if "uq_defect_reminder_dispatch_day" not in _indexes("defect_reminder_dispatch"):
        op.create_index(
            "uq_defect_reminder_dispatch_day", "defect_reminder_dispatch",
            ["project_id", "recipient_id", "reminder_type", "business_date"], unique=True,
        )
    if "ix_defect_reminder_dispatch_project_date" not in _indexes("defect_reminder_dispatch"):
        op.create_index(
            "ix_defect_reminder_dispatch_project_date", "defect_reminder_dispatch",
            ["project_id", "business_date"],
        )


def downgrade() -> None:
    if "defect_reminder_dispatch" in _tables():
        op.drop_table("defect_reminder_dispatch")