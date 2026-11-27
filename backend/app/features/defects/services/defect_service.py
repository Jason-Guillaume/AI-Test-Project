"""缺陷服务层（无指派人模型）。

路由层只做参数、认证与响应映射；所有业务、权限与事务集中在这里。

权限模型：
- 读：对该 project 有可见性即可（viewer+ 或 platform admin）
- 写（增/改/删/队列动作）：至少 project member
- 归档、撤销归档：至少 project editor
- 越权与不存在共用 404，避免泄露他人缺陷的存在性

事务约定：service 层负责 commit；router 层不 commit。
状态变更只能通过队列动作完成，并与活动事件在同一事务提交；
record_version 提供乐观并发控制，后提交者收到 409 与最新数据。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.defects.models.activity import BugActivity
from app.features.defects.models.bug import Bug
from app.features.defects.models.share import DefectShareLink
from app.features.defects.schemas import (
    ACTION_LABELS,
    ACTION_TRANSITIONS,
    BUG_CATEGORIES,
    BUG_STATUSES,
    STATUS_DISPLAY,
    BugActionRequest,
    BugBase,
    BugBatchCreate,
    BugCreate,
    BugUpdate,
    SEVERITY_LABELS,
    UNCATEGORIZED_BUG_CATEGORY,
    normalize_bug_category,
)
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.http.errors import (
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    bad_request,
    conflict,
    forbidden,
    not_found,
)
from app.core.notifications.notify import notify
from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.core.security.sensitive import mask_header_text
from app.platform.projects.services.access_service import check_writable, get_project_or_404
from app.core.security.roles import (
    PROJECT_ROLE_EDITOR,
    accessible_project_ids,
    has_project_role,
    project_role_for,
)
from app.features.defects.services.project_config_service import DefectProjectConfigService
from app.lifecycle.service import delete_resource

UNCLOSED_STATUSES = ("待确认", "处理中", "已修复")
CONFIG_SERVICE = DefectProjectConfigService()


def status_display(value: str) -> str:
    """底层「已修复」对测试人员显示为「待验证」。"""
    return STATUS_DISPLAY.get(value, value)


class DefectService:
    """缺陷服务。无状态，可跨模块复用。"""

    # ---------------------------------------------------------------- 可见性

    def get_bug_or_404(self, db: Session, bug_id: int, user: User) -> Bug:
        """按 ID 取缺陷并校验可见性；越权与不存在共用 404。

        草稿只对创建者可见：其他成员即使能写项目也不能通过 ID 探测、
        读取、编辑、分享或提交别人的草稿，统一按不可见资源返回 404。
        """
        bug = db.get(Bug, bug_id)
        if bug is None:
            raise not_found("缺陷不存在")
        if bug.is_draft and bug.reporter_id != user.id:
            raise not_found("缺陷不存在")
        visible_ids = accessible_project_ids(db, user)
        if visible_ids is not None and bug.project_id not in visible_ids:
            raise not_found("缺陷不存在")
        return bug

    def _lock_bug(self, db: Session, bug: Bug) -> Bug:
        """锁定并刷新缺陷行，确保版本校验读到的是最新已提交数据。

        必须带 populate_existing：会话的 identity map 里可能已有旧对象，
        只加 with_for_update 会让后续版本校验继续读到旧 status/record_version，
        导致两个并发动作都通过校验。
        """
        locked = (
            db.query(Bug)
            .filter(Bug.id == bug.id)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if locked is None:
            raise not_found("缺陷不存在")
        return locked

    # ---------------------------------------------------------------- 查询

    def _base_query(self, db: Session, user: User, project_id: int | None):
        """按可见项目收敛查询；不可见项目返回空结果占位。"""
        query = db.query(Bug)
        visible_ids = accessible_project_ids(db, user)
        if visible_ids is not None:
            if project_id is not None:
                if project_id not in visible_ids:
                    return query.filter(Bug.id == -1)
                query = query.filter(Bug.project_id == project_id)
            else:
                query = query.filter(Bug.project_id.in_(visible_ids or [-1]))
        elif project_id is not None:
            query = query.filter(Bug.project_id == project_id)
        return query

    def build_list_query(
        self,
        db: Session,
        *,
        user: User,
        project_id: int | None = None,
        category: str | None = None,
        status: str | None = None,
        severity: int | None = None,
        priority: int | None = None,
        affected_version: str | None = None,
        status_group: str | None = None,
        mine: bool = False,
        include_archived: bool = False,
        include_drafts: bool = False,
        view: str | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        keyword: str | None = None,
    ):
        """构造列表与导出共用的权限+筛选查询（不附带排序，便于 count 与分页复用）。"""
        query = self._base_query(db, user, project_id)

        if category:
            category = normalize_bug_category(category)
            if category == UNCATEGORIZED_BUG_CATEGORY:
                query = query.filter(Bug.category.is_(None))
            elif category in BUG_CATEGORIES:
                query = query.filter(Bug.category == category)
            else:
                raise bad_request("前后端划分取值非法")
        if status:
            if status not in BUG_STATUSES:
                raise bad_request("状态取值非法")
            query = query.filter(Bug.status == status)
        if status_group:
            if status_group != "unclosed":
                raise bad_request("状态分组取值非法")
            query = query.filter(Bug.status.in_(UNCLOSED_STATUSES))
        if severity is not None:
            if severity not in SEVERITY_LABELS:
                raise bad_request("严重度取值非法")
            query = query.filter(Bug.severity == severity)
        if priority is not None:
            if priority not in (1, 2, 3, 4):
                raise bad_request("优先级取值非法")
            query = query.filter(Bug.priority == priority)
        if affected_version:
            query = query.filter(Bug.affected_version == affected_version.strip())
        if mine:
            query = query.filter(Bug.reporter_id == user.id)
        if view is not None and view not in ("archived", "drafts"):
            raise bad_request("视图取值非法")
        if view == "archived":
            query = query.filter(Bug.archived_at.isnot(None))
        elif view == "drafts":
            query = query.filter(Bug.is_draft.is_(True), Bug.reporter_id == user.id)
        else:
            if not include_archived:
                query = query.filter(Bug.archived_at.is_(None))
        if view != "drafts":
            if include_drafts:
                # 包含草稿时也只放行自己的：其他成员的草稿不出现在列表里。
                query = query.filter(or_(Bug.is_draft.is_(False), Bug.reporter_id == user.id))
            else:
                query = query.filter(Bug.is_draft.is_(False))
        if updated_after is not None:
            query = query.filter(Bug.updated_at >= updated_after)
        if updated_before is not None:
            query = query.filter(Bug.updated_at <= updated_before)
        if keyword:
            keyword = keyword.strip()
            if keyword:
                query = query.filter(Bug.title.ilike(f"%{keyword}%"))
        return query

    @staticmethod
    def list_order_columns(sort: str | None):
        """返回列表与导出共用的稳定排序字段，保证跨页顺序一致。"""
        primary = Bug.updated_at.desc() if sort == "updated" else Bug.id.desc()
        return (primary, Bug.id.desc())

    def list_bugs(
        self,
        db: Session,
        *,
        user: User,
        page: int,
        page_size: int,
        project_id: int | None = None,
        category: str | None = None,
        status: str | None = None,
        severity: int | None = None,
        priority: int | None = None,
        affected_version: str | None = None,
        status_group: str | None = None,
        mine: bool = False,
        include_archived: bool = False,
        include_drafts: bool = False,
        view: str | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        keyword: str | None = None,
        sort: str | None = None,
    ) -> tuple[list[Bug], int]:
        """按可见范围与过滤条件分页查询；默认排除已归档与草稿。"""
        query = self.build_list_query(
            db,
            user=user,
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
        )
        total = int(query.count())
        items = (
            query.order_by(*self.list_order_columns(sort))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def count_bugs(self, db: Session, user: User) -> int:
        """统计当前用户可见范围内的缺陷总数；供看板卡片复用。"""
        query = db.query(func.count(Bug.id))
        visible_ids = accessible_project_ids(db, user)
        if visible_ids is not None:
            query = query.filter(Bug.project_id.in_(visible_ids or [-1]))
        return int(query.scalar() or 0)

    def queue_counts(self, db: Session, *, user: User, project_id: int) -> dict[str, int]:
        """项目队列计数；口径与同条件列表一致（排除归档与草稿）。"""
        get_project_or_404(db, project_id, user)
        base = self._base_query(db, user, project_id).filter(
            Bug.archived_at.is_(None), Bug.is_draft.is_(False)
        )

        def count(*conditions) -> int:
            return int(base.filter(*conditions).count())

        return {
            "project_id": project_id,
            "unclosed": count(Bug.status.in_(UNCLOSED_STATUSES)),
            "pending_confirm": count(Bug.status == "待确认"),
            "in_progress": count(Bug.status == "处理中"),
            "pending_verify": count(Bug.status == "已修复"),
            "reported_by_me": count(Bug.reporter_id == user.id),
            "closed": count(Bug.status == "已关闭"),
            "rejected": count(Bug.status == "已拒绝"),
            "archived": int(
                self._base_query(db, user, project_id)
                .filter(Bug.archived_at.isnot(None)).count()
            ),
            "drafts": int(
                self._base_query(db, user, project_id)
                .filter(Bug.is_draft.is_(True), Bug.reporter_id == user.id).count()
            ),
        }

    def stats(self, db: Session, *, user: User, project_id: int, period_days: int) -> dict:
        """质量统计：积压、首次确认耗时、待验证时长、回归失败率（含样本量）。"""
        get_project_or_404(db, project_id, user)
        base = self._base_query(db, user, project_id).filter(
            Bug.archived_at.is_(None), Bug.is_draft.is_(False)
        )
        backlog = {s: int(base.filter(Bug.status == s).count()) for s in BUG_STATUSES}
        since = datetime.now() - timedelta(days=period_days)

        confirm_rows = (
            db.query(BugActivity.created_at, Bug.created_at)
            .join(Bug, Bug.id == BugActivity.bug_id)
            .filter(
                BugActivity.project_id == project_id,
                BugActivity.action == "confirm",
                BugActivity.created_at >= since,
            )
            .all()
        )
        confirm_hours = [
            (activity_at - created_at).total_seconds() / 3600
            for activity_at, created_at in confirm_rows
            if activity_at and created_at and activity_at >= created_at
        ]

        verify_rows = (
            db.query(BugActivity.action, BugActivity.created_at)
            .filter(
                BugActivity.project_id == project_id,
                BugActivity.action.in_(("regression_pass", "regression_fail")),
                BugActivity.created_at >= since,
            )
            .all()
        )
        regression_total = len(verify_rows)
        regression_failed = sum(1 for action, _ in verify_rows if action == "regression_fail")

        pending_verify_hours: list[float] = []
        now = datetime.now()
        for bug in base.filter(Bug.status == "已修复").all():
            entered = (
                db.query(func.max(BugActivity.created_at))
                .filter(
                    BugActivity.bug_id == bug.id,
                    BugActivity.action.in_(("ready_for_regression", "external_resolved")),
                )
                .scalar()
            ) or bug.updated_at
            if entered:
                pending_verify_hours.append(max(0.0, (now - entered).total_seconds() / 3600))

        return {
            "project_id": project_id,
            "period_days": period_days,
            "backlog": backlog,
            "first_confirm_hours_avg": (
                round(sum(confirm_hours) / len(confirm_hours), 2) if confirm_hours else None
            ),
            "first_confirm_sample": len(confirm_hours),
            "pending_verify_hours_avg": (
                round(sum(pending_verify_hours) / len(pending_verify_hours), 2)
                if pending_verify_hours else None
            ),
            "pending_verify_sample": len(pending_verify_hours),
            "regression_total": regression_total,
            "regression_failed": regression_failed,
            "regression_failure_rate": (
                round(regression_failed / regression_total, 4) if regression_total else None
            ),
        }

    # ---------------------------------------------------------------- 活动事件

    def _record_activity(
        self, db: Session, *, bug: Bug, action: str, actor: User | None,
        old_status: str | None = None, new_status: str | None = None,
        note: str | None = None, detail: dict | None = None,
        actor_type: str = "INTERNAL", actor_name: str | None = None,
    ) -> BugActivity:
        # 活动说明与附加详情都可能被人工粘贴凭证，写库前统一脱敏。
        cleaned_note = sanitize_text((note or "").strip()) or None
        row = BugActivity(
            bug_id=bug.id,
            project_id=bug.project_id,
            actor_id=actor.id if actor else None,
            actor_name=actor_name or (actor.username if actor else None),
            actor_type=actor_type,
            action=action,
            old_status=old_status,
            new_status=new_status,
            note=cleaned_note,
            detail=sanitize_context(detail) if detail else None,
        )
        db.add(row)
        db.flush()
        return row

    def list_activities(self, db: Session, bug: Bug) -> list[BugActivity]:
        return (
            db.query(BugActivity)
            .filter(BugActivity.bug_id == bug.id)
            .order_by(BugActivity.id.desc())
            .all()
        )

    def _check_version(self, db: Session, bug: Bug, expected_version: int | None) -> None:
        """乐观并发：版本不一致时返回 409 与最新缺陷数据，页面保留未提交说明。"""
        if expected_version is not None and expected_version != bug.record_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": CODE_CONFLICT,
                    "message": f"缺陷已被他人更新（当前记录版本 {bug.record_version}），请核对最新状态后重试",
                    "meta": {"record_version": bug.record_version, "status": bug.status,
                             "status_display": status_display(bug.status)},
                },
            )

    # ---------------------------------------------------------------- 写入

    def _build_bug(
        self,
        *,
        project_id: int,
        actor: User,
        item: BugBase,
        is_draft: bool = False,
    ) -> Bug:
        """根据请求契约构造 Bug ORM 实例；新单统一进入待确认队列。"""
        return Bug(
            project_id=project_id,
            title=item.title.strip(),
            category=item.category,
            description=(item.description or "").strip() or None,
            expected_result=(item.expected_result or "").strip() or None,
            actual_result=(item.actual_result or "").strip() or None,
            api_method=item.api_method,
            api_url=(item.api_url or "").strip() or None,
            # 请求头在写库前脱敏：新建、批量与编辑统一走这里，避免原凭证落库。
            api_request_headers=mask_header_text((item.api_request_headers or "").strip() or None),
            api_request_body=(item.api_request_body or "").strip() or None,
            api_response=(item.api_response or "").strip() or None,
            severity=item.severity or 2,
            priority=item.priority or 2,
            status="待确认",
            steps_to_reproduce=(item.steps_to_reproduce or "").strip() or None,
            environment=(item.environment or "").strip() or None,
            affected_version=(item.affected_version or "").strip() or None,
            reporter_id=actor.id,
            is_draft=is_draft,
        )

    def _notify_created(
        self, db: Session, *, bug: Bug, project_id: int, actor: User
    ) -> None:
        """写入缺陷创建站内通知；复用 notify 的吞异常约定不阻断主事务。"""
        category_part = f"归属：{bug.category}；" if bug.category else ""
        notify(
            db,
            user_id=actor.id,
            event_type="defect.created",
            title=f"你已创建缺陷「{bug.title}」",
            body=(
                f"{category_part}"
                f"严重度：{SEVERITY_LABELS.get(bug.severity, str(bug.severity))}；"
                f"状态：{status_display(bug.status)}"
            ),
            project_id=project_id,
            actor_id=actor.id,
            actor_username=actor.username,
            detail={
                "bug_id": bug.id,
                "project_id": project_id,
                "category": bug.category,
            },
        )

    def _request_digest(self, body: BugCreate) -> str:
        payload = body.model_dump(exclude={"request_key"}, mode="json")
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def create_bug(self, db: Session, body: BugCreate, *, actor: User, commit: bool = True) -> Bug:
        """新增缺陷；创建者成为报告人，新单自动进入待确认队列。

        携带 request_key 时按项目幂等：同键同内容返回已创建缺陷，
        同键不同内容返回 409，避免创建超时重试导致重复建单。
        """
        project = get_project_or_404(db, body.project_id, actor)
        check_writable(db, project, actor)

        if not body.title.strip():
            raise bad_request("缺陷标题不能为空")

        template = CONFIG_SERVICE.active_config(db, project.id)
        if template:
            for field, value in (template.get("defaults") or {}).items():
                if field in ("category", "environment", "affected_version", "severity", "priority"):
                    if getattr(body, field, None) in (None, ""):
                        setattr(body, field, value)
            missing = [
                field for field in template.get("required_on_create", [])
                if not body.is_draft
                and (getattr(body, field, None) is None
                     or (isinstance(getattr(body, field), str) and not getattr(body, field).strip()))
            ]
            if missing:
                raise bad_request("项目模板要求填写：" + "、".join(missing))

        digest = self._request_digest(body) if body.request_key else None
        if body.request_key:
            existing = (
                db.query(Bug)
                .filter(Bug.project_id == project.id, Bug.request_key == body.request_key)
                .first()
            )
            if existing is not None:
                if existing.request_digest != digest:
                    raise conflict("请求键已用于其他创建请求，请核对后重试")
                # 幂等重放不能把别人的草稿返回给当前用户。
                if existing.is_draft and existing.reporter_id != actor.id:
                    raise conflict("请求键已用于其他创建请求，请核对后重试")
                return existing

        bug = self._build_bug(project_id=project.id, actor=actor, item=body, is_draft=body.is_draft)
        bug.request_key = body.request_key
        bug.request_digest = digest
        db.add(bug)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            winner = (
                db.query(Bug)
                .filter(Bug.project_id == project.id, Bug.request_key == body.request_key)
                .first()
            )
            if winner is not None:
                if winner.is_draft and winner.reporter_id != actor.id:
                    raise conflict("创建请求并发冲突，请刷新后重试")
                if winner.request_digest == digest:
                    return winner
            raise conflict("创建请求并发冲突，请刷新后重试")

        self._record_activity(
            db, bug=bug, action="created", actor=actor,
            new_status=bug.status,
            detail={"is_draft": bug.is_draft},
        )
        if not bug.is_draft:
            self._notify_created(db, bug=bug, project_id=project.id, actor=actor)

        if commit:
            db.commit()
            db.refresh(bug)
        return bug

    def submit_draft(self, db: Session, bug: Bug, *, actor: User) -> Bug:
        """提交草稿：进入待确认队列并补记创建通知。"""
        bug = self._lock_bug(db, bug)
        if bug.is_draft and bug.reporter_id != actor.id:
            raise not_found("缺陷不存在")
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        check_writable(db, project, actor)
        if not bug.is_draft:
            return bug
        template = CONFIG_SERVICE.active_config(db, bug.project_id)
        if template:
            missing = [
                field for field in template.get("required_on_create", [])
                if getattr(bug, field, None) is None
                or (isinstance(getattr(bug, field), str) and not getattr(bug, field).strip())
            ]
            if missing:
                raise bad_request("项目模板要求提交前补齐：" + "、".join(missing))
        bug.is_draft = False
        bug.record_version += 1
        db.flush()
        self._record_activity(
            db, bug=bug, action="created", actor=actor,
            new_status=bug.status, detail={"submitted_draft": True},
        )
        self._notify_created(db, bug=bug, project_id=bug.project_id, actor=actor)
        db.commit()
        db.refresh(bug)
        return bug

    def create_bugs_in_transaction(
        self,
        db: Session,
        *,
        project: Project,
        items: list[BugBase],
        actor: User,
        activity_detail: dict | None = None,
    ) -> list[Bug]:
        """在调用方事务中批量写入缺陷、活动事件与站内通知（不自行 commit）。

        用于批量创建接口和 Excel 导入确认共用同一套建单与校验逻辑；
        调用方负责在同事务中提交回执或在失败时整体回滚。
        """
        row_errors: list[dict[str, object]] = []
        for row_no, item in enumerate(items, start=1):
            if not item.title.strip():
                row_errors.append({
                    "row": row_no,
                    "field": "title",
                    "message": "缺陷标题不能为空",
                })
            if item.category is not None and item.category not in BUG_CATEGORIES:
                row_errors.append({
                    "row": row_no,
                    "field": "category",
                    "message": "前后端划分必须是「前端」「前后端」或「接口」",
                })

        if row_errors:
            preview_lines = [
                f"第 {err['row']} 行：{err['message']}" for err in row_errors[:5]
            ]
            if len(row_errors) > 5:
                preview_lines.append(f"另有 {len(row_errors) - 5} 处错误")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": CODE_BAD_REQUEST,
                    "message": "批量创建校验失败：" + "；".join(preview_lines),
                    "meta": {"errors": row_errors},
                },
            )

        bugs = [
            self._build_bug(project_id=project.id, actor=actor, item=item)
            for item in items
        ]
        db.add_all(bugs)
        # 事务边界：先 flush 分配缺陷主键，再写入同事务的活动事件与通知。
        db.flush()
        for bug in bugs:
            self._record_activity(
                db,
                bug=bug,
                action="created",
                actor=actor,
                new_status=bug.status,
                detail=activity_detail,
            )
            self._notify_created(db, bug=bug, project_id=project.id, actor=actor)
        return bugs

    def batch_create_bugs(
        self, db: Session, body: BugBatchCreate, *, actor: User
    ) -> list[Bug]:
        """同一项目下原子批量创建；任意一行失败整批不落库并返回行号定位。"""
        # 权限判定：校验目标项目可见且当前用户至少具备 member 写权限。
        project = get_project_or_404(db, body.project_id, actor)
        check_writable(db, project, actor)
        bugs = self.create_bugs_in_transaction(db, project=project, items=body.items, actor=actor)
        # 事务边界：保留原批量创建 API 的独立提交行为。
        db.commit()
        for bug in bugs:
            db.refresh(bug)
        return bugs

    def update_bug(
        self, db: Session, bug: Bug, body: BugUpdate, *, actor: User
    ) -> Bug:
        """修改事实字段；状态与处理人入参已在契约层停用。"""
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        check_writable(db, project, actor)
        # 先锁行并刷新，再比较版本：两个会话基于同一版本编辑时只有一个能通过。
        bug = self._lock_bug(db, bug)
        self._check_version(db, bug, body.expected_version)

        data = body.model_dump(exclude_unset=True)
        data.pop("expected_version", None)
        # 旧客户端显式传空值表示兼容清空，直接忽略，不落库。
        data.pop("assignee_id", None)
        data.pop("status", None)
        if not data:
            return bug

        if "title" in data:
            cleaned_title = (data["title"] or "").strip()
            if not cleaned_title:
                raise bad_request("缺陷标题不能为空")
            data["title"] = cleaned_title
        for field in ("description", "expected_result", "actual_result", "steps_to_reproduce",
                      "environment", "affected_version", "api_url", "api_request_headers",
                      "api_request_body", "api_response"):
            if field in data and isinstance(data[field], str):
                data[field] = data[field].strip() or None
        if "api_request_headers" in data:
            data["api_request_headers"] = mask_header_text(data["api_request_headers"])

        changed = [field for field, value in data.items() if getattr(bug, field) != value]
        for field, value in data.items():
            setattr(bug, field, value)
        if changed:
            bug.record_version += 1
        db.flush()
        if changed:
            self._record_activity(
                db, bug=bug, action="updated", actor=actor,
                detail={"fields": changed},
            )
        db.commit()
        db.refresh(bug)
        return bug

    # ---------------------------------------------------------------- 队列动作

    def perform_action(
        self, db: Session, bug: Bug, body: BugActionRequest, *, actor: User
    ) -> tuple[Bug, BugActivity]:
        """执行队列动作：校验权限、当前状态与记录版本，状态与活动事件同事务提交。"""
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        check_writable(db, project, actor)

        locked = self._lock_bug(db, bug)
        if locked.archived_at is not None:
            raise conflict("已归档缺陷不能执行队列动作，请先撤销归档")
        if locked.is_draft:
            raise conflict("草稿尚未提交，请先提交缺陷再执行队列动作")
        self._check_version(db, locked, body.expected_version)

        allowed_from, new_status = ACTION_TRANSITIONS[body.action]
        if locked.status not in allowed_from:
            raise conflict(
                f"当前状态为「{status_display(locked.status)}」，不能执行"
                f"「{ACTION_LABELS.get(body.action, body.action)}」"
            )

        note = (body.note or "").strip() or None
        detail: dict = {}

        if body.action == "confirm":
            patch = {
                field: getattr(body, field)
                for field in ("severity", "priority", "steps_to_reproduce", "expected_result",
                              "actual_result", "environment", "affected_version")
                if getattr(body, field) is not None
            }
            for field, value in patch.items():
                setattr(locked, field, (value.strip() or None) if isinstance(value, str) else value)
            if patch:
                detail["patch"] = {
                    key: value for key, value in patch.items()
                }
            template = CONFIG_SERVICE.active_config(db, locked.project_id)
            if template:
                missing = [
                    field for field in template.get("required_on_confirm", [])
                    if getattr(locked, field, None) is None
                    or (isinstance(getattr(locked, field), str) and not getattr(locked, field).strip())
                ]
                if missing:
                    raise bad_request("项目模板要求确认时补齐：" + "、".join(missing))
        elif body.action == "ready_for_regression":
            fix_version = (body.fix_version or "").strip()
            if not fix_version:
                raise bad_request("请填写可回归的版本、构建或环境")
            locked.fix_version = fix_version
            detail["fix_version"] = fix_version
            if body.feedback_source:
                detail["feedback_source"] = body.feedback_source.strip()
        elif body.action == "regression_pass":
            if not note:
                raise bad_request("请填写验证结论")
            if body.verification_execution_id is not None:
                detail["verification_execution_id"] = body.verification_execution_id
            if body.verification_environment:
                detail["verification_environment"] = body.verification_environment.strip()
        elif body.action == "regression_fail":
            if not note:
                raise bad_request("请填写回归失败原因")
            if body.verification_execution_id is not None:
                detail["verification_execution_id"] = body.verification_execution_id
            if body.verification_environment:
                detail["verification_environment"] = body.verification_environment.strip()
        elif body.action == "reject":
            if not note:
                raise bad_request("请填写拒绝原因")
        elif body.action == "mark_duplicate":
            if body.duplicate_of_bug_id is None:
                raise bad_request("请选择同项目的主单")
            if body.duplicate_of_bug_id == locked.id:
                raise bad_request("主单不能是缺陷自身")
            target = self.get_bug_or_404(db, body.duplicate_of_bug_id, actor)
            if target.project_id != locked.project_id:
                raise bad_request("主单必须属于同一项目")
            locked.duplicate_of_bug_id = target.id
            detail["duplicate_of_bug_id"] = target.id
        elif body.action == "reopen":
            if not note:
                raise bad_request("请填写重开依据（新版本或新证据）")

        old_status = locked.status
        locked.status = new_status
        locked.record_version += 1
        db.flush()

        activity = self._record_activity(
            db, bug=locked, action=body.action, actor=actor,
            old_status=old_status, new_status=new_status, note=note, detail=detail,
        )

        if locked.reporter_id is not None:
            notify(
                db,
                user_id=locked.reporter_id,
                event_type="defect.status_changed",
                title=f"你报告的缺陷「{locked.title}」状态已变更为「{status_display(new_status)}」",
                project_id=locked.project_id,
                actor_id=actor.id,
                actor_username=actor.username,
                detail={
                    "bug_id": locked.id,
                    "project_id": locked.project_id,
                    "old_status": old_status,
                    "new_status": new_status,
                    "action": body.action,
                },
            )

        db.commit()
        db.refresh(locked)
        db.refresh(activity)
        return locked, activity

    def apply_external_repair(
        self, db: Session, bug: Bug, *, display_name: str | None,
    ) -> tuple[str, str, bool]:
        """把免登录分享提交映射为已修复（待验证）。不提交事务，也不伪造内部用户。

        已关闭和已拒绝不能被公开链接改回。已经是已修复时不产生新的状态变化。
        调用方负责在同一事务里写外部处理记录。

        Returns:
            (old_status, new_status, changed)
        """
        locked = self._lock_bug(db, bug)
        if locked.status in {"已关闭", "已拒绝"}:
            raise conflict("当前缺陷状态不允许通过分享链接修改")
        old_status = locked.status
        if old_status == "已修复":
            return old_status, old_status, False
        locked.status = "已修复"
        locked.record_version += 1
        db.flush()
        actor_name = f"{display_name}（免登录分享，未经认证）" if display_name else "免登录分享链接"
        self._record_activity(
            db, bug=locked, action="external_resolved", actor=None,
            old_status=old_status, new_status="已修复",
            actor_type="EXTERNAL_SHARE", actor_name=actor_name,
            detail={"actor_type": "EXTERNAL_SHARE"},
        )
        detail = {
            "bug_id": locked.id,
            "project_id": locked.project_id,
            "old_status": old_status,
            "new_status": "已修复",
            "actor_type": "EXTERNAL_SHARE",
        }
        if locked.reporter_id:
            notify(
                db,
                user_id=locked.reporter_id,
                event_type="defect.external_resolved",
                title=f"缺陷「{locked.title}」已由外部反馈标记为待验证",
                body="该操作来自免登录分享链接，姓名未经平台认证。请回归验证后再关闭缺陷。",
                project_id=locked.project_id,
                actor_id=None,
                actor_username=actor_name,
                detail=detail,
            )
        return old_status, locked.status, True

    # ---------------------------------------------------------------- 归档

    def _check_archive_role(self, db: Session, project: Project, actor: User) -> None:
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_EDITOR):
            raise forbidden("归档与撤销归档需要项目管理员权限")

    def _revoke_active_shares(self, db: Session, bug_id: int) -> int:
        """归档时终止单条与批次内的公开访问：撤销全部有效分享。"""
        now = datetime.now()
        shares = (
            db.query(DefectShareLink)
            .filter(
                DefectShareLink.bug_id == bug_id,
                DefectShareLink.revoked_at.is_(None),
                DefectShareLink.archived_at.is_(None),
            )
            .all()
        )
        for share in shares:
            share.revoked_at = now
        return len(shares)

    def archive_bug(self, db: Session, bug: Bug, *, actor: User, reason: str, commit: bool = True) -> Bug:
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        check_writable(db, project, actor)
        self._check_archive_role(db, project, actor)
        cleaned = (reason or "").strip()
        if not cleaned:
            raise bad_request("请填写归档原因")
        bug = self._lock_bug(db, bug)
        if bug.archived_at is not None:
            raise conflict("缺陷已归档")
        bug.archived_at = datetime.now()
        bug.archived_by = actor.id
        bug.archive_reason = cleaned
        bug.record_version += 1
        revoked = self._revoke_active_shares(db, bug.id)
        db.flush()
        self._record_activity(
            db, bug=bug, action="archive", actor=actor,
            note=cleaned, detail={"revoked_shares": revoked},
        )
        if commit:
            db.commit()
            db.refresh(bug)
        return bug

    def restore_bug(self, db: Session, bug: Bug, *, actor: User, commit: bool = True) -> Bug:
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        check_writable(db, project, actor)
        self._check_archive_role(db, project, actor)
        bug = self._lock_bug(db, bug)
        if bug.archived_at is None:
            raise conflict("缺陷未归档")
        bug.archived_at = None
        bug.archived_by = None
        bug.archive_reason = None
        bug.record_version += 1
        db.flush()
        self._record_activity(db, bug=bug, action="restore", actor=actor)
        if commit:
            db.commit()
            db.refresh(bug)
        return bug

    def batch_action(
        self, db: Session, *, actor: User, project_id: int, ids: list[int],
        action: str, priority: int | None, reason: str | None,
    ) -> dict:
        """批量治理动作；每条独立校验，部分失败返回逐项结果。"""
        project = get_project_or_404(db, project_id, actor)
        check_writable(db, project, actor)
        if action == "set_priority" and priority is None:
            raise bad_request("请选择目标优先级")
        if action == "archive" and not (reason or "").strip():
            raise bad_request("请填写归档原因")

        items: list[dict] = []
        for bug_id in dict.fromkeys(ids):
            try:
                with db.begin_nested():
                    bug = self.get_bug_or_404(db, bug_id, actor)
                    if bug.project_id != project_id:
                        raise not_found("缺陷不存在")
                    # 批量改优先级同样先锁行，避免与逐条编辑互相覆盖版本。
                    bug = self._lock_bug(db, bug)
                    if action == "set_priority":
                        if bug.archived_at is not None:
                            raise conflict("已归档缺陷不能调整优先级")
                        if bug.priority != priority:
                            bug.priority = priority
                            bug.record_version += 1
                            db.flush()
                            self._record_activity(
                                db, bug=bug, action="updated", actor=actor,
                                detail={"fields": ["priority"]},
                            )
                    elif action == "archive":
                        self.archive_bug(db, bug, actor=actor, reason=reason or "", commit=False)
                    elif action == "restore":
                        self.restore_bug(db, bug, actor=actor, commit=False)
                    else:
                        raise bad_request("不支持的批量动作")
                items.append({"id": bug_id, "succeeded": True, "error": None})
            except HTTPException as exc:
                message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
                items.append({"id": bug_id, "succeeded": False, "error": message})
        db.commit()
        succeeded = sum(1 for item in items if item["succeeded"])
        return {"succeeded": succeeded, "failed": len(items) - succeeded, "items": items}

    def delete_bug(self, db: Session, bug: Bug, *, actor: User) -> None:
        """删除缺陷；至少 member。"""
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        check_writable(db, project, actor)
        delete_resource(db, "bug", bug.id, actor=actor)