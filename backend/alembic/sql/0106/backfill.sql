DO $$
DECLARE
    src record; rid integer; vid integer; pid integer; bid integer;
    rev model_revision%ROWTYPE; cred model_credential%ROWTYPE; conn model_legacy_binding%ROWTYPE;
    marker record; holder integer; holder_revision integer;
    src_conn asr_connection%ROWTYPE; scoped integer; pinned_profile integer; cfg model_configuration%ROWTYPE;
BEGIN
    -- Restore historical terms first. The old public row below then supplies the
    -- latest values for any revision that was edited while 0105 was running.
    UPDATE model_revision v SET text_cost_input=(terms.val->>0)::double precision,
        text_cost_output=(terms.val->>1)::double precision,text_timeout=(terms.val->>2)::integer,
        text_profile_id=(SELECT p.id FROM model_parameter_profile p WHERE p.id=(terms.val->>3)::integer
                         AND p.revision_id=v.id AND p.resource_id=v.resource_id)
    FROM (SELECT revision_id,legacy_domain_id::json AS val FROM model_legacy_binding
          WHERE legacy_kind='0106_TEXT_TERMS') terms WHERE terms.revision_id=v.id;
    DELETE FROM model_legacy_binding WHERE legacy_kind='0106_TEXT_TERMS';
    -- A physical deletion on an old release did not remove model_legacy_binding.
    -- Preserve each historical association without reviving a nonexistent public row.
    UPDATE model_legacy_binding b SET legacy_kind='0106_RETIRED_'||legacy_kind
        WHERE (b.model_public_id IS NOT NULL AND NOT EXISTS (SELECT FROM b2_source_model_configuration s WHERE s.id=b.legacy_id))
           OR (b.connection_public_id IS NOT NULL AND NOT EXISTS (SELECT FROM b2_source_asr_connection s WHERE s.id=b.legacy_id))
           OR (b.parameter_public_id IS NOT NULL AND NOT EXISTS (SELECT FROM b2_source_asr_parameter_set s WHERE s.id=b.legacy_id));

    FOR src IN SELECT * FROM b2_source_model_configuration ORDER BY id LOOP
        SELECT b.id,b.resource_id INTO bid,rid FROM model_legacy_binding b WHERE b.model_public_id=src.id;
        IF rid IS NULL THEN
            SELECT id INTO rid FROM model_resource WHERE legacy_model_id=src.id;
        END IF;
        IF rid IS NULL THEN
            cfg := json_populate_record(NULL::model_configuration,to_json(src));
            -- Defaults are restored after every fallback target has a public binding.
            cfg.is_default := false;
            INSERT INTO model_configuration SELECT cfg.*;
            CONTINUE;
        END IF;
        SELECT v.* INTO STRICT rev FROM model_revision v JOIN model_resource r ON r.current_revision_id=v.id
            WHERE r.id=rid AND v.resource_id=rid;
        vid := rev.id;
        IF bid IS NULL THEN
            INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id,legacy_domain_id)
                VALUES('MODEL_CONFIGURATION',src.id,rid,vid,src.domain_id) RETURNING id INTO bid;
        END IF;
        UPDATE model_legacy_binding SET legacy_domain_id=src.domain_id,
            alias_enabled=CASE WHEN rev.enabled<>src.is_enabled THEN src.is_enabled END,
            alias_model_name=nullif(src.model_name,rev.model_name),
            alias_name=CASE WHEN r.display_name<>src.label THEN src.label END
            FROM model_resource r WHERE model_legacy_binding.id=bid AND r.id=rid;
        UPDATE model_resource SET text_sort_order=src.sort_order,text_fallback_ids=src.fallback_model_ids,text_created_by=src.created_by,
                text_created_at=src.created_at,text_updated_at=src.updated_at,text_deleted_at=src.deleted_at,
                text_deleted_by=src.deleted_by,text_deletion_reason=src.deletion_reason,
                text_deletion_batch_id=src.deletion_batch_id WHERE id=rid;
        SELECT p.id INTO pid FROM model_parameter_profile p WHERE p.resource_id=rid AND p.revision_id=vid
            AND (p.parameter_values->>'temperature')::float8=src.temperature
            AND (p.parameter_values->>'max_tokens')::integer=src.max_tokens ORDER BY p.id LIMIT 1;
        IF pid IS NULL THEN
            INSERT INTO model_parameter_profile(resource_id,revision_id,name,version,parameter_values,definitions,created_by)
                SELECT rid,vid,'默认参数',coalesce(max(version),0)+1,
                    json_build_object('temperature',src.temperature,'max_tokens',src.max_tokens),
                    rev.parameter_schema,src.created_by FROM model_parameter_profile
                WHERE revision_id=vid AND name='默认参数' RETURNING id INTO pid;
        END IF;
        UPDATE model_revision SET text_cost_input=src.cost_per_1k_input,text_cost_output=src.cost_per_1k_output,
                text_profile_id=pid,text_api_base=nullif(src.api_base,rev.endpoint_display),
                text_provider=nullif(src.provider,rev.provider),text_key_is_null=src.api_key_encrypted IS NULL,
                text_timeout=CASE WHEN coalesce((rev.config_json->>'timeout')::integer,60)<>src.timeout THEN src.timeout END
                WHERE id=vid;
        SELECT * INTO cred FROM model_credential WHERE revision_id=vid;
        IF cred.id IS NULL AND coalesce(src.api_key_encrypted,'')<>'' THEN
            INSERT INTO model_credential(revision_id,ciphertext,cipher_format,header_name)
            VALUES(vid,src.api_key_encrypted,'model-configuration-fernet','Authorization');
        ELSIF cred.id IS NOT NULL THEN
            UPDATE model_credential SET text_ciphertext=CASE WHEN cred.cipher_format='model-configuration-fernet'
                AND cred.ciphertext=src.api_key_encrypted THEN NULL ELSE src.api_key_encrypted END WHERE id=cred.id;
        END IF;
    END LOOP;

    FOR src IN SELECT * FROM b2_source_model_configuration WHERE is_default ORDER BY id LOOP
        IF NOT EXISTS (SELECT FROM model_configuration WHERE id=src.id AND is_default) THEN
            UPDATE model_configuration SET is_default=true WHERE id=src.id;
        END IF;
    END LOOP;

    FOR src IN SELECT * FROM b2_source_asr_connection ORDER BY project_id,name,version,id LOOP
        src_conn := json_populate_record(NULL::asr_connection,to_json(src));
        SELECT b.id INTO bid FROM model_legacy_binding b WHERE b.connection_public_id=src.id;
        IF bid IS NULL THEN
            SELECT v.id,v.resource_id INTO vid,rid FROM model_revision v WHERE v.legacy_connection_id=src.id;
            IF vid IS NULL THEN
                INSERT INTO asr_connection SELECT src_conn.*;
                CONTINUE;
            END IF;
            INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id)
                VALUES('ASR_CONNECTION',src.id,rid,vid) RETURNING id INTO bid;
        END IF;
        UPDATE model_legacy_binding SET allow_project_execution=true,legacy_domain_id=NULL
            WHERE id=bid AND legacy_kind='ASR_CONNECTION' AND legacy_domain_id='0106:project-legacy-execution';
        UPDATE model_revision v SET legacy_connection_id=src.id FROM model_legacy_binding b
            WHERE b.id=bid AND b.allow_project_execution AND b.revision_id=v.id AND v.legacy_connection_id IS NULL;
        PERFORM model_bind_connection(bid,src_conn);
    END LOOP;

    FOR marker IN SELECT * FROM model_legacy_binding WHERE legacy_kind='0106_SCOPED_PROFILE' LOOP
        SELECT p.resource_id,p.revision_id INTO holder,holder_revision FROM model_parameter_profile p WHERE p.id=marker.legacy_id;
        SELECT * INTO src FROM b2_source_asr_parameter_set WHERE id=marker.legacy_role::integer;
        IF holder IS NOT NULL AND src.id IS NOT NULL THEN
            SELECT * INTO STRICT conn FROM model_legacy_binding WHERE connection_public_id=src.connection_id;
            UPDATE model_parameter_profile SET resource_id=conn.resource_id,revision_id=conn.revision_id,
                scope_connection_id=src.connection_id,name=src.name,version=src.version,
                parameter_values=src.parameters,definitions=src.definitions WHERE id=marker.legacy_id;
        END IF;
        DELETE FROM model_legacy_binding WHERE id=marker.id;
        -- Leave a private holder intact if anything acquired a reference while the old release ran.
        DELETE FROM model_resource r WHERE r.id=holder AND r.visibility='PROJECT' AND r.status='DISABLED'
            AND r.resource_key LIKE '0106-private-profile-%'
            AND NOT EXISTS (SELECT FROM model_revision WHERE resource_id=holder AND id<>holder_revision)
            AND NOT EXISTS (SELECT FROM model_credential WHERE revision_id=holder_revision)
            AND NOT EXISTS (SELECT FROM model_parameter_profile WHERE resource_id=holder OR revision_id=holder_revision)
            AND NOT EXISTS (SELECT FROM model_legacy_binding WHERE resource_id=holder OR revision_id=holder_revision)
            AND NOT EXISTS (SELECT FROM model_resource_grant WHERE resource_id=holder)
            AND NOT EXISTS (SELECT FROM model_default_binding WHERE resource_id=holder OR revision_id=holder_revision)
            AND NOT EXISTS (SELECT FROM model_task_slot WHERE resource_id=holder OR revision_id=holder_revision)
            AND NOT EXISTS (SELECT FROM model_validation_run WHERE resource_id=holder OR revision_id=holder_revision)
            AND NOT EXISTS (SELECT FROM knowledge_retrieval_config WHERE rerank_revision_id=holder_revision)
            AND NOT EXISTS (SELECT FROM knowledge_index_generation WHERE embedding_revision_id=holder_revision);
    END LOOP;

    FOR src IN SELECT * FROM b2_source_asr_parameter_set ORDER BY id LOOP
        SELECT * INTO STRICT conn FROM model_legacy_binding WHERE connection_public_id=src.connection_id;
        IF conn.project_id<>src.project_id THEN
            RAISE EXCEPTION 'parameter set % and connection % have different project owners',src.id,src.connection_id;
        END IF;
        SELECT b.id,substring(b.legacy_domain_id FROM '^0106:profile:([0-9]+)$')::integer INTO bid,pinned_profile
            FROM model_legacy_binding b WHERE b.parameter_public_id=src.id;
        SELECT p.id INTO pid FROM model_parameter_profile p WHERE p.resource_id=conn.resource_id
            AND p.revision_id=conn.revision_id AND (p.id=pinned_profile OR p.legacy_parameter_set_id=src.id OR
                (p.name=src.name AND p.version=src.version AND p.scope_connection_id IS NULL))
            AND p.parameter_values::jsonb=src.parameters::jsonb AND p.definitions::jsonb=src.definitions::jsonb
            ORDER BY (p.id=pinned_profile) DESC NULLS LAST,(p.legacy_parameter_set_id=src.id) DESC NULLS LAST,p.id LIMIT 1;
        IF pid IS NULL THEN
            scoped := CASE WHEN conn.legacy_kind='ASR_SHARED_CONNECTION' OR EXISTS (
                SELECT FROM model_parameter_profile WHERE revision_id=conn.revision_id AND name=src.name AND version=src.version
            ) THEN src.connection_id END;
            INSERT INTO model_parameter_profile(resource_id,revision_id,name,version,parameter_values,definitions,
                    scope_connection_id,created_at,created_by)
            VALUES(conn.resource_id,conn.revision_id,src.name,src.version,src.parameters,src.definitions,scoped,
                    src.created_at,src.created_by) RETURNING id INTO pid;
            IF NOT EXISTS (SELECT FROM model_parameter_profile WHERE legacy_parameter_set_id=src.id) THEN
                UPDATE model_parameter_profile SET legacy_parameter_set_id=src.id WHERE id=pid;
            END IF;
        END IF;
        IF bid IS NULL THEN
            INSERT INTO model_legacy_binding(legacy_kind,legacy_id,resource_id,revision_id)
            VALUES('ASR_PARAMETER_SET',src.id,conn.resource_id,conn.revision_id) RETURNING id INTO bid;
        END IF;
        UPDATE model_legacy_binding SET profile_id=pid,parent_connection_id=src.connection_id,project_id=src.project_id,
            legacy_domain_id=CASE WHEN pinned_profile IS NULL THEN legacy_domain_id END,
            alias_name=src.name,alias_version=src.version,alias_created_at=src.created_at,
            alias_created_by=src.created_by,legacy_task_type=conn.legacy_task_type WHERE id=bid;
    END LOOP;
END $$;
