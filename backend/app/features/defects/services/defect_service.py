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

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.features.defects.models.bug import Bug
from app.features.defects.schemas import (
    BUG_STATUSES,
    BugCreate,
    BugUpdate,
    SEVERITY_LABELS,
)
from app.models.identity import User
from app.models.project import Project
from app.shared.errors import bad_request, forbidden, not_found
from app.shared.notify import notify
from app.shared.roles import (
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    accessible_project_ids,
    has_project_role,
    project_role_for,
)


class DefectService:
    """缺陷服务。无状态，可跨模块复用。"""

    # ---------------------------------------------------------------- 可见性

    def _get_project_or_404(self, db: Session, project_id: int, user: User) -> Project:
        """取项目并校验可见性；不可见与不存在共用 404。"""
        project = db.get(Project, project_id)
        if project is None:
            raise not_found("项目不存在")
        # 权限判定：至少 viewer；否则统一 404 隐藏项目存在性。
        if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
            raise not_found("项目不存在")
        return project

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
        status: str | None = None,
        severity: int | None = None,
        assignee_id: int | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Bug], int]:
        """按当前用户可见范围与过滤条件分页查询缺陷。

        Args:
            project_id: 可选的项目过滤；传入后先校验该项目的可见性，
                不可见时直接返回空列表（不抛 404，因为列表接口语义是「没有」而非「无权」）。
            status / severity / assignee_id: 精确过滤。
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

    def _check_writable(self, db: Session, project: Project, actor: User) -> None:
        """写操作权限校验：至少 project member。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_MEMBER):
            raise forbidden("需要项目成员权限")

    def _validate_assignee(self, db: Session, project: Project, assignee_id: int) -> User:
        """校验处理人：必须存在、启用且为该项目成员；返回用户对象。"""
        assignee = db.get(User, assignee_id)
        if assignee is None or not assignee.is_active:
            raise bad_request("处理人不存在或已停用")
        if project_role_for(db, project, assignee) is None:
            raise bad_request("处理人必须是该项目成员")
        return assignee

    def create_bug(self, db: Session, body: BugCreate, *, actor: User, commit: bool = True) -> Bug:
        """新增缺陷；创建者成为报告人。"""
        project = self._get_project_or_404(db, body.project_id, actor)
        self._check_writable(db, project, actor)

        # 创建时若直接指定处理人，走与更新相同的校验；报告人本身默认可作为处理人。
        if body.assignee_id is not None and body.assignee_id != actor.id:
            self._validate_assignee(db, project, body.assignee_id)

        bug = Bug(
            project_id=project.id,
            title=body.title.strip(),
            description=(body.description or "").strip() or None,
            severity=body.severity,
            status=body.status,
            steps_to_reproduce=(body.steps_to_reproduce or "").strip() or None,
            environment=(body.environment or "").strip() or None,
            reporter_id=actor.id,
            assignee_id=body.assignee_id,
        )
        db.add(bug)
        db.flush()  # 先落库拿到 ID，便于通知 detail 引用。

        # 通知：报告人自己确认收到（对齐 user.created 的自我通知模式）。
        notify(
            db,
            user_id=actor.id,
            event_type="defect.created",
            title=f"你已创建缺陷「{bug.title}」",
            body=f"严重度：{SEVERITY_LABELS.get(bug.severity, str(bug.severity))}；状态：{bug.status}",
            project_id=project.id,
            actor_id=actor.id,
            actor_username=actor.username,
            detail={"bug_id": bug.id, "project_id": project.id},
        )

        if commit:
            db.commit()
            db.refresh(bug)
        return bug

    def update_bug(
        self, db: Session, bug: Bug, body: BugUpdate, *, actor: User
    ) -> Bug:
        """修改缺陷；至少 member。跟踪 status 与 assignee 变化并触发通知。"""
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        self._check_writable(db, project, actor)

        old_status = bug.status
        old_assignee_id = bug.assignee_id

        # exclude_unset 保证「未提交」与「提交为 None」语义不同：后者才清空处理人。
        data = body.model_dump(exclude_unset=True)
        if not data:
            return bug

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

    def delete_bug(self, db: Session, bug: Bug, *, actor: User) -> None:
        """删除缺陷；至少 member。"""
        project = db.get(Project, bug.project_id)
        if project is None:
            raise not_found("缺陷所属项目不存在")
        self._check_writable(db, project, actor)
        db.delete(bug)
        db.commit()
