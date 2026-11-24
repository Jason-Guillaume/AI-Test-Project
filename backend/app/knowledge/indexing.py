"""Durable generation bookkeeping for knowledge vectors.

All operations that add chunks or change a generation take the same project row
lock. This makes coverage verification and a pointer switch atomic with parsing.
"""
from sqlalchemy import exists, select

from app.core.models.project import Project
from app.core.http.errors import bad_request, not_found
from app.knowledge.models import (
    KnowledgeBase, KnowledgeChunk, KnowledgeDocument, KnowledgeIndexGeneration,
    KnowledgeIndexJob, KnowledgeRetrievalConfig, KnowledgeVector, KnowledgeVersion,
)


def lock_project(db, project_id):
    project = db.query(Project).filter_by(id=project_id).with_for_update().first()
    if project is None:
        raise not_found('项目不存在')
    return project


def enqueue_chunks(db, generation, chunk_ids):
    """Register missing work inside the caller's project-locked transaction."""
    ids = list(dict.fromkeys(chunk_ids))
    if not ids:
        return 0
    existing = {ident for (ident,) in db.query(KnowledgeIndexJob.chunk_id).filter(
        KnowledgeIndexJob.generation_id == generation.id, KnowledgeIndexJob.chunk_id.in_(ids),
    ).all()}
    db.add_all(KnowledgeIndexJob(generation_id=generation.id, chunk_id=ident)
               for ident in ids if ident not in existing)
    return len(ids) - len(existing)


def enqueue_version(db, project_id, version_id):
    """Track additions in every maintained generation, including rollback generations."""
    lock_project(db, project_id)
    db.flush()
    ids = [ident for (ident,) in db.query(KnowledgeChunk.id).filter_by(version_id=version_id).all()]
    for generation in db.query(KnowledgeIndexGeneration).filter(
        KnowledgeIndexGeneration.project_id == project_id,
        KnowledgeIndexGeneration.state.in_(['BUILDING', 'ACTIVE', 'STANDBY']),
    ).all():
        enqueue_chunks(db, generation, ids)


def project_chunks(db, project_id):
    """Include all READY versions so frozen tasks and rollback remain searchable."""
    return db.query(KnowledgeChunk.id).join(
        KnowledgeVersion, KnowledgeChunk.version_id == KnowledgeVersion.id,
    ).join(KnowledgeDocument, KnowledgeVersion.document_id == KnowledgeDocument.id).join(
        KnowledgeBase, KnowledgeDocument.base_id == KnowledgeBase.id,
    ).filter(KnowledgeDocument.project_id == project_id, KnowledgeVersion.status == 'READY',
             KnowledgeDocument.enabled.is_(True), KnowledgeBase.enabled.is_(True))


def backfill_generation(db, generation_id):
    generation = db.get(KnowledgeIndexGeneration, generation_id)
    if generation is None:
        raise not_found('索引代不存在')
    lock_project(db, generation.project_id)
    if generation.state not in {'BUILDING', 'ACTIVE', 'STANDBY'}:
        raise bad_request('索引代不可回填')
    # A deleted vector must not leave a permanently completed job behind.
    lost = db.query(KnowledgeIndexJob).filter(
        KnowledgeIndexJob.generation_id == generation.id, KnowledgeIndexJob.status == 'DONE',
        ~exists().where((KnowledgeVector.generation_id == generation.id)
                        & (KnowledgeVector.chunk_id == KnowledgeIndexJob.chunk_id)),
    ).all()
    for job in lost:
        job.status, job.attempts, job.error, job.next_attempt_at = 'QUEUED', 0, None, None
    missing = project_chunks(db, generation.project_id).filter(~exists().where(
        (KnowledgeIndexJob.generation_id == generation.id) & (KnowledgeIndexJob.chunk_id == KnowledgeChunk.id)
    ))
    count = 0
    for (ident,) in missing.yield_per(500):
        db.add(KnowledgeIndexJob(generation_id=generation.id, chunk_id=ident))
        count += 1
        if count % 500 == 0:
            db.flush()
    db.flush()
    return count + len(lost)


def reconcile_project(db, project_id):
    """Resume work when previously disabled sources become available again."""
    lock_project(db, project_id)
    generations = db.query(KnowledgeIndexGeneration).filter(
        KnowledgeIndexGeneration.project_id == project_id,
        KnowledgeIndexGeneration.state.in_(['BUILDING', 'ACTIVE', 'STANDBY']),
    ).all()
    for generation in generations:
        backfill_generation(db, generation.id)
        for job in db.query(KnowledgeIndexJob).filter_by(generation_id=generation.id, status='FAILED').all():
            job.status, job.attempts, job.error, job.next_attempt_at = 'QUEUED', 0, None, None


def activate_generation(db, project_id, generation_id):
    """Atomically switch only after every accessible READY version has a vector."""
    lock_project(db, project_id)
    generation = db.query(KnowledgeIndexGeneration).filter_by(id=generation_id, project_id=project_id).first()
    if generation is None or generation.state not in {'BUILDING', 'ACTIVE', 'STANDBY'}:
        raise bad_request('索引代不存在或不可切换')
    missing = project_chunks(db, project_id).filter(~exists().where(
        (KnowledgeVector.generation_id == generation.id) & (KnowledgeVector.chunk_id == KnowledgeChunk.id)
    )).first()
    if missing:
        raise bad_request('索引代尚未覆盖所有可用文档版本')
    config = db.get(KnowledgeRetrievalConfig, project_id)
    if config is None:
        config = KnowledgeRetrievalConfig(project_id=project_id, enabled=True)
        db.add(config)
    if config.active_generation_id and config.active_generation_id != generation.id:
        previous = db.get(KnowledgeIndexGeneration, config.active_generation_id)
        if previous is not None:
            previous.state = 'STANDBY'
    generation.state = 'ACTIVE'
    config.active_generation_id = generation.id
    config.enabled = True
    db.flush()
    return config


def claim_job(db, *, now=None, lease_seconds=660, max_attempts=3):
    """Lease one due job. Commit before calling the external service."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    from sqlalchemy import or_
    now = now or datetime.now(timezone.utc)
    expired = (KnowledgeIndexJob.status == 'RUNNING') & (KnowledgeIndexJob.lease_until <= now)
    exhausted = db.query(KnowledgeIndexJob).filter(expired, KnowledgeIndexJob.attempts >= max_attempts).with_for_update(skip_locked=True).all()
    for job in exhausted:
        job.status, job.error, job.lease_token, job.lease_until = 'FAILED', 'lease_expired', None, None
    job = db.query(KnowledgeIndexJob).filter(
        or_((KnowledgeIndexJob.status == 'QUEUED') & or_(KnowledgeIndexJob.next_attempt_at.is_(None),
            KnowledgeIndexJob.next_attempt_at <= now), expired), KnowledgeIndexJob.attempts < max_attempts,
    ).order_by(KnowledgeIndexJob.id).with_for_update(skip_locked=True).first()
    if job is None:
        db.commit()
        return None
    token = uuid4().hex
    job.status, job.lease_token = 'RUNNING', token
    job.next_attempt_at = None
    job.lease_until = now + timedelta(seconds=lease_seconds)
    job.attempts += 1
    job.error = None
    ident = job.id
    db.commit()
    return ident, token


def finish_job(db, job_id, token, vector, *, now=None):
    """Reject stale workers and write at most one vector per generation/chunk."""
    from datetime import datetime, timezone
    import math
    now = now or datetime.now(timezone.utc)
    job = db.query(KnowledgeIndexJob).filter_by(id=job_id).with_for_update().first()
    if job is None or job.status != 'RUNNING' or job.lease_token != token:
        return False
    deadline = job.lease_until
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline <= now:
        return False
    generation = db.get(KnowledgeIndexGeneration, job.generation_id)
    chunk = db.get(KnowledgeChunk, job.chunk_id)
    if generation is None or chunk is None:
        return False
    version = db.get(KnowledgeVersion, chunk.version_id)
    doc = db.get(KnowledgeDocument, version.document_id) if version else None
    base = db.get(KnowledgeBase, doc.base_id) if doc else None
    if (not version or version.status != 'READY' or not doc or not base or not doc.enabled or not base.enabled
            or doc.project_id != generation.project_id or generation.state not in {'ACTIVE', 'BUILDING', 'STANDBY'}):
        return False
    if (len(vector) != generation.dimension or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                                    or not math.isfinite(v) for v in vector)):
        raise ValueError('invalid embedding')
    if generation.distance == 'cosine' and not any(vector):
        raise ValueError('zero embedding')
    row = db.query(KnowledgeVector).filter_by(generation_id=job.generation_id, chunk_id=job.chunk_id).first()
    if row is None:
        db.add(KnowledgeVector(generation_id=job.generation_id, chunk_id=job.chunk_id, embedding=vector))
    else:
        row.embedding = vector
    job.status, job.lease_token, job.lease_until, job.error = 'DONE', None, None, None
    db.commit()
    return True


def fail_job(db, job_id, token, *, max_attempts=3, now=None):
    """Persist only a sanitized failure code and permit bounded retry."""
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    job = db.query(KnowledgeIndexJob).filter_by(id=job_id).with_for_update().first()
    if job is None or job.status != 'RUNNING' or job.lease_token != token:
        return False
    job.status = 'FAILED' if job.attempts >= max_attempts else 'QUEUED'
    job.next_attempt_at = None if job.status == 'FAILED' else now + timedelta(seconds=min(300, 5 * 2 ** (job.attempts - 1)))
    job.error, job.lease_token, job.lease_until = 'embedding_failed', None, None
    db.commit()
    return True


def retrieval_connection(db, project_id, revision_id, category, *, timeout=None):
    """Resolve an enabled model revision and recheck the project's outbound policy."""
    from app.core.security.crypto import decrypt_secret
    from app.execution.http.outbound_policy import resolve_project_outbound_target
    from app.knowledge.providers import RetrievalConnection
    from app.platform.model_configuration.models import ModelCredential, ModelResource, ModelRevision
    revision = db.get(ModelRevision, revision_id)
    resource = db.get(ModelResource, revision.resource_id) if revision else None
    if (not revision or not revision.enabled or not resource or resource.status != 'ACTIVE'
            or resource.visibility != 'PLATFORM' or resource.category != category
            or category.lower() not in (revision.capabilities or [])
            or revision.adapter_key != {'EMBEDDING': 'openai-compatible-embeddings', 'RERANK': 'json-rerank'}[category]):
        raise ValueError('model unavailable')
    endpoint = decrypt_secret(revision.endpoint_ciphertext) or ''
    if not endpoint or resolve_project_outbound_target(db, endpoint, project_id).rejection_message:
        raise ValueError('model outbound not authorized')
    # Credential rotations and timeout changes on the same model/endpoint do not
    # alter the vector space. Use the current credential in that case.
    current = db.get(ModelRevision, resource.current_revision_id) if resource.current_revision_id else None
    credential_revision = revision
    if (current and current.enabled and current.model_name == revision.model_name
            and current.adapter_key == revision.adapter_key
            and decrypt_secret(current.endpoint_ciphertext) == endpoint):
        credential_revision = current
    credential = db.query(ModelCredential).filter_by(revision_id=credential_revision.id).first()
    if credential and credential.cipher_format == 'model-configuration-fernet':
        from app.platform.model_configuration.services.model_config_service import decrypt_api_key
        secret = decrypt_api_key(credential.ciphertext)
    else:
        secret = decrypt_secret(credential.ciphertext) if credential else ''
    configured_timeout = (credential_revision.config_json or {}).get('timeout_seconds', 10)
    return RetrievalConnection(endpoint=endpoint, model=revision.model_name, credential=secret,
        timeout=min(float(configured_timeout), float(timeout)) if timeout else float(configured_timeout),
        credential_header=(credential.header_name if credential else None) or 'Authorization')


def run_job(db, job_id, token):
    """Read a leased chunk, invoke the provider outside a transaction, then recheck."""
    from app.knowledge.providers import embed
    job = db.get(KnowledgeIndexJob, job_id)
    if not job or job.status != 'RUNNING' or job.lease_token != token:
        return False
    generation = db.get(KnowledgeIndexGeneration, job.generation_id)
    chunk = db.get(KnowledgeChunk, job.chunk_id)
    version = db.get(KnowledgeVersion, chunk.version_id) if chunk else None
    doc = db.get(KnowledgeDocument, version.document_id) if version else None
    base = db.get(KnowledgeBase, doc.base_id) if doc else None
    try:
        if (not generation or not chunk or not version or version.status != 'READY' or not doc or not base
                or not doc.enabled or not base.enabled or doc.project_id != generation.project_id
                or generation.state not in {'ACTIVE', 'BUILDING', 'STANDBY'}):
            raise ValueError('source unavailable')
        connection = retrieval_connection(db, generation.project_id, generation.embedding_revision_id, 'EMBEDDING')
        source_text, dimension, mode = chunk.text, generation.dimension, generation.document_input_type
        project_id, revision_id = generation.project_id, generation.embedding_revision_id
        db.commit()
        vector = embed(connection, [source_text], dimension, input_type=mode)[0]
        db.expire_all()
        retrieval_connection(db, project_id, revision_id, 'EMBEDDING')
        if not finish_job(db, job_id, token, vector):
            db.rollback()
            fail_job(db, job_id, token)
            return False
        return True
    except Exception:
        db.rollback()
        fail_job(db, job_id, token)
        return False
