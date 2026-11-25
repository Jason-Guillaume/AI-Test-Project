-- Legacy tables now hold all project-specific values and ciphertext. Canonical
-- revision credentials retain the original format expected by pre-0106 callers.
-- The pre-0106 worker treated a direct legacy row without a canonical revision pointer as project-local.
UPDATE model_revision SET legacy_connection_id=NULL WHERE legacy_connection_id IN (
    SELECT connection_public_id FROM model_legacy_binding WHERE allow_project_execution);
UPDATE model_legacy_binding SET legacy_domain_id='0106:project-legacy-execution' WHERE allow_project_execution;
-- 0105 has no typed prices or effective timeout on a revision. Its existing
-- binding table can carry these four numbers while a newer current version is edited.
INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id,legacy_domain_id)
SELECT '0106_TEXT_TERMS',v.id,v.resource_id,v.id,
       json_build_array(v.text_cost_input,v.text_cost_output,v.text_timeout,v.text_profile_id)::text
FROM model_revision v JOIN model_resource r ON r.id=v.resource_id
WHERE r.category='TEXT_GENERATION' AND (v.text_profile_id IS NOT NULL OR v.text_timeout IS NOT NULL
        OR v.text_cost_input<>0 OR v.text_cost_output<>0);
-- Old public names need not match the canonical name when a project already used that name/version.
UPDATE model_legacy_binding b SET legacy_domain_id='0106:profile:'||p.id
    FROM model_parameter_profile p WHERE b.profile_id=p.id AND b.parameter_public_id IS NOT NULL
        AND (b.alias_name<>p.name OR p.scope_connection_id IS NOT NULL) AND b.legacy_domain_id IS NULL;
DELETE FROM model_credential WHERE alias_binding_id IS NOT NULL;
ALTER TABLE model_credential DROP COLUMN alias_binding_id, DROP COLUMN alias_endpoint_ciphertext,
    DROP COLUMN text_ciphertext,DROP CONSTRAINT ck_model_revision_credential_data,
    ALTER COLUMN revision_id SET NOT NULL,ALTER COLUMN ciphertext SET NOT NULL;
-- Old readers list every profile attached to a platform resource. Move local-only
-- profiles into disabled project-private holders while 0105 is running. Keeping the
-- same profile primary key preserves every incoming reference. Holders have no endpoint or key.
ALTER TABLE model_legacy_binding DROP CONSTRAINT fk_model_binding_profile_owner;
DO $$
DECLARE p record; holder integer; holder_revision integer; public_parameter integer;
BEGIN
    FOR p IN SELECT f.*,b.project_id,r.category FROM model_parameter_profile f
        JOIN model_legacy_binding b ON b.connection_public_id=f.scope_connection_id
        JOIN model_resource r ON r.id=f.resource_id ORDER BY f.id LOOP
        SELECT min(parameter_public_id) INTO public_parameter FROM model_legacy_binding WHERE profile_id=p.id;
        INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id,legacy_domain_id,legacy_role)
        VALUES('0106_SCOPED_PROFILE',p.id,p.resource_id,p.revision_id,p.scope_connection_id::text,public_parameter::text);
        INSERT INTO model_resource(resource_key,category,visibility,project_id,display_name,status)
        VALUES('0106-private-profile-'||txid_current()||'-'||p.id,p.category,'PROJECT',p.project_id,p.name,'DISABLED')
        RETURNING id INTO holder;
        INSERT INTO model_revision(resource_id,version,provider,adapter_key,model_name,enabled)
        VALUES(holder,1,'project','unregistered:private-profile',p.name,false) RETURNING id INTO holder_revision;
        UPDATE model_resource SET current_revision_id=holder_revision WHERE id=holder;
        UPDATE model_parameter_profile SET resource_id=holder,revision_id=holder_revision WHERE id=p.id;
    END LOOP;
END $$;
DROP INDEX uq_model_profile_version;
DROP INDEX uq_model_scoped_profile_version;
ALTER TABLE model_parameter_profile DROP COLUMN scope_connection_id,
    ADD CONSTRAINT uq_model_profile_version UNIQUE(resource_id,revision_id,name,version);
ALTER TABLE model_legacy_binding DROP CONSTRAINT fk_model_parameter_connection_owner,
    DROP CONSTRAINT uq_model_connection_owner,
    DROP CONSTRAINT fk_model_binding_revision_owner, DROP COLUMN parent_connection_id,
    DROP COLUMN profile_id,DROP COLUMN project_id,DROP COLUMN alias_name,DROP COLUMN alias_version,
    DROP COLUMN alias_enabled,DROP COLUMN alias_config,DROP COLUMN alias_provider,DROP COLUMN alias_model_name,
    DROP COLUMN alias_endpoint_display,DROP COLUMN alias_header,DROP COLUMN use_revision_credential,DROP COLUMN allow_project_execution,
    DROP COLUMN alias_created_by,DROP COLUMN alias_created_at,DROP COLUMN alias_updated_at,
    DROP COLUMN model_public_id,DROP COLUMN connection_public_id,DROP COLUMN parameter_public_id;
ALTER TABLE model_parameter_profile DROP CONSTRAINT uq_model_profile_owner;
ALTER TABLE model_revision DROP CONSTRAINT uq_model_revision_owner,DROP COLUMN text_profile_id,DROP COLUMN text_api_base,
    DROP COLUMN text_provider,DROP COLUMN text_timeout,DROP COLUMN text_key_is_null,DROP COLUMN text_cost_input,DROP COLUMN text_cost_output;
ALTER TABLE model_resource DROP COLUMN text_sort_order,
    DROP COLUMN text_fallback_ids,DROP COLUMN text_created_by,DROP COLUMN text_created_at,DROP COLUMN text_updated_at,
    DROP COLUMN text_deleted_at,DROP COLUMN text_deleted_by,DROP COLUMN text_deletion_reason,DROP COLUMN text_deletion_batch_id;

UPDATE model_legacy_binding SET legacy_kind=substr(legacy_kind,14) WHERE left(legacy_kind,13)='0106_RETIRED_';
