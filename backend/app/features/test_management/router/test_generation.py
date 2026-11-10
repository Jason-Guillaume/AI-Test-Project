"""用例生成草稿路由。生成沿用既有主子 Agent，入库必须再走接受接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.features.test_management.schemas.generation import (
    BatchReviewRequest,
    BatchReviewResponse,
    CaseDraftResponse,
    CaseGenerationAuditResponse,
    DraftDecisionResponse,
    DraftRejectRequest,
    DraftUpdateRequest,
    GenerationAgentOption,
    GenerationBatchListResponse,
    GenerationBatchResponse,
    GenerationStartRequest,
    RegenerateRequest,
)
from app.features.test_management.services.generation_service import GenerationService

router = APIRouter()
_GENERATION = GenerationService()


@router.get(
    "/projects/{project_id}/case-generation-agents",
    response_model=list[GenerationAgentOption],
    summary="可调用的用例生成主 Agent",
)
def list_generation_agents(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前项目成员可选用的用例生成主 Agent。"""
    return _GENERATION.list_agents(db, project_id, user)


@router.post(
    "/projects/{project_id}/case-generation-batches",
    response_model=GenerationBatchResponse,
    summary="按测试方向生成用例草稿",
)
def start_generation(
    project_id: int,
    body: GenerationStartRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """调度对应子 Agent 生成草稿。结果只进入审核批次。"""
    return _GENERATION.start(db, project_id, body, actor=user)


@router.get(
    "/projects/{project_id}/case-generation-batches",
    response_model=GenerationBatchListResponse,
    summary="生成批次列表",
)
def list_generation_batches(
    project_id: int,
    page: int = 1,
    page_size: int = 20,
    direction: str | None = None,
    status: str | None = None,
    module: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """分页查看历史生成批次，含状态统计与各批次草稿计数。"""
    return _GENERATION.list_batches(
        db, project_id, user,
        page=page, page_size=page_size, direction=direction, status=status, module=module, keyword=keyword,
    )


@router.get("/case-generation-batches/{batch_id}", response_model=GenerationBatchResponse, summary="生成批次详情")
def get_generation_batch(batch_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """读取批次、审阅摘要和草稿。"""
    return _GENERATION.get_batch(db, batch_id, user)


@router.post(
    "/case-generation-batches/{batch_id}/review",
    response_model=BatchReviewResponse,
    summary="批量审核草稿",
)
def batch_review(
    batch_id: int,
    body: BatchReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量接受（入库）或拒绝。必须 confirm=true 二次确认。"""
    return _GENERATION.batch_review(db, batch_id, body, actor=user)


@router.post(
    "/case-generation-batches/{batch_id}/regenerate",
    response_model=GenerationBatchResponse,
    summary="重新生成失败模块",
)
def regenerate_batch(
    batch_id: int,
    body: RegenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """只重跑失败模块；已成功与已审核草稿不受影响。"""
    return _GENERATION.regenerate(db, batch_id, body, actor=user)


@router.get(
    "/case-generation-batches/{batch_id}/audits",
    response_model=list[CaseGenerationAuditResponse],
    summary="批次审计记录",
)
def list_generation_audits(batch_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """查看批次的编辑、审核、入库与再生成审计。"""
    return _GENERATION.list_audits(db, batch_id, user)


@router.patch("/case-drafts/{draft_id}", response_model=CaseDraftResponse, summary="修改用例草稿")
def update_draft(
    draft_id: int,
    body: DraftUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修改待审核草稿的标题、步骤和期望。"""
    return _GENERATION.update_draft(db, draft_id, body, actor=user)


@router.post("/case-drafts/{draft_id}/accept", response_model=DraftDecisionResponse, summary="接受草稿并入库")
def accept_draft(draft_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """人工接受后才写入正式用例。"""
    return _GENERATION.accept_draft(db, draft_id, actor=user)


@router.post("/case-drafts/{draft_id}/reject", response_model=DraftDecisionResponse, summary="拒绝草稿")
def reject_draft(
    draft_id: int,
    body: DraftRejectRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """拒绝草稿，不创建用例。可附拒绝原因。"""
    return _GENERATION.reject_draft(db, draft_id, body, actor=user)


@router.post("/case-drafts/{draft_id}/reopen", response_model=CaseDraftResponse, summary="恢复草稿为待审核")
def reopen_draft(draft_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """仅已拒绝的草稿可恢复；已入库草稿不能回退。"""
    return _GENERATION.reopen_draft(db, draft_id, actor=user)
