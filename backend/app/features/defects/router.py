"""缺陷路由（无指派人模型）。

路径前缀 /api/v1/bugs。所有接口需要登录，资源级权限由服务层校验：
- 读：viewer+（对该 project 有可见性）
- 写：member+（创建、修改、删除、队列动作）
- 归档/撤销归档/项目开关/模板：editor+
- 越权访问统一按 404 处理，避免泄露他人缺陷的存在性

响应约定：列表返回 {items, total, page, page_size} 信封。
列表只返回摘要字段；请求头/请求体/响应正文、附件与活动按需加载。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import Response
from urllib.parse import quote

from app.features.defects.models.attachment import BugAttachment
from app.core.http.errors import bad_request, not_found
from app.platform.projects.services.access_service import check_writable
from sqlalchemy.orm import Session

from app.features.defects.models.bug import Bug
from app.features.defects.schemas import (
    ACTION_LABELS,
    BugActionRequest,
    BugActionResponse,
    BugActivityResponse,
    BugArchiveRequest,
    BugBatchActionReceipt,
    BugBatchActionRequest,
    BugBatchCreate,
    BugBatchCreateResponse,
    BugCreate,
    BugListResponse,
    BugQueueCountsResponse,
    BugResponse,
    BugStatsResponse,
    BugUpdate,
    DefectProjectSettingResponse,
    DefectProjectSettingUpdate,
    DefectSourceRequest,
    DefectSourceResponse,
    DefectTemplateCreate,
    DefectTemplatePreviewRequest,
    DefectTemplatePreviewResponse,
    DefectTemplateResponse,
)
from app.features.defects.services.defect_service import DefectService, status_display
from app.features.defects.services.project_config_service import DefectProjectConfigService
from app.features.defects.services.share_service import DefectShareService
from app.features.defects.services.source_service import DefectSourceService
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.security.auth import get_current_user
from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.core.security.sensitive import mask_header_text
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/bugs", tags=["缺陷管理"])
# 服务实例无状态，路由层复用一个单例即可。
SERVICE = DefectService()
SOURCE_SERVICE = DefectSourceService()
SHARE_SERVICE = DefectShareService()
CONFIG_SERVICE = DefectProjectConfigService()


def _responses(
    db: Session,
    bugs: list[Bug],
    counts: dict[int, int] | None = None,
    *,
    summary: bool = False,
) -> list[BugResponse]:
    """批量构造缺陷响应，一次加载关联项目与报告人，避免 N+1 查询。

    summary=True 时不返回请求头/请求体/响应正文，供列表按需加载。
    报告人可能被删除，对应字段回退为 None 而非报错。
    """
    if not bugs:
        return []
    project_ids = {bug.project_id for bug in bugs}
    user_ids = {bug.reporter_id for bug in bugs if bug.reporter_id is not None}
    projects = {
        row.id: row
        for row in db.query(Project).filter(Project.id.in_(project_ids)).all()
    }
    users = (
        {
            row.id: row
            for row in db.query(User).filter(User.id.in_(user_ids)).all()
        }
        if user_ids
        else {}
    )
    share_counts = (
        counts
        if counts is not None
        else SHARE_SERVICE.active_counts(db, [bug.id for bug in bugs])
    )
    items: list[BugResponse] = []
    for bug in bugs:
        project = projects.get(bug.project_id)
        reporter = users.get(bug.reporter_id) if bug.reporter_id else None
        items.append(
            BugResponse(
                id=bug.id,
                project_id=bug.project_id,
                project_name=project.name if project else None,
                title=bug.title,
                category=bug.category,
                description=bug.description,
                expected_result=bug.expected_result,
                actual_result=bug.actual_result,
                api_method=bug.api_method,
                api_url=bug.api_url,
                api_request_headers=None if summary else mask_header_text(bug.api_request_headers),
                api_request_body=None if summary else bug.api_request_body,
                api_response=None if summary else bug.api_response,
                severity=bug.severity,
                priority=bug.priority,
                status=bug.status,
                status_display=status_display(bug.status),
                steps_to_reproduce=bug.steps_to_reproduce,
                environment=bug.environment,
                affected_version=bug.affected_version,
                fix_version=bug.fix_version,
                reporter_id=bug.reporter_id,
                reporter_username=reporter.username if reporter else None,
                record_version=bug.record_version,
                is_draft=bug.is_draft,
                archived_at=bug.archived_at,
                archive_reason=bug.archive_reason,
                duplicate_of_bug_id=bug.duplicate_of_bug_id,
                created_at=bug.created_at,
                updated_at=bug.updated_at,
                active_share_count=share_counts.get(bug.id, 0),
            )
        )
    return items


def _response(db: Session, bug: Bug, active_share_count: int | None = None) -> BugResponse:
    """构造单个缺陷响应，复用批量映射函数保持口径一致。"""
    counts = {bug.id: active_share_count} if active_share_count is not None else None
    return _responses(db, [bug], counts=counts)[0]


def _activity_response(row) -> BugActivityResponse:
    """活动响应在出口再脱敏一次，兼容历史存量里已带凭证的记录。"""
    return BugActivityResponse(
        id=row.id,
        bug_id=row.bug_id,
        action=row.action,
        action_label=ACTION_LABELS.get(row.action, row.action),
        actor_id=row.actor_id,
        actor_name=row.actor_name,
        actor_type=row.actor_type,
        old_status=row.old_status,
        new_status=row.new_status,
        note=sanitize_text(row.note),
        detail=sanitize_context(row.detail),
        created_at=row.created_at,
    )


@router.get("", response_model=BugListResponse)
def list_bugs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    project_id: int | None = Query(None, ge=1),
    category: str | None = Query(None),
    status: str | None = Query(None),
    severity: int | None = Query(None, ge=1, le=4),
    priority: int | None = Query(None, ge=1, le=4),
    affected_version: str | None = Query(None, max_length=100),
    status_group: Literal["unclosed"] | None = Query(None),
    mine: bool = Query(False),
    include_archived: bool = Query(False),
    include_drafts: bool = Query(False),
    view: Literal["archived", "drafts"] | None = Query(None),
    updated_after: datetime | None = Query(None),
    updated_before: datetime | None = Query(None),
    keyword: str | None = None,
    sort: Literal["updated"] | None = Query(None),
    assignee_id: int | None = Query(None, description="已停用"),
):
    """分页列出当前用户可见范围内的缺陷；默认排除已归档与草稿。"""
    if assignee_id is not None:
        raise bad_request("处理人筛选已停用：缺陷改由项目状态队列跟进，请按状态队列检索")
    items, total = SERVICE.list_bugs(
        db,
        user=user,
        page=page,
        page_size=page_size,
        project_id=project_id,
        category=category,
        status=status,
        severity=severity,
        priority=priority,
        affected_version=affected_version,
        status_group=status_group,
        mine=mine,
        include_archived=include_archived,
        include_drafts=include_drafts,
        view=view,
        updated_after=updated_after,
        updated_before=updated_before,
        keyword=keyword,
        sort=sort,
    )
    counts = SHARE_SERVICE.active_counts(db, [item.id for item in items])
    return BugListResponse(
        items=_responses(db, items, counts=counts, summary=True),
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/queues", response_model=BugQueueCountsResponse)
def queue_counts(
    project_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """项目队列计数；与同条件列表总数一致。"""
    return SERVICE.queue_counts(db, user=user, project_id=project_id)


@router.get("/stats", response_model=BugStatsResponse)
def bug_stats(
    project_id: int = Query(..., ge=1),
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """质量统计：积压、首次确认耗时、待验证时长、回归失败率（含样本量）。"""
    return SERVICE.stats(db, user=user, project_id=project_id, period_days=period_days)


@router.post("/batch-actions", response_model=BugBatchActionReceipt)
def batch_actions(
    body: BugBatchActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量调整优先级、归档或撤销归档；部分失败返回逐项结果。"""
    return SERVICE.batch_action(
        db, actor=user, project_id=body.project_id, ids=body.ids,
        action=body.action, priority=body.priority, reason=body.reason,
    )


@router.get("/project-setting", response_model=DefectProjectSettingResponse)
def get_project_setting(
    project_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = CONFIG_SERVICE.get_setting(db, project_id, user)
    return DefectProjectSettingResponse(
        project_id=project_id,
        queue_enabled=row.queue_enabled,
        reminder_enabled=row.reminder_enabled,
        stale_reminder_days=row.stale_reminder_days,
    )


@router.put("/project-setting", response_model=DefectProjectSettingResponse)
def update_project_setting(
    body: DefectProjectSettingUpdate,
    project_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = CONFIG_SERVICE.update_setting(
        db, project_id, user,
        queue_enabled=body.queue_enabled,
        reminder_enabled=body.reminder_enabled,
        stale_reminder_days=body.stale_reminder_days,
    )
    return DefectProjectSettingResponse(
        project_id=project_id,
        queue_enabled=row.queue_enabled,
        reminder_enabled=row.reminder_enabled,
        stale_reminder_days=row.stale_reminder_days,
    )


def _template_response(db: Session, row) -> DefectTemplateResponse:
    creator = db.get(User, row.created_by) if row.created_by else None
    return DefectTemplateResponse(
        id=row.id,
        project_id=row.project_id,
        version=row.version,
        status=row.status,
        config=row.config,
        created_by_username=creator.username if creator else None,
        created_at=row.created_at,
        published_at=row.published_at,
    )


@router.get("/templates", response_model=list[DefectTemplateResponse])
def list_templates(
    project_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return [_template_response(db, row) for row in CONFIG_SERVICE.list_templates(db, project_id, user)]


@router.post("/templates", response_model=DefectTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(
    body: DefectTemplateCreate,
    project_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _template_response(db, CONFIG_SERVICE.create_draft(db, project_id, user, body.config))


@router.post("/templates/preview", response_model=DefectTemplatePreviewResponse)
def preview_template(
    body: DefectTemplatePreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return CONFIG_SERVICE.preview(body.config)


@router.post("/templates/{template_id}/publish", response_model=DefectTemplateResponse)
def publish_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _template_response(db, CONFIG_SERVICE.publish(db, template_id, user))


@router.get("/sources/context")
def source_context(source_type: Literal["CASE_EXECUTION", "SECURITY_FINDING"], source_id: int = Query(gt=0), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """读取授权来源的项目和测试运行编号，不返回敏感证据。"""
    return SOURCE_SERVICE.source_context(db, source_type, source_id, user)


@router.get("/sources", response_model=list[DefectSourceResponse])
def list_source_links(source_type: Literal["CASE_EXECUTION", "SECURITY_FINDING"], source_id: int = Query(gt=0), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """按真实来源查询授权范围内的缺陷关联。"""
    return SOURCE_SERVICE.list_for_source(db, source_type, source_id, user)


@router.post("/sources", response_model=DefectSourceResponse)
def link_source(body: DefectSourceRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """人工创建或关联缺陷，重复请求安全返回已有关系。"""
    return SOURCE_SERVICE.link(db, body, user)


@router.post("/batch", response_model=BugBatchCreateResponse, status_code=status.HTTP_201_CREATED)
def batch_create_bugs(
    body: BugBatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """同一项目下原子批量新增缺陷；至少 member 权限。"""
    bugs = SERVICE.batch_create_bugs(db, body, actor=user)
    # 新建缺陷尚未分享，直接传空映射避免无谓查询分享表。
    items = _responses(db, bugs, counts={})
    return BugBatchCreateResponse(items=items, created_count=len(items))


def _attachment_response(row: BugAttachment):
    return {"id": row.id, "filename": row.filename, "size": row.size, "created_at": row.created_at}


@router.get("/{bug_id}/attachments")
def list_attachments(bug_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    SERVICE.get_bug_or_404(db, bug_id, user)
    return [_attachment_response(row) for row in db.query(BugAttachment).filter_by(bug_id=bug_id).order_by(BugAttachment.id).all()]


@router.post("/{bug_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(bug_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    check_writable(db, db.get(Project, bug.project_id), user)
    content = await file.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024:
        raise bad_request("附件不能为空且不能超过 10 MB")
    filename = (file.filename or 'attachment').replace('\\', '/').split('/')[-1][:255] or 'attachment'
    row = BugAttachment(bug_id=bug_id, filename=filename, content_type=(file.content_type or 'application/octet-stream')[:255], content=content, size=len(content))
    db.add(row)
    db.commit()
    db.refresh(row)
    return _attachment_response(row)


@router.get("/{bug_id}/attachments/{attachment_id}")
def download_attachment(bug_id: int, attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    SERVICE.get_bug_or_404(db, bug_id, user)
    row = db.query(BugAttachment).filter_by(id=attachment_id, bug_id=bug_id).first()
    if row is None:
        raise not_found("附件不存在")
    return Response(content=row.content, media_type='application/octet-stream', headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.filename, safe=''), "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.delete("/{bug_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(bug_id: int, attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    check_writable(db, db.get(Project, bug.project_id), user)
    row = db.query(BugAttachment).filter_by(id=attachment_id, bug_id=bug_id).first()
    if row is None:
        raise not_found("附件不存在")
    db.delete(row)
    db.commit()


@router.get("/{bug_id}/sources", response_model=list[DefectSourceResponse])
def list_bug_sources(bug_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """查询缺陷的真实来源。"""
    return SOURCE_SERVICE.list_for_bug(db, bug_id, user)


@router.get("/{bug_id}/activities", response_model=list[BugActivityResponse])
def list_bug_activities(bug_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """按需加载缺陷活动时间线。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    return [_activity_response(row) for row in SERVICE.list_activities(db, bug)]


@router.post("/{bug_id}/actions", response_model=BugActionResponse)
def perform_action(
    bug_id: int,
    body: BugActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """队列动作：确认问题/登记可回归/回归通过/回归失败/拒绝/判重/重开。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    bug, activity = SERVICE.perform_action(db, bug, body, actor=user)
    return BugActionResponse(bug=_response(db, bug), activity=_activity_response(activity))


@router.post("/{bug_id}/submit-draft", response_model=BugResponse)
def submit_draft(bug_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """提交草稿，进入待确认队列。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    return _response(db, SERVICE.submit_draft(db, bug, actor=user))


@router.post("/{bug_id}/archive", response_model=BugResponse)
def archive_bug(
    bug_id: int,
    body: BugArchiveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """归档缺陷（editor+）；保留原因并终止全部公开分享访问。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    return _response(db, SERVICE.archive_bug(db, bug, actor=user, reason=body.reason))


@router.post("/{bug_id}/restore", response_model=BugResponse)
def restore_bug(bug_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """撤销归档（editor+）。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    return _response(db, SERVICE.restore_bug(db, bug, actor=user))


@router.get("/{bug_id}", response_model=BugResponse)
def get_bug(
    bug_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询缺陷详情；越权与不存在共用 404。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    return _response(db, bug)


@router.post("", response_model=BugResponse, status_code=status.HTTP_201_CREATED)
def create_bug(
    body: BugCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新增缺陷；至少 member 权限。新单自动进入待确认队列。"""
    bug = SERVICE.create_bug(db, body, actor=user)
    return _response(db, bug)


@router.put("/{bug_id}", response_model=BugResponse)
def update_bug(
    bug_id: int,
    body: BugUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修改事实字段；至少 member 权限。状态请通过队列动作变更。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    bug = SERVICE.update_bug(db, bug, body, actor=user)
    return _response(db, bug)


@router.delete("/{bug_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bug(
    bug_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除缺陷；至少 member 权限。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    SERVICE.delete_bug(db, bug, actor=user)
    return None