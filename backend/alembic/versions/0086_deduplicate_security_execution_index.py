"""Remove the duplicate security execution run index."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None


TABLE = "security_execution"
CANONICAL_INDEX = "ix_security_execution_test_run_id"
REDUNDANT_INDEX = "ix_security_execution_run"


def _indexes() -> dict[str, dict] | None:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return None
    return {index["name"]: index for index in inspector.get_indexes(TABLE)}


def _validate_index(index: dict, name: str) -> None:
    if index.get("column_names") != ["test_run_id"] or index.get("unique", False):
        raise RuntimeError(
            f"Refusing to alter unexpected {TABLE}.{name}: expected a non-unique index on test_run_id"
        )


def upgrade() -> None:
    indexes = _indexes()
    if indexes is None:
        return

    for name in (CANONICAL_INDEX, REDUNDANT_INDEX):
        if name in indexes:
            _validate_index(indexes[name], name)

    if CANONICAL_INDEX not in indexes:
        op.create_index(CANONICAL_INDEX, TABLE, ["test_run_id"])
    if REDUNDANT_INDEX in indexes:
        op.drop_index(REDUNDANT_INDEX, table_name=TABLE)


def downgrade() -> None:
    indexes = _indexes()
    if indexes is None or REDUNDANT_INDEX in indexes:
        return
    if CANONICAL_INDEX in indexes:
        _validate_index(indexes[CANONICAL_INDEX], CANONICAL_INDEX)
    op.create_index(REDUNDANT_INDEX, TABLE, ["test_run_id"])
