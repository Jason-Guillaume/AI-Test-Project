"""看板服务层。

所有统计都以「当前用户可见范围」为口径；响应体带 scope 字段说明统计范围，
避免把全局数字误当成个人指标展示。

项目、测试执行、报告与缺陷统计均直接读取现有业务表，并按当前用户可见项目过滤。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.features.dashboard.schemas import (
    DashboardOverviewResponse,
    DashboardChartsResponse,
    DashboardDailyCount,
    DashboardDefectSeverityItem,
    DashboardExecutionTrendItem,
    DashboardScopeResponse,
    ProjectSummaryItem,
    ProjectSummaryResponse,
    ReadyCheckItem,
    ReadyResponse,
    StatCard,
)
from app.features.defects.models.bug import Bug
from app.features.defects.schemas import SEVERITY_LABELS
from app.features.reports.models.report import TestReport
from app.features.test_management.models.execution import CaseExecution, TestRun
from app.features.test_management.models.test_case import TestCase
from app.models.configuration import Environment, ModelConfiguration
from app.models.identity import Organization, OrganizationMember, User
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.shared.errors import bad_request
from app.shared.roles import (
    accessible_organization_ids,
    accessible_project_ids,
    is_platform_admin,
    normalize_project_role,
    project_role_for,
)

def build_scope(db: Session, user: User) -> DashboardScopeResponse:
    """构造当前统计口径说明。"""
    # 可见边界：平台管理员返回 None 表示「不过滤」，本函数统一归一成空列表返回给前端。
    org_ids = accessible_organization_ids(db, user)
    project_ids = accessible_project_ids(db, user)
    return DashboardScopeResponse(
        subject="platform" if is_platform_admin(user) else "user",
        user_id=user.id,
        role=user.role or "test",
        is_platform_admin=is_platform_admin(user),
        organization_ids=sorted(org_ids) if org_ids is not None else [],
        project_ids=sorted(project_ids) if project_ids is not None else [],
    )


def project_visible_query(db: Session, user: User):
    """构造当前用户可见项目的查询。"""
    query = db.query(Project)
    # ids 为 None 代表平台管理员：保持无过滤，即可看到全部项目。
    ids = accessible_project_ids(db, user)
    if ids is not None:
        # 可见集合为空时用 [-1] 造一个必然不命中的条件，避免空 IN () 退化成「不过滤」。
        query = query.filter(Project.id.in_(ids or [-1]))
    return query


def _member_count(db: Session, project_id: int) -> int:
    """统计单个项目下的成员行数。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。

    Returns:
        int: project_member 表中该项目的行数；查询无结果时返回 0 而非 None。
    """
    return int(
        db.query(func.count(ProjectMember.id)).filter(ProjectMember.project_id == project_id).scalar() or 0
    )


def overview_for_user(db: Session, user: User) -> DashboardOverviewResponse:
    """个人工作台总览。

    统计项说明：
    - projects / organizations：当前用户可见范围内的真实计数
    - my_projects：我在其中担任负责人或成员的项目数
    - unread_notifications：当前用户收件箱未读数
    - models_available / environments_available：组织级授权内可用的配置数
    - defects：当前用户可见范围内的真实缺陷计数（bug 表按 accessible_project_ids 过滤）
    - test_runs / reports：当前用户可见项目内的真实执行与报告数量
    """
    scope = build_scope(db, user)
    is_admin = is_platform_admin(user)

    project_query = project_visible_query(db, user)
    projects_total = int(project_query.count())

    test_run_query = db.query(func.count(TestRun.id))
    report_query = db.query(func.count(TestReport.id))
    if not is_admin:
        # 执行与报告沿用项目可见范围，避免普通成员看到其它项目的统计。
        visible_project_ids = scope.project_ids or [-1]
        test_run_query = test_run_query.filter(TestRun.project_id.in_(visible_project_ids))
        report_query = report_query.filter(TestReport.project_id.in_(visible_project_ids))
    test_runs_total = int(test_run_query.scalar() or 0)
    reports_total = int(report_query.scalar() or 0)

    if is_admin:
        organizations_total = int(db.query(func.count(Organization.id)).scalar() or 0)
        defects_total = int(db.query(func.count(Bug.id)).scalar() or 0)
    else:
        # 非管理员只统计自己所在的组织；空集合用 [-1] 保证不返回任何组织。
        org_ids = scope.organization_ids
        organizations_total = int(
            db.query(func.count(Organization.id)).filter(Organization.id.in_(org_ids or [-1])).scalar() or 0
        )
        # 缺陷计数同样按可见项目过滤；空集合用 [-1] 保证不返回任何缺陷。
        visible_project_ids = scope.project_ids
        defects_total = int(
            db.query(func.count(Bug.id))
            .filter(Bug.project_id.in_(visible_project_ids or [-1]))
            .scalar()
            or 0
        )

    # 用子查询判断成员关系：直接在 filter 里引用 project_member 会让 SQLAlchemy
    # 生成笛卡尔积，把「项目数」放大成「项目×成员」的行数。
    owned_or_member = project_query.filter(
        (Project.owner_id == user.id)
        | Project.id.in_(
            db.query(ProjectMember.project_id).filter(ProjectMember.user_id == user.id)
        )
    )
    my_projects = int(owned_or_member.count())

    unread_notifications = int(
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .scalar()
        or 0
    )

    if is_admin:
        # 平台管理员统计全平台启用中的模型配置，不做组织级授权过滤。
        models_available = int(
            db.query(func.count(ModelConfiguration.id))
            .filter(ModelConfiguration.is_enabled.is_(True))
            .scalar()
            or 0
        )
    else:
        # 汇总当前用户在所有组织中被授权且开启 agent 的模型 domain_id（集合去重）。
        orgs = db.query(OrganizationMember).filter(
            OrganizationMember.user_id == user.id,
            OrganizationMember.agent_enabled.is_(True),
        )
        ids: set[str] = set()
        for row in orgs:
            for item in row.allowed_model_ids or []:
                ids.add(str(item))
        models_available = int(
            db.query(func.count(ModelConfiguration.id))
            .filter(ModelConfiguration.is_enabled.is_(True), ModelConfiguration.domain_id.in_(ids or {"__none__"}))
            .scalar()
            or 0
        )

    environments_available = int(
        db.query(func.count(Environment.id)).filter(Environment.is_active.is_(True)).scalar() or 0
    )

    stats = [
        StatCard(
            key="projects",
            label="可见项目",
            value=projects_total,
            hint="当前用户可见范围" + ("（平台管理员：全部）" if is_admin else ""),
        ),
        StatCard(
            key="organizations",
            label="可见组织",
            value=organizations_total,
            hint="当前用户所属组织" + ("（平台管理员：全部）" if is_admin else ""),
        ),
        StatCard(key="my_projects", label="我参与的项目", value=my_projects, hint="负责人或成员身份"),
        StatCard(key="unread_notifications", label="未读通知", value=unread_notifications, hint="个人收件箱"),
        StatCard(key="models_available", label="可用模型配置", value=models_available, hint="组织授权且已启用"),
        StatCard(key="environments_available", label="可用环境", value=environments_available, hint="已启用的执行环境"),
        StatCard(key="test_runs", label="测试执行", value=test_runs_total, hint="当前用户可见项目"),
        StatCard(key="reports", label="测试报告", value=reports_total, hint="当前用户可见项目"),
        StatCard(key="defects", label="缺陷", value=defects_total, hint="我可见项目内的缺陷"),
    ]
    return DashboardOverviewResponse(scope=scope, stats=stats)


def charts_for_user(
    db: Session,
    user: User,
    *,
    days: int = 7,
    organization_id: int | None = None,
    project_id: int | None = None,
) -> DashboardChartsResponse:
    """返回工作台趋势图数据，只统计当前用户可见的项目。"""
    today = date.today()
    first_day = today - timedelta(days=days - 1)
    after_last_day = today + timedelta(days=1)
    start_at = datetime.combine(first_day, time.min)
    end_at = datetime.combine(after_last_day, time.min)
    days_in_range = [first_day + timedelta(days=offset) for offset in range(days)]
    day_keys = [item.isoformat() for item in days_in_range]

    # 先由既有项目可见性查询收敛，再叠加用户在顶栏选择的组织和项目。
    # 不可见或不存在的选择都会得到空数据，不泄露项目是否存在。
    visible_projects = project_visible_query(db, user)
    if organization_id is not None:
        visible_projects = visible_projects.filter(Project.organization_id == organization_id)
    if project_id is not None:
        visible_projects = visible_projects.filter(Project.id == project_id)
    project_ids = [row[0] for row in visible_projects.with_entities(Project.id).all()]
    scoped_project_ids = project_ids or [-1]

    execution_counts = {key: {"total": 0, "passed": 0, "failed": 0} for key in day_keys}
    if project_ids:
        execution_time = func.coalesce(CaseExecution.started_at, CaseExecution.created_at)
        day_expression = func.date(execution_time)
        rows = (
            db.query(
                day_expression,
                CaseExecution.status,
                func.count(CaseExecution.id),
            )
            .join(TestRun, TestRun.id == CaseExecution.test_run_id)
            .filter(
                TestRun.project_id.in_(scoped_project_ids),
                execution_time >= start_at,
                execution_time < end_at,
            )
            .group_by(day_expression, CaseExecution.status)
            .all()
        )
        for day_value, status_value, count in rows:
            day_key = day_value.isoformat() if hasattr(day_value, "isoformat") else str(day_value)
            if day_key not in execution_counts:
                continue
            bucket = execution_counts[day_key]
            value = int(count or 0)
            bucket["total"] += value
            normalized_status = str(status_value or "").upper()
            if normalized_status == "PASSED":
                bucket["passed"] += value
            elif normalized_status in {"FAILED", "ERROR"}:
                bucket["failed"] += value

    generation_counts = {key: 0 for key in day_keys}
    if project_ids:
        day_expression = func.date(TestCase.created_at)
        rows = (
            db.query(day_expression, func.count(TestCase.id))
            .filter(
                TestCase.project_id.in_(scoped_project_ids),
                TestCase.source_type == "AI",
                TestCase.created_at >= start_at,
                TestCase.created_at < end_at,
            )
            .group_by(day_expression)
            .all()
        )
        for day_value, count in rows:
            day_key = day_value.isoformat() if hasattr(day_value, "isoformat") else str(day_value)
            if day_key in generation_counts:
                generation_counts[day_key] = int(count or 0)

    severity_counts = {severity: 0 for severity in SEVERITY_LABELS}
    if project_ids:
        rows = (
            db.query(Bug.severity, func.count(Bug.id))
            .filter(Bug.project_id.in_(scoped_project_ids))
            .group_by(Bug.severity)
            .all()
        )
        for severity, count in rows:
            if severity in severity_counts:
                severity_counts[severity] = int(count or 0)

    return DashboardChartsResponse(
        scope=build_scope(db, user),
        days=days,
        execution_trend=[
            DashboardExecutionTrendItem(date=key, **execution_counts[key]) for key in day_keys
        ],
        defect_severity=[
            DashboardDefectSeverityItem(
                severity=severity,
                label=SEVERITY_LABELS[severity],
                value=severity_counts[severity],
            )
            for severity in SEVERITY_LABELS
        ],
        case_generation=[DashboardDailyCount(date=key, count=generation_counts[key]) for key in day_keys],
    )


def project_summaries(db: Session, user: User, *, page: int, page_size: int) -> ProjectSummaryResponse:
    """当前用户可见项目的概况列表，附带角色与成员数。"""
    # 分页参数校验：页码与页大小必须为正，页大小上限 200，防止一次拉全表。
    if page < 1 or page_size < 1 or page_size > 200:
        raise bad_request("分页参数无效")
    query = project_visible_query(db, user)
    total = int(query.count())
    rows = (
        # 双键倒序：先按更新时间再按 ID，保证分页稳定，翻页不会出现重复或漏项。
        query.order_by(Project.updated_at.desc(), Project.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 负责人用户名按用户 ID 缓存：同页多个项目常指向同一负责人，避免重复查库。
    user_cache: dict[int, User] = {}

    def owner_username(owner_id: int) -> str | None:
        """按用户 ID 取项目负责人的用户名。

        Args:
            owner_id: 负责人用户 ID。

        Returns:
            str | None: 用户名；负责人账号已删除时返回 None，前端展示空值而非报错。
        """
        if owner_id not in user_cache:
            user_cache[owner_id] = db.get(User, owner_id)
        row = user_cache[owner_id]
        return row.username if row is not None else None

    # 组织名按 organization_id 缓存：同一组织下的项目共享同一次查询。
    org_cache: dict[int, Organization] = {}
    items: list[ProjectSummaryItem] = []
    for project in rows:
        # 项目可以不归属任何组织，此时 organization_name 保持 None 直接返回。
        organization_name: str | None = None
        if project.organization_id is not None:
            if project.organization_id not in org_cache:
                org_cache[project.organization_id] = db.get(Organization, project.organization_id)
            org = org_cache[project.organization_id]
            organization_name = org.name if org is not None else None
        # 取不到任何项目身份时返回 None，normalize_project_role 会把 None 归一成 viewer
        # （而不是按字面值放行），所以可见项目的 my_role 至少是 viewer。
        raw_role = project_role_for(db, project, user)
        items.append(
            ProjectSummaryItem(
                id=project.id,
                name=project.name,
                description=project.description,
                owner_id=project.owner_id,
                owner_username=owner_username(project.owner_id),
                organization_id=project.organization_id,
                organization_name=organization_name,
                my_role=normalize_project_role(raw_role),
                member_count=_member_count(db, project.id),
                updated_at=project.updated_at,
            )
        )
    return ProjectSummaryResponse(total=total, items=items)


def platform_statistics(db: Session) -> DashboardOverviewResponse:
    """平台管理端首页统计，口径为全平台。"""
    return DashboardOverviewResponse(
        # 平台级统计没有具体用户：user_id 固定 0、role 固定 admin，仅用于声明统计口径。
        scope=DashboardScopeResponse(
            subject="platform",
            user_id=0,
            role="admin",
            is_platform_admin=True,
            organization_ids=[],
            project_ids=[],
        ),
        stats=[
            StatCard(
                key="users",
                label="用户总数",
                value=int(db.query(func.count(User.id)).scalar() or 0),
                hint="全平台注册用户",
            ),
            StatCard(
                key="active_users",
                label="启用中用户",
                value=int(
                    db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
                ),
                hint="is_active = true",
            ),
            StatCard(
                key="organizations",
                label="组织总数",
                value=int(db.query(func.count(Organization.id)).scalar() or 0),
                hint="全平台组织",
            ),
            StatCard(
                key="projects",
                label="项目总数",
                value=int(db.query(func.count(Project.id)).scalar() or 0),
                hint="全平台项目",
            ),
            StatCard(
                key="memberships",
                label="项目成员关系",
                value=int(db.query(func.count(ProjectMember.id)).scalar() or 0),
                hint="project_member 行数",
            ),
            StatCard(
                key="model_configs",
                label="模型配置",
                value=int(db.query(func.count(ModelConfiguration.id)).scalar() or 0),
                hint="全平台模型配置",
            ),
            StatCard(
                key="enabled_model_configs",
                label="启用中的模型配置",
                value=int(
                    db.query(func.count(ModelConfiguration.id))
                    .filter(ModelConfiguration.is_enabled.is_(True))
                    .scalar()
                    or 0
                ),
                hint="is_enabled = true",
            ),
            StatCard(
                key="environments",
                label="环境配置",
                value=int(db.query(func.count(Environment.id)).scalar() or 0),
                hint="全平台执行环境",
            ),
            StatCard(
                key="notifications",
                label="通知总量",
                value=int(db.query(func.count(Notification.id)).scalar() or 0),
                hint="全平台收件箱记录",
            ),
        ],
    )


def readiness(db: Session) -> ReadyResponse:
    """依赖就绪检查。数据库不可用时返回 not_ready，其它依赖仅影响 degraded。"""
    # 局部导入：text() 只有在这个函数里用一次，模块顶层不需要额外依赖。
    from sqlalchemy import text

    checks: list[ReadyCheckItem] = []
    overall = "ready"

    try:
        # 数据库是唯一硬性依赖：探活失败直接置为 not_ready 并提前返回，供探针摘除实例。
        db.execute(text("SELECT 1"))
        checks.append(ReadyCheckItem(name="database", status="up"))
    except Exception as exc:  # noqa: BLE001
        # 异常分支只暴露异常类型名，不把连接串、主机名等内部信息带回响应。
        checks.append(ReadyCheckItem(name="database", status="down", detail=type(exc).__name__))
        overall = "not_ready"
        return ReadyResponse(status=overall, checks=checks)

    try:
        # 模型配置缺失只降级不判死：无可用模型或未设默认模型时，其它统计接口仍可用。
        enabled_models = int(
            db.query(func.count(ModelConfiguration.id))
            .filter(ModelConfiguration.is_enabled.is_(True))
            .scalar()
            or 0
        )
        default_models = int(
            db.query(func.count(ModelConfiguration.id))
            .filter(ModelConfiguration.is_enabled.is_(True), ModelConfiguration.is_default.is_(True))
            .scalar()
            or 0
        )
        if enabled_models == 0:
            checks.append(
                ReadyCheckItem(name="llm_configs", status="degraded", detail="未配置启用的模型连接")
            )
            overall = "degraded"
        elif default_models == 0:
            checks.append(
                ReadyCheckItem(name="llm_configs", status="degraded", detail="未设置默认模型")
            )
            overall = "degraded"
        else:
            checks.append(ReadyCheckItem(name="llm_configs", status="up", detail=f"启用 {enabled_models} 个"))
    except Exception as exc:  # noqa: BLE001
        checks.append(ReadyCheckItem(name="llm_configs", status="unknown", detail=type(exc).__name__))
        overall = "degraded"

    # 执行环境：没有启用的环境属于 degraded，但读取类接口仍可正常工作。
    try:
        active_envs = int(
            db.query(func.count(Environment.id)).filter(Environment.is_active.is_(True)).scalar() or 0
        )
        checks.append(
            ReadyCheckItem(
                name="environments",
                status="up" if active_envs else "degraded",
                detail=f"启用 {active_envs} 个" if active_envs else "未配置启用的执行环境",
            )
        )
        # 只有前面环节仍是 ready 时才被拉低：避免把已判定的 degraded 覆盖回 ready。
        if active_envs == 0 and overall == "ready":
            overall = "degraded"
    except Exception as exc:  # noqa: BLE001
        checks.append(ReadyCheckItem(name="environments", status="unknown", detail=type(exc).__name__))
        overall = "degraded"

    # overall 只会从 ready 向下收敛（degraded / not_ready），不会被后续环节回写为 ready。
    return ReadyResponse(status=overall, checks=checks)
