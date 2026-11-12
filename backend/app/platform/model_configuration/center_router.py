"""统一模型中心 HTTP 接口；权限、事务和资源过滤由 service 负责。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.platform.model_configuration.center_schemas import (
    ModelConnectionTestInput, ModelDefaultInput, ModelDiagnosticInput, ModelGrantInput,
    ModelImportPreview, ModelProfileCreate, ModelResourceCreate, ModelRevisionInput,
)
from app.platform.model_configuration.services.model_center_service import (
    adapter_catalog, copy_resource, create_diagnostic, create_profile, create_resource, create_revision,
    get_diagnostic, import_resources, list_available_models, list_resources, preview_import, run_model_diagnostic,
    set_default_binding, set_resource_grants, test_model_connection,
)

router = APIRouter(prefix="/model-center", tags=["统一模型中心"])


@router.get("/catalog")
def catalog():
    """列出类别、供应商目录和已实现适配器。"""
    return adapter_catalog()


@router.get("/resources")
def resources(
    category: str | None = None, project_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """管理者列出模型资源；项目编辑者只查看该项目私有资源。"""
    return list_resources(db, actor, category=category, project_id=project_id)


@router.get("/available")
def available(
    project_id: int = Query(gt=0), category: str | None = None,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """读取项目普通成员可选择的模型摘要，不返回地址、凭据或协议模板。"""
    return list_available_models(db, project_id=project_id, category=category, actor=actor)


@router.post("/resources", status_code=status.HTTP_201_CREATED)
def resource_create(
    body: ModelResourceCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """新增模型连接、连接修订、参数方案并生成兼容运行时投影。"""
    return create_resource(db, body, actor)


@router.post("/resources/{resource_id}/revisions", status_code=status.HTTP_201_CREATED)
def revision_create(
    resource_id: int, body: ModelRevisionInput,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """为同一服务追加不可变连接修订。"""
    return create_revision(db, resource_id, body, actor)


@router.post("/resources/{resource_id}/profiles", status_code=status.HTTP_201_CREATED)
def profile_create(
    resource_id: int, body: ModelProfileCreate,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """创建独立版本化参数方案，不复制或修改连接凭据。"""
    return create_profile(db, resource_id, body, actor)


@router.put("/resources/{resource_id}/grants")
def resource_grants(
    resource_id: int, body: ModelGrantInput,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """替换平台共享模型的项目授权。"""
    return set_resource_grants(db, resource_id, body.project_ids, actor)


@router.put("/defaults")
def default_binding(
    body: ModelDefaultInput, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """按模型类别与用途配置默认项和同类别备用策略。"""
    return set_default_binding(db, body, actor)


@router.post("/resources/{resource_id}/copy", status_code=status.HTTP_201_CREATED)
def resource_copy(
    resource_id: int, project_id: int = Query(gt=0),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """复制非敏感模型配置到项目作用域并清空凭据。"""
    return copy_resource(db, resource_id, project_id, actor)


@router.post("/resources/{resource_id}/diagnostics", status_code=status.HTTP_202_ACCEPTED)
def diagnostic_create(
    resource_id: int, body: ModelDiagnosticInput, background: BackgroundTasks,
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """用户明确确认后排队真实在线诊断，打开页面与保存配置不会触发调用。"""
    run = create_diagnostic(db, resource_id, body, actor)
    background.add_task(run_model_diagnostic, run["id"])
    return run


@router.post("/connection-tests")
def connection_test(
    body: ModelConnectionTestInput, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """真实发送一次未保存的文本推理测试请求，并返回脱敏状态与耗时。"""
    return test_model_connection(db, body, actor)


@router.get("/diagnostics/{run_id}")
def diagnostic_detail(
    run_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """读取持久化诊断进度和脱敏结果。"""
    return get_diagnostic(db, run_id, actor)


@router.post("/imports/preview")
def import_preview(
    body: ModelImportPreview, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """预检非敏感配置批次；不保存资源也不调用模型。"""
    return preview_import(db, body.items, actor)


@router.post("/imports", status_code=status.HTTP_201_CREATED)
def import_create(
    body: ModelImportPreview, db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    """在全批预检通过后原子导入非敏感配置；不携带凭据、不发起模型调用。"""
    return import_resources(db, body.items, actor)


__all__ = ["router"]


@router.put("/resources/{resource_id}/enabled")
def resource_enabled(resource_id: int, enabled: bool, db: Session = Depends(get_db), actor=Depends(get_current_user)):
    from app.platform.model_configuration.models import ModelResource, ModelRevision
    from app.platform.model_configuration.services.model_center_service import _require_platform_admin
    from app.core.models.configuration import ModelConfiguration
    from app.core.http.errors import not_found, bad_request
    _require_platform_admin(actor)
    resource = db.get(ModelResource, resource_id)
    if resource is None:
        raise not_found("模型不存在")
    if resource.visibility != 'PLATFORM':
        raise bad_request("历史私有模型需明确审核后迁移，不得直接启用共享")
    resource.status = 'ACTIVE' if enabled else 'DISABLED'
    revision = db.get(ModelRevision, resource.current_revision_id)
    if revision:
        revision.enabled = enabled
    legacy = db.get(ModelConfiguration, resource.legacy_model_id) if resource.legacy_model_id else None
    if legacy:
        legacy.is_enabled = enabled
    from app.features.asr_evaluation.models import AsrConnection
    revisions = db.query(ModelRevision).filter_by(resource_id=resource.id).all()
    connection_ids = [r.legacy_connection_id for r in revisions if r.legacy_connection_id]
    if connection_ids:
        db.query(AsrConnection).filter(AsrConnection.id.in_(connection_ids)).update({'enabled': enabled}, synchronize_session=False)
    # Platform ASR slots create per-project compatibility connections; retire these too.
    from app.platform.model_configuration.models import ModelTaskSlot
    slots = db.query(ModelTaskSlot).filter_by(resource_id=resource.id).all()
    for slot in slots:
        connection_id = getattr(slot, 'legacy_connection_id', None)
        if connection_id:
            connection = db.get(AsrConnection, connection_id)
            if connection:
                connection.enabled = enabled
    db.commit()
    return {'enabled': enabled}
