"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from app.features.security_testing.models import SecurityCase, SecurityExecution, SecurityFinding
from app.features.test_management.executors.contracts import CaseExecutionResult
from app.features.test_management.models.test_case import TestCase
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.features.security_testing.runtime.preparation import baseline_conclusion_of
from app.features.security_testing.runtime.preparation import baseline_status_of


_CASE_STATUS_BY_RESULT = {
    "PASS": "PASSED",
    "POTENTIAL_ISSUE": "FAILED",
    "FAILED_EXECUTION": "ERROR",
    "INCONCLUSIVE": "SKIPPED",
    "SKIPPED": "SKIPPED",
}


def write_execution(
    db: Session,
    *,
    project_id: int | None,
    test_run_id: int | None,
    case_execution_id: int | None,
    security_case: SecurityCase,
    environment: Environment,
    actor: User,
    baseline_status: int | None,
    security_result: str,
    classification: str | None,
    mutation_trace: list[dict[str, Any]],
    replay_count: int,
    actual_status_codes: list[int],
    evidence: dict[str, Any] | None,
    error_code: str | None,
    started_at: datetime,
) -> SecurityExecution:
    """写一行 security_execution。commit 由 RunService 统一做。

    ``baseline_status`` 存的是基线 HTTP 状态码，列上是 ``PASSED/FAILED``，
    原始码另存 ``baseline_http_status``（§4.6）。
    """
    row = SecurityExecution(
        project_id=project_id,
        test_run_id=test_run_id,
        case_execution_id=case_execution_id,
        security_case_id=security_case.id,
        environment_id=getattr(environment, "id", None),
        actor_id=getattr(actor, "id", None),
        baseline_status=baseline_conclusion_of(baseline_status),
        baseline_http_status=baseline_status,
        security_result=security_result,
        classification=classification,
        mutation_trace=mutation_trace,
        replay_count=replay_count,
        actual_status_codes=actual_status_codes,
        evidence=evidence,
        error_code=error_code,
        started_at=started_at,
        finished_at=datetime.now(),
    )
    db.add(row)
    db.flush()
    return row


def upsert_finding(
    db: Session,
    *,
    project_id: int | None,
    test_run_id: int | None,
    case_execution_id: int | None,
    security_execution_id: int | None,
    security_case: SecurityCase,
    fingerprint: str,
    severity: str,
    evidence: dict[str, Any],
    title: str,
    description: str,
    recommendation: str,
    actor: User,
    mutation_type: str,
) -> SecurityFinding | None:
    """同 fingerprint 的未关闭 Finding 只保留一条，重复执行只累加 ``evidence.repeat_count``。

    部分唯一索引只在 status IN ('OPEN','CONFIRMED') 上生效，所以误报 / 忽略 / 已解决
    之后可以重新开一条 OPEN，并把旧状态写进 ``evidence.prior_status`` 留作复核线索；
    并发插入撞索引时改走更新分支。
    """
    if not severity or not project_id:
        return None
    open_row = (
        db.query(SecurityFinding)
        .filter(
            SecurityFinding.project_id == project_id,
            SecurityFinding.fingerprint == fingerprint,
            SecurityFinding.status.in_(("OPEN", "CONFIRMED")),
        )
        .order_by(SecurityFinding.id.desc())
        .first()
    )
    if open_row is not None:
        # 还在跟的那一条：累加次数、把指针指向最新一次执行，不重复开记录。
        count = int((open_row.evidence or {}).get("repeat_count") or 1)
        evidence["repeat_count"] = count + 1
        open_row.security_execution_id = security_execution_id
        open_row.case_execution_id = case_execution_id
        open_row.test_run_id = test_run_id or open_row.test_run_id
        open_row.evidence = evidence
        open_row.updated_at = datetime.now()
        db.add(open_row)
        db.flush()
        return open_row

    prior = (
        db.query(SecurityFinding)
        .filter(
            SecurityFinding.project_id == project_id,
            SecurityFinding.fingerprint == fingerprint,
        )
        .order_by(SecurityFinding.id.desc())
        .first()
    )
    prior_status = str(getattr(prior, "status", None) or "") if prior is not None else None
    return SecurityFinding(
        project_id=project_id,
        test_run_id=test_run_id,
        case_execution_id=case_execution_id,
        security_execution_id=security_execution_id,
        api_id=security_case.api_id,
        business_action_id=security_case.business_action_id,
        strategy_id=security_case.strategy_id,
        security_case_id=security_case.id,
        mutation_type=mutation_type,
        severity=severity,
        status="OPEN",
        title=title,
        description=description,
        # 误报 / 忽略 / 已解决之后又出现：留一条旧状态线索，便于复核为什么重新开。
        evidence={**evidence, "prior_status": prior_status or None, "repeat_count": 1},
        recommendation=recommendation,
        fingerprint=fingerprint,
        created_by=getattr(actor, "id", None),
    )


class CaseContext:
    """一次安全执行的落库上下文，避免各分支重复传参。"""

    def __init__(
        self,
        db: Session,
        *,
        security_case: SecurityCase,
        environment: Environment,
        actor: User,
        run_id: int | None,
        case_execution_id: int | None,
        started_at: datetime,
    ) -> None:
        """初始化对象状态。"""
        self.db = db
        self.security_case = security_case
        self.environment = environment
        self.actor = actor
        self.run_id = run_id
        self.case_execution_id = case_execution_id
        self.started_at = started_at

    def finish(
        self,
        test_case: TestCase,
        *,
        security_result: str,
        classification: str,
        message: str,
        error_code: str | None,
        baseline_result: Any = None,
        mutation_trace: list[dict[str, Any]] | None = None,
        replay_count: int = 0,
        actual_status_codes: list[int] | None = None,
        evidence: dict[str, Any] | None = None,
        assertion_results: list[dict[str, Any]] | None = None,
    ) -> Any:
        """写 execution 并返回既有四态的 CaseExecutionResult。"""
        baseline_http = baseline_status_of(baseline_result) if baseline_result is not None else None
        execution = write_execution(
            self.db,
            project_id=self.security_case.project_id,
            test_run_id=self.run_id,
            case_execution_id=self.case_execution_id,
            security_case=self.security_case,
            environment=self.environment,
            actor=self.actor,
            baseline_status=baseline_http,
            security_result=security_result,
            classification=classification,
            mutation_trace=list(mutation_trace or []),
            replay_count=replay_count,
            actual_status_codes=list(actual_status_codes or []),
            evidence=evidence,
            error_code=error_code,
            started_at=self.started_at,
        )
        return CaseExecutionResult(
            status=_CASE_STATUS_BY_RESULT.get(security_result, "SKIPPED"),
            executor_type="SECURITY",
            request_snapshot=getattr(baseline_result, "request_snapshot", None),
            response_snapshot=getattr(baseline_result, "response_snapshot", None),
            assertion_results=list(assertion_results or []),
            context_json={
                "security_execution_id": execution.id,
                "security_case_id": self.security_case.id,
                "security_result": security_result,
                "security_classification": classification,
                "security_message": message,
            },
            error_code=error_code,
            error_message=message,
        )
