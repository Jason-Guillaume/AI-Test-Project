"""Generation bookkeeping against a real database; provider calls are not needed."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.core.models
import app.features.asr_evaluation.models
import app.platform.model_configuration.models
import app.orchestration.tasks.models
import app.agents.models
from app.core.database.base import Base
from app.core.models.identity import User
from app.core.models.project import Project
from app.knowledge.indexing import activate_generation, backfill_generation, enqueue_version
from app.knowledge.models import (KnowledgeBase, KnowledgeChunk, KnowledgeDocument,
    KnowledgeIndexGeneration, KnowledgeIndexJob, KnowledgeRetrievalConfig, KnowledgeVector, KnowledgeVersion)
from app.platform.model_configuration.models import ModelResource, ModelRevision


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    names = {'user', 'organization', 'project', 'model_configuration', 'model_resource', 'model_revision',
             'knowledge_base', 'knowledge_document', 'knowledge_document_version', 'knowledge_chunk',
             'knowledge_index_generation', 'knowledge_index_job', 'knowledge_vector', 'knowledge_retrieval_config',
             'project_agent_knowledge_binding', 'runtime_event_fact'}
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values() if t.name in names])
    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id=1, username='owner'))
        session.add(Project(id=1, name='one', owner_id=1))
        session.add(ModelResource(id=1, resource_key='embedding', category='EMBEDDING', visibility='PLATFORM', display_name='embed', status='ACTIVE', current_revision_id=1))
        session.add_all([ModelRevision(id=i, resource_id=1, version=i, provider='test', adapter_key='openai-compatible-embeddings', model_name=str(i), enabled=True) for i in (1, 2)])
        session.add(KnowledgeBase(id=1, project_id=1, name='base'))
        session.add(KnowledgeDocument(id=1, project_id=1, base_id=1, name='doc', category='', current_version_id=1))
        session.add(KnowledgeVersion(id=1, document_id=1, version=1, filename='doc.txt', digest='x', content=b'x', status='READY'))
        session.add(KnowledgeChunk(id=1, version_id=1, position=0, text='text'))
        session.add_all([KnowledgeIndexGeneration(id=i, project_id=1, embedding_revision_id=i, dimension=2,
            distance='cosine', encoding_version=f'v{i}', state='BUILDING') for i in (1, 2)])
        session.commit()
        yield session
    engine.dispose()


def test_generation_backfill_and_atomic_switch(db):
    assert backfill_generation(db, 1) == 1
    assert backfill_generation(db, 1) == 0
    with pytest.raises(HTTPException):
        activate_generation(db, 1, 1)
    assert db.get(KnowledgeRetrievalConfig, 1) is None
    db.add(KnowledgeVector(generation_id=1, chunk_id=1, embedding=[1, 0]))
    db.flush()
    activate_generation(db, 1, 1)
    db.flush()
    # Same dimension does not permit the second model to use the first vector.
    with pytest.raises(HTTPException):
        activate_generation(db, 1, 2)
    assert db.get(KnowledgeRetrievalConfig, 1).active_generation_id == 1
    db.add(KnowledgeVector(generation_id=2, chunk_id=1, embedding=[0, 1]))
    db.flush()
    activate_generation(db, 1, 2)
    assert db.get(KnowledgeIndexGeneration, 1).state == 'STANDBY'
    assert db.get(KnowledgeRetrievalConfig, 1).active_generation_id == 2
    activate_generation(db, 1, 1)
    assert db.get(KnowledgeRetrievalConfig, 1).active_generation_id == 1


def test_new_chunks_are_enqueued_for_building_and_rollback_generations(db):
    db.get(KnowledgeIndexGeneration, 1).state = 'STANDBY'
    enqueue_version(db, 1, 1)
    db.flush()
    enqueue_version(db, 1, 1)
    db.flush()
    assert {(job.generation_id, job.chunk_id) for job in db.query(KnowledgeIndexJob).all()} == {(1, 1), (2, 1)}


def test_lease_expiry_recovery_and_stale_worker_cannot_write(db):
    from datetime import datetime, timedelta, timezone
    from app.knowledge.indexing import claim_job, finish_job
    backfill_generation(db, 1)
    db.commit()
    start = datetime.now(timezone.utc)
    job_id, old_token = claim_job(db, now=start, lease_seconds=5)
    reclaimed_id, new_token = claim_job(db, now=start + timedelta(seconds=6), lease_seconds=5)
    assert reclaimed_id == job_id and new_token != old_token
    assert not finish_job(db, job_id, old_token, [1, 0], now=start + timedelta(seconds=7))
    assert finish_job(db, job_id, new_token, [0, 1], now=start + timedelta(seconds=7))
    assert not finish_job(db, job_id, new_token, [1, 0], now=start + timedelta(seconds=8))
    assert db.query(KnowledgeVector).one().embedding == [0, 1]


def test_worker_retries_without_duplicate_vectors(db, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.knowledge import indexing, providers
    backfill_generation(db, 1)
    db.commit()
    monkeypatch.setattr(indexing, 'retrieval_connection', lambda *a, **kw: object())
    calls = []
    def encode(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError()
        return [[0.1, 0.2]]
    monkeypatch.setattr(providers, 'embed', encode)
    assert not indexing.run_job(db, *indexing.claim_job(db))
    assert db.query(KnowledgeIndexJob).one().status == 'QUEUED'
    assert indexing.claim_job(db) is None
    assert indexing.run_job(db, *indexing.claim_job(db, now=datetime.now(timezone.utc) + timedelta(seconds=6)))
    assert db.query(KnowledgeIndexJob).one().status == 'DONE'
    assert db.query(KnowledgeVector).count() == 1


def test_worker_advances_vector_jobs_while_parse_queue_is_still_nonempty(db, monkeypatch):
    from app.knowledge import indexing, providers, worker

    assert backfill_generation(db, 1) == 1
    db.add_all(KnowledgeVersion(document_id=1, version=version, filename='doc.txt', digest='x',
        content=b'new text', status='QUEUED') for version in (2, 3, 4))
    db.commit()
    monkeypatch.setattr(worker, 'SessionLocal', lambda: Session(db.bind))
    monkeypatch.setattr(indexing, 'retrieval_connection', lambda *args, **kwargs: object())
    monkeypatch.setattr(providers, 'embed', lambda *args, **kwargs: [[1, 0]])

    class TwoPolls:
        polls = 0

        def is_set(self):
            self.polls += 1
            return self.polls > 2

        def wait(self, timeout):
            pytest.fail('both queues have work')

    worker.run(TwoPolls())
    assert db.query(KnowledgeVersion).filter_by(status='QUEUED').count() == 2
    assert db.query(KnowledgeVector).filter_by(generation_id=1, chunk_id=1).count() == 1


def test_queue_ages_are_scoped_and_legacy_ages_are_unknown(db):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import null
    from app.knowledge.indexing import queue_status

    now = datetime.now(timezone.utc)
    db.add_all([
        KnowledgeVersion(document_id=1, version=2, filename='doc.txt', digest='x', content=b'x',
                         status='QUEUED', queued_at=now - timedelta(seconds=42)),
        KnowledgeIndexJob(generation_id=1, chunk_id=1, queued_at=now - timedelta(seconds=17)),
    ])
    db.commit()
    assert queue_status(db, 1, now=now) == {
        'parse': {'queued_count': 1, 'unknown_age_count': 0, 'oldest_wait_seconds': 42},
        'vector': {'queued_count': 1, 'unknown_age_count': 0, 'oldest_wait_seconds': 17,
                   'expired_lease_count': 0, 'oldest_expired_seconds': None},
    }
    assert queue_status(db, 2, now=now)['vector']['queued_count'] == 0
    job = db.query(KnowledgeIndexJob).filter_by(generation_id=1).one()
    job.status, job.lease_until = 'RUNNING', now - timedelta(seconds=31)
    db.commit()
    vector = queue_status(db, 1, now=now)['vector']
    assert (vector['queued_count'], vector['expired_lease_count'], vector['oldest_expired_seconds']) == (0, 1, 31)
    db.add(KnowledgeVersion(document_id=1, version=3, filename='old.txt', digest='x', content=b'x',
        status='QUEUED', queued_at=null()))
    db.commit()
    assert queue_status(db, 1, now=now)['parse'] == {
        'queued_count': 2, 'unknown_age_count': 1, 'oldest_wait_seconds': None,
    }


def test_public_search_uses_authorized_vector_candidates_and_rerank(db, monkeypatch):
    from app.knowledge import hybrid, service
    db.add(KnowledgeChunk(id=2, version_id=1, position=1, text='semantic answer'))
    db.add(KnowledgeVector(generation_id=1, chunk_id=1, embedding=[0, 1]))
    db.add(KnowledgeVector(generation_id=1, chunk_id=2, embedding=[1, 0]))
    db.add(KnowledgeRetrievalConfig(project_id=1, enabled=True, active_generation_id=1,
        rerank_revision_id=2, bm25_candidates=50, vector_candidates=50, rerank_window=30, timeout_seconds=10))
    db.get(KnowledgeIndexGeneration, 1).state = 'ACTIVE'
    db.commit()
    monkeypatch.setattr(service, 'access', lambda *args, **kwargs: None)
    monkeypatch.setattr(hybrid, 'retrieval_connection', lambda *args, **kwargs: object())
    monkeypatch.setattr(hybrid, 'embed', lambda *args, **kwargs: [[1, 0]])
    received = []
    def fake_rerank(connection, query, texts):
        received.extend(texts)
        return [(i, 1.0 - i / 10) for i in range(len(texts))]
    monkeypatch.setattr(hybrid, 'rerank', fake_rerank)
    snapshot = service.freeze(db, 1, 0, object())
    rows, metadata = service.search(db, snapshot, object(), 'query without overlap', return_metadata=True)
    assert rows[0]['chunk_id'] == 2
    assert rows[0]['score_type'] == 'RERANK'
    assert metadata['strategy'] == 'HYBRID_RRF'
    assert 'semantic answer' in received


def test_remote_revocation_prevents_rerank_and_return(db, monkeypatch):
    from app.knowledge import hybrid, service
    db.add(KnowledgeVector(generation_id=1, chunk_id=1, embedding=[1, 0]))
    db.add(KnowledgeRetrievalConfig(project_id=1, enabled=True, active_generation_id=1,
        rerank_revision_id=2, bm25_candidates=50, vector_candidates=50, rerank_window=30, timeout_seconds=10))
    db.get(KnowledgeIndexGeneration, 1).state = 'ACTIVE'
    db.commit()
    monkeypatch.setattr(service, 'access', lambda *a, **kw: None)
    monkeypatch.setattr(hybrid, 'retrieval_connection', lambda *a, **kw: object())
    def revoke(*args, **kwargs):
        db.get(KnowledgeDocument, 1).enabled = False
        db.commit()
        return [[1, 0]]
    monkeypatch.setattr(hybrid, 'embed', revoke)
    monkeypatch.setattr(hybrid, 'rerank', lambda *a, **kw: pytest.fail('unauthorized rerank'))
    snapshot = service.freeze(db, 1, 0, object())
    with pytest.raises(HTTPException):
        service.search(db, snapshot, object(), 'query')


def test_real_search_degrades_and_permission_only_avoids_models(db, monkeypatch):
    from app.knowledge import hybrid, service
    db.add(KnowledgeVector(generation_id=1, chunk_id=1, embedding=[1, 0]))
    db.add(KnowledgeRetrievalConfig(project_id=1, enabled=True, active_generation_id=1,
        rerank_revision_id=2, bm25_candidates=50, vector_candidates=50, rerank_window=30, timeout_seconds=10))
    db.get(KnowledgeIndexGeneration, 1).state = 'ACTIVE'
    db.commit()
    monkeypatch.setattr(service, 'access', lambda *a, **kw: None)
    monkeypatch.setattr(hybrid, 'retrieval_connection', lambda *a, **kw: object())
    calls = []
    def broken(*args, **kwargs):
        calls.append(1)
        raise TimeoutError()
    monkeypatch.setattr(hybrid, 'embed', broken)
    snapshot = service.freeze(db, 1, 0, object())
    assert service.search(db, snapshot, object(), '', limit=0) == []
    assert service.search(db, snapshot, object(), '') and not calls
    rows, metadata = service.search(db, snapshot, object(), 'text', return_metadata=True)
    assert rows[0]['score_type'] == 'BM25' and metadata['vector_status'] == 'FAILED'
    monkeypatch.setattr(hybrid, 'embed', lambda *a, **kw: [[1, 0]])
    monkeypatch.setattr(hybrid, 'rerank', broken)
    rows, metadata = service.search(db, snapshot, object(), 'text', return_metadata=True)
    assert rows[0]['score_type'] == 'RRF' and metadata['reranker_status'] == 'FAILED'


def test_vector_path_excludes_other_project_even_with_bad_vector_row(db, monkeypatch):
    from app.knowledge import hybrid, service
    db.add(Project(id=2, name='other', owner_id=1))
    db.add(KnowledgeBase(id=2, project_id=2, name='other'))
    db.add(KnowledgeDocument(id=2, project_id=2, base_id=2, name='secret', category='', current_version_id=2))
    db.add(KnowledgeVersion(id=2, document_id=2, version=1, filename='secret.txt', digest='y', content=b'y', status='READY'))
    db.add(KnowledgeChunk(id=2, version_id=2, position=0, text='private other project'))
    db.add_all([KnowledgeVector(generation_id=1, chunk_id=1, embedding=[0, 1]),
                KnowledgeVector(generation_id=1, chunk_id=2, embedding=[1, 0])])
    db.add(KnowledgeRetrievalConfig(project_id=1, enabled=True, active_generation_id=1,
        rerank_revision_id=2, bm25_candidates=50, vector_candidates=50, rerank_window=30, timeout_seconds=10))
    db.get(KnowledgeIndexGeneration, 1).state = 'ACTIVE'
    db.commit()
    monkeypatch.setattr(service, 'access', lambda *a, **kw: None)
    monkeypatch.setattr(hybrid, 'retrieval_connection', lambda *a, **kw: object())
    monkeypatch.setattr(hybrid, 'embed', lambda *a, **kw: [[1, 0]])
    seen = []
    def rank(connection, query, texts):
        seen.extend(texts)
        return [(i, 1.0) for i in range(len(texts))]
    monkeypatch.setattr(hybrid, 'rerank', rank)
    snapshot = service.freeze(db, 1, 0, object())
    rows = service.search(db, snapshot, object(), 'missing')
    assert {row['chunk_id'] for row in rows} == {1}
    assert seen == ['text']


def test_synthetic_public_search_comparison(db, monkeypatch):
    """Same labelled questions, real public search, deterministic fake retrieval endpoints."""
    import statistics
    import time
    from app.knowledge import hybrid, service
    from app.knowledge.retrieval import mean_reciprocal_rank, recall_at_k
    corpus = [
        (1, 'E42 invalid request', [1, 0]),
        (2, '原路退还款项', [0, 1]),
        (3, '账户身份验证', [-1, 0]),
    ] + [(i, f'无关记录 {i}', [-1, -0.1 * i]) for i in range(4, 16)]
    db.get(KnowledgeChunk, 1).text = corpus[0][1]
    for ident, text, vector in corpus:
        if ident != 1:
            db.add(KnowledgeChunk(id=ident, version_id=1, position=ident, text=text))
        db.add(KnowledgeVector(generation_id=1, chunk_id=ident, embedding=vector))
    config = KnowledgeRetrievalConfig(project_id=1, enabled=False, active_generation_id=1,
        rerank_revision_id=None, bm25_candidates=50, vector_candidates=50, rerank_window=30, timeout_seconds=10)
    db.add(config)
    db.get(KnowledgeIndexGeneration, 1).state = 'ACTIVE'
    db.commit()
    monkeypatch.setattr(service, 'access', lambda *a, **kw: None)
    monkeypatch.setattr(hybrid, 'retrieval_connection', lambda *a, **kw: object())
    vectors = {'E42': [1, 0], '退款渠道': [0, 1], '登录认证': [-1, 0], '未知问题': [-0.5, -1]}
    labels = {'E42': 1, '退款渠道': 2, '登录认证': 3}
    monkeypatch.setattr(hybrid, 'embed', lambda connection, texts, *a, **kw: [vectors[texts[0]]])
    def rank(connection, query, texts):
        target = dict((ident, text) for ident, text, _ in corpus).get(labels.get(query))
        order = sorted(range(len(texts)), key=lambda i: (texts[i] != target, i))
        return [(i, 1.0 if texts[i] == target else 0.0) for i in order]
    monkeypatch.setattr(hybrid, 'rerank', rank)
    snapshot = service.freeze(db, 1, 0, object())
    report = {}
    for name, enabled, reranker in [('BM25', False, None), ('HYBRID', True, None), ('RERANK', True, 2)]:
        config.enabled, config.rerank_revision_id = enabled, reranker
        db.commit()
        service.search(db, snapshot, object(), 'E42', limit=30)  # exclude import/cache warmup
        rankings, elapsed = [], []
        for query in vectors:
            start = time.perf_counter()
            rows = service.search(db, snapshot, object(), query, limit=30)
            elapsed.append((time.perf_counter() - start) * 1000)
            rankings.append([row['chunk_id'] for row in rows])
        relevant = [{labels[q]} for q in list(vectors)[:3]]
        report[name] = {
            'recall30': statistics.mean(recall_at_k(r, expected, 30) for r, expected in zip(rankings, relevant)),
            'hit8': statistics.mean(bool(set(r[:8]) & expected) for r, expected in zip(rankings, relevant)),
            'mrr': mean_reciprocal_rank(rankings[:3], relevant),
            'no_answer_hits': len(rankings[3][:8]),
            'p95_ms': sorted(elapsed)[-1],
        }
    print('SYNTHETIC_RAG_REPORT', report)
    assert report['BM25']['recall30'] == pytest.approx(1 / 3)
    assert report['HYBRID']['recall30'] == report['RERANK']['recall30'] == 1
    config.enabled = False
    db.commit()
    title_only = service.search(db, snapshot, object(), '统一测试', limit=8)
    title_with_goal = service.search(db, snapshot, object(), '统一测试 E42', limit=8)
    print('SYNTHETIC_QUERY_REWRITE', {'title_hit8': int(any(r['chunk_id'] == 1 for r in title_only)),
                                      'title_goal_hit8': int(any(r['chunk_id'] == 1 for r in title_with_goal))})
    assert not title_only and title_with_goal[0]['chunk_id'] == 1


def test_parsing_and_enqueue_commit_together_for_all_generations(db):
    from app.knowledge.service import parse_version
    db.add(KnowledgeVersion(id=2, document_id=1, version=2, filename='next.txt', digest='z',
                            content='新的版本内容'.encode(), status='QUEUED'))
    db.commit()
    parse_version(db, 2)
    assert db.get(KnowledgeDocument, 1).current_version_id == 2
    chunk = db.query(KnowledgeChunk).filter_by(version_id=2).one()
    assert {job.generation_id for job in db.query(KnowledgeIndexJob).filter_by(chunk_id=chunk.id)} == {1, 2}


def test_different_dimension_generation_can_switch_and_rollback(db):
    db.get(KnowledgeIndexGeneration, 2).dimension = 3
    db.add_all([KnowledgeVector(generation_id=1, chunk_id=1, embedding=[1, 0]),
                KnowledgeVector(generation_id=2, chunk_id=1, embedding=[0, 1, 0])])
    db.flush()
    activate_generation(db, 1, 1)
    activate_generation(db, 1, 2)
    assert db.get(KnowledgeRetrievalConfig, 1).active_generation_id == 2
    activate_generation(db, 1, 1)
    assert db.get(KnowledgeRetrievalConfig, 1).active_generation_id == 1


def test_rerank_config_change_does_not_queue_or_encode_documents(db, monkeypatch):
    from app.knowledge import router
    db.add(KnowledgeVector(generation_id=1, chunk_id=1, embedding=[1, 0]))
    db.flush()
    activate_generation(db, 1, 1)
    db.commit()
    monkeypatch.setattr(router.service, 'access', lambda *a, **kw: None)
    monkeypatch.setattr(router, '_available_revision', lambda *a, **kw: object())
    body = router.RetrievalConfigInput(enabled=True, rerank_revision_id=2)
    router.put_retrieval_config(1, body, db, object())
    assert db.get(KnowledgeRetrievalConfig, 1).rerank_revision_id == 2
    assert db.query(KnowledgeIndexJob).count() == 0
    assert db.query(KnowledgeVector).count() == 1


def test_retiring_inactive_generation_stops_work_and_blocks_retry(db, monkeypatch):
    from app.knowledge import router
    from app.knowledge.indexing import claim_job, finish_job
    monkeypatch.setattr(router.service, 'access', lambda *args, **kwargs: None)
    db.add(KnowledgeVector(generation_id=1, chunk_id=1, embedding=[1, 0]))
    db.flush()
    activate_generation(db, 1, 1)
    db.get(KnowledgeIndexGeneration, 2).state = 'STANDBY'
    backfill_generation(db, 2)
    db.commit()
    job_id, token = claim_job(db)
    with pytest.raises(HTTPException):
        router.index_generation_command(1, 1, router.Command(action='retire'), db, object())
    db.rollback()
    router.index_generation_command(1, 2, router.Command(action='retire'), db, object())
    assert db.get(KnowledgeIndexGeneration, 2).state == 'RETIRED'
    assert db.get(KnowledgeIndexJob, job_id).status == 'FAILED'
    assert not finish_job(db, job_id, token, [1, 0])
    with pytest.raises(HTTPException):
        router.index_generation_command(1, 2, router.Command(action='retry'), db, object())
