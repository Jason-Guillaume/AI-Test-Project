"""Real SQLite persistence; access is substituted only to model project membership."""
import math
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.database.base import Base
import app.core.models
from app.agents.models import AgentDefinition
from app.knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeVersion, KnowledgeChunk, KnowledgeBinding
from app.knowledge import service


def test_bm25_uses_document_frequency_and_declared_parameters():
    """BM25 uses k1=1.2/b=0.75 and ranks repeated terms deterministically."""
    row = SimpleNamespace(id=1, text="api api")
    scores = service._bm25_scores([row], "api")
    expected = math.log(1 + (1 - 1 + 0.5) / (1 + 0.5)) * (2.2 * 2 / 3.2)
    assert scores[1] == pytest.approx(expected)
    assert service._BM25_K1 == 1.2
    assert service._BM25_B == 0.75
    assert service._TOKENIZER_VERSION == "unicode-bigram-v1"

@pytest.fixture
def db(monkeypatch):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.tables.values() if t.name in {
        'user', 'organization', 'organization_member', 'project', 'project_member', 'model_configuration',
        'agent_definition', 'knowledge_base', 'knowledge_document', 'knowledge_document_version',
        'knowledge_chunk', 'project_agent_knowledge_binding'}])
    def access(db, project_id, actor, write=False):
        if project_id not in actor:
            raise HTTPException(404)
    monkeypatch.setattr(service, 'access', access)
    with Session(engine, expire_on_commit=False) as session:
        for i in (1, 2):
            session.add(KnowledgeBase(id=i, project_id=i, name='规范'))
        session.commit()
        yield session


def prepared(db):
    for project, text in [(1, '商城订单规范'), (2, '支付安全规范')]:
        version = service.upload(db, project, project, {project}, '规范.md', text.encode())
        service.parse_version(db, version.id)
        db.add(KnowledgeBinding(project_id=project, agent_id=1, scopes=[{'base_id': project, 'mode': 'ALL'}]))
    db.commit()


def test_project_isolation_and_unbound_agent(db):
    prepared(db)
    a = service.freeze(db, 1, 1, {1})
    assert '商城' in service.search(db, a, {1}, '规范')[0]['text']
    # 同一项目的另一个 Agent 读到同一批资料，不需要单独绑定。
    assert service.freeze(db, 1, 2, {1})['version_ids'] == a['version_ids']
    b = service.freeze(db, 2, 1, {2})
    assert '支付' in service.search(db, b, {2}, '规范')[0]['text']
    assert set(a['version_ids']).isdisjoint(b['version_ids'])
    with pytest.raises(HTTPException):
        service.search(db, a, {2}, '')


def test_pinned_version_failed_update_and_revocation(db):
    prepared(db)
    snapshot = service.freeze(db, 1, 1, {1})
    original = db.get(KnowledgeVersion, snapshot['version_ids'][0])
    doc = db.get(KnowledgeDocument, original.document_id)
    failed = service.upload(db, 1, 1, {1}, '规范.txt', b'\xff', document_id=doc.id)
    service.parse_version(db, failed.id)
    assert failed.status == 'FAILED' and doc.current_version_id == original.id
    newer = service.upload(db, 1, 1, {1}, '规范.txt', '新版本'.encode(), document_id=doc.id)
    service.parse_version(db, newer.id)
    assert service.search(db, snapshot, {1}, '')[0]['version_id'] == original.id
    doc.enabled = False; db.commit()
    with pytest.raises(HTTPException):
        service.search(db, snapshot, {1}, '')


def test_explicit_agent_scope_filters_project_knowledge(db):
    prepared(db)
    binding = db.query(KnowledgeBinding).filter_by(project_id=1).one()
    doc = db.query(KnowledgeDocument).filter_by(project_id=1).one()
    other = service.upload(db, 1, 1, {1}, 'extra.md', '单独授权的内容'.encode())
    service.parse_version(db, other.id)
    binding.access_mode = 'AGENT_SCOPED'
    binding.scopes = [{'base_id': 1, 'mode': 'DOCUMENTS', 'document_ids': [doc.id]}]
    binding.required = True
    db.commit()
    snapshot = service.freeze(db, 1, 1, {1})
    assert snapshot['version_ids'] == [doc.current_version_id]


def test_text_docx_and_scanned_pdf():
    import io
    import zipfile
    from pypdf import PdfWriter
    assert service.extract('a.md', '需求说明'.encode())[0][1] == '需求说明'
    file = io.BytesIO()
    with zipfile.ZipFile(file, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>合同规范</w:t></w:r></w:p></w:body></w:document>')
    assert '合同规范' in service.extract('a.docx', file.getvalue())[0][1]
    file = io.BytesIO()
    pdf = PdfWriter(); pdf.add_blank_page(width=100, height=100); pdf.write(file)
    with pytest.raises(ValueError):
        service.extract('scan.pdf', file.getvalue())


def test_agents_share_project_knowledge(db):
    prepared(db)
    first_doc = db.query(KnowledgeDocument).filter_by(project_id=1).one()
    extra = service.upload(db, 1, 1, {1}, '安全.md', '安全规则禁止明文密码'.encode())
    service.parse_version(db, extra.id)
    binding = db.query(KnowledgeBinding).filter_by(project_id=1, agent_id=1).one()
    binding.scopes = [{'base_id': 1, 'mode': 'DOCUMENTS', 'document_ids': [first_doc.id]}]
    binding.access_mode = 'AGENT_SCOPED'
    db.add(KnowledgeBinding(project_id=1, agent_id=2, access_mode='AGENT_SCOPED',
        scopes=[{'base_id': 1, 'mode': 'DOCUMENTS', 'document_ids': [extra.document_id]}]))
    db.commit()
    first = service.search(db, service.freeze(db, 1, 1, {1}), {1}, '')
    second = service.search(db, service.freeze(db, 1, 2, {1}), {1}, '')
    assert {s['document_id'] for s in first} == {first_doc.id}
    assert {s['document_id'] for s in second} == {extra.document_id}


def test_bm25_top_k_and_relevance_threshold(db):
    """BM25 排序返回可追溯版本，并遵守 Top-K 与最低分阈值。"""
    prepared(db)
    snapshot = service.freeze(db, 1, 1, {1})
    version = db.get(KnowledgeVersion, snapshot['version_ids'][0])
    db.add(KnowledgeChunk(version_id=version.id, position=1, page=None, text='支付流程的支付步骤'))
    db.commit()
    results = service.search(db, snapshot, {1}, '支付', limit=1)
    assert len(results) == 1
    assert results[0]['score_type'] == 'BM25'
    assert results[0]['score'] > 0
    assert results[0]['version'] == version.version
    assert service.search(db, snapshot, {1}, '支付', minimum_score=100.0) == []


def test_source_requires_exactly_authorized_version(db):
    """同一文档的新版本可见时，不能通过旧 Chunk ID 绕过当前版本范围。"""
    prepared(db)
    old_version = db.query(KnowledgeVersion).join(KnowledgeDocument).filter(
        KnowledgeDocument.project_id == 1,
    ).one()
    old_chunk = db.query(KnowledgeChunk).filter_by(version_id=old_version.id).one()
    assert service.source(db, 1, 1, {1}, old_chunk.id).id == old_chunk.id

    service.upload(db, 1, 1, {1}, '规范新版本.md', '更新后的商城规范'.encode(), document_id=old_version.document_id)
    new_version = db.query(KnowledgeVersion).filter_by(document_id=old_version.document_id).order_by(
        KnowledgeVersion.version.desc(),
    ).first()
    service.parse_version(db, new_version.id)
    with pytest.raises(HTTPException):
        service.source(db, 1, 1, {1}, old_chunk.id)
