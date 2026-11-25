CREATE VIEW model_configuration AS
SELECT b.model_public_id AS id, b.legacy_domain_id::varchar(100) AS domain_id, coalesce(b.alias_name,r.display_name)::varchar(120) AS label,
       coalesce(v.text_provider, v.provider)::varchar(50) AS provider,
       coalesce(v.text_api_base, v.endpoint_display)::varchar(500) AS api_base,
       CASE WHEN v.text_key_is_null THEN NULL ELSE coalesce((SELECT coalesce(c.text_ciphertext, CASE WHEN c.cipher_format='model-configuration-fernet'
           THEN c.ciphertext END) FROM model_credential c WHERE c.revision_id=v.id), '') END AS api_key_encrypted,
       coalesce(b.alias_model_name,v.model_name)::varchar(200) AS model_name, coalesce((SELECT p.parameter_values->>'temperature' FROM model_parameter_profile p WHERE p.id=v.text_profile_id)::double precision,0.2) AS temperature,
       coalesce((SELECT p.parameter_values->>'max_tokens' FROM model_parameter_profile p WHERE p.id=v.text_profile_id)::integer,4096) AS max_tokens,
       coalesce(v.text_timeout,(v.config_json->>'timeout')::integer,60) AS timeout,
       v.text_cost_input AS cost_per_1k_input, v.text_cost_output AS cost_per_1k_output,
       coalesce(b.alias_enabled,v.enabled) AS is_enabled, EXISTS (SELECT FROM model_default_binding d WHERE d.category='TEXT_GENERATION'
          AND d.purpose='TEXT_INFERENCE' AND d.project_id IS NULL AND d.resource_id=r.id) AS is_default,
       r.text_fallback_ids AS fallback_model_ids, r.text_sort_order AS sort_order, r.text_created_by AS created_by,
       r.text_created_at AS created_at, r.text_updated_at AS updated_at, r.text_deleted_at AS deleted_at,
       r.text_deleted_by AS deleted_by, r.text_deletion_reason AS deletion_reason,
       r.text_deletion_batch_id AS deletion_batch_id
FROM model_legacy_binding b JOIN model_resource r ON r.id=b.resource_id
JOIN model_revision v ON v.id=r.current_revision_id AND v.resource_id=r.id
WHERE b.model_public_id IS NOT NULL;

CREATE VIEW asr_connection AS
SELECT b.connection_public_id AS id,b.project_id,b.alias_name AS name,b.legacy_role AS role,
       coalesce(b.alias_provider,v.provider)::varchar(80) AS provider_id,coalesce(b.alias_model_name,v.model_name)::varchar(160) AS model_id,b.alias_version AS version,
       coalesce(a.alias_endpoint_ciphertext,v.endpoint_ciphertext) AS endpoint_ciphertext,
       coalesce(b.alias_endpoint_display,v.endpoint_display) AS endpoint_display,
       coalesce(b.alias_config,v.config_json) AS config_json,
       CASE WHEN b.use_revision_credential THEN c.ciphertext ELSE a.ciphertext END AS secret_ciphertext,
       b.alias_header AS secret_header,coalesce(b.alias_enabled,v.enabled) AS enabled,
       b.alias_created_by AS created_by,b.alias_created_at AS created_at,b.alias_updated_at AS updated_at,
       b.legacy_task_type AS task_type
FROM model_legacy_binding b JOIN model_revision v ON v.id=b.revision_id
LEFT JOIN model_credential c ON c.revision_id=v.id
LEFT JOIN model_credential a ON a.alias_binding_id=b.id
WHERE b.connection_public_id IS NOT NULL;

CREATE VIEW asr_parameter_set AS
SELECT b.parameter_public_id AS id,b.project_id,b.parent_connection_id AS connection_id,b.alias_name AS name,
       b.alias_version AS version,p.parameter_values AS parameters,p.definitions,b.alias_created_by AS created_by,
       b.alias_created_at AS created_at
FROM model_legacy_binding b JOIN model_parameter_profile p ON p.id=b.profile_id
WHERE b.parameter_public_id IS NOT NULL;
