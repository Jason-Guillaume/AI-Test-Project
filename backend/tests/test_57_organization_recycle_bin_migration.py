"""0084 migration compatibility with partially pre-existing lifecycle schema."""

from __future__ import annotations

import importlib.util

import psycopg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from tests.test_50_migration_0049 import BACKEND_DIR, _upgrade, _url, scratch

MIGRATION_FILE = BACKEND_DIR / "alembic/versions/0084_organization_recycle_bin.py"
spec = importlib.util.spec_from_file_location("migration_0084", MIGRATION_FILE)
migration_0084 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(migration_0084)


@pytest.mark.parametrize(
    "preexisting, existing_deleted_by_fk",
    [
        (set(), False),
        ({"deleted_at"}, False),
        ({"deleted_by"}, False),
        ({"deletion_reason"}, False),
        ({"deletion_batch_id"}, False),
        ({"deleted_at", "deleted_by", "deletion_reason", "deletion_batch_id"}, False),
        ({"deleted_at", "deleted_by", "deletion_reason", "deletion_batch_id"}, True),
    ],
)
def test_0084_sqlite_adds_each_missing_field_and_fk_without_losing_data(preexisting, existing_deleted_by_fk):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql('CREATE TABLE "user" (id INTEGER PRIMARY KEY)')
            connection.exec_driver_sql('CREATE TABLE organization (id INTEGER PRIMARY KEY)')
            connection.exec_driver_sql('INSERT INTO "user" (id) VALUES (1)')
            connection.exec_driver_sql("INSERT INTO organization (id) VALUES (1)")
            definitions = {
                "deleted_at": "DATETIME",
                "deleted_by": "INTEGER",
                "deletion_reason": "VARCHAR(500)",
                "deletion_batch_id": "VARCHAR(36)",
            }
            for name in preexisting:
                existing_reference = ' REFERENCES "user"(id) ON DELETE SET NULL' if name == "deleted_by" and existing_deleted_by_fk else ""
                connection.exec_driver_sql(f"ALTER TABLE organization ADD COLUMN {name} {definitions[name]}{existing_reference}")
                value = {"deleted_at": "2026-11-13 00:00:00", "deleted_by": 1,
                         "deletion_reason": "retained", "deletion_batch_id": "legacy-batch"}[name]
                connection.execute(text(f"UPDATE organization SET {name}=:value WHERE id=1"), {"value": value})
            with Operations.context(MigrationContext.configure(connection)):
                migration_0084.upgrade()
                migration_0084.upgrade()
                migration_0084.downgrade()

            columns = {column["name"] for column in inspect(connection).get_columns("organization")}
            assert {"deleted_at", "deleted_by", "deletion_reason", "deletion_batch_id"} <= columns
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_list(organization)").fetchall()
            assert any(
                fk[2] == "user" and fk[3] == "deleted_by" and fk[4] == "id" and fk[6] == "SET NULL"
                for fk in foreign_keys
            )
            assert sum(1 for fk in foreign_keys if fk[3] == "deleted_by") == 1
            values = connection.execute(text(
                "SELECT deleted_at, deleted_by, deletion_reason, deletion_batch_id FROM organization WHERE id=1"
            )).one()
            for index, name in enumerate(("deleted_at", "deleted_by", "deletion_reason", "deletion_batch_id")):
                if name in preexisting:
                    expected = {"deleted_at": "2026-11-13 00:00:00", "deleted_by": 1,
                                "deletion_reason": "retained", "deletion_batch_id": "legacy-batch"}[name]
                    assert str(values[index]).startswith(str(expected))
                else:
                    assert values[index] is None
    finally:
        engine.dispose()


def test_0084_postgres_adds_all_missing_fields_and_is_repeatable(scratch):
    _upgrade(scratch, "0083")
    plain_url = _url(scratch).replace("+psycopg", "")
    with psycopg.connect(plain_url, autocommit=True) as connection:
        connection.execute('INSERT INTO "user" (username, hashed_password) VALUES (%s, %s)', ("0084-fresh-owner", "x"))
        connection.execute("INSERT INTO organization (name, owner_id) VALUES (%s, %s)", ("fresh-org", 1))

    _upgrade(scratch, "0084")
    _upgrade(scratch, "0084")
    with psycopg.connect(plain_url) as connection:
        columns = {row[0] for row in connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='organization'"
        )}
        assert {"deleted_at", "deleted_by", "deletion_reason", "deletion_batch_id"} <= columns
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0084"
        assert connection.execute(
            "SELECT 1 FROM pg_constraint WHERE conrelid='organization'::regclass AND contype='f' "
            "AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (deleted_by)%' "
            "AND pg_get_constraintdef(oid) LIKE '%ON DELETE SET NULL%'"
        ).fetchone()

    _upgrade(scratch, "0083")
    _upgrade(scratch, "0084")


def test_0084_postgres_repairs_partial_schema_and_safe_downgrade(scratch):
    _upgrade(scratch, "0083")
    plain_url = _url(scratch).replace("+psycopg", "")
    with psycopg.connect(plain_url, autocommit=True) as connection:
        connection.execute('INSERT INTO "user" (username, hashed_password) VALUES (%s, %s)', ("0084-owner", "x"))
        connection.execute("INSERT INTO organization (name, owner_id) VALUES (%s, %s)", ("legacy-org", 1))
        connection.execute("ALTER TABLE organization ADD COLUMN deleted_at timestamp NULL")
        connection.execute("ALTER TABLE organization ADD COLUMN deleted_by integer NULL")
        connection.execute("ALTER TABLE organization ADD COLUMN deletion_reason varchar(500) NULL")
        connection.execute(
            "UPDATE organization SET deleted_at=%s, deleted_by=1, deletion_reason=%s WHERE id=1",
            ("2026-11-13 00:00:00", "retained"),
        )

    _upgrade(scratch, "0084")
    with psycopg.connect(plain_url) as connection:
        columns = {row[0] for row in connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='organization'"
        )}
        assert {"deleted_at", "deleted_by", "deletion_reason", "deletion_batch_id"} <= columns
        foreign_key = connection.execute(
            "SELECT 1 FROM pg_constraint WHERE conrelid='organization'::regclass AND contype='f' "
            "AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (deleted_by)%' "
            "AND pg_get_constraintdef(oid) LIKE '%ON DELETE SET NULL%'"
        ).fetchone()
        assert foreign_key
        row = connection.execute(
            "SELECT deleted_at, deleted_by, deletion_reason, deletion_batch_id FROM organization WHERE id=1"
        ).fetchone()
        assert row and row[0] and row[1] == 1 and row[2] == "retained" and row[3] is None

    _upgrade(scratch, "0083")
    with psycopg.connect(plain_url) as connection:
        row = connection.execute(
            "SELECT deleted_at, deleted_by, deletion_reason FROM organization WHERE id=1"
        ).fetchone()
        assert row and row[0] and row[1] == 1 and row[2] == "retained"
    _upgrade(scratch, "0084")
