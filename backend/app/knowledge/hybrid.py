"""Authorized exact-vector retrieval helpers used by the shared search entry point."""
import math
import time
from types import SimpleNamespace
from sqlalchemy.orm import Session

from app.knowledge.indexing import retrieval_connection
from app.knowledge.models import KnowledgeChunk, KnowledgeIndexGeneration, KnowledgeVector
from app.knowledge.providers import embed, rerank


def vector_candidates(db, project_id, version_ids, query, settings):
    if not settings or not settings.enabled or not settings.active_generation_id:
        return None, None, 'UNCONFIGURED', 0
    # One search uses a consistent config snapshot even if an administrator
    # switches generations while the query embedding request is in flight.
    config = SimpleNamespace(**{key: getattr(settings, key) for key in (
        'active_generation_id', 'rerank_revision_id', 'vector_candidates',
        'rerank_window', 'timeout_seconds', 'fusion_min_score', 'rerank_min_score',
    )})
    # Do not commit or roll back the caller's task transaction around I/O.
    with Session(bind=db.get_bind(), expire_on_commit=False) as isolated:
        return _vector_candidates(isolated, project_id, version_ids, query, config)


def _vector_candidates(db, project_id, version_ids, query, config):
    started = time.monotonic()
    generation = db.get(KnowledgeIndexGeneration, config.active_generation_id)
    if not generation or generation.project_id != project_id or generation.state != 'ACTIVE':
        return None, config, 'UNAVAILABLE', 0
    config.embedding_revision_id = generation.embedding_revision_id
    try:
        available = db.query(KnowledgeVector.id).join(
            KnowledgeChunk, KnowledgeVector.chunk_id == KnowledgeChunk.id,
        ).filter(KnowledgeVector.generation_id == generation.id,
                 KnowledgeChunk.version_id.in_(version_ids)).first()
        if available is None:
            return None, config, 'EMPTY', int((time.monotonic() - started) * 1000)
        connection = retrieval_connection(db, project_id, generation.embedding_revision_id, 'EMBEDDING', timeout=config.timeout_seconds)
        generation_id, dimension, mode, distance = generation.id, generation.dimension, generation.query_input_type, generation.distance
        cap = config.vector_candidates
        db.commit()
        query_vector = embed(connection, [query], dimension, input_type=mode)[0]
        if distance == 'cosine' and not any(query_vector):
            raise ValueError('zero query embedding')
        db.expire_all()
        # Recheck model enablement and outbound policy after the remote call.
        retrieval_connection(db, project_id, generation.embedding_revision_id, 'EMBEDDING', timeout=config.timeout_seconds)
        rows = db.query(KnowledgeVector, KnowledgeChunk).join(
            KnowledgeChunk, KnowledgeVector.chunk_id == KnowledgeChunk.id,
        ).filter(KnowledgeVector.generation_id == generation_id, KnowledgeChunk.version_id.in_(version_ids))
        if db.bind.dialect.name == 'postgresql':
            vector_column = KnowledgeVector.embedding
            metric = {'cosine': vector_column.cosine_distance, 'l2': vector_column.l2_distance,
                      'inner_product': vector_column.max_inner_product}[distance]
            ids = [row.chunk_id for row in rows.order_by(metric(query_vector), KnowledgeChunk.id).limit(cap).with_entities(KnowledgeVector.chunk_id).all()]
        else:
            def score(vector):
                dot = sum(a * b for a, b in zip(vector, query_vector))
                if distance == 'inner_product':
                    return -dot
                if distance == 'l2':
                    return sum((a - b) ** 2 for a, b in zip(vector, query_vector))
                norm = math.sqrt(sum(a*a for a in vector) * sum(b*b for b in query_vector))
                return 1 - dot / norm if norm else float('inf')
            matches = [(score(vector.embedding), chunk.id) for vector, chunk in rows.all()
                       if len(vector.embedding) == dimension]
            ids = [ident for _, ident in sorted(matches)[:cap]]
        return ids, config, 'ACTIVE' if ids else 'EMPTY', int((time.monotonic() - started) * 1000)
    except Exception:
        db.rollback()
        return None, config, 'FAILED', int((time.monotonic() - started) * 1000)


def rerank_candidates(db, project_id, revision_id, timeout, query, rows):
    texts = [row.text for row in rows]
    with Session(bind=db.get_bind(), expire_on_commit=False) as isolated:
        return _rerank_candidates(isolated, project_id, revision_id, timeout, query, texts)


def _rerank_candidates(db, project_id, revision_id, timeout, query, texts):
    started = time.monotonic()
    try:
        connection = retrieval_connection(db, project_id, revision_id, 'RERANK', timeout=timeout)
        db.commit()
        result = rerank(connection, query, texts)
        db.expire_all()
        retrieval_connection(db, project_id, revision_id, 'RERANK', timeout=timeout)
        return result, 'ACTIVE', int((time.monotonic() - started) * 1000)
    except Exception:
        db.rollback()
        return None, 'FAILED', int((time.monotonic() - started) * 1000)
