"""项目服务层。

路由层只做参数、认证与响应映射；所有业务与事务集中在这里。
与旧项目的差异：
- 可见性统一走 roles.accessible_project_ids，补上旧实现遗漏的组织边界前置校验
- 成员变更、负责人转移、组织归属变更**不**递增 token_version：令牌撤销只发生在
  users 模块与 shared.auth，项目权限变化不会让已签发令牌立刻失效
- 列表统一分页信封，默认按 ID 降序
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.platform.projects.schemas import (
    OutboundTargetCreate,
    ProjectCreate,
    ProjectMemberCreate,
    ProjectUpdate,
)
from app.core.models.identity import Organization, User
from app.core.models.project import Project, ProjectMember, ProjectOutboundTarget
from app.core.http.errors import bad_request, conflict, forbidden, not_found
from app.core.security.roles import (
    ORG_ADMIN_ROLES,
    PROJECT_ROLE_ADMIN,
    PROJECT_ROLE_EDITOR,
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    accessible_project_ids,
    has_project_role,
    is_org_admin,
    organization_role,
    project_role_for,
)


class ProjectAdminService:
    """项目与成员服务。无状态，可跨模块复用。"""

    # ---------------------------------------------------------------- 可见性

    def visible_projects_query(
        self, db: Session, user: User, *, org_id: int | None = None, keyword: str | None = None
    ):
        """构造当前用户可见项目的查询。

        Args:
            db: 数据库会话。
            user: 当前登录用户。
            org_id: 可选的组织过滤条件，用于列表页按组织筛选。
            keyword: 可选关键字，同时匹配名称、描述与数字 ID。

        Returns:
            未排序的 Project 查询对象，由调用方决定分页与排序。
        """
        query = db.query(Project)
        ids = accessible_project_ids(db, user)
        if ids is not None:
            # ids 为 None 表示平台管理员：不加过滤，可见全部项目；
            # 空列表用 [-1] 占位，保证查询不匹配任何行而不会退化成全表。
            query = query.filter(Project.id.in_(ids or [-1]))
        # 组织边界前置校验：非平台管理员即使拿到某个项目 ID，也只在可见集合内被允许访问。
        if org_id is not None:
            query = query.filter(Project.organization_id == org_id)
        if keyword:
            keyword = keyword.strip()
            query = query.filter(
                (Project.name.ilike(f"%{keyword}%"))
                | (Project.description.ilike(f"%{keyword}%"))
                | (Project.id == int(keyword) if keyword.isdigit() else False)
            )
        return query

    def get_or_404(self, db: Session, project_id: int) -> Project:
        """按 ID 取项目，不存在抛 404；不做任何可见性判断。"""
        project = db.get(Project, project_id)
        if project is None:
            raise not_found("项目不存在")
        return project


    @staticmethod
    def count_members(db: Session, project_id: int) -> int:
        """统计项目成员表行数，不包含负责人（负责人不占成员行）。"""
        return int(
            db.query(func.count(ProjectMember.id))
            .filter(ProjectMember.project_id == project_id)
            .scalar()
            or 0
        )

    # ---------------------------------------------------------------- 写入

    def create_project(self, db: Session, body: ProjectCreate, *, actor: User) -> Project:
        """创建项目；创建者自动成为负责人。"""
        name = body.name.strip()
        if len(name) < 2:
            raise bad_request("项目名称至少 2 个字符")
        if db.query(Project).filter(Project.name == name).first() is not None:
            raise conflict("项目名称已存在")

        organization_id = body.organization_id
        if organization_id is not None:
            organization = db.get(Organization, organization_id)
            if organization is None:
                raise not_found("组织不存在")
            # 非平台管理员只能把项目放到自己所在的组织中。
            if organization.owner_id != actor.id:
                role = organization_role(db, organization_id, actor)
                # 组织边界：跨组织挂载项目需要组织管理员身份，否则任何人都能往任意组织塞项目。
                if role not in ORG_ADMIN_ROLES:
                    raise forbidden("只能把项目创建到自己管理的组织中")

        project = Project(
            name=name,
            description=(body.description or "").strip() or None,
            owner_id=actor.id,
            organization_id=organization_id,
        )
        db.add(project)
        db.flush()
        # 新项目获得独立的环境配置副本，之后修改目标地址不会影响其他项目。
        from app.platform.environment_configuration.services.environment_service import ensure_project_environments

        ensure_project_environments(db, project.id, actor_id=actor.id)
        db.commit()  # 事务提交点：路由层不再自行 commit。
        db.refresh(project)
        return project

    def update_project(self, db: Session, project: Project, body: ProjectUpdate, *, actor: User) -> Project:
        """更新项目字段；负责人变更额外要求编辑权限。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_EDITOR):
            raise forbidden("需要项目编辑权限")

        # exclude_unset 保证「字段未提交」和「字段提交为 None」语义不同，后者才能清空。
        data = body.model_dump(exclude_unset=True)
        if not data:
            return project

        if "name" in data and data["name"]:
            name = data["name"].strip()
            if len(name) < 2:
                raise bad_request("项目名称至少 2 个字符")
            duplicate = (
                db.query(Project)
                .filter(Project.name == name, Project.id != project.id)
                .first()
            )
            if duplicate is not None:
                raise conflict("项目名称已存在")
            data["name"] = name

        if "description" in data and data["description"] is not None:
            data["description"] = data["description"].strip() or None

        if "organization_id" in data and data["organization_id"] is not None:
            organization = db.get(Organization, data["organization_id"])
            if organization is None:
                raise not_found("组织不存在")
            if organization.owner_id != actor.id:
                org_role = organization_role(db, organization.id, actor)
                # 跨组织转移同样受组织边界约束，防止把项目挪到自己无权管理的组织。
                if org_role not in ORG_ADMIN_ROLES:
                    raise forbidden("只能把项目转移到自己管理的组织")
            data["organization_id"] = organization.id
        elif "organization_id" in data:
            data["organization_id"] = None

        if "owner_id" in data and data["owner_id"] is not None:
            if data["owner_id"] != project.owner_id:
                owner = db.get(User, data["owner_id"])
                if owner is None or not owner.is_active:
                    raise not_found("目标负责人不存在或已停用")
                if project.organization_id is not None:
                    # 组织边界：新负责人必须已经在项目所属组织内，避免交出跨组织的控制权。
                    if organization_role(db, project.organization_id, owner) is None:
                        raise forbidden("新负责人必须是项目所属组织的成员")
                data["owner_id"] = owner.id

        for field, value in data.items():
            setattr(project, field, value)
        db.commit()
        db.refresh(project)
        return project

    def delete_project(self, db: Session, project: Project, *, actor: User) -> None:
        """删除项目；仅负责人或平台管理员可操作。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, "owner"):
            raise forbidden("只有项目负责人或管理员可以删除项目")
        db.delete(project)
        db.commit()

    # ---------------------------------------------------------------- 成员

    def page_members(self, db: Session, project: Project, *, page: int, page_size: int):
        """分页查询项目成员，负责人由 owner_id 推导不计入成员行。"""
        query = db.query(ProjectMember).filter(ProjectMember.project_id == project.id)
        total = int(query.count())
        items = (
            query.order_by(ProjectMember.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def upsert_member(
        self, db: Session, project: Project, body: ProjectMemberCreate, *, actor: User
    ) -> ProjectMember:
        """新增或更新项目成员角色。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_EDITOR):
            raise forbidden("需要项目编辑权限")

        target = db.get(User, body.user_id)
        if target is None or not target.is_active:
            raise not_found("成员用户不存在或已停用")
        if target.id == project.owner_id:
            raise bad_request("项目负责人不需要单独添加为成员")
        # 组织边界：项目归属某组织时，成员必须也在同一组织，跨组织用户一律拒绝。
        if project.organization_id is not None and organization_role(
            db, project.organization_id, target
        ) is None:
            raise forbidden("成员必须是项目所属组织的成员")

        row = (
            db.query(ProjectMember)
            .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == target.id)
            .first()
        )
        if row is None:
            row = ProjectMember(project_id=project.id, user_id=target.id, created_by=actor.id)
            db.add(row)
        row.role = body.role
        db.commit()
        db.refresh(row)
        # 说明：本模块的成员/负责人变更并不递增 token_version，
        # 令牌撤销只发生在 users 模块与 shared.auth，旧令牌不会因此立刻失效。
        return row

    def remove_member(self, db: Session, project: Project, user_id: int, *, actor: User) -> None:
        """移除项目成员；负责人不可移除。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_EDITOR):
            raise forbidden("需要项目编辑权限")
        if project.owner_id == user_id:
            raise bad_request("项目负责人不能移除；如需变更请使用负责人转移接口")
        row = (
            db.query(ProjectMember)
            .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id)
            .first()
        )
        if row is None:
            raise not_found("项目成员不存在")
        db.delete(row)
        db.commit()

    def transfer_owner(self, db: Session, project: Project, new_owner_id: int, *, actor: User) -> Project:
        """把项目负责人转移给另一名成员。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, "owner"):
            raise forbidden("只有项目负责人或管理员可以转移负责人")
        if project.owner_id == new_owner_id:
            return project

        new_owner = db.get(User, new_owner_id)
        if new_owner is None or not new_owner.is_active:
            raise not_found("目标负责人不存在或已停用")
        if project.organization_id is not None:
            # 与 add_member 同样的组织边界，避免把项目交给组织外的人。
            if organization_role(db, project.organization_id, new_owner) is None:
                raise forbidden("新负责人必须是项目所属组织的成员")

        project.owner_id = new_owner_id
        db.commit()
        db.refresh(project)
        return project

    # ---------------------------------------------------------------- 出站目标

    def list_outbound_targets(self, db: Session, project: Project) -> list[ProjectOutboundTarget]:
        """列出项目下全部出站目标，按 ID 升序，供执行侧读取白名单。"""
        return (
            db.query(ProjectOutboundTarget)
            .filter(ProjectOutboundTarget.project_id == project.id)
            .order_by(ProjectOutboundTarget.id)
            .all()
        )

    @staticmethod
    def _normalize_target(body: OutboundTargetCreate) -> tuple[str, str, int, bool]:
        """规范化出站目标四元组，任何非法输入直接抛 400。

        Returns:
            (scheme, host, port, is_production)，host 已去掉尾部斜杠。
        """
        scheme = body.scheme.lower()
        if scheme not in {"http", "https"}:
            raise bad_request("协议只能是 http 或 https")
        host = body.host.strip().rstrip("/")
        # 禁止带端口的旧写法，端口由 port 字段单独表达。
        if any(ch in host for ch in ":[]"):
            raise bad_request("主机名不能包含端口或方括号")
        if not host:
            raise bad_request("主机名不能为空")
        if len(host) > 253:
            raise bad_request("主机名过长")
        if body.is_production and scheme != "https":
            raise bad_request("生产目标必须使用 https")
        return scheme, host, body.port, body.is_production

    def create_outbound_target(
        self, db: Session, project: Project, body: OutboundTargetCreate, *, actor: User
    ) -> ProjectOutboundTarget:
        """新增项目出站目标；仅编辑权限及以上可操作。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_EDITOR):
            raise forbidden("需要项目编辑权限")

        scheme, host, port, is_production = self._normalize_target(body)
        exists = (
            db.query(ProjectOutboundTarget)
            .filter(
                ProjectOutboundTarget.project_id == project.id,
                ProjectOutboundTarget.scheme == scheme,
                ProjectOutboundTarget.host == host,
                ProjectOutboundTarget.port == port,
            )
            .first()
        )
        if exists is not None:
            # 幂等保护：四元组重复直接报冲突，而不是静默新增重复白名单条目。
            raise conflict("该目标已存在")

        row = ProjectOutboundTarget(
            project_id=project.id,
            scheme=scheme,
            host=host,
            port=port,
            is_production=is_production,
            enabled=True,
            approved_by=actor.id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def update_outbound_target(
        self, db: Session, project: Project, target: ProjectOutboundTarget, *, enabled: bool, actor: User
    ) -> ProjectOutboundTarget:
        """更新出站目标开关。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_EDITOR):
            raise forbidden("需要项目编辑权限")
        target.enabled = enabled
        db.commit()
        db.refresh(target)
        return target

    def delete_outbound_target(self, db: Session, project: Project, target: ProjectOutboundTarget, *, actor: User) -> None:
        """删除出站目标。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_EDITOR):
            raise forbidden("需要项目编辑权限")
        db.delete(target)
        db.commit()
