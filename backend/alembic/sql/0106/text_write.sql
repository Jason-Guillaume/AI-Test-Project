CREATE FUNCTION model_compat_text_write() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    rid integer; vid integer; pid integer; old_revision model_revision%ROWTYPE;
    b_id integer; new_version integer; fallback_ids json; public_key varchar(120); safe_endpoint varchar(500);
    config_schema json := '[{"path":"temperature","display_name":"采样温度","value_type":"number","minimum":0,"maximum":2},
                            {"path":"max_tokens","display_name":"最大输出 Token","value_type":"integer","minimum":1}]';
BEGIN
    IF TG_OP <> 'DELETE' AND (NEW.is_default OR (TG_OP='UPDATE' AND OLD.is_default)) THEN
        PERFORM pg_advisory_xact_lock(hashtext('model-center'),hashtext('text-inference-default'));
    END IF;
    IF TG_OP <> 'INSERT' THEN
        SELECT r.id,b.id INTO STRICT rid,b_id FROM model_resource r
        JOIN model_legacy_binding b ON b.resource_id=r.id WHERE b.model_public_id=OLD.id FOR UPDATE OF r,b;
        IF TG_OP='DELETE' THEN
            -- References to the public ID apply their original RESTRICT/SET NULL actions.
            DELETE FROM model_legacy_binding WHERE id=b_id;
            RETURN OLD;
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id THEN RAISE EXCEPTION 'text model public ID is immutable'; END IF;
        SELECT v.* INTO STRICT old_revision FROM model_revision v JOIN model_resource r
            ON r.current_revision_id=v.id WHERE r.id=rid;
        vid := old_revision.id;
        pid := old_revision.text_profile_id;
    END IF;
    IF NEW.domain_id IS NULL OR NEW.label IS NULL OR NEW.api_base IS NULL OR NEW.model_name IS NULL
       OR NEW.provider IS NULL OR NEW.temperature IS NULL OR NEW.max_tokens IS NULL OR NEW.timeout IS NULL
       OR NEW.is_enabled IS NULL OR NEW.is_default IS NULL OR NEW.created_at IS NULL OR NEW.updated_at IS NULL THEN
        RAISE EXCEPTION 'required text configuration field missing' USING ERRCODE='23502';
    END IF;
    IF TG_OP='INSERT' OR NEW.domain_id IS DISTINCT FROM OLD.domain_id OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN
        PERFORM pg_advisory_xact_lock(hashtext('model-compat-domain'),hashtext(NEW.domain_id));
        IF NEW.deleted_at IS NULL AND EXISTS (SELECT FROM model_configuration
          WHERE domain_id=NEW.domain_id AND id<>NEW.id AND deleted_at IS NULL) THEN
            RAISE EXCEPTION 'active model domain already exists' USING ERRCODE='23505';
        END IF;
    END IF;
    IF TG_OP='INSERT' THEN
        public_key := NEW.domain_id;
        IF EXISTS (SELECT FROM model_resource WHERE resource_key=public_key) THEN
            public_key := 'legacy-text-' || NEW.id || '-' || md5(NEW.domain_id);
        END IF;
        INSERT INTO model_resource(resource_key,category,visibility,display_name,status,created_by)
        VALUES(public_key,'TEXT_GENERATION','PLATFORM',NEW.label,
            CASE WHEN NEW.deleted_at IS NOT NULL THEN 'ARCHIVED' WHEN NEW.is_enabled THEN 'ACTIVE' ELSE 'DISABLED' END,
            NEW.created_by) RETURNING id INTO rid;
    END IF;
    IF TG_OP='INSERT' OR (NEW.provider,NEW.api_base,NEW.api_key_encrypted,NEW.model_name,NEW.temperature,
            NEW.max_tokens,NEW.timeout,NEW.is_enabled,NEW.cost_per_1k_input,NEW.cost_per_1k_output,NEW.label,
            NEW.sort_order,NEW.fallback_model_ids::jsonb) IS DISTINCT FROM (OLD.provider,OLD.api_base,OLD.api_key_encrypted,
            OLD.model_name,OLD.temperature,OLD.max_tokens,OLD.timeout,OLD.is_enabled,OLD.cost_per_1k_input,
            OLD.cost_per_1k_output,OLD.label,OLD.sort_order,OLD.fallback_model_ids::jsonb) THEN
        SELECT coalesce(max(version),0)+1 INTO new_version FROM model_revision WHERE resource_id=rid;
        safe_endpoint := regexp_replace(split_part(split_part(NEW.api_base,'?',1),'#',1),'^(https?://)[^/@]+@','\1','i');
        INSERT INTO model_revision(resource_id,version,provider,adapter_key,model_name,endpoint_display,text_api_base,config_json,
                capabilities,parameter_schema,enabled,created_by,text_key_is_null,text_cost_input,text_cost_output)
        VALUES (rid,new_version,NEW.provider,
            CASE WHEN NEW.provider='anthropic' THEN 'unregistered:anthropic-native' ELSE 'openai-compatible-chat' END,
            NEW.model_name,safe_endpoint,nullif(NEW.api_base,safe_endpoint),json_build_object('timeout',NEW.timeout,'legacy_model_id',NEW.id),
            '["text_generation"]',config_schema,NEW.is_enabled,NEW.created_by,NEW.api_key_encrypted IS NULL,
            NEW.cost_per_1k_input,NEW.cost_per_1k_output)
        RETURNING id INTO vid;
        IF coalesce(NEW.api_key_encrypted,'')<>'' THEN
            INSERT INTO model_credential(revision_id,ciphertext,cipher_format,header_name)
            VALUES (vid,NEW.api_key_encrypted,'model-configuration-fernet','Authorization');
        END IF;
        INSERT INTO model_parameter_profile(resource_id,revision_id,name,version,parameter_values,definitions,created_by)
        VALUES(rid,vid,'默认参数',1,json_build_object('temperature',NEW.temperature,'max_tokens',NEW.max_tokens),
               config_schema,NEW.created_by) RETURNING id INTO pid;
        UPDATE model_revision SET text_profile_id=pid WHERE id=vid;
        INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id,legacy_domain_id)
        VALUES('MODEL_REVISION',vid,rid,vid,NEW.domain_id);
    END IF;
    IF TG_OP='INSERT' THEN
        INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id,legacy_domain_id)
        VALUES('MODEL_CONFIGURATION',NEW.id,rid,vid,NEW.domain_id);
    ELSE
        UPDATE model_legacy_binding SET legacy_domain_id=NEW.domain_id,
            alias_name=NULL,alias_model_name=CASE WHEN vid=old_revision.id THEN alias_model_name END,
            alias_enabled=CASE WHEN vid=old_revision.id THEN alias_enabled END WHERE id=b_id;
    END IF;
    UPDATE model_resource SET current_revision_id=vid,legacy_model_id=NEW.id,display_name=NEW.label,
        status=CASE WHEN NEW.deleted_at IS NOT NULL THEN 'ARCHIVED'
            WHEN TG_OP='INSERT' OR OLD.is_enabled IS DISTINCT FROM NEW.is_enabled
            THEN CASE WHEN NEW.is_enabled THEN 'ACTIVE' ELSE 'DISABLED' END ELSE status END,
        text_sort_order=NEW.sort_order,
        text_fallback_ids=NEW.fallback_model_ids,text_created_by=NEW.created_by,text_created_at=NEW.created_at,
        text_updated_at=NEW.updated_at,text_deleted_at=NEW.deleted_at,text_deleted_by=NEW.deleted_by,
        text_deletion_reason=NEW.deletion_reason,text_deletion_batch_id=NEW.deletion_batch_id
        WHERE id=rid;
    IF NEW.is_default THEN
        SELECT coalesce(json_agg(b.resource_id ORDER BY f.n),'[]'::json) INTO fallback_ids
            FROM json_array_elements_text(NEW.fallback_model_ids) WITH ORDINALITY f(id,n)
            JOIN model_legacy_binding b ON b.model_public_id=f.id::integer;
        UPDATE model_default_binding SET resource_id=rid,revision_id=vid,profile_id=pid,
            fallback_resource_ids=fallback_ids,automatic_fallback=json_array_length(fallback_ids)>0
            WHERE category='TEXT_GENERATION' AND purpose='TEXT_INFERENCE' AND project_id IS NULL;
        IF NOT FOUND THEN
            INSERT INTO model_default_binding(category,purpose,resource_id,revision_id,profile_id,
                    fallback_resource_ids,automatic_fallback)
            VALUES('TEXT_GENERATION','TEXT_INFERENCE',rid,vid,pid,fallback_ids,json_array_length(fallback_ids)>0);
        END IF;
    ELSIF TG_OP='UPDATE' AND OLD.is_default THEN
        DELETE FROM model_default_binding WHERE category='TEXT_GENERATION' AND purpose='TEXT_INFERENCE'
            AND project_id IS NULL AND resource_id=rid;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER model_configuration_write INSTEAD OF INSERT OR UPDATE OR DELETE ON model_configuration
    FOR EACH ROW EXECUTE FUNCTION model_compat_text_write();
