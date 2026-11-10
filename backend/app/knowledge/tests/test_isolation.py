"""Real SQLite persistence; access is substituted only to model project membership."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.database.base import Base
import app.core.models
from app.agents.models import AgentDefinition
from app.knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeVersion, KnowledgeChunk, KnowledgeBinding
from app.knowledge import service

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
    b = service.freeze(db, 2, 1, {2})
    assert '支付' in service.search(db, b, {2}, '规范')[0]['text']
    assert not service.freeze(db, 1, 2, {1})['version_ids']
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


def test_agent_document_scope_and_required(db):
    prepared(db)
    binding = db.query(KnowledgeBinding).filter_by(project_id=1).one()
    binding.scopes = [{'base_id': 1, 'mode': 'DOCUMENTS', 'document_ids': []}]
    db.commit()
    assert service.freeze(db, 1, 1, {1})['version_ids'] == []
    binding.required = True; db.commit()
    with pytest.raises(HTTPException):
        service.freeze(db, 1, 1, {1})


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


def test_two_agents_with_distinct_nonempty_scopes(db):
    prepared(db)
    first_doc = db.query(KnowledgeDocument).filter_by(project_id=1).one()
    extra = service.upload(db, 1, 1, {1}, '安全.md', '安全规则禁止明文密码'.encode())
    service.parse_version(db, extra.id)
    binding = db.query(KnowledgeBinding).filter_by(project_id=1, agent_id=1).one()
    binding.scopes = [{'base_id': 1, 'mode': 'DOCUMENTS', 'document_ids': [first_doc.id]}]
    db.add(KnowledgeBinding(project_id=1, agent_id=2, scopes=[{'base_id': 1, 'mode': 'DOCUMENTS', 'document_ids': [extra.document_id]}]))
    db.commit()
    first = service.search(db, service.freeze(db, 1, 1, {1}), {1}, '')
    second = service.search(db, service.freeze(db, 1, 2, {1}), {1}, '')
    assert {s['document_id'] for s in first} == {first_doc.id}
    assert {s['document_id'] for s in second} == {extra.document_id}
