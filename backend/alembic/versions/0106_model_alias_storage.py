"""Move text configurations and project ASR aliases into the model center."""

from pathlib import Path

import sqlalchemy as sa
from alembic import op

from alembic_support.frozen_schema import execute, restore_table, retain_sequence

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None

_PUBLIC_KEYS = {
    "model_configuration": "model_public_id",
    "asr_connection": "connection_public_id",
    "asr_parameter_set": "parameter_public_id",
}
_SQL = Path(__file__).resolve().parents[1] / "sql" / "0106"


def _run(name):
    execute((_SQL / f"{name}.sql").read_text(encoding="utf-8"))


def _foreign_keys(upgrading):
    """Find real FK definitions, including historical names, actions and deferrability."""
    db = op.get_bind()
    return db.execute(sa.text("""
        SELECT src.relname AS source, c.conname AS name, dst.relname AS target, a.attname AS target_key,
               pg_get_constraintdef(c.oid) AS definition
        FROM pg_constraint c JOIN pg_class src ON src.oid=c.conrelid JOIN pg_class dst ON dst.oid=c.confrelid
        JOIN pg_attribute a ON a.attrelid=dst.oid AND a.attnum=c.confkey[1]
        WHERE c.contype='f' AND src.relnamespace='public'::regnamespace
          AND dst.relnamespace='public'::regnamespace AND cardinality(c.confkey)=1
          AND ((:up AND dst.relname IN ('model_configuration','asr_connection','asr_parameter_set')
                       AND src.relname<>'asr_parameter_set')
            OR (NOT :up AND dst.relname='model_legacy_binding'
                AND a.attname IN ('model_public_id','connection_public_id','parameter_public_id')
                AND src.relname<>'model_legacy_binding' AND c.conname<>'model_parameter_profile_scope_connection_id_fkey'))
        ORDER BY src.relname,c.conname
    """), {"up": upgrading}).mappings().all()


def _drop_keys(keys):
    quote = op.get_bind().dialect.identifier_preparer.quote
    for fk in keys:
        execute(f'ALTER TABLE {quote(fk["source"])} DROP CONSTRAINT {quote(fk["name"])}')


def _restore_keys(keys, upgrading):
    quote = op.get_bind().dialect.identifier_preparer.quote
    for fk in keys:
        target = fk["target"]
        column = fk["target_key"]
        if upgrading:
            replacement = f'model_legacy_binding({_PUBLIC_KEYS[target]})'
        else:
            original = next(name for name, key in _PUBLIC_KEYS.items() if key == column)
            replacement = f'{original}(id)'
        definition = fk["definition"].replace(f"REFERENCES {target}({column})", f"REFERENCES {replacement}")
        if definition == fk["definition"]:
            raise RuntimeError(f'Cannot redirect {fk["source"]}.{fk["name"]}')
        execute(f'ALTER TABLE {quote(fk["source"])} ADD CONSTRAINT {quote(fk["name"])} {definition}')


def _verify_rows(source, target):
    """Compare all columns, including original timestamps and exact encrypted bytes, without logging data."""
    mismatch = op.get_bind().exec_driver_sql(f"""
        SELECT count(*) FROM {source} s FULL JOIN {target} t USING(id)
        WHERE to_jsonb(s) IS DISTINCT FROM to_jsonb(t)
    """).scalar_one()
    if mismatch:
        raise RuntimeError(f"{source} / {target}: {mismatch} mismatched model identities; migration rolled back")


def upgrade():
    execute("LOCK TABLE model_configuration, asr_connection, asr_parameter_set, model_resource, model_revision, "
            "model_parameter_profile, model_credential, model_legacy_binding, model_default_binding IN ACCESS EXCLUSIVE MODE")
    keys = _foreign_keys(True)
    _drop_keys(keys)
    for table in _PUBLIC_KEYS:
        retain_sequence(f"{table}_id_seq", table, "id")
        execute(f"ALTER TABLE {table} RENAME TO b2_source_{table}")
    _run("schema")
    _run("views")
    db = op.get_bind()
    for table in _PUBLIC_KEYS:
        defaults = db.execute(sa.text("""
            SELECT a.attname, pg_get_expr(d.adbin,d.adrelid) FROM pg_attrdef d
            JOIN pg_attribute a ON a.attrelid=d.adrelid AND a.attnum=d.adnum
            WHERE d.adrelid=to_regclass(:name)
        """), {"name": f"b2_source_{table}"})
        for col, expression in defaults:
            execute(f"ALTER VIEW {table} ALTER COLUMN {col} SET DEFAULT {expression}")
    _run("text_write")
    _run("asr_write")
    _run("backfill")
    for table in _PUBLIC_KEYS:
        _verify_rows(f"b2_source_{table}", table)
    # Ensure the pinned revision and exact parameter profile belong to this alias's resource.
    execute("""
        ALTER TABLE model_revision ADD CONSTRAINT uq_model_revision_owner UNIQUE(resource_id,id);
        ALTER TABLE model_parameter_profile ADD CONSTRAINT uq_model_profile_owner UNIQUE(resource_id,revision_id,id);
        ALTER TABLE model_legacy_binding ADD CONSTRAINT uq_model_connection_owner
           UNIQUE(connection_public_id,project_id,resource_id,revision_id);
        ALTER TABLE model_legacy_binding ADD CONSTRAINT fk_model_parameter_connection_owner
           FOREIGN KEY(parent_connection_id,project_id,resource_id,revision_id)
           REFERENCES model_legacy_binding(connection_public_id,project_id,resource_id,revision_id) ON DELETE CASCADE,
           ADD CONSTRAINT fk_model_binding_revision_owner
           FOREIGN KEY(resource_id,revision_id) REFERENCES model_revision(resource_id,id) ON DELETE CASCADE,
           ADD CONSTRAINT fk_model_binding_profile_owner FOREIGN KEY(resource_id,revision_id,profile_id)
           REFERENCES model_parameter_profile(resource_id,revision_id,id) ON DELETE CASCADE,
           ADD CONSTRAINT ck_model_connection_alias CHECK(connection_public_id IS NULL OR
                (project_id IS NOT NULL AND alias_name IS NOT NULL AND alias_version IS NOT NULL
                 AND legacy_task_type IS NOT NULL AND alias_created_at IS NOT NULL AND alias_updated_at IS NOT NULL)),
           ADD CONSTRAINT ck_model_parameter_alias CHECK(parameter_public_id IS NULL OR
                (project_id IS NOT NULL AND parent_connection_id IS NOT NULL AND profile_id IS NOT NULL
                 AND alias_name IS NOT NULL AND alias_version IS NOT NULL AND alias_created_at IS NOT NULL));
    """)
    _restore_keys(keys, True)
    execute("DROP TABLE b2_source_asr_parameter_set, b2_source_asr_connection, b2_source_model_configuration")


def downgrade():
    execute("LOCK TABLE model_legacy_binding, model_resource, model_revision, model_parameter_profile, "
            "model_credential, model_default_binding IN ACCESS EXCLUSIVE MODE")
    keys = _foreign_keys(False)
    _drop_keys(keys)
    for table in _PUBLIC_KEYS:
        execute(f"CREATE TEMP TABLE b2_restore_{table} ON COMMIT DROP AS SELECT * FROM {table}")
    execute("DROP FUNCTION model_bind_connection(integer,asr_connection)")
    for table in _PUBLIC_KEYS:
        execute(f"DROP VIEW {table}")
    for name in ("model_compat_text_write", "model_compat_connection_write", "model_compat_parameter_write"):
        execute(f"DROP FUNCTION {name}()")
    for table in _PUBLIC_KEYS:
        restore_table("0106", table)
        columns = ", ".join(col["name"] for col in sa.inspect(op.get_bind()).get_columns(table))
        execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM b2_restore_{table}")
        _verify_rows(f"b2_restore_{table}", table)
        retain_sequence(f"{table}_id_seq", table, "id")
        execute(f"ALTER SEQUENCE {table}_id_seq OWNED BY {table}.id")
    _restore_keys(keys, False)
    _run("downgrade")
