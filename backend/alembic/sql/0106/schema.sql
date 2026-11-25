ALTER TABLE model_resource
    ADD COLUMN text_sort_order integer NOT NULL DEFAULT 0,
    ADD COLUMN text_fallback_ids json NOT NULL DEFAULT '[]',
    ADD COLUMN text_created_by integer REFERENCES "user"(id),
    ADD COLUMN text_created_at timestamp,
    ADD COLUMN text_updated_at timestamp,
    ADD COLUMN text_deleted_at timestamp,
    ADD COLUMN text_deleted_by integer REFERENCES "user"(id) ON DELETE SET NULL,
    ADD COLUMN text_deletion_reason varchar(500),
    ADD COLUMN text_deletion_batch_id varchar(36);
ALTER TABLE model_revision
    ADD COLUMN text_cost_input double precision NOT NULL DEFAULT 0,
    ADD COLUMN text_cost_output double precision NOT NULL DEFAULT 0,
    ADD COLUMN text_profile_id integer REFERENCES model_parameter_profile(id) ON DELETE SET NULL,
    ADD COLUMN text_api_base varchar(500),
    ADD COLUMN text_timeout integer,
    ADD COLUMN text_provider varchar(50),
    ADD COLUMN text_key_is_null boolean NOT NULL DEFAULT false;
ALTER TABLE model_legacy_binding
    ADD COLUMN model_public_id integer GENERATED ALWAYS AS
        (CASE WHEN legacy_kind='MODEL_CONFIGURATION' THEN legacy_id END) STORED UNIQUE,
    ADD COLUMN connection_public_id integer GENERATED ALWAYS AS
        (CASE WHEN legacy_kind IN ('ASR_CONNECTION','ASR_SHARED_CONNECTION') THEN legacy_id END) STORED UNIQUE,
    ADD COLUMN parameter_public_id integer GENERATED ALWAYS AS
        (CASE WHEN legacy_kind IN ('ASR_PARAMETER_SET','ASR_SHARED_PARAMETER_SET') THEN legacy_id END) STORED UNIQUE,
    ADD COLUMN profile_id integer REFERENCES model_parameter_profile(id) ON DELETE CASCADE,
    ADD COLUMN parent_connection_id integer,
    ADD COLUMN project_id integer REFERENCES project(id) ON DELETE CASCADE,
    ADD COLUMN alias_name varchar(120),
    ADD COLUMN alias_version integer,
    ADD COLUMN alias_enabled boolean,
    ADD COLUMN alias_config json,
    ADD COLUMN alias_provider varchar(80),
    ADD COLUMN alias_model_name varchar(200),
    ADD COLUMN alias_endpoint_display varchar(500),
    ADD COLUMN alias_header varchar(100),
    ADD COLUMN allow_project_execution boolean NOT NULL DEFAULT false,
    ADD COLUMN use_revision_credential boolean NOT NULL DEFAULT true,
    ADD COLUMN alias_created_by integer REFERENCES "user"(id) ON DELETE SET NULL,
    ADD COLUMN alias_created_at timestamptz,
    ADD COLUMN alias_updated_at timestamptz,
    ADD CONSTRAINT fk_model_binding_parent_connection FOREIGN KEY (parent_connection_id)
        REFERENCES model_legacy_binding(connection_public_id) ON DELETE CASCADE;
CREATE UNIQUE INDEX uq_model_connection_alias_version ON model_legacy_binding (project_id, alias_name, alias_version)
    WHERE connection_public_id IS NOT NULL;
CREATE UNIQUE INDEX uq_model_parameter_alias_version ON model_legacy_binding (parent_connection_id, alias_name, alias_version)
    WHERE parameter_public_id IS NOT NULL;
CREATE INDEX ix_model_alias_scope ON model_legacy_binding (project_id, revision_id, profile_id);
ALTER TABLE model_credential
    ALTER COLUMN revision_id DROP NOT NULL,
    ALTER COLUMN ciphertext DROP NOT NULL,
    ADD CONSTRAINT ck_model_revision_credential_data CHECK (revision_id IS NULL OR ciphertext IS NOT NULL),
    ADD COLUMN alias_binding_id integer UNIQUE REFERENCES model_legacy_binding(id) ON DELETE CASCADE,
    ADD COLUMN alias_endpoint_ciphertext text,
    ADD COLUMN text_ciphertext text,
    ADD CONSTRAINT ck_model_credential_owner CHECK ((revision_id IS NULL) <> (alias_binding_id IS NULL));
ALTER TABLE model_parameter_profile
    ADD COLUMN scope_connection_id integer REFERENCES model_legacy_binding(connection_public_id) ON DELETE CASCADE,
    DROP CONSTRAINT uq_model_profile_version;
CREATE UNIQUE INDEX uq_model_profile_version ON model_parameter_profile(resource_id,revision_id,name,version)
    WHERE scope_connection_id IS NULL;
CREATE UNIQUE INDEX uq_model_scoped_profile_version ON model_parameter_profile(scope_connection_id,name,version)
    WHERE scope_connection_id IS NOT NULL;
