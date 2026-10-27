"""安全用例：列表 / 详情 / 启停 / 高风险确认 / 批量执行。

批量执行（``run_security_cases``）是本模块唯一的「批量执行入口」（§16.2）：
组装一个临时的 TestPlan + TestSuite 后调用既有 ``RunService.create_and_execute_run``。
临时计划只是执行载体，不是第二套执行器——Fixture、Mock Context、Cleanup、
并发互斥全部沿用现有生命周期。

``confirm_risk`` 只能由人调用：Agent 工具没有这个动作（§13.4）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.security_testing.models import (
    SecurityCase,
    SecurityExecution,
    SecurityMutationRule,
)
from app.features.security_testing.schemas import (
    SecurityCaseDetail,
    SecurityCaseListResponse,
    SecurityCaseRead,
    SecurityCaseUpdate,
    SecurityExecutionRead,
    SecurityRunRequest,
)
from app.features.security_testing.services._access import (
    get_project_or_404,
    require_writable_project,
)
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_plan import TestPlan, TestPlanSuite
from app.features.test_management.models.test_suite import TestSuite, TestSuiteCase
from app.features.test_management.schemas import TestRunCreateRequest, TestRunResponse
from app.features.test_management.services.run_service import RunService
from app.features.environment_configuration.services.environment_service import resolve_project_environment
from app.models.identity import User
from app.shared.errors import bad_request, not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

__all__ = ["SecurityCaseService"]


class SecurityCaseService:
    """安全用例服务。所有写方法负责 commit。"""

    # ------------------------------------------------------------------ 查询

    @staticmethod
    def list_cases(
        db: Session,
        project_id: int,
        *,
        user: User,
        api_id: int | None = None,
        strategy_id: int | None = None,
        mutation_type: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SecurityCaseListResponse:
        """筛选安全用例。过滤条件全部可选，``mutation_type`` 大小写不敏感。"""
        get_project_or_404(db, project_id, user)
        page = max(1, page)
        page_size = min(max(1, page_size), MAX_PAGE_SIZE)

        query = db.query(SecurityCase).filter(SecurityCase.project_id == project_id)
        if api_id is not None:
            query = query.filter(SecurityCase.api_id == api_id)
        if strategy_id is not None:
            query = query.filter(SecurityCase.strategy_id == strategy_id)
        if mutation_type:
            query = query.filter(SecurityCase.mutation_type == mutation_type.upper())
        if enabled is not None:
            query = query.filter(SecurityCase.test_case_id.in_(
                db.query(TestCase.id).filter(TestCase.enabled.is_(enabled))
            ))

        total = query.count()
        rows = (
            query.order_by(SecurityCase.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return SecurityCaseListResponse(
            items=[_detail(db, row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def get_case(db: Session, security_case_id: int, *, user: User) -> SecurityCaseDetail:
        """详情：基线引用、期望、目标名与最近一次 security_execution。"""
        return _detail(db, _get_or_404(db, security_case_id, user))

    # ------------------------------------------------------------------ 启停

    @staticmethod
    def update_case(
        db: Session, security_case_id: int, body: SecurityCaseUpdate, *, actor: User
    ) -> SecurityCaseRead:
        """只允许改启用状态，并同步 ``test_case.enabled``。

        扩展行本身没有 enabled 列；启停的唯一事实来源是 TestCase。
        """
        row = _get_or_404(db, security_case_id, actor)
        require_writable_project(db, row.project_id, actor)
        case = db.get(TestCase, row.test_case_id)
        if case is None:
            raise not_found("关联的测试用例不存在")
        case.enabled = body.enabled
        row.updated_at = datetime.now()
        db.add(case)
        db.add(row)
        db.commit()
        db.refresh(row)
        return SecurityCaseRead.model_validate(row)

    # ------------------------------------------------------------------ 高风险确认

    @staticmethod
    def confirm_risk(db: Session, security_case_id: int, *, actor: User) -> SecurityCaseRead:
        """写 ``confirmed_by`` / ``confirmed_at``，同一用例只允许确认一次。"""
        row = _get_or_404(db, security_case_id, actor)
        require_writable_project(db, row.project_id, actor)
        if not bool(row.confirmation_required):
            raise bad_request("该安全用例不需要高风险确认")
        if row.confirmed_by is not None and row.confirmed_at is not None:
            raise bad_request("该安全用例已经确认过，不能重复确认")
        row.confirmed_by = actor.id
        row.confirmed_at = datetime.now()
        row.updated_at = datetime.now()
        db.add(row)
        db.commit()
        db.refresh(row)
        return SecurityCaseRead.model_validate(row)

    # ------------------------------------------------------------------ 批量执行

    @staticmethod
    def run_security_cases(
        db: Session, project_id: int, body: SecurityRunRequest, *, actor: User
    ) -> TestRunResponse:
        """把选中的安全用例打包执行一次 TestRun。

        只执行仍启用的用例；一个都不剩则 400，避免创建一个空计划。
        """
        require_writable_project(db, project_id, actor)
        environment = resolve_project_environment(db, project_id, body.environment_id) if body.environment_id else None
        if environment is None:
            raise not_found("环境未关联当前项目或已停用")

        cases = _load_enabled_security_cases(db, project_id, body.security_case_ids)
        if not cases:
            raise bad_request("所选安全用例不存在或已停用")
        unconfirmed_high_risk = [
            row.id for row in cases
            if row.confirmation_required and not (row.confirmed_by and row.confirmed_at)
        ]
        if unconfirmed_high_risk:
            raise bad_request("所选安全用例包含尚未人工确认的高风险变异")

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = (body.plan_name or f"安全测试-{stamp}").strip()[:200]

        suite = TestSuite(
            project_id=project_id,
            name=f"{name}-用例集",
            description="安全测试批量执行的临时套件",
            suite_type="MANUAL",
            enabled=True,
            created_by=actor.id,
        )
        db.add(suite)
        db.flush()
        for offset, case in enumerate(cases):
            db.add(TestSuiteCase(
                suite_id=suite.id,
                test_case_id=case.test_case_id,
                sort=offset,
                enabled=True,
            ))
        plan = TestPlan(
            project_id=project_id,
            name=name,
            description="安全测试批量执行的临时计划",
            environment_id=environment.id,
            status="ACTIVE",
            execution_mode="MANUAL",
            created_by=actor.id,
        )
        db.add(plan)
        db.flush()
        db.add(TestPlanSuite(plan_id=plan.id, suite_id=suite.id, sort=0))
        db.commit()
        db.flush()

        return RunService().create_and_execute_run(
            db, plan.id,
            TestRunCreateRequest(environment_id=environment.id),
            actor=actor,
        )


# --------------------------------------------------------------------------- 辅助


def _get_or_404(db: Session, security_case_id: int, user: User) -> SecurityCase:
    """按扩展行 id 取；不可见项目与不存在共用 404（隐藏存在性）。"""
    row = db.get(SecurityCase, security_case_id)
    if row is None:
        raise not_found("安全用例不存在")
    get_project_or_404(db, row.project_id, user)
    return row


def _load_enabled_security_cases(
    db: Session, project_id: int, case_ids: list[int]
) -> list[SecurityCase]:
    """按请求顺序取出仍启用的安全用例，重复 id 去重。"""
    unique = list(dict.fromkeys(case_ids))
    rows = (
        db.query(SecurityCase)
        .join(TestCase, TestCase.id == SecurityCase.test_case_id)
        .filter(
            SecurityCase.project_id == project_id,
            SecurityCase.id.in_(unique),
            TestCase.enabled.is_(True),
        )
        .all()
    )
    by_id = {row.id: row for row in rows}
    return [by_id[cid] for cid in unique if cid in by_id]


def _latest_security_execution(db: Session, row: SecurityCase) -> SecurityExecutionRead | None:
    """最近一次执行；取不到时为 None，而不是伪造一条。"""
    execution = (
        db.query(SecurityExecution)
        .filter(SecurityExecution.security_case_id == row.id)
        .order_by(SecurityExecution.id.desc())
        .first()
    )
    if execution is None:
        return None
    return SecurityExecutionRead.model_validate(execution)


def _detail(db: Session, row: SecurityCase) -> SecurityCaseDetail:
    """组装详情。基线名与规则名允许缺失（对象可能已删除）。"""
    case = db.get(TestCase, row.test_case_id)
    baseline = db.get(TestCase, row.baseline_case_id) if row.baseline_case_id else None
    iface = db.get(ApiInterface, row.api_id) if row.api_id else None
    rule = db.get(SecurityMutationRule, row.rule_id) if row.rule_id else None
    return SecurityCaseDetail(
        **SecurityCaseRead.model_validate(row).model_dump(),
        enabled=bool(case.enabled) if case is not None else False,
        case_name=case.name if case is not None else None,
        baseline_case_name=baseline.name if baseline is not None else None,
        api_name=getattr(iface, "name", None),
        rule_name=getattr(rule, "name", None),
        latest_execution=_latest_security_execution(db, row),
    )
