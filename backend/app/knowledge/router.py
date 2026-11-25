from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.database.session import get_db, SessionLocal
from app.core.security.auth import get_current_user
from app.core.http.errors import bad_request, not_found
from app.knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeVersion, KnowledgeBinding
from app.knowledge import service
from app.lifecycle.service import delete_resource
from app.tools.builtin.case_generation.contracts import GenerationRequest

router = APIRouter(prefix='/projects/{project_id}', tags=['项目知识库'])

class BaseInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)

class Scope(BaseModel):
    base_id: int
    mode: str
    document_ids: list[int] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)

class BindingInput(BaseModel):
    revision: int = 0
    enabled: bool = True
    required: bool = False
    access_mode: str | None = Field(default=None, pattern='^(PROJECT_SHARED|AGENT_SCOPED)$')
    scopes: list[Scope] = Field(default_factory=list, max_length=100)

class SearchInput(BaseModel):
    query: str = Field(max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    candidate_k: int | None = Field(default=None, ge=1, le=5000, description='仅覆盖本次 BM25 候选窗口')
    minimum_score: float = Field(default=0.0, ge=0.0, le=100.0)

class Command(BaseModel):
    action: str


def dump(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != 'content'}


def parse(ident):
    with SessionLocal() as db:
        service.parse_version(db, ident)

@router.get('/knowledge-bases')
def bases(project_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor)
    return {'items': [dump(r) for r in db.query(KnowledgeBase).filter_by(project_id=project_id).all()]}

@router.post('/knowledge-bases')
def create_base(project_id: int, body: BaseInput, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor, True)
    row = KnowledgeBase(project_id=project_id, name=body.name)
    db.add(row); db.commit()
    return dump(row)

@router.delete('/knowledge-bases/{base_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_base(project_id: int, base_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor, True)
    service.owned(db, KnowledgeBase, base_id, project_id)
    delete_resource(db, 'knowledge_base', base_id, actor=actor, project_id=project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get('/knowledge-bases/{base_id}/documents')
def documents(project_id: int, base_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor)
    service.owned(db, KnowledgeBase, base_id, project_id)
    return {'items': [dump(r) for r in db.query(KnowledgeDocument).filter_by(project_id=project_id, base_id=base_id).all()]}

@router.post('/knowledge-bases/{base_id}/documents', status_code=202)
async def upload(project_id: int, base_id: int, background: BackgroundTasks, file: UploadFile = File(...),
                 category: str = Form(''), document_id: int | None = Form(None), db: Session = Depends(get_db), actor=Depends(get_current_user)):
    row = service.upload(db, project_id, base_id, actor, file.filename or '', await file.read(20*1024*1024+1), category, document_id)
    background.add_task(parse, row.id)
    return dump(row)

@router.get('/knowledge-documents/{document_id}/versions')
def versions(project_id: int, document_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor)
    service.owned(db, KnowledgeDocument, document_id, project_id)
    return {'items': [dump(r) for r in db.query(KnowledgeVersion).filter_by(document_id=document_id).order_by(KnowledgeVersion.version.desc()).all()]}

@router.delete('/knowledge-documents/{document_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_document(project_id: int, document_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor, True)
    service.owned(db, KnowledgeDocument, document_id, project_id)
    delete_resource(db, 'knowledge_document', document_id, actor=actor, project_id=project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post('/knowledge-document-versions/{version_id}/commands')
def command(project_id: int, version_id: int, body: Command, background: BackgroundTasks, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor, True)
    document_id = db.query(KnowledgeVersion.document_id).filter_by(id=version_id).scalar()
    if document_id is None:
        raise not_found('版本不存在')
    # Match the parser's lock order. A concurrent retry must never reset a READY version.
    doc = db.query(KnowledgeDocument).filter_by(id=document_id, project_id=project_id).populate_existing().with_for_update().first()
    if doc is None:
        raise not_found('知识资源不存在')
    row = db.query(KnowledgeVersion).filter_by(id=version_id).populate_existing().with_for_update().first()
    if row is None:
        raise not_found('版本不存在')
    if body.action == 'retry' and row.status in {'FAILED', 'QUEUED'}:
        row.status = 'QUEUED'
        row.queued_at = datetime.now(timezone.utc)
        db.commit()
        background.add_task(parse, row.id)
    elif body.action in {'enable', 'disable'}:
        doc.enabled = body.action == 'enable'
        if doc.enabled:
            from app.knowledge.indexing import reconcile_project
            db.flush()
            reconcile_project(db, project_id)
        db.commit()
    else:
        raise bad_request('操作无效')
    return dump(row)

@router.get('/agents/{agent_id}/knowledge-binding')
def binding(project_id: int, agent_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor)
    row = db.query(KnowledgeBinding).filter_by(project_id=project_id, agent_id=agent_id).first()
    return dump(row) if row else {'revision': 0, 'enabled': True, 'required': False,
                                  'access_mode': 'PROJECT_SHARED', 'scopes': []}

@router.put('/agents/{agent_id}/knowledge-binding')
def put_binding(project_id: int, agent_id: int, body: BindingInput, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    return dump(service.save_binding(db, project_id, agent_id, actor, body.model_dump()))

@router.post('/knowledge-search')
def project_search(project_id: int, body: SearchInput, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    # 项目检索管理入口可查看项目内全部启用知识；运行时应使用 Agent 级检索入口。
    snapshot = service.freeze(db, project_id, 0, actor)
    items, retrieval = service.search(
        db, snapshot, actor, body.query, limit=body.top_k,
        minimum_score=body.minimum_score, candidate_limit=body.candidate_k,
        return_metadata=True,
    )
    return {'items': items, 'retrieval': retrieval}

@router.post('/agents/{agent_id}/knowledge-search')
def search(project_id: int, agent_id: int, body: SearchInput, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    # Agent 检索按显式知识绑定过滤；尚未配置范围的旧 Agent 维持项目默认范围。
    snapshot = service.freeze(db, project_id, agent_id, actor)
    from app.agents.models import AgentDefinition
    agent = db.get(AgentDefinition, agent_id)
    if agent is None or not agent.is_enabled:
        raise not_found('当前 Agent 不可试搜')
    items, retrieval = service.search(
        db, snapshot, actor, body.query, limit=body.top_k,
        minimum_score=body.minimum_score, candidate_limit=body.candidate_k,
        return_metadata=True,
    )
    return {'snapshot': snapshot, 'items': items, 'retrieval': retrieval}

@router.get('/agents/{agent_id}/knowledge-sources/{chunk_id}')
def source(project_id: int, agent_id: int, chunk_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    return dump(service.source(db, project_id, agent_id, actor, chunk_id))

@router.get('/knowledge-sources/{chunk_id}')
def project_source(project_id: int, chunk_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    return dump(service.source(db, project_id, 0, actor, chunk_id))

@router.post('/knowledge-bases/{base_id}/commands')
def base_command(project_id: int, base_id: int, body: Command, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor, True)
    row = service.owned(db, KnowledgeBase, base_id, project_id)
    if body.action not in {'enable', 'disable'}:
        raise bad_request('操作无效')
    row.enabled = body.action == 'enable'
    if row.enabled:
        from app.knowledge.indexing import reconcile_project
        db.flush()
        reconcile_project(db, project_id)
    db.commit()
    return dump(row)

@router.get('/knowledge-agent-options')
def agent_options(project_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    from app.agents.models import AgentDefinition
    service.access(db, project_id, actor)
    return [{'id': row.id, 'name': row.name} for row in db.query(AgentDefinition).filter_by(is_enabled=True).order_by(AgentDefinition.id).all()]

@router.post('/agents/{agent_id}/generate-cases')
def project_generate_cases(project_id: int, agent_id: int, body: GenerationRequest, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    from app.platform.projects.services.access_service import require_writable_project
    from app.agents.services.case_generation_service import generate_case_suite
    require_writable_project(db, project_id, actor)
    if body.project_id != project_id:
        raise bad_request('请求项目与路径不一致')
    return generate_case_suite(db, actor, agent_id, body)


class GenerationInput(BaseModel):
    embedding_revision_id: int = Field(gt=0)
    dimension: int = Field(gt=0, le=16000)
    distance: str = Field(pattern='^(cosine|l2|inner_product)$')
    encoding_version: str = Field(min_length=1, max_length=200)
    document_input_type: str | None = Field(default=None, max_length=100)
    query_input_type: str | None = Field(default=None, max_length=100)


class RetrievalConfigInput(BaseModel):
    enabled: bool = False
    rerank_revision_id: int | None = Field(default=None, gt=0)
    bm25_candidates: int = Field(default=50, ge=1, le=5000)
    vector_candidates: int = Field(default=50, ge=1, le=5000)
    rerank_window: int = Field(default=30, ge=1, le=5000)
    default_top_k: int = Field(default=8, ge=1, le=50)
    timeout_seconds: int = Field(default=10, ge=1, le=600)
    fusion_min_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    rerank_min_score: float | None = Field(default=None, allow_inf_nan=False)


def _available_revision(db, project_id, actor, revision_id, category, *, current=True):
    from app.platform.model_configuration.models import ModelResource, ModelRevision
    from app.platform.model_configuration.services.model_center_service import list_available_models
    revision = db.get(ModelRevision, revision_id)
    resource = (db.query(ModelResource).filter_by(id=revision.resource_id).with_for_update().populate_existing().first()
                if revision else None)
    available = list_available_models(db, project_id=project_id, category=category, actor=actor)['items']
    if (not resource or not revision.enabled or resource.category != category
            or category.lower() not in (revision.capabilities or [])
            or revision.adapter_key != {'EMBEDDING': 'openai-compatible-embeddings', 'RERANK': 'json-rerank'}[category]
            or (current and resource.current_revision_id != revision_id)
            or not any(item['id'] == resource.id for item in available)):
        raise bad_request('模型修订不存在、已停用或当前项目不可使用')
    return revision


@router.get('/knowledge-retrieval-config')
def retrieval_config(project_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    from app.knowledge.models import KnowledgeIndexGeneration, KnowledgeIndexJob, KnowledgeRetrievalConfig, KnowledgeVector
    from app.knowledge.indexing import project_chunks, queue_status
    from sqlalchemy import func
    service.access(db, project_id, actor)
    config = db.get(KnowledgeRetrievalConfig, project_id)
    generations = db.query(KnowledgeIndexGeneration).filter_by(project_id=project_id).order_by(KnowledgeIndexGeneration.id.desc()).all()
    eligible = project_chunks(db, project_id)
    eligible_count = eligible.count()
    items = []
    for generation in generations:
        counts = dict(db.query(KnowledgeIndexJob.status, func.count(KnowledgeIndexJob.id)).filter_by(
            generation_id=generation.id).group_by(KnowledgeIndexJob.status).all())
        vectors = db.query(func.count(KnowledgeVector.id)).filter_by(generation_id=generation.id).scalar()
        covered = db.query(func.count(KnowledgeVector.id)).filter(
            KnowledgeVector.generation_id == generation.id, KnowledgeVector.chunk_id.in_(eligible),
        ).scalar()
        items.append({**dump(generation), 'jobs': counts, 'vector_count': vectors,
                      'eligible_count': eligible_count, 'covered_count': covered,
                      'coverage': covered / eligible_count if eligible_count else 1.0})
    return {'config': dump(config) if config else None, 'generations': items, 'queues': queue_status(db, project_id)}


@router.put('/knowledge-retrieval-config')
def put_retrieval_config(project_id: int, body: RetrievalConfigInput, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    from app.knowledge.indexing import lock_project
    from app.knowledge.models import KnowledgeRetrievalConfig
    service.access(db, project_id, actor, True)
    lock_project(db, project_id)
    if body.rerank_revision_id:
        _available_revision(db, project_id, actor, body.rerank_revision_id, 'RERANK')
    config = db.get(KnowledgeRetrievalConfig, project_id)
    if config is None:
        config = KnowledgeRetrievalConfig(project_id=project_id)
        db.add(config)
    if body.enabled and not config.active_generation_id:
        raise bad_request('请先切换到已完成回填的索引代')
    for key, value in body.model_dump().items():
        setattr(config, key, value)
    db.commit()
    return dump(config)


@router.post('/knowledge-index-generations', status_code=201)
def create_index_generation(project_id: int, body: GenerationInput, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    from app.knowledge.indexing import backfill_generation, lock_project
    from app.knowledge.models import KnowledgeIndexGeneration
    service.access(db, project_id, actor, True)
    lock_project(db, project_id)
    _available_revision(db, project_id, actor, body.embedding_revision_id, 'EMBEDDING')
    generation = KnowledgeIndexGeneration(project_id=project_id, **body.model_dump(), state='BUILDING')
    db.add(generation)
    db.flush()
    queued = backfill_generation(db, generation.id)
    db.commit()
    return {**dump(generation), 'queued': queued}


@router.post('/knowledge-index-generations/{generation_id}/commands')
def index_generation_command(project_id: int, generation_id: int, body: Command,
                             db: Session = Depends(get_db), actor=Depends(get_current_user)):
    from app.knowledge.indexing import activate_generation, backfill_generation, lock_project, requeue_job
    from app.knowledge.models import KnowledgeIndexGeneration, KnowledgeIndexJob
    service.access(db, project_id, actor, True)
    lock_project(db, project_id)
    generation = db.query(KnowledgeIndexGeneration).filter_by(id=generation_id, project_id=project_id).first()
    if generation is None:
        raise not_found('索引代不存在')
    if body.action == 'backfill':
        result = {'queued': backfill_generation(db, generation_id)}
    elif body.action == 'retry':
        if generation.state not in {'BUILDING', 'ACTIVE', 'STANDBY'}:
            raise bad_request('该索引代不可重试')
        jobs = db.query(KnowledgeIndexJob).filter_by(generation_id=generation_id, status='FAILED').all()
        for job in jobs:
            requeue_job(job)
        result = {'queued': len(jobs)}
    elif body.action == 'activate':
        _available_revision(db, project_id, actor, generation.embedding_revision_id, 'EMBEDDING', current=False)
        activate_generation(db, project_id, generation_id)
        result = {'active_generation_id': generation_id}
    elif body.action == 'retire':
        from app.knowledge.models import KnowledgeRetrievalConfig
        config = db.get(KnowledgeRetrievalConfig, project_id)
        if config and config.active_generation_id == generation.id:
            raise bad_request('当前索引代不能退役，请先切换到其他索引代')
        if generation.state not in {'BUILDING', 'STANDBY'}:
            raise bad_request('该索引代不可退役')
        generation.state = 'RETIRED'
        for job in db.query(KnowledgeIndexJob).filter(
            KnowledgeIndexJob.generation_id == generation_id,
            KnowledgeIndexJob.status.in_(['QUEUED', 'RUNNING']),
        ).with_for_update().all():
            job.status, job.error = 'FAILED', 'generation_retired'
            job.lease_token, job.lease_until, job.next_attempt_at = None, None, None
        result = {'retired_generation_id': generation_id}
    else:
        raise bad_request('操作无效')
    db.commit()
    return result
