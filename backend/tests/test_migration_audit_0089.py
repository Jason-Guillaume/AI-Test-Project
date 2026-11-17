"""Alembic 0087-0089 数据库迁移一致性、幂等性、索引外键与回滚安全验证。"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from tests.conftest import BACKEND_DIR


def test_alembic_has_single_head_0089():
    script = ScriptDirectory(str(Path(BACKEND_DIR) / "alembic"))
    heads = script.get_heads()
    assert heads == ["0089"]


def test_upgrade_from_0086_through_0089_and_verify_schema_indexes(isolated_migration_database):
    config, engine = isolated_migration_database

    # Downgrade to 0086 on isolated empty schema, then upgrade cleanly to head (0089).
    command.downgrade(config, "0086")
    command.upgrade(config, "head")
    # Re-running upgrade head is idempotent (no-op).
    command.upgrade(config, "head")

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"defect_share_link", "defect_external_action", "automation_execution_idempotency"} <= tables

    share_indexes = {idx["name"] for idx in inspector.get_indexes("defect_share_link")}
    assert {
        "ix_defect_share_link_bug_id",
        "ix_defect_share_link_project_id",
        "ix_defect_share_link_channel_id",
        "ix_defect_share_link_expires_at",
    } <= share_indexes

    share_fks = {fk["name"]: fk for fk in inspector.get_foreign_keys("defect_share_link")}
    assert share_fks["fk_defect_share_link_bug_id"]["options"].get("ondelete") == "CASCADE"
    assert share_fks["fk_defect_share_link_project_id"]["options"].get("ondelete") == "CASCADE"
    assert share_fks["fk_defect_share_link_channel_id"]["options"].get("ondelete") == "SET NULL"

    action_indexes = {idx["name"] for idx in inspector.get_indexes("defect_external_action")}
    assert {
        "ix_defect_external_action_bug_id",
        "ix_defect_external_action_share_link_id",
    } <= action_indexes

    notif_indexes = {idx["name"] for idx in inspector.get_indexes("notification_record")}
    assert {
        "ix_notification_record_bug_id",
        "ix_notification_record_share_link_id",
        "uq_notification_record_idempotency_key",
    } <= notif_indexes


def test_downgrade_0089_to_0088_and_reupgrade(isolated_migration_database):
    config, engine = isolated_migration_database

    command.downgrade(config, "0088")
    inspector = inspect(engine)
    tables_0088 = set(inspector.get_table_names())
    assert "defect_share_link" not in tables_0088
    assert "defect_external_action" not in tables_0088

    command.upgrade(config, "0089")
    inspector = inspect(engine)
    tables_0089 = set(inspector.get_table_names())
    assert {"defect_share_link", "defect_external_action"} <= tables_0089
