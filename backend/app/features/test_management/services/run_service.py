"""测试执行编排服务（TestRun）。

触发一次测试计划执行：
1. 校验计划可写（member+）→ 解析执行环境（请求体覆盖计划环境）
2. 收集计划下所有套件的启用用例（按 plan_suite.sort → suite_case.sort 去重保序）
3. 创建 TestRun（RUNNING）→ PREPARE（RUN 级 Fixture，整轮一次）→ 逐用例
   SETUP / EXECUTE / ASSERT / CLEANUP（§12.2）
4. RUN 级 Cleanup 一次，汇总 passed/failed/skipped/error，置 Run 终态（SUCCESS/FAILED）

执行复用 TestCaseExecutor（API→ApiRequestExecutor，BUSINESS_FLOW→execute_flow），
造数复用 test_data.runtime 的 LifecycleManager（不新写执行器，也不直接调 Provider）。

本服务 owns commit：逐用例提交，保证部分结果持久化（即使中途异常，已执行用例可见）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.configuration import Environment
from app.features.business.executors.context import ExecutionContext
from app.features.test_data.models.case_fixture import TestCaseFixture
from app.features.test_data.models.fixture import Fixture
from app.features.test_data.runtime.lifecycle import CleanupOutcome, LifecycleManager
from app.features.mock_management.runtime.lifecycle import MockLifecycle
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
from app.shared.errors import (
    CODE_CLEANUP_FAILED,
    CODE_SETUP_FAILED,
    AppError,
    bad_request,
    not_found,
)
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def _response(r: TestRun) -> TestRunResponse:
    return TestRunResponse.model_validate(r)


class RunService:
    """测试执行编排服务。无状态，路由层复用单例。"""

    def __init__(self) -> None:
        self._lifecycle = LifecycleManager()
        self._mock = MockLifecycle()

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
        project_id = plan.project_id

        # 3. 创建 TestRun。
        run = TestRun(
            project_id=project_id, plan_id=plan_id, environment_id=environment.id,
            status="RUNNING", total=len(ordered_cases),
            started_at=datetime.now(), created_by=actor.id,
        )
        db.add(run)
        db.flush()

        lifecycle = self._lifecycle
        declared = self._declared_fixtures(db, project_id, [c.id for c in ordered_cases])

        # 4. PREPARE：RUN 作用域的 Fixture 整轮只生成一次（§12.2）。
        run_keys: list[str] = []
        for case in ordered_cases:
            for fx in declared.get(case.id, []):
                if (fx.scope or "CASE") == "RUN" and fx.fixture_key not in run_keys:
                    run_keys.append(fx.fixture_key)

        run_outputs: dict[str, dict[str, Any]] = {}
        prep_failed: AppError | None = None
        if run_keys:
            try:
                run_outputs = lifecycle.prepare_run(
                    db, project_id=project_id, test_run_id=run.id,
                    environment=environment, actor=actor, fixture_keys=run_keys,
                )
            except AppError as exc:
                # RUN 级造数失败：整轮没有可用数据，每条用例都是 ERROR（不是 FAILED）。
                prep_failed = exc

        # 5. 逐用例 SETUP → EXECUTE → ASSERT → CLEANUP 并落库。
        for case in ordered_cases:
            ce = CaseExecution(
                test_run_id=run.id, test_case_id=case.id,
                status="RUNNING", executor_type=case.target_type,
                started_at=datetime.now(),
            )
            db.add(ce)
            db.flush()

            # Mock 执行作用域激活（§二十三）：用例声明了 required_mocks 才创建 Context；
            # 提交后才对 Mock Runtime 的独立会话可见。无声明时 mock_context_id 为 None，零影响。
            mock_context_id = self._mock.activate_for_case(
                db, project_id=project_id, test_run_id=run.id,
                case_execution_id=ce.id, case_id=case.id,
            )
            if mock_context_id:
                db.commit()
                db.refresh(ce)

            if prep_failed is not None:
                self._fail_case(ce, prep_failed)
                self._bump_counter(run, ce.status)
            else:
                case_keys = [
                    fx.fixture_key for fx in declared.get(case.id, [])
                    if (fx.scope or "CASE") != "RUN"
                ]
                try:
                    case_outputs = lifecycle.setup_case(
                        db, project_id=project_id, case_execution_id=ce.id,
                        test_run_id=run.id, environment=environment, actor=actor,
                        fixture_keys=case_keys,
                    )
                except AppError as exc:
                    # SETUP 失败：ERROR + 造数原始错误码；仍然清理已生成的步骤。
                    self._fail_case(ce, exc)
                    self._bump_counter(run, ce.status)
                    self._write_cleanup(
                        ce,
                        lifecycle.cleanup_case(
                            db, case_execution_id=ce.id, project_id=project_id, actor=actor,
                        ),
                    )
                    self._mock.deactivate(db, mock_context_id)
                    db.commit()
                    continue

                variables = (
                    ExecutionContext(variables={**run_outputs, **case_outputs})
                    if (run_outputs or case_outputs) else None
                )
                try:
                    result = test_case_executor.execute(
                        db, case, environment=environment, actor=actor, variables=variables,
                    )
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

                # CLEANUP：PASSED / FAILED / ERROR 都清；失败只写 cleanup_*，不改结论。
                self._write_cleanup(
                    ce,
                    lifecycle.cleanup_case(
                        db, case_execution_id=ce.id, project_id=project_id, actor=actor,
                    ),
                )
            # Mock 执行作用域关闭（§二十七：finally 必须关闭）；prep_failed 与正常路径都走这里。
            self._mock.deactivate(db, mock_context_id)
            db.commit()
            db.refresh(ce)

        # 6. RUN 级 Cleanup（整轮一次）。失败不增加 run.error（§15）。
        lifecycle.cleanup_run(db, project_id=project_id, test_run_id=run.id, actor=actor)

        # 7. 汇总终态。
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

    @staticmethod
    def _declared_fixtures(
        db: Session, _project_id: int, case_ids: list[int],
    ) -> dict[int, list[Fixture]]:
        """用例声明的 Fixture，按 sort 排序。

        造数只看 ``test_case_fixture``。跨项目私有夹具和已停用夹具都原样交给
        LifecycleManager，由它报 FIXTURE_NOT_FOUND / FIXTURE_DISABLED。
        在这里丢掉的话，用例会在没有造数的情况下直接通过。
        """
        if not case_ids:
            return {}
        rows = (
            db.query(TestCaseFixture, Fixture)
            .join(Fixture, Fixture.id == TestCaseFixture.fixture_id)
            .filter(TestCaseFixture.test_case_id.in_(case_ids))
            .order_by(TestCaseFixture.sort.asc(), TestCaseFixture.id.asc())
            .all()
        )
        declared: dict[int, list[Fixture]] = {}
        for tcf, fx in rows:
            # 跨项目私有夹具也要带上 key。Lifecycle 按当前项目重新加载，
            # 看不见时抛 FIXTURE_NOT_FOUND，用例记 ERROR。这里丢掉的话，
            # 用例会在没有造数的情况下直接跑过。
            declared.setdefault(tcf.test_case_id, []).append(fx)
        return declared

    @staticmethod
    def _fail_case(ce: CaseExecution, exc: AppError) -> None:
        """造数失败 → 用例 ERROR，保留 Data Factory 的原始错误码（绝不写 FAILED）。"""
        ce.status = "ERROR"
        ce.error_code = exc.code or CODE_SETUP_FAILED
        ce.error_message = str(exc)[:2000]
        ce.finished_at = datetime.now()

    @staticmethod
    def _write_cleanup(ce: CaseExecution, outcome: CleanupOutcome) -> None:
        """写 cleanup_* 三列。PASSED 用例清理失败仍是 PASSED，产品通过率不受影响。"""
        if outcome.failures:
            ce.cleanup_status = "FAILED"
            ce.cleanup_error_code = CODE_CLEANUP_FAILED
            ce.cleanup_error_message = "; ".join(outcome.failures)[:2000]
        elif outcome.cleaned > 0:
            ce.cleanup_status = "SUCCESS"
        else:
            ce.cleanup_status = "SKIPPED"

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
