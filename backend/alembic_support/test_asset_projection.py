"""Transactional transfer of the typed test-asset projections in 0103/0105."""

from dataclasses import dataclass, field

import sqlalchemy as sa
from alembic import op

from alembic_support.frozen_schema import execute, restore_table, retain_sequence


@dataclass(frozen=True)
class AssetProjection:
    table: str
    storage: str
    kind: str
    aliases: dict[str, str] = field(default_factory=dict)

    @property
    def staged(self):
        return f"{self.table}_before_transfer"

    def fold(self):
        """Install an automatically updatable view with the historical defaults."""
        bind = op.get_bind()
        columns = sa.inspect(bind).get_columns(self.table)
        seq = f"{self.table}_id_seq"
        retain_sequence(seq, self.table, "id")
        execute(f"ALTER TABLE {self.table} RENAME TO {self.staged}")
        names = {"id": "public_id", **self.aliases}
        fields = ", ".join(f"{names.get(col['name'], col['name'])} AS {col['name']}" for col in columns)
        execute(f"CREATE VIEW {self.table} AS SELECT {fields} FROM {self.storage} "
                f"WHERE kind = '{self.kind}' WITH LOCAL CHECK OPTION")
        for column in columns:
            if column["default"] is not None:
                execute(f"ALTER VIEW {self.table} ALTER COLUMN {column['name']} SET DEFAULT {column['default']}")
        execute(f"ALTER SEQUENCE {seq} OWNED BY {self.storage}.public_id")
        self.copy_and_verify()

    def unfold(self):
        """Rebuild the entire original contract, including indexes and sequence ownership."""
        retain_sequence(f"{self.table}_id_seq", self.table, "id")
        execute(f"ALTER VIEW {self.table} RENAME TO {self.staged}")
        restore_table("0099", self.table)
        self.copy_and_verify()

    def copy_and_verify(self):
        bind = op.get_bind()
        last_id = None
        batch_size = 5000
        while True:
            after = "" if last_id is None else "WHERE id > :last_id"
            last_id, copied = bind.execute(sa.text(f"""
                WITH inserted AS (
                    INSERT INTO {self.table} SELECT * FROM {self.staged} {after}
                    ORDER BY id LIMIT :batch_size RETURNING id
                )
                SELECT max(id), count(*) FROM inserted
            """), {"last_id": last_id, "batch_size": batch_size}).one()
            if copied < batch_size:
                break
        # JSON columns have no PostgreSQL equality operator. Convert whole rows
        # only for comparison; the inserts above preserve the original JSON.
        different = bind.exec_driver_sql(f"""
            SELECT coalesce(source.id, target.id)
            FROM {self.staged} source FULL JOIN {self.table} target USING (id)
            WHERE source.id IS NULL OR target.id IS NULL OR to_jsonb(source.*) IS DISTINCT FROM to_jsonb(target.*)
            LIMIT 1
        """).scalar()
        if different is not None:
            raise ValueError(f"{self.table}: public ID {different} differs after transfer")


def external_keys():
    """Only foreign-key targets are needed to compile the frozen table definitions."""
    metadata = sa.MetaData()
    for table in ("user", "project", "environment"):
        sa.Table(table, metadata, sa.Column("id", sa.Integer))
    sa.Table("test_case", metadata, sa.Column("id", sa.Integer), sa.Column("project_id", sa.Integer))
    return metadata
