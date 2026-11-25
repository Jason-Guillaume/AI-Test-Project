CREATE TABLE "test_scope_migration_check" (
    id integer DEFAULT nextval('test_scope_migration_check_id_seq'::regclass) NOT NULL,
    metric character varying(80) NOT NULL,
    before_count integer NOT NULL,
    after_count integer NOT NULL,
    CONSTRAINT test_scope_migration_check_metric_key UNIQUE (metric),
    CONSTRAINT test_scope_migration_check_pkey PRIMARY KEY (id)
);
ALTER SEQUENCE test_scope_migration_check_id_seq OWNED BY "test_scope_migration_check".id;
