"""Fold a one-to-one child into nullable parent columns while retaining its SQL interface."""
from dataclasses import dataclass

import sqlalchemy as sa
from alembic import op

from alembic_support.frozen_schema import execute, restore_table, retain_sequence


@dataclass(frozen=True)
class Extension:
    child: str
    parent: str
    parent_key: str
    fields: dict[str, str]  # old child name -> separate physical column on the parent
    marker: str             # a required child field whose NULL represents an absent child

    @property
    def sequence(self) -> str | None:
        return f"{self.child}_id_seq" if "id" in self.fields else None

    def fold(self) -> None:
        table, parent, key = self.child, self.parent, self.parent_key
        execute(f"LOCK TABLE {parent}, {table} IN ACCESS EXCLUSIVE MODE")
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        columns = {col["name"]: col for col in inspector.get_columns(table)}
        if set(columns) != {key, *self.fields}:
            raise ValueError(f"Unexpected columns in {table}: {set(columns) ^ {key, *self.fields}}")
        for old, new in self.fields.items():
            op.add_column(parent, sa.Column(new, columns[old]["type"], comment=columns[old]["comment"]))
        for fk in inspector.get_foreign_keys(table):
            old, = fk["constrained_columns"]
            if old != key:
                op.create_foreign_key(f"fk_{parent}_{self.fields[old]}", parent, fk["referred_table"],
                                      [self.fields[old]], fk["referred_columns"], **fk["options"])
        absent = " AND ".join(f"{col} IS NULL" for col in self.fields.values())
        present = " AND ".join(f"{new} IS NOT NULL" for old, new in self.fields.items()
                               if not columns[old]["nullable"])
        op.create_check_constraint(f"ck_{table}_presence", parent, f"({absent}) OR ({present})")
        if self.sequence:
            retain_sequence(self.sequence, table, "id")
            op.create_unique_constraint(f"uq_{parent}_{self.fields['id']}", parent, [self.fields["id"]])
        assignments = ", ".join(f"{new} = c.{old}" for old, new in self.fields.items())
        execute(f"UPDATE {parent} p SET {assignments} FROM {table} c WHERE p.id = c.{key}")
        op.drop_table(table)
        if self.sequence:
            execute(f"ALTER SEQUENCE {self.sequence} OWNED BY {parent}.{self.fields['id']}")
        mapping = {old: ("id" if old == key else self.fields[old]) for old in columns}
        projection = ", ".join(f"{new} AS {old}" for old, new in mapping.items())
        marker = self.fields[self.marker]
        execute(f"CREATE VIEW {table} AS SELECT {projection} FROM {parent} WHERE {marker} IS NOT NULL")
        for old, col in columns.items():
            if col["default"] is not None:
                execute(f"ALTER VIEW {table} ALTER COLUMN {old} SET DEFAULT {col['default']}")
        self._write_trigger(mapping, columns)

    def _write_trigger(self, mapping: dict, columns: dict) -> None:
        table, parent, key = self.child, self.parent, self.parent_key
        marker = self.fields[self.marker]
        # A concurrently replaced child has a different public identity even on the same parent.
        match_old = f"{marker} = OLD.id" if self.sequence else f"{marker} IS NOT NULL"
        clear = ", ".join(f"{col} = NULL" for col in self.fields.values())
        insert = ", ".join(f"{new} = NEW.{old}" for old, new in self.fields.items())
        # A partial UPDATE must preserve other fields a concurrent writer has just committed.
        changes = []
        for old, new in self.fields.items():
            cast = "::text" if isinstance(columns[old]["type"], sa.JSON) else ""
            changes.append(f"{new} = CASE WHEN NEW.{old}{cast} IS DISTINCT FROM OLD.{old}{cast} "
                           f"THEN NEW.{old} ELSE {new} END")
        changes = ", ".join(changes)
        returning = ", ".join(mapping.values())
        execute(f"""
            CREATE FUNCTION write_{table}() RETURNS trigger LANGUAGE plpgsql AS $fold$
            DECLARE target_id integer;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    UPDATE {parent} SET {clear} WHERE id = OLD.{key} AND {match_old};
                    IF NOT FOUND THEN RETURN NULL; END IF;
                    RETURN OLD;
                END IF;
                IF NEW.{self.marker} IS NULL THEN
                    RAISE EXCEPTION 'Missing required {table}.{self.marker}' USING ERRCODE = '23502';
                END IF;
                IF TG_OP = 'UPDATE' THEN
                    IF NEW.{key} IS NOT DISTINCT FROM OLD.{key} THEN
                        UPDATE {parent} SET {changes} WHERE id = OLD.{key} AND {match_old}
                        RETURNING {returning} INTO NEW;
                        IF NOT FOUND THEN RETURN NULL; END IF;
                        RETURN NEW;
                    END IF;
                    UPDATE {parent} SET {clear} WHERE id = OLD.{key} AND {match_old};
                    IF NOT FOUND THEN RETURN NULL; END IF;
                END IF;
                target_id := NEW.{key};
                UPDATE {parent} SET {insert} WHERE id = NEW.{key} AND {marker} IS NULL
                RETURNING {returning} INTO NEW;
                IF NOT FOUND THEN
                    IF EXISTS (SELECT 1 FROM {parent} WHERE id = target_id) THEN
                        RAISE EXCEPTION 'Duplicate {table}' USING ERRCODE = '23505';
                    END IF;
                    RAISE EXCEPTION 'Missing {parent}' USING ERRCODE = '23503';
                END IF;
                RETURN NEW;
            END
            $fold$
        """)
        execute(f"CREATE TRIGGER write_{table} INSTEAD OF INSERT OR UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION write_{table}()")

    def unfold(self) -> None:
        table, parent, key = self.child, self.parent, self.parent_key
        execute(f"LOCK TABLE {parent} IN ACCESS EXCLUSIVE MODE")
        if self.sequence:
            retain_sequence(self.sequence, parent, self.fields["id"])
        execute(f"DROP VIEW {table}")
        execute(f"DROP FUNCTION write_{table}()")
        restore_table("0099", table)
        fields = ", ".join([key, *self.fields])
        projected = ", ".join(["id", *self.fields.values()])
        execute(f"INSERT INTO {table} ({fields}) SELECT {projected} FROM {parent} "
                f"WHERE {self.fields[self.marker]} IS NOT NULL")
        for new in self.fields.values():
            op.drop_column(parent, new)
