"""缺陷免登录分享、外部修复审计，以及通知记录上的缺陷关联。

分享凭证只存 SHA-256。降级会删除分享和外部处理记录，通知记录上的新增列一并移除。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    """读取当前库里的表名；空库升级时用来跳过不存在的对象。"""
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    """读取一张表的列名。表不存在时返回空集。"""
    if table not in _tables():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """建立分享表和外部处理表，并给通知记录补上缺陷关联列。"""
    # 旧开发库可能将分享迁移标记为 0088；补执行幂等的 Dagu 0088。
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    spec = spec_from_file_location("dagu_0088_compat", Path(__file__).with_name("0088_dagu_dispatch_idempotency.py"))
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()
    tables = _tables()
    if "defect_share_link" not in tables:
        op.create_table(
            "defect_share_link",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("share_id", sa.String(length=64), nullable=False),
            sa.Column("bug_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("channel_id", sa.Integer(), nullable=True),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("allow_view", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("allow_resolve", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("visible_fields", sa.JSON(), nullable=False),
            sa.Column("content_snapshot", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("pushed_by", sa.Integer(), nullable=True),
            sa.Column("pushed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("view_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_viewed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["bug_id"], ["bug.id"], name="fk_defect_share_link_bug_id", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], name="fk_defect_share_link_project_id", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["channel_id"], ["notification_channel.id"], name="fk_defect_share_link_channel_id", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["pushed_by"], ["user.id"], name="fk_defect_share_link_pushed_by", ondelete="SET NULL"),
            sa.UniqueConstraint("share_id", name="uq_defect_share_link_share_id"),
            sa.UniqueConstraint("token_hash", name="uq_defect_share_link_token_hash"),
            comment="缺陷免登录分享：只保存访问凭证哈希",
        )
        op.create_index("ix_defect_share_link_bug_id", "defect_share_link", ["bug_id"])
        op.create_index("ix_defect_share_link_project_id", "defect_share_link", ["project_id"])
        op.create_index("ix_defect_share_link_channel_id", "defect_share_link", ["channel_id"])
        op.create_index("ix_defect_share_link_expires_at", "defect_share_link", ["expires_at"])
    if "defect_external_action" not in _tables():
        op.create_table(
            "defect_external_action",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("bug_id", sa.Integer(), nullable=False),
            sa.Column("share_link_id", sa.Integer(), nullable=False),
            sa.Column("action_type", sa.String(length=32), nullable=False),
            sa.Column("old_status", sa.String(length=20), nullable=False),
            sa.Column("new_status", sa.String(length=20), nullable=False),
            sa.Column("actor_type", sa.String(length=32), nullable=False),
            sa.Column("actor_display_name", sa.String(length=40), nullable=True),
            sa.Column("repair_description", sa.Text(), nullable=False),
            sa.Column("fix_version", sa.String(length=80), nullable=True),
            sa.Column("commit_sha", sa.String(length=64), nullable=True),
            sa.Column("idempotency_key", sa.String(length=120), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["bug_id"], ["bug.id"], name="fk_defect_external_action_bug_id", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["share_link_id"], ["defect_share_link.id"], name="fk_defect_external_action_share_id", ondelete="CASCADE"),
            sa.UniqueConstraint("idempotency_key", name="uq_defect_external_action_idempotency"),
            comment="免登录分享产生的缺陷处理记录",
        )
        op.create_index("ix_defect_external_action_bug_id", "defect_external_action", ["bug_id"])
        op.create_index("ix_defect_external_action_share_link_id", "defect_external_action", ["share_link_id"])
        op.create_index(
            "uq_defect_external_resolve_once",
            "defect_external_action",
            ["share_link_id"],
            unique=True,
            postgresql_where=sa.text("action_type = 'RESOLVE'"),
        )
    columns = _columns("notification_record")
    if "bug_id" not in columns:
        op.add_column("notification_record", sa.Column("bug_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_notification_record_bug_id", "notification_record", "bug", ["bug_id"], ["id"], ondelete="SET NULL")
        op.create_index("ix_notification_record_bug_id", "notification_record", ["bug_id"])
    if "share_link_id" not in columns:
        op.add_column("notification_record", sa.Column("share_link_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_notification_record_share_link_id", "notification_record", "defect_share_link",
            ["share_link_id"], ["id"], ondelete="SET NULL",
        )
        op.create_index("ix_notification_record_share_link_id", "notification_record", ["share_link_id"])
    if "event_type" not in columns:
        op.add_column("notification_record", sa.Column("event_type", sa.String(length=40), nullable=True))
    if "idempotency_key" not in columns:
        op.add_column("notification_record", sa.Column("idempotency_key", sa.String(length=120), nullable=True))
        op.create_index("uq_notification_record_idempotency_key", "notification_record", ["idempotency_key"], unique=True)
    if "retry_count" not in columns:
        op.add_column(
            "notification_record",
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    """移除本次新增的分享结构。已有报告通知记录保留，只删新增列。"""
    columns = _columns("notification_record")
    if "retry_count" in columns:
        op.drop_column("notification_record", "retry_count")
    if "idempotency_key" in columns:
        op.drop_index("uq_notification_record_idempotency_key", table_name="notification_record")
        op.drop_column("notification_record", "idempotency_key")
    if "event_type" in columns:
        op.drop_column("notification_record", "event_type")
    if "share_link_id" in columns:
        op.drop_index("ix_notification_record_share_link_id", table_name="notification_record")
        op.drop_constraint("fk_notification_record_share_link_id", "notification_record", type_="foreignkey")
        op.drop_column("notification_record", "share_link_id")
    if "bug_id" in columns:
        op.drop_index("ix_notification_record_bug_id", table_name="notification_record")
        op.drop_constraint("fk_notification_record_bug_id", "notification_record", type_="foreignkey")
        op.drop_column("notification_record", "bug_id")
    tables = _tables()
    if "defect_external_action" in tables:
        op.drop_index("uq_defect_external_resolve_once", table_name="defect_external_action")
        op.drop_index("ix_defect_external_action_share_link_id", table_name="defect_external_action")
        op.drop_index("ix_defect_external_action_bug_id", table_name="defect_external_action")
        op.drop_table("defect_external_action")
    if "defect_share_link" in tables:
        op.drop_index("ix_defect_share_link_expires_at", table_name="defect_share_link")
        op.drop_index("ix_defect_share_link_channel_id", table_name="defect_share_link")
        op.drop_index("ix_defect_share_link_project_id", table_name="defect_share_link")
        op.drop_index("ix_defect_share_link_bug_id", table_name="defect_share_link")
        op.drop_table("defect_share_link")
