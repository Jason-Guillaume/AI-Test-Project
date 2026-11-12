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
from sqlalchemy import case, delete, func, or_
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
    row = db.query(cls).filter(cls.id == ident).first()
    if row is None or row.project_id != project_id:
        raise not_found('知识资源不存在')
    return row


def upload(db, project_id, base_id, actor, filename, content, category='', document_id=None):
    access(db, project_id, actor, True)
    base = db.query(KnowledgeBase).filter_by(id=base_id, project_id=project_id).with_for_update().first()
    if base is None:
        raise not_found('知识资源不存在')
    if Path(filename).suffix.lower() not in {'.txt', '.md', '.markdown', '.docx', '.pdf'}:
        raise bad_request('仅支持 TXT、Markdown、DOCX、文本 PDF')
    if not content or len(content) > 20 * 1024 * 1024:
        raise bad_request('文件不能为空且不得超过 20 MB')
    doc = (
        db.query(KnowledgeDocument).filter_by(id=document_id, project_id=project_id)
        .with_for_update().first()
        if document_id else KnowledgeDocument(
            project_id=project_id, base_id=base_id, name=Path(filename).name, category=category,
        )
    )
    if document_id and doc is None:
        raise not_found('知识资源不存在')
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
    # Lock the document first, matching upload/delete ordering. A trashed document
    # cannot be parsed after a queued worker wakes up.
    hint = db.query(KnowledgeVersion).filter_by(id=version_id).first()
    if hint is None:
        return
    doc = db.query(KnowledgeDocument).filter_by(id=hint.document_id).with_for_update().first()
    if doc is None or db.query(KnowledgeBase).filter_by(id=doc.base_id).first() is None:
        db.rollback()
        return
    # The document lock serializes parse retries and concurrent uploads/deletes.
    row = db.query(KnowledgeVersion).filter_by(id=version_id).with_for_update().first()
    if row is None:
        return
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


def _candidate_chunks(db, version_ids: list[int], query: str, *, candidate_limit: int):
    """在 PostgreSQL 侧按词项过滤和截断候选，应用层只加载有限 Chunk 正文。"""
    base = db.query(KnowledgeChunk).filter(KnowledgeChunk.version_id.in_(version_ids))
    terms = list(dict.fromkeys(_terms(query)))[:64]
    if not terms:
        rows = base.order_by(
            KnowledgeChunk.version_id, KnowledgeChunk.position, KnowledgeChunk.id,
        ).limit(candidate_limit + 1).all()
    else:
        predicates = []
        for term in terms:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            predicates.append(KnowledgeChunk.text.ilike(f"%{escaped}%", escape="\\"))
        match_count = sum(case((predicate, 1), else_=0) for predicate in predicates)
        rows = base.filter(or_(*predicates)).order_by(
            match_count.desc(), KnowledgeChunk.version_id,
            KnowledgeChunk.position, KnowledgeChunk.id,
        ).limit(candidate_limit + 1).all()
    truncated = len(rows) > candidate_limit
    return rows[:candidate_limit], truncated, len(terms)


def search(
    db, snapshot, actor, query, limit=8, minimum_score=0.0, *,
    candidate_limit: int | None = None, return_metadata: bool = False,
    vector_candidate_ids: list[int] | None = None,
):
    """按当前权限执行 SQL 候选 BM25；可安全融合外部授权候选，分数不代表概率。"""
    retrieval_started = time.monotonic()
    current = freeze(db, snapshot['project_id'], snapshot['agent_id'], actor)
    # 修订号来自已停用的 Agent 绑定，不能再用来拒绝检索；停用文档由下面的来源校验拦截。
    allowed_documents = {
        row[0] for row in db.query(KnowledgeVersion.document_id).filter(
            KnowledgeVersion.id.in_(current['version_ids']),
        ).all()
    }
    version_rows = db.query(
        KnowledgeVersion.id, KnowledgeVersion.document_id,
        KnowledgeVersion.version, KnowledgeVersion.status,
    ).filter(KnowledgeVersion.id.in_(snapshot['version_ids'])).all()
    versions_by_id = {
        row.id: {'document_id': row.document_id, 'version': row.version}
        for row in version_rows
    }
    if (
        len(versions_by_id) != len(set(snapshot['version_ids']))
        or any(row.status != 'READY' or row.document_id not in allowed_documents for row in version_rows)
    ):
        raise forbidden('知识来源已停用或权限已撤销')
    top_k = max(0, min(int(limit), 50))
    cap = max(1, min(int(candidate_limit if candidate_limit is not None else max(200, top_k * 40)), 5000))
    rows, candidates_truncated, _ = (
        _candidate_chunks(db, list(versions_by_id), query, candidate_limit=cap)
        if versions_by_id and top_k else ([], False, 0)
    )
    scores = _bm25_scores(rows, query)
    scored = sorted(rows, key=lambda c: (-scores.get(c.id, 0.0), c.version_id, c.position))
    # 空查询保留旧版来源浏览行为；有查询词但无匹配时不再返回无关片段。
    hybrid = vector_candidate_ids is not None
    if _terms(query) and not hybrid:
        scored = [row for row in scored if scores.get(row.id, 0.0) >= minimum_score and scores.get(row.id, 0.0) > 0]
    ranked_score_by_id = {row.id: scores.get(row.id, 0.0) for row in scored}
    score_type = 'BM25'
    candidate_rows_by_id = {row.id: row for row in rows}
    vector_count = 0
    fusion_metadata = None
    if hybrid:
        from app.knowledge.retrieval import reciprocal_rank_fusion

        vector_ids = list(dict.fromkeys(
            int(ident) for ident in (vector_candidate_ids or []) if isinstance(ident, int) and ident > 0
        ))[:cap]
        vector_rows = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.id.in_(vector_ids),
            KnowledgeChunk.version_id.in_(list(versions_by_id)),
        ).all() if vector_ids and versions_by_id else []
        vector_by_id = {row.id: row for row in vector_rows}
        authorized_vector_ids = [ident for ident in vector_ids if ident in vector_by_id]
        vector_count = len(authorized_vector_ids)
        candidate_rows_by_id.update(vector_by_id)
        fused = reciprocal_rank_fusion([
            [row.id for row in scored],
            authorized_vector_ids,
        ])
        fusion_metadata = 'RRF'
        score_type = 'RRF'
        ranked_score_by_id = {item['chunk_id']: item['score'] for item in fused}
        selected_ids = [
            item['chunk_id'] for item in fused
            if item['score'] >= minimum_score
        ][:top_k]
        selected = [candidate_rows_by_id[ident] for ident in selected_ids]
    else:
        selected = scored[:top_k]
    documents_by_id = {doc.id: doc for doc in db.query(KnowledgeDocument).filter(
        KnowledgeDocument.id.in_([versions_by_id[row.version_id]['document_id'] for row in selected])
    ).all()} if selected else {}
    from app.llm.tracing import record_runtime_span, task_trace_metadata
    runtime = task_trace_metadata.get() or {}
    elapsed_ms = int((time.monotonic() - retrieval_started) * 1000)
    retrieval_metadata = {
        'strategy': 'HYBRID_RRF' if hybrid else 'BM25_SQL_CANDIDATE',
        'candidate_count': len(rows),
        'candidate_limit': cap,
        'candidate_truncated': candidates_truncated,
        'vector_candidate_count': vector_count,
        'result_count': len(selected),
        'minimum_score': minimum_score,
        'top_k': top_k,
        'duration_ms': elapsed_ms,
        'tokenizer_version': _TOKENIZER_VERSION,
        # 当前仓库无 pgvector 扩展和 Embedding Provider，保留显式降级状态。
        'vector_status': 'ACTIVE' if hybrid and vector_count else 'UNAVAILABLE',
        'reranker_status': 'UNAVAILABLE',
        'fusion': fusion_metadata,
    }
    span_id = None
    if runtime:
        metadata = {
            key: runtime.get(key) for key in (
                'task_id', 'task_run_id', 'execution_root_run_id', 'trace_id', 'agent_run_id',
                'agent_id', 'agent_revision_id', 'work_item_id', 'attempt_id', 'project_id',
            ) if runtime.get(key) is not None
        } | {
            'strategy': retrieval_metadata['strategy'], 'query_sha256': hashlib.sha256(query.encode('utf-8')).hexdigest(),
            'candidate_count': len(rows), 'candidate_limit': cap,
            'candidate_truncated': candidates_truncated, 'result_count': len(selected),
            'vector_candidate_count': vector_count, 'fusion': fusion_metadata,
            'minimum_score': minimum_score, 'top_k': top_k,
            'bm25_k1': _BM25_K1, 'bm25_b': _BM25_B, 'tokenizer_version': _TOKENIZER_VERSION,
        }
        span_id = record_runtime_span(
            name='knowledge.retrieve',
            metadata=metadata,
            output={'results': [
                {'chunk_id': row.id, 'version_id': row.version_id, 'rank': index + 1,
                 'score': round(ranked_score_by_id.get(row.id, 0.0), 6), 'score_type': score_type}
                for index, row in enumerate(selected)
            ]},
        )
    from app.orchestration.tasks.services.runtime_fact_service import record_runtime_event
    record_runtime_event(
        db=db,
        project_id=snapshot['project_id'],
        task_id=runtime.get('task_id'), task_run_id=runtime.get('task_run_id'),
        execution_root_run_id=runtime.get('execution_root_run_id'),
        work_item_id=runtime.get('work_item_id'), attempt_id=runtime.get('attempt_id'),
        agent_session_id=runtime.get('agent_session_id'),
        agent_instance_id=runtime.get('agent_run_id'),
        agent_definition_id=runtime.get('agent_id') or snapshot['agent_id'] or None,
        agent_definition_revision_id=runtime.get('agent_revision_id'),
        trace_id=runtime.get('trace_id'), span_id=span_id,
        event_type='KNOWLEDGE_RETRIEVAL', event_name='BM25', status='SUCCEEDED',
        duration_ms=elapsed_ms,
        event_metadata={
            'query_sha256': hashlib.sha256(query.encode('utf-8')).hexdigest(),
            **retrieval_metadata,
            'fusion': fusion_metadata,
            'bm25_k1': _BM25_K1, 'bm25_b': _BM25_B,
            'chunk_ids': [row.id for row in selected],
            'version_ids': sorted({row.version_id for row in selected}),
        },
    )
    results = [{
        'chunk_id': row.id,
        'version_id': row.version_id,
        'version': versions_by_id[row.version_id]['version'],
        'document_id': versions_by_id[row.version_id]['document_id'],
        'document_name': documents_by_id[versions_by_id[row.version_id]['document_id']].name,
        'base_id': documents_by_id[versions_by_id[row.version_id]['document_id']].base_id,
        'agent_id': snapshot['agent_id'],
        'page': row.page,
        'position': row.position,
        'score': round(ranked_score_by_id.get(row.id, 0.0), 6),
        'score_type': score_type,
        'text': row.text,
    } for row in selected]
    return (results, retrieval_metadata) if return_metadata else results


def source(db, project_id, agent_id, actor, chunk_id):
    """读取当前 Agent 快照确切授权的 Chunk 版本，防止同文档旧版本越权回读。"""
    snapshot = freeze(db, project_id, agent_id, actor)
    chunk = db.get(KnowledgeChunk, chunk_id)
    version = db.get(KnowledgeVersion, chunk.version_id) if chunk else None
    if version is None or version.status != 'READY' or version.id not in snapshot['version_ids']:
        raise not_found('来源不在当前 Agent 知识范围')
    return chunk
