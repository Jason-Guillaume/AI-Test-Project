"""Load reviewed, historical PostgreSQL DDL without importing current application models."""
from pathlib import Path

from alembic import op

_DDL = Path(__file__).resolve().parents[1] / "alembic" / "ddl"


def execute(sql: str) -> None:
    # Send literal DDL directly. Comments and PL/pgSQL may contain colons and percent signs.
    context = op.get_context()
    if context.as_sql:
        context.impl.static_output(sql.rstrip().removesuffix(";") + ";")
    else:
        op.get_bind().exec_driver_sql(sql, execution_options={"no_parameters": True})


def restore_table(version: str, name: str) -> None:
    execute((_DDL / version / f"{name}.sql").read_text(encoding="utf-8"))


def retain_sequence(sequence: str, table: str, column: str) -> None:
    """Detach a historical SERIAL before dropping its table; never lower its high-water mark."""
    execute(f"ALTER SEQUENCE {sequence} OWNED BY NONE")
    execute(f"""
        SELECT setval('{sequence}', max({column}), true)
        FROM {table}
        HAVING max({column}) > (SELECT last_value FROM {sequence})
            OR (max({column}) = (SELECT last_value FROM {sequence})
                AND NOT (SELECT is_called FROM {sequence}))
    """)
