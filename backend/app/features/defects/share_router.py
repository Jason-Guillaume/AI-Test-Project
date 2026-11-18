"""缺陷分享的登录接口。

这些路由都要求平台身份，并在服务层再次检查项目权限。
公开免登录接口不在这里注册。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.features.defects.schemas_share import (
    ArchiveExpiredResponse,
    BatchShareRequest,
    BatchShareResponse,
    RevokeBatchRequest,
    ShareDetailResponse,
    ShareListResponse,
    ShareOptions,
    SharePreviewRequest,
    SharePreviewResponse,
    SharePushResponse,
    ShareRetryRequest,
    ShareSummaryResponse,
)
from app.features.defects.services.share_service import DefectShareService

router = APIRouter(prefix="/bugs", tags=["缺陷分享"])
SERVICE = DefectShareService()


@router.post("/shares/preview", response_model=SharePreviewResponse)
def preview_share(
    body: SharePreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """预览推送对象、有效期和字段范围，不产生分享记录。"""
    return SERVICE.preview(db, body, user)


@router.post("/shares/batch", response_model=BatchShareResponse)
def batch_share(
    body: BatchShareRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量创建独立分享并发送汇总飞书卡片。"""
    return SERVICE.create_batch(db, body, user)


@router.post("/shares/revoke-batch", response_model=list[ShareSummaryResponse])
def revoke_batch(
    body: RevokeBatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量撤销分享。前端必须先向用户二次确认。"""
    return SERVICE.revoke_batch(db, body, user)


@router.post("/shares/batches/{public_id}/retry", response_model=BatchShareResponse)
def retry_share_batch(public_id: str, body: ShareRetryRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """从批次历史重推整组，仍只调用一次飞书 Webhook。"""
    return SERVICE.retry_batch(db, public_id, body, user)


@router.post("/shares/batches/{public_id}/revoke", response_model=BatchShareResponse)
def revoke_share_batch(public_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """撤销批次入口，不改动逐条分享审计。"""
    return SERVICE.revoke_batch_link(db, public_id, user)


@router.post("/shares/archive-expired", response_model=ArchiveExpiredResponse)
def archive_expired(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """归档已过期分享。只允许平台管理员调用。"""
    return ArchiveExpiredResponse(archived=SERVICE.archive_expired(db, user))


@router.post("/{bug_id}/shares", response_model=SharePushResponse)
def create_share(
    bug_id: int,
    body: ShareOptions,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建一条分享并推送到选定飞书渠道。"""
    return SERVICE.create(db, bug_id, body, user)


@router.get("/{bug_id}/shares", response_model=ShareListResponse)
def list_shares(
    bug_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查看缺陷的分享历史。"""
    return SERVICE.list_shares(db, bug_id, user)


@router.get("/{bug_id}/shares/{share_id}", response_model=ShareDetailResponse)
def get_share(
    bug_id: int,
    share_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查看单条分享、快照和外部处理记录。"""
    return SERVICE.get_share(db, bug_id, share_id, user)


@router.post("/{bug_id}/shares/{share_id}/revoke", response_model=ShareSummaryResponse)
def revoke_share(
    bug_id: int,
    share_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """撤销指定分享，不影响同一缺陷的其他链接。"""
    return SERVICE.revoke(db, bug_id, share_id, user)


@router.post("/{bug_id}/shares/{share_id}/retry", response_model=SharePushResponse)
def retry_share(
    bug_id: int,
    share_id: str,
    body: ShareRetryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重新推送。失败重试不新增分享行。"""
    return SERVICE.retry(db, bug_id, share_id, body, user)
