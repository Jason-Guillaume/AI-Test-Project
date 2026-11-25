"""Fold ASR work queues and human review history into typed physical tables."""

from alembic import op
import sqlalchemy as sa


revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


def _fields(names):
    return tuple((name, name) for name in names.split())


_ID = ("id", "public_id")
_LEASE = _fields("available_at lease_owner lease_generation lease_expires_at attempts")
# Field pairs are in the exact legacy column order, including the two meanings of speaker_id.
_SOURCES = (
    ("asr_work_item", "asr_queue_item", "MODEL_RUN", (_ID, ("run_id", "run_id"), *_LEASE)),
    ("asr_processing_work_item", "asr_queue_item", "PROCESSING_RUN",
     (_ID, ("processing_run_id", "processing_run_id"), *_LEASE)),
    ("asr_review_audit", "asr_review_event", "TEXT", (_ID, *_fields(
        "block_id reviewer_id version review_status confirmed_text include_reference_sample created_at"
    ))),
    ("asr_speaker_review_audit", "asr_review_event", "SPEAKER_ASSIGNMENT",
     (_ID, *_fields("assignment_id version reviewer_id"), ("speaker_id", "selected_speaker_id"),
      *_fields("review_status created_at"))),
    ("asr_speaker_name_audit", "asr_review_event", "SPEAKER_NAME",
     (_ID, ("speaker_id", "subject_speaker_id"), ("reviewer_id", "reviewer_id"),
      ("revision", "version"), *_fields("previous_name next_name created_at"))),
)
_LEASE_DDL = """
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_owner varchar(160),
    lease_generation integer NOT NULL DEFAULT 0,
    lease_expires_at timestamptz,
    attempts integer NOT NULL DEFAULT 0
"""
_REVIEWER = 'reviewer_id integer REFERENCES "user"(id) ON DELETE SET NULL'
_CREATED = "created_at timestamptz NOT NULL DEFAULT now()"


def _create_storage():
    op.execute(f"""
        CREATE TABLE asr_queue_item (
            id serial PRIMARY KEY, kind varchar(24) NOT NULL, public_id integer NOT NULL,
            run_id integer REFERENCES asr_model_run(id) ON DELETE CASCADE,
            processing_run_id integer REFERENCES asr_processing_run(id) ON DELETE CASCADE,
            {_LEASE_DDL},
            CONSTRAINT uq_asr_queue_public UNIQUE (kind, public_id),
            CONSTRAINT uq_asr_queue_model_run UNIQUE (run_id),
            CONSTRAINT uq_asr_queue_processing_run UNIQUE (processing_run_id),
            CONSTRAINT ck_asr_queue_parent CHECK (
                (kind = 'MODEL_RUN' AND run_id IS NOT NULL AND processing_run_id IS NULL) OR
                (kind = 'PROCESSING_RUN' AND processing_run_id IS NOT NULL AND run_id IS NULL)
            )
        )
    """)
    op.execute("CREATE INDEX ix_asr_queue_available ON asr_queue_item(kind, available_at, public_id)")
    op.execute(f"""
        CREATE TABLE asr_review_event (
            id serial PRIMARY KEY, kind varchar(24) NOT NULL, public_id integer NOT NULL,
            block_id integer REFERENCES asr_diff_block(id) ON DELETE CASCADE,
            assignment_id integer REFERENCES asr_speaker_assignment(id) ON DELETE CASCADE,
            subject_speaker_id integer REFERENCES asr_speaker(id) ON DELETE CASCADE,
            selected_speaker_id integer REFERENCES asr_speaker(id) ON DELETE SET NULL,
            {_REVIEWER}, version integer NOT NULL, review_status varchar(20), confirmed_text text,
            include_reference_sample boolean NOT NULL DEFAULT false, previous_name varchar(120),
            next_name varchar(120), {_CREATED},
            CONSTRAINT uq_asr_review_public UNIQUE (kind, public_id),
            CONSTRAINT uq_asr_review_assignment_version UNIQUE (assignment_id, version),
            CONSTRAINT ck_asr_review_subject CHECK (
                (kind = 'TEXT' AND block_id IS NOT NULL AND assignment_id IS NULL
                    AND subject_speaker_id IS NULL AND selected_speaker_id IS NULL
                    AND review_status IS NOT NULL AND previous_name IS NULL AND next_name IS NULL) OR
                (kind = 'SPEAKER_ASSIGNMENT' AND assignment_id IS NOT NULL AND block_id IS NULL
                    AND subject_speaker_id IS NULL AND review_status IS NOT NULL AND confirmed_text IS NULL
                    AND NOT include_reference_sample AND previous_name IS NULL AND next_name IS NULL) OR
                (kind = 'SPEAKER_NAME' AND subject_speaker_id IS NOT NULL AND block_id IS NULL
                    AND assignment_id IS NULL AND selected_speaker_id IS NULL AND review_status IS NULL
                    AND confirmed_text IS NULL AND NOT include_reference_sample
                    AND previous_name IS NOT NULL AND next_name IS NOT NULL)
            )
        )
    """)
    op.execute("CREATE INDEX ix_asr_review_block_version ON asr_review_event(block_id, version, public_id)")
    op.execute("CREATE INDEX ix_asr_review_subject_speaker ON asr_review_event(subject_speaker_id)")
    for table, subject_kinds in (
        ("asr_queue_item", (("run_id", "MODEL_RUN"), ("processing_run_id", "PROCESSING_RUN"))),
        ("asr_review_event", (("block_id", "TEXT"), ("assignment_id", "SPEAKER_ASSIGNMENT"),
                              ("subject_speaker_id", "SPEAKER_NAME"))),
    ):
        # A legacy view omits the discriminator. Its parent FK identifies the type.
        kind_cases = " ".join(f"WHEN NEW.{subject} IS NOT NULL THEN '{kind}'" for subject, kind in subject_kinds)
        sequence_cases = " ".join(
            f"WHEN '{kind}' THEN '{legacy}_id_seq'"
            for legacy, target, kind, _ in _SOURCES if target == table
        )
        op.execute(f"""
            CREATE FUNCTION {table}_identity() RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE sequence_name text;
            BEGIN
                NEW.kind := COALESCE(NEW.kind, CASE {kind_cases} END);
                IF NEW.public_id IS NULL THEN
                    sequence_name := CASE NEW.kind {sequence_cases} END;
                    NEW.public_id := nextval(format('%I.%I', TG_TABLE_SCHEMA, sequence_name)::regclass);
                END IF;
                RETURN NEW;
            END $$
        """)
        op.execute(f"CREATE TRIGGER assign_public_id BEFORE INSERT ON {table} FOR EACH ROW "
                   f"EXECUTE FUNCTION {table}_identity()")


def _create_legacy():
    def create(table, fields):
        op.execute(f"CREATE TABLE {table} (id integer PRIMARY KEY DEFAULT nextval('{table}_id_seq'), {fields})")
        op.execute(f"ALTER SEQUENCE {table}_id_seq OWNED BY {table}.id")

    for table, parent, column, unique, index in (
        ("asr_work_item", "asr_model_run", "run_id", "uq_asr_work_run", "ix_asr_work_available"),
        ("asr_processing_work_item", "asr_processing_run", "processing_run_id",
         "uq_asr_processing_work_run", "ix_asr_processing_work_available"),
    ):
        create(table, f"{column} integer NOT NULL REFERENCES {parent}(id) ON DELETE CASCADE, "
                      f"{_LEASE_DDL}, CONSTRAINT {unique} UNIQUE ({column})")
        op.execute(f"CREATE INDEX {index} ON {table}(available_at)")
    create("asr_review_audit", f"""
        block_id integer NOT NULL REFERENCES asr_diff_block(id) ON DELETE CASCADE, {_REVIEWER},
        version integer NOT NULL, review_status varchar(20) NOT NULL, confirmed_text text,
        include_reference_sample boolean NOT NULL DEFAULT false, {_CREATED}
    """)
    create("asr_speaker_review_audit", f"""
        assignment_id integer NOT NULL REFERENCES asr_speaker_assignment(id) ON DELETE CASCADE,
        version integer NOT NULL, {_REVIEWER}, speaker_id integer REFERENCES asr_speaker(id) ON DELETE SET NULL,
        review_status varchar(20) NOT NULL, {_CREATED},
        CONSTRAINT uq_asr_speaker_review_version UNIQUE (assignment_id, version)
    """)
    create("asr_speaker_name_audit", f"""
        speaker_id integer NOT NULL REFERENCES asr_speaker(id) ON DELETE CASCADE, {_REVIEWER},
        revision integer NOT NULL, previous_name varchar(120) NOT NULL, next_name varchar(120) NOT NULL, {_CREATED}
    """)
    for table, column in (("asr_review_audit", "block_id"), ("asr_speaker_review_audit", "assignment_id"),
                          ("asr_speaker_name_audit", "speaker_id")):
        op.execute(f"CREATE INDEX ix_{table}_{column} ON {table}({column})")


def _comments(name, new_relation_type):
    """Carry existing PostgreSQL descriptions between the physical table and its view."""
    return op.get_bind().execute(sa.text("""
        SELECT CASE WHEN d.objsubid = 0
                THEN format('COMMENT ON %s %I IS %L', CAST(:relation_type AS text), CAST(:name AS text), d.description)
                ELSE format('COMMENT ON COLUMN %I.%I IS %L', CAST(:name AS text), a.attname, d.description) END
        FROM pg_description d LEFT JOIN pg_attribute a ON a.attrelid = d.objoid AND a.attnum = d.objsubid
        WHERE d.classoid = 'pg_class'::regclass AND d.objoid = to_regclass(:name)
    """), {"name": name, "relation_type": new_relation_type}).scalars().all()


def _align_sequence(name):
    # Explicit historical IDs may exceed a SERIAL high water. Never rewind a sequence
    # for consumed/deleted/rolled-back IDs, including when a source table is empty.
    op.execute(f"""
        SELECT setval('{name}_id_seq', max_id, true)
        FROM (SELECT max(id) AS max_id FROM {name}) ids, {name}_id_seq
        WHERE max_id > last_value OR (max_id = last_value AND NOT is_called)
    """)


def _compare(name, projection, columns):
    source = f"SELECT {columns} FROM {name}"
    op.execute(f"""
        DO $$ BEGIN
            IF EXISTS (({source} EXCEPT ALL {projection}) UNION ALL ({projection} EXCEPT ALL {source})) THEN
                RAISE EXCEPTION 'ASR migration changed fields for {name}';
            END IF;
        END $$
    """)


def upgrade():
    op.execute("LOCK TABLE " + ", ".join(item[0] for item in _SOURCES) + " IN ACCESS EXCLUSIVE MODE")
    _create_storage()
    for name, target, kind, fields in _SOURCES:
        columns = ", ".join(old for old, _ in fields)
        new_columns = ", ".join(new for _, new in fields)
        select = ", ".join(f"{new} AS {old}" for old, new in fields)
        projection = f"SELECT {select} FROM {target} WHERE kind = '{kind}'"
        op.execute(f"INSERT INTO {target} (kind, {new_columns}) SELECT '{kind}', {columns} FROM {name} ORDER BY id")
        _compare(name, projection, columns)
        _align_sequence(name)
        comments = _comments(name, "VIEW")
        op.execute(f"ALTER SEQUENCE {name}_id_seq OWNED BY {target}.public_id")
        op.drop_table(name)
        op.execute(f"CREATE VIEW {name} AS {projection} WITH LOCAL CHECK OPTION")
        for statement in comments:
            op.get_bind().exec_driver_sql(statement, execution_options={"no_parameters": True})


def downgrade():
    op.execute("LOCK TABLE asr_queue_item, asr_review_event IN ACCESS EXCLUSIVE MODE")
    comments = []
    for name, *_ in _SOURCES:
        comments.extend(_comments(name, "TABLE"))
        op.execute(f"DROP VIEW {name}")
    _create_legacy()
    for name, target, kind, fields in _SOURCES:
        columns = ", ".join(old for old, _ in fields)
        new_columns = ", ".join(new for _, new in fields)
        projection = f"SELECT {new_columns} FROM {target} WHERE kind = '{kind}'"
        op.execute(f"INSERT INTO {name} ({columns}) {projection}")
        _compare(name, projection, columns)
        _align_sequence(name)
    for statement in comments:
        op.get_bind().exec_driver_sql(statement, execution_options={"no_parameters": True})
    for table in ("asr_review_event", "asr_queue_item"):
        op.drop_table(table)
        op.execute(f"DROP FUNCTION {table}_identity()")
