"""缺陷服务层。

路由层只做参数、认证与响应映射；所有业务、权限与事务集中在这里。

权限模型（对齐旧项目 ROLE_MEMBER 语义）：
- 读：对该 project 有可见性即可（viewer+ 或 platform admin）
- 写（增/改/删）：至少 project member；对齐 has_project_role(role, "member")
- 越权与不存在共用 404，避免泄露他人缺陷的存在性

事务约定：service 层负责 commit；router 层不 commit。

回归关联、通知渠道推送、趋势统计等能力未接入，属后续阶段。
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.features.defects.models.bug import Bug
from app.features.defects.schemas import (
    BUG_CATEGORIES,
    BUG_STATUSES,
    BugBase,
    BugBatchCreate,
    BugCreate,
    BugUpdate,
    SEVERITY_LABELS,
    UNCATEGORIZED_BUG_CATEGORY,
)
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.http.errors import (
    CODE_BAD_REQUEST,
    bad_request,
    conflict,
    forbidden,
    not_found,
)
from app.core.notifications.notify import notify
from app.platform.projects.services.access_service import check_writable, get_project_or_404
from app.core.security.roles import (
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    accessible_project_ids,
    has_project_role,
    project_role_for,
)
from app.lifecycle.service import delete_resource


class DefectService:
    """缺陷服务。无状态，可跨模块复用。"""

    # ---------------------------------------------------------------- 可见性


    def get_bug_or_404(self, db: Session, bug_id: int, user: User) -> Bug:
        """按 ID 取缺陷并校验可见性；越权与不存在共用 404。"""
        bug = db.get(Bug, bug_id)
        if bug is None:
            raise not_found("缺陷不存在")
        visible_ids = accessible_project_ids(db, user)
        # 平台管理员不受过滤；其余用户按可见项目集合判断。
        if visible_ids is not None and bug.project_id not in visible_ids:
            raise not_found("缺陷不存在")
        return bug

    # ---------------------------------------------------------------- 查询

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
        assignee_id: int | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Bug], int]:
        """按当前用户可见范围与过滤条件分页查询缺陷。

        Args:
            project_id: 可选的项目过滤；传入后先校验该项目的可见性，
                不可见时直接返回空列表（不抛 404，因为列表接口语义是「没有」而非「无权」）。
            category / status / severity / assignee_id: 精确过滤（category 为「未划分」时匹配 NULL）。
            keyword: 对 title 做不区分大小写的模糊匹配。

        Returns:
            (items, total)：当前页数据与总条数。
        """
        query = db.query(Bug)
        visible_ids = accessible_project_ids(db, user)

        if visible_ids is not None:
            # 非平台管理员：先把可见集合限定住，空集合用 [-1] 占位避免 IN () 退化成全表。
            if project_id is not None:
                if project_id not in visible_ids:
                    return [], 0
                query = query.filter(Bug.project_id == project_id)
            else:
                query = query.filter(Bug.project_id.in_(visible_ids or [-1]))
        elif project_id is not None:
            query = query.filter(Bug.project_id == project_id)

        if category:
            if category == UNCATEGORIZED_BUG_CATEGORY:
                # 历史存量缺陷 category 为空，用「未划分」显式筛选 NULL 行。
                query = query.filter(Bug.category.is_(None))
            elif category in BUG_CATEGORIES:
                query = query.filter(Bug.category == category)
            else:
                raise bad_request("前后端划分取值非法")
        if status:
            if status not in BUG_STATUSES:
                raise bad_request("状态取值非法")
            query = query.filter(Bug.status == status)
        if severity is not None:
            if severity not in SEVERITY_LABELS:
                raise bad_request("严重度取值非法")
            query = query.filter(Bug.severity == severity)
        if assignee_id is not None:
            query = query.filter(Bug.assignee_id == assignee_id)
        if keyword:
            keyword = keyword.strip()
            if keyword:
                query = query.filter(Bug.title.ilike(f"%{keyword}%"))

        total = int(query.count())
        items = (
            query.order_by(Bug.id.desc())
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

    # ---------------------------------------------------------------- 写入


    def _validate_assignee(self, db: Session, project: Project, assignee_id: int) -> User:
        """校验处理人：必须存在、启用且为该项目成员；返回用户对象。"""
        assignee = db.get(User, assignee_id)
        if assignee is None or not assignee.is_active:
            raise bad_request("处理人不存在或已停用")
        if project_role_for(db, project, assignee) is None:
            raise bad_request("处理人必须是该项目成员")
        return assignee

    def _build_bug(
        self,
        *,
        project_id: int,
        actor: User,
        item: BugBase,
        assignee_id: int | None,
    ) -> Bug:
        """根据请求契约构造 Bug ORM 实例，统一空白裁剪与默认值规则。"""
        return Bug(
            project_id=project_id,
            title=item.title.strip(),
            category=item.category,
            description=(item.description or "").strip() or None,
            severity=item.severity,
            status=item.status,
            steps_to_reproduce=(item.steps_to_reproduce or "").strip() or None,
            environment=(item.environment or "").strip() or None,
            reporter_id=actor.id,
            assignee_id=assignee_id,
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
                f"状态：{bug.status}"
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

    def create_bug(self, db: Session, body: BugCreate, *, actor: User, commit: bool = True) -> Bug:
        """新增缺陷；创建者成为报告人。"""
        project = get_project_or_404(db, body.project_id, actor)
        check_writable(db, project, actor)

        if not body.title.strip():
            raise bad_request("缺陷标题不能为空")

        # 创建时若直接指定处理人，走与更新相同的校验；报告人本身默认可作为处理人。
        if body.assignee_id is not None and body.assignee_id != actor.id:
            self._validate_assignee(db, project, body.assignee_id)

        bug = self._build_bug(
            project_id=project.id,
            actor=actor,
            item=body,
            assignee_id=body.assignee_id,
        )
        db.add(bug)
        db.flush()  # 先落库拿到 ID，便于通知 detail 引用。

        # 通知：报告人自己确认收到（对齐 user.created 的自我通知模式）。
        self._notify_created(db, bug=bug, project_id=project.id, actor=actor)

        if commit:
            db.commit()
            db.refresh(bug)
        return bug

    def batch_create_bugs(
        self, db: Session, body: BugBatchCreate, *, actor: User
    ) -> list[Bug]:
        """同一项目下原子批量创建缺陷；任意一行失败则整批不落库并返回行号定位。"""
        project = get_project_or_404(db, body.project_id, actor)
        check_writable(db, project, actor)

        row_errors: list[dict[str, object]] = []
        # 缓存已校验过的处理人结果，避免同一批次多行指向同一处理人时重复查库。
        assignee_error_cache: dict[int, str | None] = {}

        for row_no, item in enumerate(body.items, start=1):
            if not item.title.strip():
                row_errors.append({
                    "row": row_no,
                    "field": "title",
                    "message": "缺陷标题不能为空",
                })
            if item.category not in BUG_CATEGORIES:
                row_errors.append({
                    "row": row_no,
                    "field": "category",
                    "message": "前后端划分必须是「前端」或「后端」",
                })
            if item.assignee_id is not None and item.assignee_id != actor.id:
                if item.assignee_id not in assignee_error_cache:
                    try:
                        self._validate_assignee(db, project, item.assignee_id)
                        assignee_error_cache[item.assignee_id] = None
                    except HTTPException as exc:
                        assignee_error_cache[item.assignee_id] = str(exc.detail)
                cached_error = assignee_error_cache[item.assignee_id]
                if cached_error:
                    row_errors.append({
                        "row": row_no,
                        "field": "assignee_id",
                        "message": cached_error,
                    })

        if row_errors:
            # 任意一行不合法即在写库前中断，确保整批原子语义并返回精确定位信息。
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
            self._build_bug(
                project_id=project.id,
                actor=actor,
                item=item,
                assignee_id=item.assignee_id,
            )
            for item in body.items
        ]
        db.add_all(bugs)
        db.flush()  # 一次性生成全部主键，再统一写入站内通知。
        for bug in bugs:
            self._notify_created(db, bug=bug, project_id=project.id, actor=actor)
        db.commit()
        for bug in bugs:
            db.refresh(bug)
        return bugs

    def update_bug(
        self, db: Session, bug: Bug, body: BugUpdate, *, actor: User
    ) -> Bug:
        """修改缺陷；至少 member。跟踪 status 与 assignee 变化并触发通知。"""
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        check_writable(db, project, actor)

        old_status = bug.status
        old_assignee_id = bug.assignee_id

        # exclude_unset 保证「未提交」与「提交为 None」语义不同：后者才清空处理人。
        data = body.model_dump(exclude_unset=True)
        if not data:
            return bug

        if "title" in data:
            cleaned_title = (data["title"] or "").strip()
            if not cleaned_title:
                raise bad_request("缺陷标题不能为空")
            data["title"] = cleaned_title

        # 处理人变更：新值必须为 None 或合法的项目成员。
        if "assignee_id" in data and data["assignee_id"] is not None:
            self._validate_assignee(db, project, data["assignee_id"])

        for field, value in data.items():
            setattr(bug, field, value)
        db.flush()

        # 通知：状态变化 → 通知报告人；处理人变化 → 通知新处理人。
        if "status" in data and data["status"] != old_status and bug.reporter_id is not None:
            notify(
                db,
                user_id=bug.reporter_id,
                event_type="defect.status_changed",
                title=f"你报告的缺陷「{bug.title}」状态已变更为「{data['status']}」",
                project_id=bug.project_id,
                actor_id=actor.id,
                actor_username=actor.username,
                detail={
                    "bug_id": bug.id,
                    "project_id": bug.project_id,
                    "old_status": old_status,
                    "new_status": data["status"],
                },
            )

        new_assignee_id = data.get("assignee_id", old_assignee_id)
        if (
            "assignee_id" in data
            and new_assignee_id != old_assignee_id
            and new_assignee_id is not None
        ):
            notify(
                db,
                user_id=new_assignee_id,
                event_type="defect.assigned",
                title=f"有新的缺陷分配给你：「{bug.title}」",
                body=f"严重度：{SEVERITY_LABELS.get(bug.severity, str(bug.severity))}；状态：{bug.status}",
                project_id=bug.project_id,
                actor_id=actor.id,
                actor_username=actor.username,
                detail={"bug_id": bug.id, "project_id": bug.project_id},
            )

        db.commit()
        db.refresh(bug)
        return bug

    def apply_external_repair(
        self, db: Session, bug: Bug, *, display_name: str | None,
    ) -> tuple[str, str, bool]:
        """把免登录分享提交映射为已修复。不提交事务，也不伪造内部用户。

        已关闭和已拒绝不能被公开链接改回。已经是已修复时不产生新的状态变化。
        调用方负责在同一事务里写外部处理记录。

        Returns:
            (old_status, new_status, changed)
        """
        locked = db.query(Bug).filter(Bug.id == bug.id).with_for_update().one()
        # 公开链接不能越过测试关闭或拒绝结论。
        if locked.status in {"已关闭", "已拒绝"}:
            raise conflict("当前缺陷状态不允许通过分享链接修改")
        old_status = locked.status
        if old_status == "已修复":
            return old_status, old_status, False
        locked.status = "已修复"
        db.flush()
        actor_name = f"{display_name}（免登录分享，未经认证）" if display_name else "免登录分享链接"
        detail = {
            "bug_id": locked.id,
            "project_id": locked.project_id,
            "old_status": old_status,
            "new_status": "已修复",
            "actor_type": "EXTERNAL_SHARE",
        }
        recipients: list[int] = []
        if locked.reporter_id:
            recipients.append(locked.reporter_id)
        if locked.assignee_id and locked.assignee_id not in recipients:
            recipients.append(locked.assignee_id)
        for user_id in recipients:
            notify(
                db,
                user_id=user_id,
                event_type="defect.external_resolved",
                title=f"缺陷「{locked.title}」已由开发人员标记为已修复",
                body="该操作来自免登录分享链接，姓名未经平台认证。请回归验证后再关闭缺陷。",
                project_id=locked.project_id,
                actor_id=None,
                actor_username=actor_name,
                detail=detail,
            )
        return old_status, locked.status, True

    def delete_bug(self, db: Session, bug: Bug, *, actor: User) -> None:
        """删除缺陷；至少 member。"""
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        check_writable(db, project, actor)
        delete_resource(db, "bug", bug.id, actor=actor)
