-- Only historical differences and explicit edits to a project alias need their own
-- credential. A missing credential on one project must stay missing.
CREATE FUNCTION model_bind_connection(bid integer, src asr_connection) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v model_revision%ROWTYPE; secret text; endpoint_override text;
BEGIN
    SELECT rev.* INTO STRICT v FROM model_revision rev JOIN model_legacy_binding b ON b.revision_id=rev.id
        WHERE b.id=bid;
    SELECT ciphertext INTO secret FROM model_credential WHERE revision_id=v.id;
    endpoint_override := nullif(src.endpoint_ciphertext, v.endpoint_ciphertext);
    UPDATE model_legacy_binding SET project_id=src.project_id, alias_name=src.name, alias_version=src.version,
        legacy_role=src.role, legacy_task_type=src.task_type, alias_created_by=src.created_by,
        alias_created_at=src.created_at, alias_updated_at=src.updated_at, alias_header=src.secret_header,
        alias_enabled=CASE WHEN src.enabled IS DISTINCT FROM v.enabled THEN src.enabled END,
        alias_config=CASE WHEN src.config_json::jsonb IS DISTINCT FROM v.config_json::jsonb THEN src.config_json END,
        alias_provider=nullif(src.provider_id,v.provider),alias_model_name=nullif(src.model_id,v.model_name),
        alias_endpoint_display=nullif(src.endpoint_display,v.endpoint_display),
        use_revision_credential=src.secret_ciphertext IS NOT DISTINCT FROM secret
        WHERE id=bid;
    IF endpoint_override IS NOT NULL OR (src.secret_ciphertext IS NOT NULL AND src.secret_ciphertext IS DISTINCT FROM secret) THEN
        INSERT INTO model_credential(alias_binding_id,ciphertext,header_name,alias_endpoint_ciphertext)
        VALUES(bid,CASE WHEN secret IS DISTINCT FROM src.secret_ciphertext THEN src.secret_ciphertext END,
               src.secret_header,endpoint_override)
        ON CONFLICT(alias_binding_id) DO UPDATE SET ciphertext=excluded.ciphertext,
            header_name=excluded.header_name,alias_endpoint_ciphertext=excluded.alias_endpoint_ciphertext;
    ELSE
        DELETE FROM model_credential WHERE alias_binding_id=bid;
    END IF;
END
$$;

CREATE FUNCTION model_compat_connection_write() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    rid integer; vid integer; bid integer; next_version integer; cat varchar(30); caps jsonb; direct boolean;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT id INTO STRICT bid FROM model_legacy_binding WHERE connection_public_id=OLD.id FOR UPDATE;
        IF TG_OP='DELETE' THEN DELETE FROM model_legacy_binding WHERE id=bid; RETURN OLD; END IF;
        IF NEW.id IS DISTINCT FROM OLD.id THEN RAISE EXCEPTION 'connection public ID is immutable'; END IF;
    END IF;
    IF NEW.project_id IS NULL OR NEW.name IS NULL OR NEW.task_type IS NULL OR NEW.provider_id IS NULL
        OR NEW.model_id IS NULL OR NEW.version IS NULL OR NEW.endpoint_ciphertext IS NULL
        OR NEW.endpoint_display IS NULL OR NEW.config_json IS NULL OR NEW.enabled IS NULL
        OR NEW.created_at IS NULL OR NEW.updated_at IS NULL THEN
        RAISE EXCEPTION 'required connection field missing' USING ERRCODE='23502';
    END IF;
    IF TG_OP='INSERT' THEN
        direct := current_setting('model_center.managed_connection',true) IS DISTINCT FROM NEW.id::text;
        cat := CASE WHEN NEW.task_type='DIARIZATION' THEN 'DIARIZATION' ELSE 'ASR' END;
        PERFORM pg_advisory_xact_lock(NEW.project_id,hashtext(NEW.name));
        SELECT id INTO rid FROM model_resource WHERE project_id=NEW.project_id AND category=cat
            AND display_name=NEW.name AND visibility='PROJECT' AND EXISTS (
                SELECT FROM model_legacy_binding b WHERE b.resource_id=model_resource.id AND b.connection_public_id IS NOT NULL
                    AND b.allow_project_execution=direct
            ) AND NOT EXISTS (
                SELECT FROM model_global_migration_audit a WHERE a.resource_id=model_resource.id
                    AND a.decision='DISABLED_PENDING_ADMIN_REVIEW'
            ) ORDER BY id LIMIT 1 FOR UPDATE;
        IF rid IS NULL THEN
            INSERT INTO model_resource(resource_key,category,visibility,project_id,display_name,status,created_by)
            VALUES('legacy-connection-'||NEW.id,cat,'PROJECT',NEW.project_id,NEW.name,
                 CASE WHEN NEW.enabled THEN 'ACTIVE' ELSE 'DISABLED' END,NEW.created_by)
            RETURNING id INTO rid;
        END IF;
        SELECT greatest(NEW.version,coalesce(max(version),0)+1) INTO next_version FROM model_revision WHERE resource_id=rid;
        caps := CASE WHEN cat='DIARIZATION' THEN '["speaker_intervals"]'::jsonb ELSE '["transcription"]'::jsonb END;
        IF NEW.config_json->'response_mapping'->>'segments_pointer' IS NOT NULL THEN caps:=caps||'"timestamped_segments"'::jsonb; END IF;
        IF NEW.config_json->'response_mapping'->>'speaker_pointer' IS NOT NULL THEN caps:=caps||'"native_speaker_labels"'::jsonb; END IF;
        INSERT INTO model_revision(resource_id,version,provider,adapter_key,model_name,endpoint_ciphertext,endpoint_display,
                config_json,capabilities,parameter_schema,enabled,created_by,created_at)
        VALUES(rid,next_version,left(NEW.provider_id,60),CASE WHEN NEW.provider_id='generic-json' THEN 'generic-json-http'
               ELSE 'unregistered:'||NEW.provider_id END,NEW.model_id,NEW.endpoint_ciphertext,NEW.endpoint_display,
               NEW.config_json,caps,coalesce(NEW.config_json->'parameter_definitions','[]'::json),NEW.enabled,
               NEW.created_by,NEW.created_at) RETURNING id INTO vid;
        IF NEW.secret_ciphertext IS NOT NULL THEN
            INSERT INTO model_credential(revision_id,ciphertext,header_name) VALUES(vid,NEW.secret_ciphertext,NEW.secret_header);
        END IF;
        INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id,project_id,alias_name,
                alias_version,legacy_task_type,alias_created_at,alias_updated_at,allow_project_execution)
        VALUES('ASR_CONNECTION',NEW.id,rid,vid,NEW.project_id,NEW.name,NEW.version,NEW.task_type,NEW.created_at,NEW.updated_at,direct) RETURNING id INTO bid;
        UPDATE model_revision SET legacy_connection_id=NEW.id WHERE id=vid;
        UPDATE model_resource SET current_revision_id=vid,status=CASE WHEN NEW.enabled THEN 'ACTIVE' ELSE 'DISABLED' END
            WHERE id=rid;
    END IF;
    PERFORM model_bind_connection(bid,NEW);
    RETURN NEW;
END
$$;
CREATE TRIGGER asr_connection_write INSTEAD OF INSERT OR UPDATE OR DELETE ON asr_connection
    FOR EACH ROW EXECUTE FUNCTION model_compat_connection_write();

CREATE FUNCTION model_compat_parameter_write() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    conn model_legacy_binding%ROWTYPE; pid integer; bid integer; previous model_parameter_profile%ROWTYPE;
    scoped integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT id,profile_id INTO STRICT bid,pid FROM model_legacy_binding WHERE parameter_public_id=OLD.id FOR UPDATE;
        IF TG_OP='DELETE' THEN DELETE FROM model_legacy_binding WHERE id=bid; RETURN OLD; END IF;
        IF NEW.id IS DISTINCT FROM OLD.id THEN RAISE EXCEPTION 'parameter set public ID is immutable'; END IF;
        SELECT * INTO previous FROM model_parameter_profile WHERE id=pid;
    END IF;
    IF NEW.project_id IS NULL OR NEW.name IS NULL OR NEW.version IS NULL OR NEW.parameters IS NULL
       OR NEW.definitions IS NULL OR NEW.created_at IS NULL THEN
        RAISE EXCEPTION 'required parameter set field missing' USING ERRCODE='23502';
    END IF;
    SELECT * INTO conn FROM model_legacy_binding WHERE connection_public_id=NEW.connection_id FOR UPDATE;
    IF NOT FOUND OR conn.project_id <> NEW.project_id THEN
        RAISE EXCEPTION 'parameter set has no connection in its project' USING ERRCODE='23503';
    END IF;
    IF TG_OP='INSERT' OR (NEW.connection_id,NEW.name,NEW.version,NEW.parameters::jsonb,NEW.definitions::jsonb)
        IS DISTINCT FROM (OLD.connection_id,OLD.name,OLD.version,OLD.parameters::jsonb,OLD.definitions::jsonb) THEN
        scoped := CASE WHEN conn.legacy_kind='ASR_SHARED_CONNECTION' THEN NEW.connection_id END;
        IF TG_OP='UPDATE' AND previous.scope_connection_id IS NOT DISTINCT FROM scoped
           AND previous.legacy_parameter_set_id=NEW.id AND conn.revision_id=previous.revision_id THEN
            UPDATE model_parameter_profile SET name=NEW.name,version=NEW.version,parameter_values=NEW.parameters,
                definitions=NEW.definitions WHERE id=pid;
        ELSE
            INSERT INTO model_parameter_profile(resource_id,revision_id,name,version,parameter_values,definitions,
                                               created_by,created_at,scope_connection_id)
            VALUES(conn.resource_id,conn.revision_id,NEW.name,NEW.version,NEW.parameters,NEW.definitions,
                   NEW.created_by,NEW.created_at,scoped) RETURNING id INTO pid;
        END IF;
    END IF;
    IF TG_OP='INSERT' THEN
        INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id,profile_id,project_id,
                parent_connection_id,legacy_task_type,alias_name,alias_version,alias_created_by,alias_created_at)
        VALUES('ASR_PARAMETER_SET',NEW.id,conn.resource_id,conn.revision_id,pid,NEW.project_id,
               NEW.connection_id,conn.legacy_task_type,NEW.name,NEW.version,NEW.created_by,NEW.created_at)
        RETURNING id INTO bid;
    ELSE
        UPDATE model_legacy_binding SET resource_id=conn.resource_id,revision_id=conn.revision_id,profile_id=pid,
                project_id=NEW.project_id,parent_connection_id=NEW.connection_id,legacy_task_type=conn.legacy_task_type,
                alias_name=NEW.name,alias_version=NEW.version,alias_created_by=NEW.created_by,
                alias_created_at=NEW.created_at WHERE id=bid;
    END IF;
    IF previous.id IS DISTINCT FROM pid THEN
        UPDATE model_parameter_profile SET legacy_parameter_set_id=NULL WHERE legacy_parameter_set_id=NEW.id;
        UPDATE model_parameter_profile SET legacy_parameter_set_id=NEW.id WHERE id=pid;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER asr_parameter_set_write INSTEAD OF INSERT OR UPDATE OR DELETE ON asr_parameter_set
    FOR EACH ROW EXECUTE FUNCTION model_compat_parameter_write();
