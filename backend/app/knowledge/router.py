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
    top_k: int = Field(default=8, ge=1, le=50)
    candidate_k: int = Field(default=320, ge=50, le=2000)
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
    row = db.get(KnowledgeVersion, version_id)
    if row is None:
        raise not_found('版本不存在')
    doc = service.owned(db, KnowledgeDocument, row.document_id, project_id)
    if body.action == 'retry' and row.status in {'FAILED', 'QUEUED'}:
        row.status = 'QUEUED'; db.commit(); background.add_task(parse, row.id)
    elif body.action in {'enable', 'disable'}:
        doc.enabled = body.action == 'enable'; db.commit()
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
    items, retrieval = service.search(
        db, snapshot, actor, body.query, limit=body.top_k,
        minimum_score=body.minimum_score, candidate_limit=body.candidate_k,
        return_metadata=True,
    )
    return {'snapshot': snapshot, 'items': items, 'retrieval': retrieval}

@router.get('/agents/{agent_id}/knowledge-sources/{chunk_id}')
def source(project_id: int, agent_id: int, chunk_id: int, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    return dump(service.source(db, project_id, agent_id, actor, chunk_id))

@router.post('/knowledge-bases/{base_id}/commands')
def base_command(project_id: int, base_id: int, body: Command, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    service.access(db, project_id, actor, True)
    row = service.owned(db, KnowledgeBase, base_id, project_id)
    if body.action not in {'enable', 'disable'}:
        raise bad_request('操作无效')
    row.enabled = body.action == 'enable'
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
