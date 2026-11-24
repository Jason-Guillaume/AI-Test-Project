"""pgvector integration against Alembic-created PostgreSQL tables."""
import hashlib

from app.core.models.identity import User
from app.knowledge import hybrid, service
from app.knowledge.models import (KnowledgeBase, KnowledgeChunk, KnowledgeDocument,
    KnowledgeIndexGeneration, KnowledgeRetrievalConfig, KnowledgeVector, KnowledgeVersion)
from app.platform.model_configuration.models import ModelResource, ModelRevision
from tests.conftest import unique


def test_pgvector_generations_and_authorized_search(api, admin, db, monkeypatch):
    project_ids = []
    for _ in range(2):
        response = api.post('/projects', username=admin, json={'name': unique('rag-pg')})
        assert response.status_code == 201
        project_ids.append(response.json()['id'])
    actor = db.query(User).filter_by(username=admin).one()
    resource = ModelResource(resource_key=unique('rag-embedding'), category='EMBEDDING', visibility='PLATFORM',
                             display_name='test', status='ACTIVE')
    db.add(resource); db.flush()
    revisions = [ModelRevision(resource_id=resource.id, version=i, provider='test',
                 adapter_key='openai-compatible-embeddings', model_name=str(i), capabilities=['embedding'], enabled=True)
                 for i in (1, 2)]
    db.add_all(revisions); db.flush(); resource.current_revision_id = revisions[0].id
    chunks = []
    for project_id in project_ids:
        base = KnowledgeBase(project_id=project_id, name='test'); db.add(base); db.flush()
        doc = KnowledgeDocument(project_id=project_id, base_id=base.id, name='test'); db.add(doc); db.flush()
        version = KnowledgeVersion(document_id=doc.id, version=1, filename='doc.txt',
            digest=hashlib.sha256(b'test').hexdigest(), content=b'test', status='READY')
        db.add(version); db.flush(); doc.current_version_id = version.id
        chunk = KnowledgeChunk(version_id=version.id, position=0, text='semantic source'); db.add(chunk); db.flush()
        chunks.append(chunk)
    generations = [KnowledgeIndexGeneration(project_id=project_ids[0], embedding_revision_id=revisions[0].id,
                    dimension=2, distance='cosine', encoding_version='one', state='ACTIVE'),
                   KnowledgeIndexGeneration(project_id=project_ids[0], embedding_revision_id=revisions[1].id,
                    dimension=3, distance='cosine', encoding_version='two', state='BUILDING')]
    db.add_all(generations); db.flush()
    db.add_all([KnowledgeVector(generation_id=generations[0].id, chunk_id=chunks[0].id, embedding=[1, 0]),
                KnowledgeVector(generation_id=generations[0].id, chunk_id=chunks[1].id, embedding=[1, 0]),
                KnowledgeVector(generation_id=generations[1].id, chunk_id=chunks[0].id, embedding=[1, 0, 0])])
    db.add(KnowledgeRetrievalConfig(project_id=project_ids[0], active_generation_id=generations[0].id,
                                  enabled=True, bm25_candidates=50, vector_candidates=50,
                                  rerank_window=30, default_top_k=8, timeout_seconds=10))
    db.commit()
    monkeypatch.setattr(hybrid, 'retrieval_connection', lambda *a, **kw: object())
    monkeypatch.setattr(hybrid, 'embed', lambda *a, **kw: [[1, 0]])
    snapshot = service.freeze(db, project_ids[0], 0, actor)
    rows, metadata = service.search(db, snapshot, actor, 'unmatched words', return_metadata=True)
    assert [row['chunk_id'] for row in rows] == [chunks[0].id]
    assert metadata['strategy'] == 'HYBRID_RRF'
    assert metadata['vector_candidate_count'] == 1


def test_postgres_full_path_with_fake_model_http(api, admin, db):
    import json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from app.core.models.project import ProjectOutboundTarget
    from app.knowledge.indexing import claim_job, run_job
    from app.knowledge.models import KnowledgeIndexJob

    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.path, payload, self.headers.get('Authorization')))
            if self.path == '/embedding':
                response = {'data': [{'index': i, 'embedding': [1, 0]} for i, _ in enumerate(payload['input'])]}
            else:
                response = {'results': [{'index': i, 'relevance_score': 0.9} for i, _ in enumerate(payload['documents'])]}
            content = json.dumps(response).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(content))); self.end_headers(); self.wfile.write(content)
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        response = api.post('/projects', username=admin, json={'name': unique('rag-http')})
        assert response.status_code == 201
        project_id = response.json()['id']
        actor = db.query(User).filter_by(username=admin).one()
        db.add(ProjectOutboundTarget(project_id=project_id, scheme='http', host='127.0.0.1',
                                     port=server.server_port, enabled=True, approved_by=actor.id))
        base = KnowledgeBase(project_id=project_id, name='test'); db.add(base); db.commit()
        version = service.upload(db, project_id, base.id, actor, 'source.txt', '原路返还款项'.encode())
        service.parse_version(db, version.id)
        revisions = []
        resource_ids = []
        for category, adapter, capability, path in [
            ('EMBEDDING', 'openai-compatible-embeddings', 'embedding', 'embedding'),
            ('RERANK', 'json-rerank', 'rerank', 'rerank'),
        ]:
            response = api.post('/model-center/resources', username=admin, json={
                'category': category, 'visibility': 'PLATFORM', 'display_name': unique(category),
                'provider': 'fake', 'adapter_key': adapter, 'model_name': 'fixture',
                'endpoint': f'http://127.0.0.1:{server.server_port}/{path}',
                'credential': 'fixture-secret', 'credential_header': 'Authorization',
                'config': {'timeout_seconds': 5}, 'capabilities': [capability],
            })
            assert response.status_code == 201, response.text
            resource_ids.append(response.json()['id'])
            revisions.append(response.json()['current_revision']['id'])
        response = api.post(f'/projects/{project_id}/knowledge-index-generations', username=admin, json={
            'embedding_revision_id': revisions[0], 'dimension': 2, 'distance': 'cosine',
            'encoding_version': 'fixture-v1', 'document_input_type': 'document', 'query_input_type': 'query',
        })
        assert response.status_code == 201, response.text
        generation_id = response.json()['id']
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            db.expire_all()
            job = db.query(KnowledgeIndexJob).filter_by(generation_id=generation_id).one()
            if job.status == 'DONE':
                break
            claim = claim_job(db)
            if claim:
                run_job(db, *claim)
            else:
                time.sleep(0.1)
        db.expire_all()
        assert db.query(KnowledgeIndexJob).filter_by(generation_id=generation_id).one().status == 'DONE'
        status = api.get(f'/projects/{project_id}/knowledge-retrieval-config', username=admin)
        assert status.status_code == 200, status.text
        assert status.json()['generations'][0]['coverage'] == 1.0
        response = api.post(f'/projects/{project_id}/knowledge-index-generations/{generation_id}/commands',
                            username=admin, json={'action': 'activate'})
        assert response.status_code == 200, response.text
        response = api.put(f'/projects/{project_id}/knowledge-retrieval-config', username=admin,
                           json={'enabled': True, 'rerank_revision_id': revisions[1]})
        assert response.status_code == 200, response.text
        documents_before_rotation = sum(path == '/embedding' and payload.get('input_type') == 'document'
                                        for path, payload, _ in requests)
        response = api.post(f'/model-center/resources/{resource_ids[0]}/revisions', username=admin, json={
            'provider': 'fake', 'adapter_key': 'openai-compatible-embeddings', 'model_name': 'fixture',
            'endpoint': f'http://127.0.0.1:{server.server_port}/embedding', 'credential': 'rotated-secret',
            'credential_header': 'Authorization', 'config': {'timeout_seconds': 5}, 'capabilities': ['embedding'],
        })
        assert response.status_code == 201, response.text
        response = api.post(f'/projects/{project_id}/knowledge-search', username=admin, json={'query': '退款渠道'})
        assert response.status_code == 200, response.text
        assert response.json()['items'][0]['score_type'] == 'RERANK'
        assert any(path == '/embedding' and payload.get('input_type') == 'document' for path, payload, _ in requests)
        assert any(path == '/embedding' and payload.get('input_type') == 'query' for path, payload, _ in requests)
        assert any(path == '/rerank' and payload['documents'] == ['原路返还款项'] for path, payload, _ in requests)
        assert any(path == '/embedding' and payload.get('input_type') == 'query' and header == 'Bearer rotated-secret'
                   for path, payload, header in requests)
        assert sum(path == '/embedding' and payload.get('input_type') == 'document'
                   for path, payload, _ in requests) == documents_before_rotation
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_postgres_upload_during_generation_switch_enqueues_new_version(api, admin, db):
    import threading
    import time
    from app.core.database.session import SessionLocal
    from app.knowledge.indexing import activate_generation, lock_project
    from app.knowledge.models import KnowledgeIndexJob
    response = api.post('/projects', username=admin, json={'name': unique('rag-concurrent')})
    assert response.status_code == 201
    project_id = response.json()['id']
    actor = db.query(User).filter_by(username=admin).one()
    resource = ModelResource(resource_key=unique('rag-concurrent-model'), category='EMBEDDING', visibility='PLATFORM',
                             display_name='test', status='ACTIVE')
    db.add(resource); db.flush()
    revision = ModelRevision(resource_id=resource.id, version=1, provider='test', adapter_key='openai-compatible-embeddings',
                             model_name='fixture', capabilities=['embedding'], enabled=True)
    db.add(revision); db.flush(); resource.current_revision_id = revision.id
    base = KnowledgeBase(project_id=project_id, name='test'); db.add(base); db.commit()
    old = service.upload(db, project_id, base.id, actor, 'source.txt', b'old')
    service.parse_version(db, old.id)
    old_chunk = db.query(KnowledgeChunk).filter_by(version_id=old.id).one()
    generation = KnowledgeIndexGeneration(project_id=project_id, embedding_revision_id=revision.id, dimension=2,
                                           distance='cosine', encoding_version='fixture', state='BUILDING')
    db.add(generation); db.flush()
    db.add(KnowledgeVector(generation_id=generation.id, chunk_id=old_chunk.id, embedding=[1, 0])); db.commit()
    new = service.upload(db, project_id, base.id, actor, 'source.txt', b'new', document_id=old.document_id)
    generation_id, new_id = generation.id, new.id
    started = threading.Event()
    errors = []
    def parse():
        try:
            with SessionLocal() as other:
                started.set()
                service.parse_version(other, new_id)
        except Exception as exc:
            errors.append(type(exc).__name__)
    lock_project(db, project_id)
    thread = threading.Thread(target=parse); thread.start(); assert started.wait(2)
    time.sleep(0.2)
    activate_generation(db, project_id, generation_id)
    db.commit()
    thread.join(timeout=10)
    assert not thread.is_alive() and not errors
    db.expire_all()
    chunk = db.query(KnowledgeChunk).filter_by(version_id=new_id).one()
    assert db.query(KnowledgeIndexJob).filter_by(generation_id=generation_id, chunk_id=chunk.id).count() == 1
