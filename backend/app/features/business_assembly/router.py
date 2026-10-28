"""业务组装 API 路由。

组装任务无测试环境要求；草稿编辑按修订号并发控制，确认保存时服务端重验权限、来源和结构。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.features.business_assembly.schemas import (
    AssemblyTaskCreate,
    BusinessAssemblyApplyResponse,
    BusinessAssemblyDraftResponse,
    BusinessAssemblyValidationResponse,
    DraftApplyRequest,
    DraftUpdate,
    DraftValidateRequest,
)
from app.features.business_assembly.services.assembly_service import BusinessAssemblyService
from app.features.business.services._access import get_project_or_404
from app.features.tasks.models import Task
from app.features.tasks.schemas import TaskResponse
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db

router = APIRouter(tags=["业务组装"])
service = BusinessAssemblyService()


@router.post(
    "/projects/{project_id}/business-assembly-tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交 Agent 业务组装任务",
)
def create_assembly_task(
    project_id: int,
    body: AssemblyTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """登记持久化业务组装任务；模型生成由统一 Worker 异步处理。"""
    return service.create_task(db, project_id, body, actor=user)


@router.get(
    "/business-assembly-drafts/{draft_id}",
    response_model=BusinessAssemblyDraftResponse,
    summary="读取业务组装草稿",
)
def get_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BusinessAssemblyDraftResponse:
    """读取当前修订的流程、依据、覆盖与校验状态。"""
    return service.get_draft(db, draft_id, user)


@router.get(
    "/task-runs/{run_id}/business-assembly-draft",
    response_model=BusinessAssemblyDraftResponse,
    summary="按来源任务运行读取业务草稿",
)
def get_draft_for_run(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BusinessAssemblyDraftResponse:
    """让任务详情页通过其运行 ID 取得已生成的草稿。"""
    from app.features.business_assembly.models import BusinessAssemblyDraft
    from app.features.tasks.models import TaskRun
    from app.shared.errors import not_found

    run = db.get(TaskRun, run_id)
    if run is None:
        raise not_found("任务运行不存在")
    task = db.get(Task, run.task_id)
    if task is None:
        raise not_found("任务运行不存在")
    get_project_or_404(db, task.project_id, user)
    draft = db.query(BusinessAssemblyDraft).filter(BusinessAssemblyDraft.task_run_id == run.id).first()
    if draft is None:
        raise not_found("业务组装草稿尚未生成")
    return service.get_draft(db, draft.id, user)


@router.patch(
    "/business-assembly-drafts/{draft_id}",
    response_model=BusinessAssemblyDraftResponse,
    summary="保存人工编辑的草稿修订",
)
def update_draft(
    draft_id: int,
    body: DraftUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BusinessAssemblyDraftResponse:
    """按期望修订号追加修改，冲突时拒绝覆盖其他编辑。"""
    return service.update_draft(db, draft_id, body, actor=user)


@router.post(
    "/business-assembly-drafts/{draft_id}/validate",
    response_model=BusinessAssemblyValidationResponse,
    summary="校验业务组装草稿修订",
)
def validate_draft(
    draft_id: int,
    body: DraftValidateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BusinessAssemblyValidationResponse:
    """在服务端核验来源、变量连接、接口归属与保存边界。"""
    return service.validate_draft(db, draft_id, body.revision, user)


@router.post(
    "/business-assembly-drafts/{draft_id}/apply",
    response_model=BusinessAssemblyApplyResponse,
    summary="原子保存所选业务流程",
)
def apply_draft(
    draft_id: int,
    body: DraftApplyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BusinessAssemblyApplyResponse:
    """以修订号、流程集合和幂等键确认业务保存。"""
    return service.apply_draft(db, draft_id, body, actor=user)
