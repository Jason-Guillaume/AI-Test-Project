"""Allocate public compatibility identities without materializing a second model or credential."""

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.http.errors import not_found
from app.core.models.configuration import ModelConfiguration
from app.features.asr_evaluation.models.asr_models import AsrConnection, AsrParameterSet
from app.platform.model_configuration.models import (
    ModelCredential, ModelLegacyBinding, ModelParameterProfile, ModelResource, ModelRevision,
)
from app.platform.model_configuration.schemas import normalize_provider


def canonical_storage(db: Session) -> bool:
    """PostgreSQL installs write-through views. Lightweight SQLite fixtures use local tables."""
    return db.get_bind().dialect.name == "postgresql"


def mark_managed_connection_insert(db: Session, connection: AsrConnection) -> None:
    """Identify this exact API insert so the view can group private revisions under the existing admission policy."""
    if canonical_storage(db):
        connection.id = db.scalar(text("SELECT nextval('asr_connection_id_seq')"))
        db.execute(text("SELECT set_config('model_center.managed_connection', :public_id, true)"),
                   {"public_id": str(connection.id)})


def lock_text_default(db: Session) -> None:
    if canonical_storage(db):
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('model-center'),hashtext('text-inference-default'))"))


def bind_text_revision(db: Session, resource: ModelResource, revision: ModelRevision, profile: ModelParameterProfile,
                       endpoint: str, previous_config: tuple | None = None) -> None:
    """Expose the admitted text revision under its stable integer ID and fingerprint."""
    revision.text_profile_id = profile.id
    revision.text_api_base = endpoint if endpoint != revision.endpoint_display else None
    provider = normalize_provider(revision.provider)
    revision.text_provider = provider if provider != revision.provider else None
    now = db.scalar(select(func.localtimestamp()))
    if resource.legacy_model_id is None:
        public_id = db.scalar(text("SELECT nextval('model_configuration_id_seq')"))
        db.add(ModelLegacyBinding(
            legacy_kind="MODEL_CONFIGURATION", legacy_id=public_id, resource_id=resource.id,
            revision_id=revision.id, legacy_domain_id=resource.resource_key,
        ))
        db.flush()
        resource.legacy_model_id = public_id
        resource.text_created_by = resource.created_by
        resource.text_created_at = resource.text_updated_at = now
        return

    db.add(ModelLegacyBinding(
        legacy_kind="MODEL_REVISION", legacy_id=revision.id, resource_id=resource.id,
        revision_id=revision.id, legacy_domain_id=resource.resource_key,
    ))
    binding = db.query(ModelLegacyBinding).filter_by(model_public_id=resource.legacy_model_id).one()
    binding.alias_model_name = binding.alias_name = binding.alias_enabled = None
    db.flush()
    current = db.get(ModelConfiguration, resource.legacy_model_id, populate_existing=True)
    if text_state(current) != previous_config:
        resource.text_updated_at = now


def text_state(row: ModelConfiguration | None) -> tuple | None:
    if row is None:
        return None
    return (row.provider, row.api_base, row.model_name, row.api_key_encrypted, row.temperature,
            row.max_tokens, row.timeout, row.is_enabled, row.label)


def _parameter_alias_name(db, connection_id, profile, public_id):
    occupied = db.query(ModelLegacyBinding.id).filter_by(parent_connection_id=connection_id, alias_version=profile.version)
    name = profile.name
    suffix = 0
    while occupied.filter_by(alias_name=name).first():
        suffix += 1
        tag = f" [{public_id}.{suffix}]"
        name = f"{profile.name[:120-len(tag)]}{tag}"
    return name


def resolve_project_aliases(db: Session, project_id: int, resource: ModelResource, revision: ModelRevision,
                            profile: ModelParameterProfile, actor_id: int) -> tuple[AsrConnection, AsrParameterSet]:
    """Return a project-local connection and exact profile alias for these fixed canonical versions."""
    conn = db.query(ModelLegacyBinding).filter(
        ModelLegacyBinding.connection_public_id.is_not(None), ModelLegacyBinding.project_id == project_id,
        ModelLegacyBinding.revision_id == revision.id, ModelLegacyBinding.resource_id == resource.id,
    ).order_by(ModelLegacyBinding.legacy_id).with_for_update().first()
    if conn is None:
        public_id = db.scalar(text("SELECT nextval('asr_connection_id_seq')"))
        credential = db.query(ModelCredential).filter_by(revision_id=revision.id).first()
        now = db.scalar(select(func.now()))
        conn = ModelLegacyBinding(
            legacy_kind="ASR_SHARED_CONNECTION", legacy_id=public_id, resource_id=resource.id, revision_id=revision.id,
            project_id=project_id, alias_name=f"{resource.display_name[:109]} [{resource.resource_key[-8:]}]",
            alias_version=revision.version, legacy_task_type="DIARIZATION" if resource.category == "DIARIZATION" else "TRANSCRIPTION",
            alias_header=credential.header_name if credential else None, alias_created_at=now,
            alias_updated_at=now, alias_created_by=actor_id,
        )
        db.add(conn)
        db.flush()
    connection = db.get(AsrConnection, conn.legacy_id)
    if not connection.enabled:
        raise not_found("项目模型连接不可用")
    parameter = db.query(ModelLegacyBinding).filter_by(
        parent_connection_id=conn.legacy_id, profile_id=profile.id,
    ).order_by(ModelLegacyBinding.legacy_id).first()
    if parameter is None:
        public_id = db.scalar(text("SELECT nextval('asr_parameter_set_id_seq')"))
        parameter = ModelLegacyBinding(
            legacy_kind="ASR_SHARED_PARAMETER_SET", legacy_id=public_id, resource_id=resource.id,
            revision_id=revision.id, profile_id=profile.id, project_id=project_id,
            parent_connection_id=conn.legacy_id, legacy_task_type=conn.legacy_task_type,
            alias_name=_parameter_alias_name(db, conn.legacy_id, profile, public_id),
            alias_version=profile.version, alias_created_by=actor_id,
            alias_created_at=func.now(),
        )
        db.add(parameter)
        db.flush()
    return connection, db.get(AsrParameterSet, parameter.legacy_id)
