"""Create one public link and delivery row for multi-defect shares.

Revision ID: 0095
Revises: 0094
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0095"
down_revision = "0094"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)} if table in _tables() else set()


def upgrade() -> None:
    if "defect_share_batch" not in _tables():
        op.create_table(
            "defect_share_batch",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("public_id", sa.String(64), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel_id", sa.Integer(), sa.ForeignKey("notification_channel.id", ondelete="SET NULL"), nullable=True),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("request_key", sa.String(100), nullable=False),
            sa.Column("payload_hash", sa.String(64), nullable=False),
            sa.Column("allow_view", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("allow_resolve", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("pushed_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
            sa.Column("pushed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("delivery_status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("public_id", name="uq_defect_share_batch_public_id"),
            sa.UniqueConstraint("token_hash", name="uq_defect_share_batch_token_hash"),
            sa.UniqueConstraint("request_key", name="uq_defect_share_batch_request_key"),
        )
    batch_indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("defect_share_batch")}
    for name, column in (
        ("ix_defect_share_batch_project_id", "project_id"),
        ("ix_defect_share_batch_channel_id", "channel_id"),
        ("ix_defect_share_batch_expires_at", "expires_at"),
    ):
        if name not in batch_indexes:
            op.create_index(name, "defect_share_batch", [column])
    for name, column in (
        ("batch_id", sa.Column("batch_id", sa.Integer(), sa.ForeignKey("defect_share_batch.id", ondelete="SET NULL"), nullable=True)),
        ("request_key", sa.Column("request_key", sa.String(100), nullable=True)),
        ("payload_hash", sa.Column("payload_hash", sa.String(64), nullable=True)),
    ):
        if name not in _columns("defect_share_link"):
            op.add_column("defect_share_link", column)
    if not any(item["name"] == "ix_defect_share_link_batch_id" for item in sa.inspect(op.get_bind()).get_indexes("defect_share_link")):
        op.create_index("ix_defect_share_link_batch_id", "defect_share_link", ["batch_id"])
    if "share_batch_id" not in _columns("notification_record"):
        op.add_column("notification_record", sa.Column("share_batch_id", sa.Integer(), sa.ForeignKey("defect_share_batch.id", ondelete="SET NULL"), nullable=True))
    if not any(item["name"] == "ix_notification_record_share_batch_id" for item in sa.inspect(op.get_bind()).get_indexes("notification_record")):
        op.create_index("ix_notification_record_share_batch_id", "notification_record", ["share_batch_id"])
    if not any(item["name"] == "uq_defect_share_link_request_key" for item in sa.inspect(op.get_bind()).get_indexes("defect_share_link")):
        op.create_index("uq_defect_share_link_request_key", "defect_share_link", ["request_key"], unique=True)


def downgrade() -> None:
    if "notification_record" in _tables() and "share_batch_id" in _columns("notification_record"):
        op.drop_index("ix_notification_record_share_batch_id", table_name="notification_record")
        op.drop_column("notification_record", "share_batch_id")
    if "defect_share_link" in _tables():
        op.drop_index("uq_defect_share_link_request_key", table_name="defect_share_link")
        op.drop_index("ix_defect_share_link_batch_id", table_name="defect_share_link")
        for name in ("payload_hash", "request_key", "batch_id"):
            if name in _columns("defect_share_link"):
                op.drop_column("defect_share_link", name)
    if "defect_share_batch" in _tables():
        batch_indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("defect_share_batch")}
        for name in (
            "ix_defect_share_batch_project_id",
            "ix_defect_share_batch_channel_id",
            "ix_defect_share_batch_expires_at",
        ):
            if name in batch_indexes:
                op.drop_index(name, table_name="defect_share_batch")
        op.drop_table("defect_share_batch")
