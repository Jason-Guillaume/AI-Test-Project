"""测试报告服务层（ReportBuilder + ReportService）。

职责（§五）：
- build_report：读 TestRun + CaseExecution + AssertionResult，由**代码**统计 total/passed/
  failed/error/skipped、pass_rate（passed/(total-skipped)*100，分母 0 记 0）、总耗时、
  失败分类（§七）、风险等级（§八）；LLM 只负责总结 / 风险解释 / 失败聚类 / 建议。
- 报告只存汇总 + AI 总结 + 风险 + 元数据；明细实时读取 CaseExecution（§四，不复制快照）。
- 幂等：同一 test_run_id 已有 COMPLETED 报告时默认返回已有；regenerate=true 仅重生成 AI 总结（§二九）。
- AI 总结失败不影响基础报告：报告仍 COMPLETED，ai_summary 置空（§九）。

权限（§三三）：读 viewer+（get_project_or_404 → 404 隐藏存在性）；生成 / 删除 member+。
跨 feature 复用：RunService / _access / TestCase 模型（与 agent.tools.execution_tool 同款范式）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.features.agent.providers.sanitizer import sanitize_context, sanitize_text
from app.features.mock_management.models import MockExecution, MockScenario, MockService
from app.features.reports.models.report import TestReport
from app.features.reports.schemas import (
    CaseExecutionSummary,
    ReportGenerateResponse,
    TestReportDetailResponse,
    TestReportListItem,
    TestReportListResponse,
    TestReportResponse,
    TestRunBrief,
)
from app.features.reports.services.ai_summary import generate_summary as generate_ai_summary
from app.features.test_management.models.execution import CaseExecution, TestRun
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.services._access import (
    get_project_or_404,
    require_writable_project,
)
from app.models.identity import User
from app.shared.errors import (
    AppError,
    CODE_REPORT_GENERATION_FAILED,
    not_found,
)
from app.shared.notify import notify
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

# 失败分类启发式关键词（小写子串匹配 error_message）。环境类：超时/连接/5xx/网络；
# 数据类：参数/变量/数据缺失或无效。用于 EXECUTION_ERROR/ENVIRONMENT_ERROR/TEST_DATA_ISSUE 判定。
_ENV_SIGNALS = (
    "timeout", "timed out", "connection", "refused", "dns", "unreachable",
    "reset", "broken pipe", "网络", "环境", "500", "502", "503", "504",
)
_DATA_SIGNALS = (
    "数据", "参数", "变量", "缺少", "无效", "缺失", "非法",
    "data", "variable", "param", "missing", "invalid", "required field",
)


class ReportService:
    """测试报告生成与查询服务。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 生成报告

    def build_report(
        self, db: Session, test_run_id: int, *, actor: User,
        generate_ai_summary: bool = True, regenerate: bool = False,
        provider: Any = None,
    ) -> ReportGenerateResponse:
        """为一次 TestRun 生成正式报告（代码统计 + 可选 AI 总结）。

        project_id 由 TestRun 解析（路由只有 run_id），权限 member+ 走
        require_writable_project → 跨项目 / 无权统一 404 隐藏存在性。

        Args:
            test_run_id：目标执行记录。
            actor: 触发人（member+ 权限）。
            generate_ai_summary: 是否调用 LLM 生成结构化总结（§九）。
            regenerate: 已有 COMPLETED 报告时，仅重生成 AI 总结（§二九 幂等）。
            provider: 可选 LLMProvider（测试注入 Fake）；为空时按需构造生产 Provider。
        """
        run = db.get(TestRun, test_run_id)
        if run is None:
            # 跨项目执行记录统一 404，隐藏存在性。
            raise not_found("测试执行记录不存在")
        require_writable_project(db, run.project_id, actor)

        # 幂等：已有 COMPLETED 报告时默认返回已有；regenerate 仅重生成 AI 总结。
        existing = (
            db.query(TestReport)
            .filter(TestReport.test_run_id == test_run_id, TestReport.status == "COMPLETED")
            .first()
        )
        if existing is not None:
            if regenerate:
                self._generate_ai_summary(db, existing, self._rows_for_run(db, test_run_id), provider)
                db.commit()
                db.refresh(existing)
            return ReportGenerateResponse(report_id=existing.id, status="COMPLETED")

        # 新建报告：先以 GENERATING 落库占位，统计完成置 COMPLETED，异常置 FAILED。
        report_no = self._gen_report_no(db)
        report = TestReport(
            project_id=run.project_id,
            test_run_id=test_run_id,
            report_no=report_no,
            title=f"测试报告-执行{test_run_id}",
            environment_id=run.environment_id,
            status="GENERATING",
            risk_level="LOW",
            created_by=actor.id,
        )
        db.add(report)
        db.flush()  # 拿到自增 ID，便于异常分支定位。

        rows = self._rows_for_run(db, test_run_id)
        try:
            stats, summary, duration_ms, risk = self._analyze(rows)
            # Mock Summary（§六十二）：与统计同步写入 summary JSON，不可变。
            summary["mock_summary"] = self._mock_summary(db, test_run_id)
            report.total_cases = stats["total"]
            report.passed_cases = stats["passed"]
            report.failed_cases = stats["failed"]
            report.error_cases = stats["error"]
            report.skipped_cases = stats["skipped"]
            report.pass_rate = stats["pass_rate"]
            report.duration_ms = duration_ms or None
            report.summary = summary
            report.risk_level = risk
            report.status = "COMPLETED"
            if generate_ai_summary:
                # AI 总结失败不影响报告 COMPLETED（§九），内部已 try/except 兜底。
                self._generate_ai_summary(db, report, rows, provider)
            db.commit()
        except Exception as exc:  # noqa: BLE001 — 统计阶段异常要把报告置 FAILED 并上报。
            report.status = "FAILED"
            db.commit()
            raise AppError(
                f"报告生成失败：{exc}", status_code=500, code=CODE_REPORT_GENERATION_FAILED,
            ) from exc
        db.refresh(report)

        # 站内信通知（no-throw，失败不影响报告）。
        notify(
            db, user_id=actor.id, event_type="report.generated",
            title=f"测试报告已生成 {report.report_no}",
            body=f"风险等级 {report.risk_level}，通过率 {report.pass_rate}%",
            project_id=run.project_id, actor_id=actor.id, actor_username=getattr(actor, "username", None),
            detail={"report_id": report.id, "risk_level": report.risk_level},
        )
        db.commit()
        return ReportGenerateResponse(report_id=report.id, status=report.status)

    # ---------------------------------------------------------------- 查询 / 删除

    def get_report_orm(self, db: Session, report_id: int, user: User) -> TestReport:
        """取报告 ORM（带 viewer+ 鉴权），供飞书通知等需要读 ORM 的调用方使用。

        与 get_report 共用同一鉴权；返回 ORM 而非响应模型，避免重复构造大对象。
        """
        report = db.get(TestReport, report_id)
        if report is None:
            raise not_found("测试报告不存在")
        get_project_or_404(db, report.project_id, user)
        return report

    def get_report(self, db: Session, report_id: int, user: User) -> TestReportDetailResponse:
        """报告详情：报告本体 + TestRun 摘要 + 逐用例执行明细 + 失败分类（实时读取）。"""
        report = db.get(TestReport, report_id)
        if report is None:
            raise not_found("测试报告不存在")
        get_project_or_404(db, report.project_id, user)  # viewer+

        run = db.get(TestRun, report.test_run_id) if report.test_run_id else None
        rows = self._rows_for_run(db, report.test_run_id) if report.test_run_id else []
        case_failure_types: dict[str, str] = (report.summary or {}).get("case_failure_types", {}) or {}

        case_execs: list[CaseExecutionSummary] = []
        for ce, case in rows:
            # 快照执行时已脱敏落库；此处 sanitize_context 兜底（§敏感数据）。
            case_execs.append(
                CaseExecutionSummary(
                    id=ce.id,
                    test_case_id=ce.test_case_id,
                    case_name=(case.name if case else "(已删除用例)"),
                    priority=(case.priority if case else "P1"),
                    case_type=(case.case_type if case else None),
                    status=ce.status,
                    failure_type=(
                        case_failure_types.get(str(ce.id))
                        or (self._classify_failure(ce, case) if ce.status in ("FAILED", "ERROR") else None)
                    ),
                    executor_type=ce.executor_type,
                    duration_ms=ce.duration_ms,
                    error_code=ce.error_code,
                    error_message=sanitize_text(ce.error_message) if ce.error_message else None,
                    started_at=ce.started_at,
                    finished_at=ce.finished_at,
                    request_snapshot=sanitize_context(ce.request_snapshot),
                    response_snapshot=sanitize_context(ce.response_snapshot),
                    assertion_results=sanitize_context(ce.assertion_results),
                    context_json=sanitize_context(ce.context_json),
                )
            )

        run_brief = (
            TestRunBrief(
                id=run.id, status=run.status, environment_id=run.environment_id,
                started_at=run.started_at, finished_at=run.finished_at,
            )
            if run is not None
            else None
        )
        failure_clusters = (report.summary or {}).get("failure_clusters", []) or []
        return TestReportDetailResponse(
            report=TestReportResponse.model_validate(report),
            test_run=run_brief,
            case_executions=case_execs,
            failure_clusters=failure_clusters,
        )

    def list_reports(
        self, db: Session, project_id: int, user: User, *,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
        environment_id: int | None = None,
        risk_level: str | None = None,
        status: str | None = None,
        test_run_id: int | None = None,
    ) -> TestReportListResponse:
        """报告列表（按项目 + 可选筛选）。读权限 viewer+。"""
        get_project_or_404(db, project_id, user)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        q = db.query(TestReport).filter(TestReport.project_id == project_id)
        if environment_id is not None:
            q = q.filter(TestReport.environment_id == environment_id)
        if risk_level:
            q = q.filter(TestReport.risk_level == risk_level)
        if status:
            q = q.filter(TestReport.status == status)
        if test_run_id is not None:
            q = q.filter(TestReport.test_run_id == test_run_id)
        total = int(q.count())
        items = q.order_by(TestReport.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return TestReportListResponse(
            items=[TestReportListItem.model_validate(r) for r in items],
            total=total, page=page, page_size=page_size,
        )

    def delete_report(self, db: Session, report_id: int, user: User) -> None:
        """删除报告记录（仅报告，不删 TestRun / CaseExecution，§十一）。member+。"""
        report = db.get(TestReport, report_id)
        if report is None:
            raise not_found("测试报告不存在")
        require_writable_project(db, report.project_id, user)
        db.delete(report)
        db.commit()

    def regenerate_ai_summary(
        self, db: Session, report_id: int, user: User, *, provider: Any = None,
    ) -> TestReportResponse:
        """重生成 AI 总结（统计字段不变，§三十 报告统计数据不可变）。member+。"""
        report = db.get(TestReport, report_id)
        if report is None:
            raise not_found("测试报告不存在")
        require_writable_project(db, report.project_id, user)
        rows = self._rows_for_run(db, report.test_run_id) if report.test_run_id else []
        self._generate_ai_summary(db, report, rows, provider)
        db.commit()
        db.refresh(report)
        return TestReportResponse.model_validate(report)

    # ---------------------------------------------------------------- 内部：统计 / 分类 / 风险

    def _rows_for_run(self, db: Session, test_run_id: int | None) -> list[tuple[CaseExecution, TestCase | None]]:
        """取执行记录下的逐用例执行 + 关联用例（左 join，用例可能已删）。"""
        if test_run_id is None:
            return []
        return (
            db.query(CaseExecution, TestCase)
            .outerjoin(TestCase, CaseExecution.test_case_id == TestCase.id)
            .filter(CaseExecution.test_run_id == test_run_id)
            .order_by(CaseExecution.id.asc())
            .all()
        )

    def _mock_summary(self, db: Session, test_run_id: int | None) -> dict[str, Any]:
        """Mock Summary（§六十二）：本次执行期间的 Mock 调用汇总，纯统计口径。

        服务数 / 场景数 / 调用数 / 失败调用数（未命中或 5xx）+ 按 service_key / scenario_key
        的明细。只给计数与键名，**不复制任何请求 / 响应快照** —— 快照已脱敏落库在
        mock_execution，报告明细走实时读取，不在此二次搬运（§四 同一约束）。
        """
        empty = {
            "involved": False,
            "services": 0,
            "scenarios": 0,
            "calls": 0,
            "failed_calls": 0,
            "services_used": [],
            "scenarios_used": [],
        }
        if test_run_id is None:
            return empty
        rows = (
            db.query(MockExecution)
            .filter(MockExecution.test_run_id == test_run_id)
            .order_by(MockExecution.id.asc())
            .all()
        )
        if not rows:
            return empty

        service_ids = sorted({r.mock_service_id for r in rows if r.mock_service_id is not None})
        scenario_ids = sorted({r.mock_scenario_id for r in rows if r.mock_scenario_id is not None})
        failed = sum(
            1 for r in rows if (not r.matched) or (r.response_status or 0) >= 500
        )

        keys: dict[int, str] = {}
        if service_ids:
            keys.update({
                row.id: row.service_key
                for row in db.query(MockService.id, MockService.service_key)
                .filter(MockService.id.in_(service_ids)).all()
            })
        scenario_keys: dict[int, str] = {}
        if scenario_ids:
            scenario_keys = {
                row.id: row.scenario_key
                for row in db.query(MockScenario.id, MockScenario.scenario_key)
                .filter(MockScenario.id.in_(scenario_ids)).all()
            }

        return {
            "involved": True,
            "services": len(service_ids),
            "scenarios": len(scenario_ids),
            "calls": len(rows),
            "failed_calls": failed,
            "services_used": [
                {"service_id": sid, "service_key": keys.get(sid)} for sid in service_ids
            ],
            "scenarios_used": [
                {"scenario_id": sid, "scenario_key": scenario_keys.get(sid)} for sid in scenario_ids
            ],
        }

    def _analyze(
        self, rows: list[tuple[CaseExecution, TestCase | None]],
    ) -> tuple[dict[str, Any], dict[str, Any], int, str]:
        """代码统计：计数 / 通过率 / 总耗时 / 失败分类 / 风险等级。

        Returns:
            (stats, summary, duration_ms, risk_level)。统计字段绝不交给 LLM（§五）。
        """
        total = len(rows)
        passed = failed = error = skipped = 0
        duration_ms = 0
        case_failure_types: dict[str, str] = {}
        clusters: dict[str, list[int]] = {}

        for ce, case in rows:
            status = ce.status
            if status == "PASSED":
                passed += 1
            elif status == "FAILED":
                failed += 1
            elif status == "ERROR":
                error += 1
            elif status == "SKIPPED":
                skipped += 1
            if ce.duration_ms:
                duration_ms += int(ce.duration_ms)
            if status in ("FAILED", "ERROR"):
                ftype = self._classify_failure(ce, case)
                case_failure_types[str(ce.id)] = ftype
                clusters.setdefault(ftype, []).append(ce.id)

        # 通过率：passed / (total - skipped) * 100；分母为 0 记 0（§六）。
        denom = total - skipped
        pass_rate = round(passed / denom * 100, 2) if denom > 0 else 0

        stats = {
            "total": total, "passed": passed, "failed": failed,
            "error": error, "skipped": skipped, "pass_rate": pass_rate,
        }
        summary = {
            "failure_clusters": [
                {"failure_type": ft, "count": len(ids), "case_execution_ids": ids}
                for ft, ids in clusters.items()
            ],
            "case_failure_types": case_failure_types,
        }
        risk = self._compute_risk(rows)
        return stats, summary, duration_ms, risk

    def _classify_failure(self, ce: CaseExecution, case: TestCase | None) -> str:
        """失败分类（§七）。POTENTIAL_BUG 仅表示疑似产品问题、需人工确认。"""
        status = ce.status
        err_msg = (ce.error_message or "").lower()
        assertions = ce.assertion_results or []
        has_failed_assertion = any(
            isinstance(a, dict) and not bool(a.get("passed", True)) for a in assertions
        )

        if status == "ERROR":
            if any(s in err_msg for s in _ENV_SIGNALS):
                return "ENVIRONMENT_ERROR"
            return "EXECUTION_ERROR"

        # status == "FAILED"
        if any(s in err_msg for s in _ENV_SIGNALS):
            return "ENVIRONMENT_ERROR"
        if any(s in err_msg for s in _DATA_SIGNALS):
            return "TEST_DATA_ISSUE"
        # 权限/负向/安全用例失败 → 疑似产品问题（如「无权限用户竟返回 200」），需人工确认。
        if case is not None and case.case_type in ("PERMISSION", "NEGATIVE", "SECURITY"):
            return "POTENTIAL_BUG"
        if has_failed_assertion:
            return "ASSERTION_FAILURE"
        return "UNKNOWN"

    def _compute_risk(self, rows: list[tuple[CaseExecution, TestCase | None]]) -> str:
        """风险等级（§八）：由代码规则决定，AI 仅提供解释。

        - 全部通过 → LOW
        - 权限/鉴权类（PERMISSION/SECURITY）P0 失败 → CRITICAL
        - 其余 P0 失败 → HIGH
        - 仅 P1/P2/P3 失败 → MEDIUM
        """
        failed_rows = [(ce, case) for ce, case in rows if ce.status in ("FAILED", "ERROR")]
        if not failed_rows:
            return "LOW"
        if any(
            case is not None and case.priority == "P0"
            and case.case_type in ("PERMISSION", "SECURITY")
            for ce, case in failed_rows
        ):
            return "CRITICAL"
        if any(case is not None and case.priority == "P0" for ce, case in failed_rows):
            return "HIGH"
        return "MEDIUM"

    def _gen_report_no(self, db: Session) -> str:
        """生成稳定编号 RPT-YYYYMMDD-NNNNNN（按当日已存在报告数 +1）。"""
        now = datetime.now()
        prefix = f"RPT-{now.strftime('%Y%m%d')}-"
        count = db.query(TestReport).filter(TestReport.report_no.like(f"{prefix}%")).count()
        return f"{prefix}{count + 1:06d}"

    def _generate_ai_summary(
        self, db: Session, report: TestReport,
        rows: list[tuple[CaseExecution, TestCase | None]], provider: Any,
    ) -> None:
        """调用 LLM 生成结构化 AI 总结；失败置空，不影响报告 COMPLETED（§九）。"""
        try:
            if provider is None:
                # 懒构造生产 Provider：无默认模型时 generate_summary 内部会捕获并返回 None。
                from app.features.agent.providers.llm_provider import ProductionLLMProvider
                provider = ProductionLLMProvider(db)
            payload = self._build_ai_payload(report, rows)
            result = generate_ai_summary(provider, payload)
            if result is not None:
                report.ai_summary = result
                report.ai_summary_version = "summary-v1"
            else:
                report.ai_summary = None
        except Exception:  # noqa: BLE001 — AI 失败绝不拖垮基础报告。
            report.ai_summary = None

    def _build_ai_payload(
        self, report: TestReport, rows: list[tuple[CaseExecution, TestCase | None]],
    ) -> dict[str, Any]:
        """构造送给 LLM 的报告数据（脱敏后，§三一 真实数据原则）。"""
        case_failure_types: dict[str, str] = (report.summary or {}).get("case_failure_types", {}) or {}
        failed_cases: list[dict[str, Any]] = []
        for ce, case in rows:
            if ce.status not in ("FAILED", "ERROR"):
                continue
            failed_cases.append({
                "case_name": case.name if case else "(已删除用例)",
                "priority": case.priority if case else "P1",
                "case_type": case.case_type if case else None,
                "status": ce.status,
                "failure_type": case_failure_types.get(str(ce.id), "UNKNOWN"),
                "error_code": ce.error_code,
                "error_message": sanitize_text(ce.error_message) if ce.error_message else None,
                "assertion_summary": [
                    {"assertion_type": a.get("assertion_type"), "passed": a.get("passed"),
                     "message": sanitize_text(a.get("message"))}
                    for a in (ce.assertion_results or []) if isinstance(a, dict)
                ],
            })
        payload = {
            "report_no": report.report_no,
            "totals": {
                "total": report.total_cases, "passed": report.passed_cases,
                "failed": report.failed_cases, "error": report.error_cases,
                "skipped": report.skipped_cases,
            },
            "pass_rate": float(report.pass_rate),
            "duration_ms": report.duration_ms,
            "risk_level": report.risk_level,
            "failure_clusters": (report.summary or {}).get("failure_clusters", []) or [],
            # Mock Summary 只有计数与 service_key / scenario_key，无快照，可安全进 LLM。
            "mock_summary": (report.summary or {}).get("mock_summary") or {},
            "failed_cases": failed_cases,
        }
        # 进 LLM 前整体脱敏（§三一、§敏感数据）。
        return sanitize_context(payload)
