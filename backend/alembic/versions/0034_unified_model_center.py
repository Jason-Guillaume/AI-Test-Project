"""建立统一模型资源目录并兼容映射旧模型、ASR 连接与任务角色。"""

from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def _json(value):
    """兼容 SQLite 与 PostgreSQL 驱动返回的 JSON 表示。"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, (dict, list)) else {}


def _resource_id(connection, resource_key: str) -> int:
    """读取已写入规范资源 ID。"""
    return int(connection.execute(
        sa.text("SELECT id FROM model_resource WHERE resource_key=:resource_key"),
        {"resource_key": resource_key},
    ).scalar_one())


def _revision_id(connection, resource_id: int, version: int) -> int:
    """读取指定逻辑资源的历史修订 ID。"""
    return int(connection.execute(
        sa.text("SELECT id FROM model_revision WHERE resource_id=:resource_id AND version=:version"),
        {"resource_id": resource_id, "version": version},
    ).scalar_one())


def upgrade() -> None:
    """创建规范化资源表，回填旧配置并为历史任务建立槽位兼容映射。"""
    op.create_table(
        "model_resource",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_key", sa.String(120), nullable=False, unique=True),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="PLATFORM"),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE")),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("current_revision_id", sa.Integer()),
        sa.Column("legacy_model_id", sa.Integer(), sa.ForeignKey("model_configuration.id", ondelete="SET NULL"), unique=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_model_resource_resource_key", "model_resource", ["resource_key"])
    op.create_index("ix_model_resource_category", "model_resource", ["category"])
    op.create_index("ix_model_resource_project_id", "model_resource", ["project_id"])
    op.create_index("ix_model_resource_status", "model_resource", ["status"])
    op.create_index("ix_model_resource_scope_category", "model_resource", ["visibility", "project_id", "category", "status"])

    op.create_table(
        "model_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("adapter_key", sa.String(100), nullable=False), sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("endpoint_ciphertext", sa.Text()), sa.Column("endpoint_display", sa.String(500)),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("parameter_schema", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("legacy_connection_id", sa.Integer(), sa.ForeignKey("asr_connection.id", ondelete="SET NULL"), unique=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("resource_id", "version", name="uq_model_revision_version"),
    )
    op.create_index("ix_model_revision_resource_id", "model_revision", ["resource_id"])

    op.create_table(
        "model_credential",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("model_revision.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("cipher_format", sa.String(40), nullable=False, server_default="shared-fernet"),
        sa.Column("header_name", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("revision_id", name="uq_model_credential_revision"),
    )

    op.create_table(
        "model_parameter_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("model_revision.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parameter_values", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("definitions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("legacy_parameter_set_id", sa.Integer(), sa.ForeignKey("asr_parameter_set.id", ondelete="SET NULL"), unique=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("resource_id", "revision_id", "name", "version", name="uq_model_profile_version"),
    )
    op.create_index("ix_model_parameter_profile_resource_id", "model_parameter_profile", ["resource_id"])
    op.create_index("ix_model_parameter_profile_revision_id", "model_parameter_profile", ["revision_id"])

    op.create_table(
        "model_legacy_binding",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("legacy_kind", sa.String(40), nullable=False),
        sa.Column("legacy_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("model_revision.id", ondelete="CASCADE"), nullable=False),
        sa.Column("legacy_domain_id", sa.String(120)), sa.Column("legacy_role", sa.String(20)),
        sa.Column("legacy_task_type", sa.String(30)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("legacy_kind", "legacy_id", name="uq_model_legacy_binding"),
    )
    op.create_index("ix_model_legacy_binding_resource_id", "model_legacy_binding", ["resource_id"])
    op.create_index("ix_model_legacy_binding_legacy_domain_id", "model_legacy_binding", ["legacy_domain_id"])

    op.create_table(
        "model_resource_grant",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("resource_id", "project_id", name="uq_model_resource_grant"),
    )
    op.create_index("ix_model_resource_grant_resource_id", "model_resource_grant", ["resource_id"])
    op.create_index("ix_model_resource_grant_project_id", "model_resource_grant", ["project_id"])

    op.create_table(
        "model_default_binding",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("category", sa.String(30), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE")),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("model_resource.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("model_revision.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("model_parameter_profile.id", ondelete="RESTRICT")),
        sa.Column("fallback_resource_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("automatic_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("category", "purpose", "project_id", name="uq_model_default_purpose"),
    )

    op.create_table(
        "model_validation_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("model_resource.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("model_revision.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("model_parameter_profile.id", ondelete="SET NULL")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE")),
        sa.Column("audio_id", sa.Integer(), sa.ForeignKey("asr_audio.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("diagnostic_kind", sa.String(30), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_model_validation_run_resource_id", "model_validation_run", ["resource_id"])
    op.create_index("ix_model_validation_run_status", "model_validation_run", ["status"])
    op.create_index("ix_model_validation_resource_created", "model_validation_run", ["resource_id", "created_at"])

    op.create_table(
        "model_task_slot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_kind", sa.String(30), nullable=False), sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(30), nullable=False),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("model_resource.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("model_revision.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("model_parameter_profile.id", ondelete="RESTRICT")),
        sa.Column("legacy_connection_id", sa.Integer(), sa.ForeignKey("asr_connection.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_kind", "task_id", "slot", name="uq_model_task_slot"),
    )
    op.create_index("ix_model_task_slot_resource_id", "model_task_slot", ["resource_id"])

    connection = op.get_bind()
    text_models = connection.execute(sa.text(
        "SELECT id, domain_id, label, provider, api_base, api_key_encrypted, model_name, temperature, max_tokens, "
        "timeout, is_enabled, is_default, fallback_model_ids, sort_order, created_by FROM model_configuration"
    )).mappings().all()
    text_resources = {}
    for row in text_models:
        key = str(row["domain_id"])
        connection.execute(sa.text(
            "INSERT INTO model_resource (resource_key, category, visibility, display_name, status, legacy_model_id, created_by) "
            "VALUES (:key, 'TEXT_GENERATION', 'PLATFORM', :name, :status, :legacy_id, :created_by)"
        ), {"key": key, "name": row["label"], "status": "ACTIVE" if row["is_enabled"] else "DISABLED",
            "legacy_id": row["id"], "created_by": row["created_by"]})
        resource_id = _resource_id(connection, key)
        connection.execute(sa.text(
            "INSERT INTO model_revision (resource_id, version, provider, adapter_key, model_name, endpoint_display, config_json, "
            "capabilities, parameter_schema, enabled, created_by) VALUES (:resource_id, 1, :provider, :adapter, "
            ":model_name, :endpoint, :config, :caps, :schema, :enabled, :created_by)"
        ), {"resource_id": resource_id, "provider": row["provider"],
            "adapter": "unregistered:anthropic-native" if row["provider"] == "anthropic" else "openai-compatible-chat",
            "model_name": row["model_name"],
            "endpoint": row["api_base"], "config": json.dumps({"timeout": row["timeout"], "legacy_model_id": row["id"]}),
            "caps": json.dumps(["text_generation"]),
            "schema": json.dumps([{"path": "temperature", "value_type": "number"}, {"path": "max_tokens", "value_type": "integer"}]),
            "enabled": row["is_enabled"], "created_by": row["created_by"]})
        revision_id = _revision_id(connection, resource_id, 1)
        if row["api_key_encrypted"]:
            connection.execute(sa.text(
                "INSERT INTO model_credential (revision_id, ciphertext, cipher_format) VALUES (:revision_id, :ciphertext, 'model-configuration-fernet')"
            ), {"revision_id": revision_id, "ciphertext": row["api_key_encrypted"]})
        connection.execute(sa.text(
            "INSERT INTO model_parameter_profile (resource_id, revision_id, name, version, parameter_values, definitions) "
            "VALUES (:resource_id, :revision_id, '默认参数', 1, :values, :definitions)"
        ), {"resource_id": resource_id, "revision_id": revision_id,
            "values": json.dumps({"temperature": row["temperature"], "max_tokens": row["max_tokens"]}),
            "definitions": json.dumps([{"path": "temperature", "display_name": "采样温度", "value_type": "number", "minimum": 0, "maximum": 2},
                                       {"path": "max_tokens", "display_name": "最大输出 Token", "value_type": "integer", "minimum": 1}])})
        profile_id = int(connection.execute(sa.text(
            "SELECT id FROM model_parameter_profile WHERE resource_id=:resource_id AND name='默认参数' AND version=1"
        ), {"resource_id": resource_id}).scalar_one())
        connection.execute(sa.text("UPDATE model_resource SET current_revision_id=:revision_id WHERE id=:id"),
                           {"revision_id": revision_id, "id": resource_id})
        connection.execute(sa.text(
            "INSERT INTO model_legacy_binding (legacy_kind, legacy_id, resource_id, revision_id, legacy_domain_id) "
            "VALUES ('MODEL_CONFIGURATION', :legacy_id, :resource_id, :revision_id, :domain_id)"
        ), {"legacy_id": row["id"], "resource_id": resource_id, "revision_id": revision_id, "domain_id": key})
        text_resources[row["id"]] = (resource_id, revision_id, profile_id)
    for row in text_models:
        if not row["is_default"]:
            continue
        resource_id, revision_id, profile_id = text_resources[row["id"]]
        fallback_ids = [text_resources[item][0] for item in _json(row["fallback_model_ids"])
                        if item in text_resources and text_resources[item][0] != resource_id]
        connection.execute(sa.text(
            "INSERT INTO model_default_binding (category, purpose, resource_id, revision_id, profile_id, fallback_resource_ids, automatic_fallback) "
            "VALUES ('TEXT_GENERATION', 'TEXT_INFERENCE', :resource_id, :revision_id, :profile_id, :fallbacks, :automatic)"
        ), {"resource_id": resource_id, "revision_id": revision_id, "profile_id": profile_id,
            "fallbacks": json.dumps(fallback_ids), "automatic": bool(fallback_ids)})

    asr_rows = connection.execute(sa.text(
        "SELECT id, project_id, name, role, task_type, provider_id, model_id, version, endpoint_ciphertext, endpoint_display, "
        "config_json, secret_ciphertext, secret_header, enabled, created_by FROM asr_connection ORDER BY project_id, name, version, id"
    )).mappings().all()
    asr_resources = {}
    asr_binding = {}
    for row in asr_rows:
        group = (row["project_id"], row["task_type"], row["name"])
        if group not in asr_resources:
            digest = hashlib.sha256(str(row["name"]).encode("utf-8")).hexdigest()[:16]
            key = f"project-{row['project_id']}-{str(row['task_type']).lower()}-{digest}"
            connection.execute(sa.text(
                "INSERT INTO model_resource (resource_key, category, visibility, project_id, display_name, status, created_by) "
                "VALUES (:key, :category, 'PROJECT', :project_id, :name, 'ACTIVE', :created_by)"
            ), {"key": key, "category": "DIARIZATION" if row["task_type"] == "DIARIZATION" else "ASR",
                "project_id": row["project_id"], "name": row["name"], "created_by": row["created_by"]})
            asr_resources[group] = _resource_id(connection, key)
        resource_id = asr_resources[group]
        config = _json(row["config_json"])
        provider_id = str(row["provider_id"] or "unknown")
        adapter = "generic-json-http" if provider_id == "generic-json" else f"unregistered:{provider_id}"
        response_mapping = config.get("response_mapping") if isinstance(config.get("response_mapping"), dict) else {}
        capabilities = ["transcription"] if row["task_type"] == "TRANSCRIPTION" else ["speaker_intervals"]
        if response_mapping.get("segments_pointer"):
            capabilities.append("timestamped_segments")
        if response_mapping.get("speaker_pointer"):
            capabilities.append("native_speaker_labels")
        version = int(row["version"] or 1)
        connection.execute(sa.text(
            "INSERT INTO model_revision (resource_id, version, provider, adapter_key, model_name, endpoint_ciphertext, "
            "endpoint_display, config_json, capabilities, parameter_schema, enabled, legacy_connection_id, created_by) "
            "VALUES (:resource_id, :version, :provider, :adapter, :model_name, :endpoint_ciphertext, :endpoint_display, "
            ":config, :caps, :schema, :enabled, :legacy_id, :created_by)"
        ), {"resource_id": resource_id, "version": version, "provider": provider_id, "adapter": adapter,
            "model_name": row["model_id"], "endpoint_ciphertext": row["endpoint_ciphertext"],
            "endpoint_display": row["endpoint_display"], "config": json.dumps(config, ensure_ascii=False),
            "caps": json.dumps(capabilities), "schema": json.dumps(config.get("parameter_definitions") or [], ensure_ascii=False),
            "enabled": row["enabled"], "legacy_id": row["id"], "created_by": row["created_by"]})
        revision_id = _revision_id(connection, resource_id, version)
        if row["secret_ciphertext"]:
            connection.execute(sa.text(
                "INSERT INTO model_credential (revision_id, ciphertext, cipher_format, header_name) "
                "VALUES (:revision_id, :ciphertext, 'shared-fernet', :header)"
            ), {"revision_id": revision_id, "ciphertext": row["secret_ciphertext"], "header": row["secret_header"]})
        connection.execute(sa.text("UPDATE model_resource SET current_revision_id=:revision_id WHERE id=:id AND (current_revision_id IS NULL OR current_revision_id < :revision_id)"),
                           {"revision_id": revision_id, "id": resource_id})
        connection.execute(sa.text(
            "INSERT INTO model_legacy_binding (legacy_kind, legacy_id, resource_id, revision_id, legacy_role, legacy_task_type) "
            "VALUES ('ASR_CONNECTION', :legacy_id, :resource_id, :revision_id, :role, :task_type)"
        ), {"legacy_id": row["id"], "resource_id": resource_id, "revision_id": revision_id,
            "role": row["role"], "task_type": row["task_type"]})
        asr_binding[row["id"]] = (resource_id, revision_id)

    parameter_rows = connection.execute(sa.text(
        "SELECT id, project_id, connection_id, name, version, parameters, definitions, created_by FROM asr_parameter_set"
    )).mappings().all()
    profile_binding = {}
    for row in parameter_rows:
        binding = asr_binding.get(row["connection_id"])
        if not binding:
            continue
        resource_id, revision_id = binding
        connection.execute(sa.text(
            "INSERT INTO model_parameter_profile (resource_id, revision_id, name, version, parameter_values, definitions, legacy_parameter_set_id, created_by) "
            "VALUES (:resource_id, :revision_id, :name, :version, :values, :definitions, :legacy_id, :created_by)"
        ), {"resource_id": resource_id, "revision_id": revision_id, "name": row["name"], "version": row["version"],
            "values": json.dumps(_json(row["parameters"]), ensure_ascii=False),
            "definitions": json.dumps(_json(row["definitions"]), ensure_ascii=False),
            "legacy_id": row["id"], "created_by": row["created_by"]})
        profile_binding[row["id"]] = int(connection.execute(sa.text(
            "SELECT id FROM model_parameter_profile WHERE legacy_parameter_set_id=:legacy_id"
        ), {"legacy_id": row["id"]}).scalar_one())

    for row in asr_rows:
        resource_id, revision_id = asr_binding[row["id"]]
        existing_profile = connection.execute(sa.text(
            "SELECT id FROM model_parameter_profile WHERE resource_id=:resource_id AND revision_id=:revision_id LIMIT 1"
        ), {"resource_id": resource_id, "revision_id": revision_id}).first()
        if existing_profile:
            continue
        connection.execute(sa.text(
            "INSERT INTO asr_parameter_set (project_id, connection_id, name, version, parameters, definitions, created_by) "
            "VALUES (:project_id, :connection_id, '默认参数', 1, :parameters, :definitions, :created_by)"
        ), {"project_id": row["project_id"], "connection_id": row["id"],
            "parameters": json.dumps({}), "definitions": json.dumps([]), "created_by": row["created_by"]})
        parameter_id = int(connection.execute(sa.text(
            "SELECT id FROM asr_parameter_set WHERE connection_id=:connection_id AND name='默认参数' AND version=1"
        ), {"connection_id": row["id"]}).scalar_one())
        connection.execute(sa.text(
            "INSERT INTO model_parameter_profile (resource_id, revision_id, name, version, parameter_values, definitions, legacy_parameter_set_id, created_by) "
            "VALUES (:resource_id, :revision_id, '默认参数', 1, :parameters, :definitions, :legacy_id, :created_by)"
        ), {"resource_id": resource_id, "revision_id": revision_id, "parameters": json.dumps({}),
            "definitions": json.dumps([]), "legacy_id": parameter_id, "created_by": row["created_by"]})
        connection.execute(sa.text(
            "INSERT INTO model_legacy_binding (legacy_kind, legacy_id, resource_id, revision_id, legacy_task_type) "
            "VALUES ('ASR_PARAMETER_SET', :legacy_id, :resource_id, :revision_id, :task_type)"
        ), {"legacy_id": parameter_id, "resource_id": resource_id, "revision_id": revision_id,
            "task_type": row["task_type"]})

    jobs = connection.execute(sa.text("SELECT id, config_snapshot FROM asr_job")).mappings().all()
    for job in jobs:
        snapshot = _json(job["config_snapshot"])
        conn_rows = snapshot.get("connections") if isinstance(snapshot, dict) else []
        if not isinstance(conn_rows, list):
            conn_rows = []
        refs = []
        for item in conn_rows:
            if not isinstance(item, dict):
                continue
            connection_id = item.get("id")
            binding = asr_binding.get(connection_id)
            if not binding:
                continue
            refs.append((str(item.get("role") or ""), int(connection_id), *binding))
        test_profile_id = None
        set_snapshot = snapshot.get("parameter_set") if isinstance(snapshot, dict) else None
        if isinstance(set_snapshot, dict):
            test_profile_id = profile_binding.get(set_snapshot.get("id"))
        references = 0
        for role, legacy_id, resource_id, revision_id in refs:
            if role == "TEST":
                slot, profile_id = "TEST", test_profile_id
            elif role == "REFERENCE":
                references += 1
                slot, profile_id = ("REFERENCE_A" if references == 1 else "REFERENCE_B"), None
            else:
                continue
            connection.execute(sa.text(
                "INSERT INTO model_task_slot (task_kind, task_id, slot, resource_id, revision_id, profile_id, legacy_connection_id) "
                "VALUES ('ASR_JOB', :task_id, :slot, :resource_id, :revision_id, :profile_id, :legacy_id)"
            ), {"task_id": job["id"], "slot": slot, "resource_id": resource_id, "revision_id": revision_id,
                "profile_id": profile_id, "legacy_id": legacy_id})

    schedules = connection.execute(sa.text(
        "SELECT id, connection_ids, parameter_set_id FROM asr_schedule"
    )).mappings().all()
    for schedule in schedules:
        connection_ids = _json(schedule["connection_ids"])
        if not isinstance(connection_ids, list):
            continue
        references = []
        for legacy_id in connection_ids:
            connection_row = connection.execute(sa.text(
                "SELECT role FROM asr_connection WHERE id=:id"
            ), {"id": legacy_id}).mappings().first()
            binding = asr_binding.get(legacy_id)
            if connection_row and binding:
                references.append((str(connection_row["role"] or ""), int(legacy_id), *binding))
        parameter_row = connection.execute(sa.text(
            "SELECT id FROM model_parameter_profile WHERE legacy_parameter_set_id=:legacy_id"
        ), {"legacy_id": schedule["parameter_set_id"]}).first()
        profile_id = int(parameter_row[0]) if parameter_row else None
        reference_count = 0
        for role, legacy_id, resource_id, revision_id in references:
            if role == "TEST":
                slot, selected_profile_id = "TEST", profile_id
            elif role == "REFERENCE":
                reference_count += 1
                slot, selected_profile_id = ("REFERENCE_A" if reference_count == 1 else "REFERENCE_B"), None
            else:
                continue
            connection.execute(sa.text(
                "INSERT INTO model_task_slot (task_kind, task_id, slot, resource_id, revision_id, profile_id, legacy_connection_id) "
                "VALUES ('ASR_SCHEDULE', :task_id, :slot, :resource_id, :revision_id, :profile_id, :legacy_id)"
            ), {"task_id": schedule["id"], "slot": slot, "resource_id": resource_id,
                "revision_id": revision_id, "profile_id": selected_profile_id, "legacy_id": legacy_id})


def downgrade() -> None:
    """回退统一目录；旧模型、ASR 连接、参数和任务快照表均保持原样。"""
    for name in ("model_task_slot", "model_validation_run", "model_default_binding", "model_resource_grant",
                 "model_legacy_binding", "model_parameter_profile", "model_credential", "model_revision", "model_resource"):
        op.drop_table(name)
