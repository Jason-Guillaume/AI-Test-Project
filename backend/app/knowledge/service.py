"""All source access is reauthorized; snapshots contain IDs, never cached source text."""
import hashlib
import io
import math
import re
import time
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
from sqlalchemy import delete
from app.core.http.errors import bad_request, forbidden, not_found
from app.core.security.roles import PROJECT_ROLE_EDITOR, has_project_role, project_role_for
from app.platform.projects.services.access_service import get_project_or_404
from app.knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeVersion, KnowledgeChunk, KnowledgeBinding

_BM25_K1 = 1.2
_BM25_B = 0.75
_TOKENIZER_VERSION = "unicode-bigram-v1"


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
    # 旧客户端未传访问模式时保留已有策略，避免更新 scopes 意外扩大知识范围。
    if body.get('access_mode') is not None:
        row.access_mode = body['access_mode']
    db.add(row)
    db.commit()
    return row


def freeze(db, project_id, agent_id, actor):
    """冻结当前 Agent 获准读取的项目知识版本；未配置范围的旧 Agent 保持项目默认权限。"""
    access(db, project_id, actor)
    ids = []
    binding = db.query(KnowledgeBinding).filter_by(project_id=project_id, agent_id=agent_id).first() if agent_id else None
    scopes = None
    if binding is not None and binding.access_mode == 'AGENT_SCOPED':
        scopes = list(binding.scopes or []) if binding.enabled else []
    bases = db.query(KnowledgeBase).filter_by(project_id=project_id, enabled=True).all()
    for base in bases:
        if scopes is not None and not any(scope.get('base_id') == base.id for scope in scopes):
            continue
        docs = db.query(KnowledgeDocument).filter_by(project_id=project_id, base_id=base.id, enabled=True).all()
        for doc in docs:
            if scopes is not None:
                matching = [scope for scope in scopes if scope.get('base_id') == base.id]
                if not any(
                    scope.get('mode') == 'ALL'
                    or (scope.get('mode') == 'DOCUMENTS' and doc.id in scope.get('document_ids', []))
                    or (scope.get('mode') == 'CATEGORIES' and doc.category in scope.get('categories', []))
                    for scope in matching
                ):
                    continue
            if doc.current_version_id:
                ids.append(doc.current_version_id)
    return {'project_id': project_id, 'agent_id': agent_id,
            'revision': binding.revision if binding else 0,
            'access_mode': binding.access_mode if binding else 'PROJECT_SHARED',
            'version_ids': sorted(set(ids))}


def _terms(text: str) -> list[str]:
    """按英文词和中文二元片段切分，避免中文整句只能做完全匹配。"""
    terms = []
    for token in re.findall(r'[a-zA-Z0-9_]+|[\u3400-\u9fff]+', text.lower()):
        if token[0].isascii():
            terms.append(token)
        elif len(token) == 1:
            terms.append(token)
        else:
            terms.extend(token[index:index + 2] for index in range(len(token) - 1))
    return terms


def _bm25_scores(rows, query: str) -> dict[int, float]:
    """在授权候选片段内计算 BM25 分数，分数是排序值而非相关性概率。"""
    query_terms = set(_terms(query))
    if not query_terms or not rows:
        return {}
    documents = {row.id: Counter(_terms(row.text)) for row in rows}
    lengths = {ident: sum(counts.values()) for ident, counts in documents.items()}
    average_length = sum(lengths.values()) / max(1, len(lengths))
    document_frequency = Counter(term for counts in documents.values() for term in counts)
    total = len(documents)
    scores = {}
    for row in rows:
        score = 0.0
        for term in query_terms:
            frequency = documents[row.id].get(term, 0)
            if not frequency:
                continue
            inverse_frequency = math.log(1 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            denominator = frequency + _BM25_K1 * (
                1 - _BM25_B + _BM25_B * lengths[row.id] / max(1.0, average_length)
            )
            score += inverse_frequency * frequency * (_BM25_K1 + 1) / denominator
        scores[row.id] = score
    return scores


def search(db, snapshot, actor, query, limit=8, minimum_score=0.0):
    """按当前权限重验快照并执行 BM25 检索；返回来源引用与原始排序分数。"""
    retrieval_started = time.monotonic()
    current = freeze(db, snapshot['project_id'], snapshot['agent_id'], actor)
    # 修订号来自已停用的 Agent 绑定，不能再用来拒绝检索；停用文档由下面的来源校验拦截。
    allowed_documents = {db.get(KnowledgeVersion, i).document_id for i in current['version_ids']}
    versions = [db.get(KnowledgeVersion, i) for i in snapshot['version_ids']]
    if any(v is None or v.status != 'READY' or v.document_id not in allowed_documents for v in versions):
        raise forbidden('知识来源已停用或权限已撤销')
    if limit == 0:
        return []
    rows = db.query(KnowledgeChunk).filter(KnowledgeChunk.version_id.in_(snapshot['version_ids'])).all() if versions else []
    scores = _bm25_scores(rows, query)
    scored = sorted(rows, key=lambda c: (-scores.get(c.id, 0.0), c.version_id, c.position))
    # 空查询保留旧版来源浏览行为；有查询词但无匹配时不再返回无关片段。
    if _terms(query):
        scored = [row for row in scored if scores.get(row.id, 0.0) >= minimum_score and scores.get(row.id, 0.0) > 0]
    selected = scored[:max(0, min(int(limit), 50))]
    versions_by_id = {version.id: version for version in versions}
    documents_by_id = {doc.id: doc for doc in db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id.in_([versions_by_id[row.version_id].document_id for row in selected])
    ).all()} if selected else {}
    from app.llm.tracing import record_runtime_span, task_trace_metadata
    runtime = task_trace_metadata.get() or {}
    if runtime:
        metadata = {
            key: runtime.get(key) for key in (
                'task_id', 'task_run_id', 'execution_root_run_id', 'trace_id', 'agent_run_id',
                'agent_id', 'agent_revision_id', 'work_item_id', 'attempt_id', 'project_id',
            ) if runtime.get(key) is not None
        } | {
            'strategy': 'BM25', 'query_sha256': hashlib.sha256(query.encode('utf-8')).hexdigest(),
            'candidate_count': len(rows), 'result_count': len(selected),
            'minimum_score': minimum_score, 'top_k': max(0, min(int(limit), 50)),
            'bm25_k1': _BM25_K1, 'bm25_b': _BM25_B, 'tokenizer_version': _TOKENIZER_VERSION,
        }
        span_id = record_runtime_span(
            name='knowledge.retrieve',
            metadata=metadata,
            output={'results': [
                {'chunk_id': row.id, 'version_id': row.version_id, 'rank': index + 1,
                 'score': round(scores.get(row.id, 0.0), 6)}
                for index, row in enumerate(selected)
            ]},
        )
        from app.orchestration.tasks.services.runtime_fact_service import record_runtime_event
        record_runtime_event(
            project_id=snapshot['project_id'],
            task_id=runtime.get('task_id'), task_run_id=runtime.get('task_run_id'),
            execution_root_run_id=runtime.get('execution_root_run_id'),
            work_item_id=runtime.get('work_item_id'), attempt_id=runtime.get('attempt_id'),
            agent_session_id=runtime.get('agent_session_id'),
            agent_instance_id=runtime.get('agent_run_id'),
            agent_definition_id=runtime.get('agent_id'),
            agent_definition_revision_id=runtime.get('agent_revision_id'),
            trace_id=runtime.get('trace_id'), span_id=span_id,
            event_type='KNOWLEDGE_RETRIEVAL', event_name='BM25', status='SUCCEEDED',
            duration_ms=int((time.monotonic() - retrieval_started) * 1000),
            event_metadata={
                'query_sha256': metadata['query_sha256'], 'strategy': 'BM25',
                'candidate_count': len(rows), 'result_count': len(selected),
                'minimum_score': minimum_score, 'top_k': metadata['top_k'],
                'bm25_k1': _BM25_K1, 'bm25_b': _BM25_B, 'tokenizer_version': _TOKENIZER_VERSION,
                'chunk_ids': [row.id for row in selected],
                'version_ids': sorted({row.version_id for row in selected}),
            },
        )
    return [{
        'chunk_id': row.id,
        'version_id': row.version_id,
        'version': versions_by_id[row.version_id].version,
        'document_id': versions_by_id[row.version_id].document_id,
        'document_name': documents_by_id[versions_by_id[row.version_id].document_id].name,
        'base_id': documents_by_id[versions_by_id[row.version_id].document_id].base_id,
        'agent_id': snapshot['agent_id'],
        'page': row.page,
        'position': row.position,
        'score': round(scores.get(row.id, 0.0), 6),
        'score_type': 'BM25',
        'text': row.text,
    } for row in selected]


def source(db, project_id, agent_id, actor, chunk_id):
    """读取当前 Agent 快照确切授权的 Chunk 版本，防止同文档旧版本越权回读。"""
    snapshot = freeze(db, project_id, agent_id, actor)
    chunk = db.get(KnowledgeChunk, chunk_id)
    version = db.get(KnowledgeVersion, chunk.version_id) if chunk else None
    if version is None or version.status != 'READY' or version.id not in snapshot['version_ids']:
        raise not_found('来源不在当前 Agent 知识范围')
    return chunk
