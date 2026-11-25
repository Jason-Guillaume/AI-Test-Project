"""Fold request bodies into interfaces and preserve both public ID namespaces for entries."""
import sqlalchemy as sa
from alembic import op

from alembic_support.fold_0100 import Extension
from alembic_support.frozen_schema import execute, restore_table, retain_sequence

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None

BODY = Extension("api_request_body", "api_interface", "interface_id", {
    "id": "request_body_id", "body_type": "request_body_type", "content_type": "request_body_content_type",
    "schema_json": "request_body_schema", "raw_text": "request_body_raw_text",
    "created_at": "request_body_created_at", "updated_at": "request_body_updated_at",
}, "id")
ENTRIES = {"api_parameter": "PARAMETER", "api_response": "RESPONSE"}


def upgrade() -> None:
    BODY.fold()
    execute("LOCK TABLE api_parameter, api_response IN ACCESS EXCLUSIVE MODE")
    execute("""
        CREATE TABLE api_contract_entry (
            id serial PRIMARY KEY, kind varchar(12) NOT NULL, public_id integer NOT NULL,
            interface_id integer NOT NULL REFERENCES api_interface(id) ON DELETE CASCADE,
            sort integer NOT NULL DEFAULT 0, created_at timestamp NOT NULL DEFAULT now(),
            description varchar(500), schema_json json,
            name varchar(100), location varchar(10), type varchar(30), required boolean,
            example text, default_value text, status_code integer, response_key varchar(16),
            example_json text, updated_at timestamp,
            CONSTRAINT uq_api_contract_public_id UNIQUE (kind, public_id),
            CONSTRAINT ck_api_contract_kind CHECK (
                (kind = 'PARAMETER' AND name IS NOT NULL AND location IS NOT NULL
                 AND type IS NOT NULL AND required IS NOT NULL AND status_code IS NULL
                 AND response_key IS NULL AND example_json IS NULL AND updated_at IS NULL)
                OR (kind = 'RESPONSE' AND response_key IS NOT NULL AND updated_at IS NOT NULL
                    AND name IS NULL AND location IS NULL AND type IS NULL AND required IS NULL
                    AND example IS NULL AND default_value IS NULL))
        );
        CREATE INDEX ix_api_contract_order ON api_contract_entry (interface_id, kind, sort, public_id);
        CREATE INDEX ix_api_contract_location ON api_contract_entry (interface_id, location)
            WHERE kind = 'PARAMETER';
        CREATE INDEX ix_api_contract_status ON api_contract_entry (interface_id, status_code)
            WHERE kind = 'RESPONSE';
    """)
    for table, kind in ENTRIES.items():
        columns = sa.inspect(op.get_bind()).get_columns(table)
        names = [col["name"] for col in columns]
        physical = ["public_id" if name == "id" else name for name in names]
        fields = ", ".join(physical)
        legacy = ", ".join(names)
        execute(f"INSERT INTO api_contract_entry (kind, {fields}) SELECT '{kind}', {legacy} FROM {table}")
        retain_sequence(f"{table}_id_seq", table, "id")
        op.drop_table(table)
        projection = ", ".join(f"{target} AS {old}" for old, target in zip(names, physical))
        execute(f"CREATE VIEW {table} AS SELECT {projection} FROM api_contract_entry "
                f"WHERE kind = '{kind}' WITH LOCAL CHECK OPTION")
        for col in columns:
            if col["default"] is not None:
                execute(f"ALTER VIEW {table} ALTER COLUMN {col['name']} SET DEFAULT {col['default']}")
        values = ", ".join(f"NEW.{old}" for old in names)
        execute(f"""
            CREATE FUNCTION insert_{table}() RETURNS trigger LANGUAGE plpgsql AS $entry$
            BEGIN
                INSERT INTO api_contract_entry (kind, {fields}) VALUES ('{kind}', {values})
                RETURNING {fields} INTO NEW;
                RETURN NEW;
            END
            $entry$;
            CREATE TRIGGER insert_{table} INSTEAD OF INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION insert_{table}();
        """)
    execute("""
        CREATE FUNCTION allocate_api_contract_public_id() RETURNS trigger LANGUAGE plpgsql AS $entry$
        BEGIN
            IF NEW.public_id IS NULL THEN
                IF NEW.kind = 'PARAMETER' THEN NEW.public_id := nextval('api_parameter_id_seq');
                ELSIF NEW.kind = 'RESPONSE' THEN NEW.public_id := nextval('api_response_id_seq');
                END IF;
            END IF;
            RETURN NEW;
        END
        $entry$;
        CREATE TRIGGER allocate_api_contract_public_id BEFORE INSERT ON api_contract_entry
        FOR EACH ROW EXECUTE FUNCTION allocate_api_contract_public_id();
    """)


def downgrade() -> None:
    execute("LOCK TABLE api_contract_entry IN ACCESS EXCLUSIVE MODE")
    for table, kind in ENTRIES.items():
        columns = [col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)]
        names = ", ".join(columns)
        physical = ", ".join("public_id" if col == "id" else col for col in columns)
        retain_sequence(f"{table}_id_seq", table, "id")
        execute(f"DROP VIEW {table}")
        execute(f"DROP FUNCTION insert_{table}()")
        restore_table("0099", table)
        execute(f"INSERT INTO {table} ({names}) SELECT {physical} FROM api_contract_entry WHERE kind = '{kind}'")
    op.drop_table("api_contract_entry")
    execute("DROP FUNCTION allocate_api_contract_public_id()")
    BODY.unfold()
