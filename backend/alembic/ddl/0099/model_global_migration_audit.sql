CREATE TABLE "model_global_migration_audit" (
    resource_id integer DEFAULT nextval('model_global_migration_audit_resource_id_seq'::regclass) NOT NULL,
    project_id integer,
    previous_status character varying(20),
    replacement_resource_id integer,
    decision character varying(40) NOT NULL,
    CONSTRAINT model_global_migration_audit_pkey PRIMARY KEY (resource_id)
);
ALTER SEQUENCE model_global_migration_audit_resource_id_seq OWNED BY "model_global_migration_audit".resource_id;
