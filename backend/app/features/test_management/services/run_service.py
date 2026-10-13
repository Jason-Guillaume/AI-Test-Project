"""测试执行编排服务（TestRun）。

触发一次测试计划执行：
1. 校验计划可写（member+）→ 解析执行环境（请求体覆盖计划环境）
2. 收集计划下所有套件的启用用例（按 plan_suite.sort → suite_case.sort 去重保序）
3. 创建 TestRun（RUNNING），逐用例调用 TestCaseExecutor，落库 CaseExecution
4. 汇总 passed/failed/skipped/error，置 Run 终态（SUCCESS/FAILED）

执行复用 TestCaseExecutor（API→ApiRequestExecutor，BUSINESS_FLOW→execute_flow）。
本服务 owns commit：逐用例提交，保证部分结果持久化（即使中途异常，已执行用例可见）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.configuration import Environment
from app.features.test_management.executors import test_case_executor
from app.features.test_management.models.execution import CaseExecution, TestRun
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_plan import TestPlan, TestPlanSuite
from app.features.test_management.models.test_suite import TestSuiteCase
from app.features.test_management.schemas import (
    CaseExecutionListResponse,
    CaseExecutionResponse,
    TestRunCreateRequest,
    TestRunListResponse,
    TestRunResponse,
)
from app.features.test_management.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_plan_project_id,
    resolve_run_project_id,
)
from app.models.identity import User
from app.shared.errors import bad_request, not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def _response(r: TestRun) -> TestRunResponse:
    return TestRunResponse.model_validate(r)


class RunService:
    """测试执行编排服务。无状态，路由层复用单例。"""

    def create_and_execute_run(
        self, db: Session, plan_id: int, body: TestRunCreateRequest, *, actor: User,
    ) -> TestRunResponse:
        plan = db.get(TestPlan, plan_id)
        if plan is None:
            raise not_found("测试计划不存在")
        require_writable_project(db, resolve_plan_project_id(db, plan_id), actor)

        # 1. 解析执行环境。
        env_id = body.environment_id if body.environment_id is not None else plan.environment_id
        if env_id is None:
            raise bad_request("未指定执行环境（计划未配置环境且请求体未提供）")
        environment = db.get(Environment, env_id)
        if environment is None or not environment.is_active:
            raise not_found("环境不存在或已停用")

        # 2. 收集有序用例（plan_suite → suite_case，去重保序，仅启用）。
        case_ids = self._collect_case_ids(db, plan_id)
        cases = (
            db.query(TestCase).filter(TestCase.id.in_(case_ids), TestCase.enabled.is_(True)).all()
            if case_ids else []
        )
        # 保持收集顺序。
        case_map = {c.id: c for c in cases}
        ordered_cases = [case_map[cid] for cid in case_ids if cid in case_map]

        # 3. 创建 TestRun。
        run = TestRun(
            project_id=plan.project_id, plan_id=plan_id, environment_id=environment.id,
            status="RUNNING", total=len(ordered_cases),
            started_at=datetime.now(), created_by=actor.id,
        )
        db.add(run)
        db.flush()

        # 4. 逐用例执行并落库。
        for seq, case in enumerate(ordered_cases):
            ce = CaseExecution(
                test_run_id=run.id, test_case_id=case.id,
                status="RUNNING", executor_type=case.target_type,
                started_at=datetime.now(),
            )
            db.add(ce)
            db.flush()
            try:
                result = test_case_executor.execute(db, case, environment=environment, actor=actor)
            except Exception as exc:  # noqa: BLE001 — 单用例异常不应拖垮整轮。
                result = test_case_executor.CaseExecutionResult(
                    status="ERROR", executor_type=case.target_type,
                    error_code="EXECUTION_ERROR", error_message=f"执行异常：{exc}",
                )
            ce.status = result.status
            ce.executor_type = result.executor_type
            ce.request_snapshot = result.request_snapshot
            ce.response_snapshot = result.response_snapshot
            ce.assertion_results = result.assertion_results
            ce.context_json = result.context_json
            ce.duration_ms = result.duration_ms
            ce.error_code = result.error_code
            ce.error_message = result.error_message
            ce.finished_at = datetime.now()
            self._bump_counter(run, result.status)
            db.commit()
            db.refresh(ce)

        # 5. 汇总终态。
        run.finished_at = datetime.now()
        run.status = "SUCCESS" if (run.failed == 0 and run.error == 0) else "FAILED"
        db.commit()
        db.refresh(run)
        return _response(run)

    def get_run(self, db: Session, run_id: int, user: User) -> TestRunResponse:
        run = db.get(TestRun, run_id)
        if run is None:
            raise not_found("测试执行记录不存在")
        get_project_or_404(db, run.project_id, user)
        return _response(run)

    def list_runs(
        self, db: Session, project_id: int, user: User, *,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TestRunListResponse:
        get_project_or_404(db, project_id, user)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        q = db.query(TestRun).filter(TestRun.project_id == project_id)
        total = int(q.count())
        items = q.order_by(TestRun.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return TestRunListResponse(items=[_response(r) for r in items], total=total, page=page, page_size=page_size)

    def list_case_executions(self, db: Session, run_id: int, user: User) -> CaseExecutionListResponse:
        run = db.get(TestRun, run_id)
        if run is None:
            raise not_found("测试执行记录不存在")
        get_project_or_404(db, run.project_id, user)
        rows = (
            db.query(CaseExecution).filter(CaseExecution.test_run_id == run_id)
            .order_by(CaseExecution.id.asc()).all()
        )
        items = [CaseExecutionResponse.model_validate(r) for r in rows]
        return CaseExecutionListResponse(items=items, total=len(items), page=1, page_size=100)

    # ---------------------------------------------------------------- 辅助

    def _collect_case_ids(self, db: Session, plan_id: int) -> list[int]:
        """按 plan_suite.sort → suite_case.sort 收集启用用例ID，去重保序。"""
        plan_suites = (
            db.query(TestPlanSuite).filter(TestPlanSuite.plan_id == plan_id)
            .order_by(TestPlanSuite.sort.asc(), TestPlanSuite.id.asc()).all()
        )
        seen: set[int] = set()
        ordered: list[int] = []
        for ps in plan_suites:
            suite_cases = (
                db.query(TestSuiteCase)
                .filter(TestSuiteCase.suite_id == ps.suite_id, TestSuiteCase.enabled.is_(True))
                .order_by(TestSuiteCase.sort.asc(), TestSuiteCase.id.asc()).all()
            )
            for sc in suite_cases:
                if sc.test_case_id not in seen:
                    seen.add(sc.test_case_id)
                    ordered.append(sc.test_case_id)
        return ordered

    def _bump_counter(self, run: TestRun, status: str) -> None:
        if status == "PASSED":
            run.passed = (run.passed or 0) + 1
        elif status == "FAILED":
            run.failed = (run.failed or 0) + 1
        elif status == "SKIPPED":
            run.skipped = (run.skipped or 0) + 1
        else:  # ERROR / 未知
            run.error = (run.error or 0) + 1
