"""Consolidate immutable migration evidence with typed columns and the original case FK."""
from alembic import op

from alembic_support.frozen_schema import execute, restore_table, retain_sequence

revision = "0104"
down_revision = "0103"
branch_labels = None
depends_on = None

# public_id preserves the original primary key in each independent namespace.
SOURCES = {
    "test_scope_migration_check": ("SCOPE_CHECK", "id", "metric, before_count, after_count"),
    "test_scope_api_backfill": ("API_BACKFILL", "test_case_id", "test_case_id"),
    "model_global_migration_audit": ("MODEL_AUDIT", "resource_id", "project_id, previous_status, replacement_resource_id, decision"),
}


def upgrade() -> None:
    execute("LOCK TABLE test_scope_migration_check, test_scope_api_backfill, model_global_migration_audit "
            "IN ACCESS EXCLUSIVE MODE")
    execute("""
        CREATE TABLE migration_evidence (
            kind varchar(20) NOT NULL, public_id integer NOT NULL,
            metric varchar(80) UNIQUE, before_count integer, after_count integer,
            test_case_id integer REFERENCES test_case(id) ON DELETE CASCADE,
            project_id integer, previous_status varchar(20), replacement_resource_id integer, decision varchar(40),
            PRIMARY KEY (kind, public_id),
            CONSTRAINT ck_migration_evidence_kind CHECK (
                (kind = 'SCOPE_CHECK' AND metric IS NOT NULL AND before_count IS NOT NULL AND after_count IS NOT NULL
                    AND test_case_id IS NULL AND project_id IS NULL AND previous_status IS NULL
                    AND replacement_resource_id IS NULL AND decision IS NULL)
                OR (kind = 'API_BACKFILL' AND test_case_id IS NOT NULL AND test_case_id = public_id AND metric IS NULL
                    AND before_count IS NULL AND after_count IS NULL AND project_id IS NULL AND previous_status IS NULL
                    AND replacement_resource_id IS NULL AND decision IS NULL)
                OR (kind = 'MODEL_AUDIT' AND decision IS NOT NULL AND metric IS NULL
                    AND before_count IS NULL AND after_count IS NULL AND test_case_id IS NULL))
        )
    """)
    for table, (kind, key, fields) in SOURCES.items():
        execute(f"INSERT INTO migration_evidence (kind, public_id, {fields}) "
                f"SELECT '{kind}', {key}, {fields} FROM {table}")
        if key != "test_case_id":
            retain_sequence(f"{table}_{key}_seq", table, key)
        op.drop_table(table)
        projection = fields if key == "test_case_id" else f"public_id AS {key}, {fields}"
        # OFFSET 0 makes these historical evidence views read-only, including single-table projections.
        execute(f"CREATE VIEW {table} AS SELECT {projection} FROM migration_evidence "
                f"WHERE kind = '{kind}' OFFSET 0")


def downgrade() -> None:
    execute("LOCK TABLE migration_evidence IN ACCESS EXCLUSIVE MODE")
    for table, (kind, key, fields) in SOURCES.items():
        if key != "test_case_id":
            retain_sequence(f"{table}_{key}_seq", table, key)
        execute(f"DROP VIEW {table}")
        restore_table("0099", table)
        columns = fields if key == "test_case_id" else f"{key}, {fields}"
        values = fields if key == "test_case_id" else f"public_id, {fields}"
        execute(f"INSERT INTO {table} ({columns}) SELECT {values} FROM migration_evidence WHERE kind = '{kind}'")
    op.drop_table("migration_evidence")
