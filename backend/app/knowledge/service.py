"""All source access is reauthorized; snapshots contain IDs, never cached source text."""
import hashlib
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from sqlalchemy import delete
from app.core.http.errors import bad_request, forbidden, not_found
from app.core.security.roles import PROJECT_ROLE_EDITOR, has_project_role, project_role_for
from app.platform.projects.services.access_service import get_project_or_404
from app.knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeVersion, KnowledgeChunk, KnowledgeBinding


def access(db, project_id, actor, write=False):
    project = get_project_or_404(db, project_id, actor)
    if write and not has_project_role(project_role_for(db, project, actor), PROJECT_ROLE_EDITOR):
        raise forbidden('需要项目编辑者权限')


def owned(db, cls, ident, project_id):
    row = db.get(cls, ident, populate_existing=True)
    if row is None or row.project_id != project_id:
        raise not_found('知识资源不存在')
    return row


def upload(db, project_id, base_id, actor, filename, content, category='', document_id=None):
    access(db, project_id, actor, True)
    owned(db, KnowledgeBase, base_id, project_id)
    if Path(filename).suffix.lower() not in {'.txt', '.md', '.markdown', '.docx', '.pdf'}:
        raise bad_request('仅支持 TXT、Markdown、DOCX、文本 PDF')
    if not content or len(content) > 20 * 1024 * 1024:
        raise bad_request('文件不能为空且不得超过 20 MB')
    doc = owned(db, KnowledgeDocument, document_id, project_id) if document_id else KnowledgeDocument(
        project_id=project_id, base_id=base_id, name=Path(filename).name, category=category)
    if doc.base_id != base_id:
        raise bad_request('文档不属于所选知识库')
    db.add(doc)
    db.flush()
    latest = db.query(KnowledgeVersion.version).filter_by(document_id=doc.id).order_by(KnowledgeVersion.version.desc()).first()
    row = KnowledgeVersion(document_id=doc.id, version=(latest[0] if latest else 0)+1,
        filename=Path(filename).name, content=content, digest=hashlib.sha256(content).hexdigest())
    db.add(row)
    db.commit()
    return row


def extract(filename, content):
    suffix = Path(filename).suffix.lower()
    if suffix == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted or len(reader.pages) > 1000:
            raise ValueError('PDF 加密或页数超出限制')
        pages = [(i+1, page.extract_text() or '') for i, page in enumerate(reader.pages)]
    elif suffix == '.docx':
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 50*1024*1024:
                raise ValueError('DOCX 解压大小超限')
            root = ElementTree.fromstring(archive.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        pages = [(None, '\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p', ns)))]
    else:
        pages = [(None, content.decode('utf-8-sig'))]
    if not any(text.strip() for _, text in pages):
        raise ValueError('未提取到文本；扫描 PDF 暂不支持')
    return pages


def parse_version(db, version_id):
    # Row lock serializes retries; interrupted transactions leave QUEUED records retryable.
    row = db.query(KnowledgeVersion).filter_by(id=version_id).with_for_update().one()
    if row.status == 'READY':
        return
    row.attempts += 1
    try:
        pages = extract(row.filename, row.content)
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.version_id == row.id))
        position = 0
        for page, text in pages:
            for offset in range(0, len(text), 1000):
                db.add(KnowledgeChunk(version_id=row.id, position=position, page=page, text=text[offset:offset+1200]))
                position += 1
        row.status, row.error = 'READY', None
        doc = db.get(KnowledgeDocument, row.document_id)
        current = db.get(KnowledgeVersion, doc.current_version_id) if doc.current_version_id else None
        if current is None or current.version < row.version:
            doc.current_version_id = row.id
    except Exception as exc:
        row.status, row.error = 'FAILED', ('解析失败：' + type(exc).__name__)[:500]
    db.commit()


def save_binding(db, project_id, agent_id, actor, body):
    from app.agents.models import AgentDefinition
    access(db, project_id, actor, True)
    if db.get(AgentDefinition, agent_id) is None:
        raise not_found('Agent 不存在')
    for scope in body['scopes']:
        owned(db, KnowledgeBase, scope['base_id'], project_id)
        if scope['mode'] not in {'ALL', 'DOCUMENTS', 'CATEGORIES'}:
            raise bad_request('知识范围模式无效')
        if scope['mode'] == 'DOCUMENTS':
            for ident in scope.get('document_ids', []):
                doc = owned(db, KnowledgeDocument, ident, project_id)
                if doc.base_id != scope['base_id']:
                    raise bad_request('文档不属于所选库')
    row = db.query(KnowledgeBinding).filter_by(project_id=project_id, agent_id=agent_id).with_for_update().first()
    if body['revision'] != (row.revision if row else 0):
        raise bad_request('配置已更新，请刷新后重试')
    if row is None:
        row = KnowledgeBinding(project_id=project_id, agent_id=agent_id, revision=0)
    row.revision += 1
    row.enabled, row.required, row.scopes = body['enabled'], body['required'], body['scopes']
    db.add(row)
    db.commit()
    return row


def freeze(db, project_id, agent_id, actor):
    """冻结当前项目已启用知识的版本清单。

    知识只属于项目。agent_id 仅保留在快照里供调用方追踪，不参与筛选；
    历史的 Agent 绑定不再决定可读范围，否则换一个 Agent 就会读不到同一项目的资料。
    """
    access(db, project_id, actor)
    ids = []
    bases = db.query(KnowledgeBase).filter_by(project_id=project_id, enabled=True).all()
    for base in bases:
        docs = db.query(KnowledgeDocument).filter_by(project_id=project_id, base_id=base.id, enabled=True).all()
        for doc in docs:
            if doc.current_version_id:
                ids.append(doc.current_version_id)
    return {'project_id': project_id, 'agent_id': agent_id, 'revision': 0, 'version_ids': sorted(set(ids))}


def search(db, snapshot, actor, query, limit=8):
    current = freeze(db, snapshot['project_id'], snapshot['agent_id'], actor)
    # 修订号来自已停用的 Agent 绑定，不能再用来拒绝检索；停用文档由下面的来源校验拦截。
    allowed_documents = {db.get(KnowledgeVersion, i).document_id for i in current['version_ids']}
    versions = [db.get(KnowledgeVersion, i) for i in snapshot['version_ids']]
    if any(v is None or v.status != 'READY' or v.document_id not in allowed_documents for v in versions):
        raise forbidden('知识来源已停用或权限已撤销')
    if limit == 0:
        return []
    terms = set(re.findall(r'\w+', query.lower()))
    rows = db.query(KnowledgeChunk).filter(KnowledgeChunk.version_id.in_(snapshot['version_ids'])).all() if versions else []
    scored = sorted(rows, key=lambda c: (-sum(c.text.lower().count(t) for t in terms), c.version_id, c.position))
    return [{'chunk_id': c.id, 'version_id': c.version_id, 'document_id': db.get(KnowledgeVersion, c.version_id).document_id,
             'base_id': db.get(KnowledgeDocument, db.get(KnowledgeVersion, c.version_id).document_id).base_id,
             'agent_id': snapshot['agent_id'], 'page': c.page, 'position': c.position, 'text': c.text} for c in scored[:limit]]
