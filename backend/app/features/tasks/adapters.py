"""任务与既有测试、报告服务之间的业务适配器。

只封装已实现的 TestRun 与 TestReport 服务调用，不复制资产表或执行器；后续 UI / 安全适配器单独接入。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.features.agent.providers.llm_provider import LLMProvider
from app.features.agent.tools.execution_tool import create_test_run
from app.features.reports.services.report_service import ReportService
from app.models.identity import User


def execute_api_cases(
    db: Session,
    project_id: int,
    actor: User,
    *,
    case_ids: list[int],
    environment_id: int,
    task_run_id: int,
) -> dict[str, Any]:
    """通过既有 Agent 执行工具和 RunService 真实执行 API 用例。"""
    return create_test_run(
        db,
        project_id,
        actor,
        case_ids=case_ids,
        environment_id=environment_id,
        session_id=task_run_id,
        source_label="Task",
    )


def execute_confirmed_web_cases(
    db: Session,
    project_id: int,
    actor: User,
    *,
    case_ids: list[int],
    environment_id: int,
    task_run_id: int,
) -> dict[str, Any]:
    """只接受当前版本已人工确认的 Web 用例，再复用 TestRun 与 Playwright 执行链。"""
    from app.features.test_management.models.test_case import TestCase
    from app.features.web_ui.models import WebCase
    from app.features.web_ui.services.web_ui_service import case_response

    ordered_ids = list(dict.fromkeys(case_ids))
    cases = db.query(TestCase).filter(TestCase.id.in_(ordered_ids), TestCase.project_id == project_id).all()
    if len(cases) != len(ordered_ids):
        raise ValueError("部分 Web 用例不存在或不属于当前项目")
    for case in cases:
        if case.target_type != "WEB" or not case.enabled or case.status != "ACTIVE":
            raise ValueError("Web Worker 仅能运行启用且 ACTIVE 的 Web 用例")
        if db.get(WebCase, case.id) is None or not case_response(db, case).get("confirmed"):
            raise ValueError("Web 用例或页面对象已变化，需先由用户重新确认")
    return create_test_run(
        db,
        project_id,
        actor,
        case_ids=ordered_ids,
        environment_id=environment_id,
        session_id=task_run_id,
        source_label="Task",
    )


def build_test_report(
    db: Session, test_run_id: int, actor: User, *, provider: LLMProvider,
) -> dict[str, Any]:
    """经既有 ReportService 创建或复用正式报告，并返回原报告 ID。"""
    result = ReportService().build_report(
        db,
        test_run_id,
        actor=actor,
        generate_ai_summary=True,
        provider=provider,
    )
    return result.model_dump(mode="json")


def create_security_scan(
    db: Session,
    project_id: int,
    approver: User,
    *,
    target_id: int,
    scan_profile_id: int,
    test_run_id: int,
    approval_note: str | None,
    idempotency_key: str,
) -> dict[str, Any]:
    """使用既有 ZAP job_service 登记扫描；扫描仍由原 ScanWorker 领取执行。"""
    from app.features.security_testing.zap.schemas import ScanJobCreate
    from app.features.security_testing.zap.services import job_service

    row = job_service.create(
        db,
        project_id,
        approver,
        ScanJobCreate(
            target_id=target_id,
            scan_profile_id=scan_profile_id,
            test_run_id=test_run_id,
            confirmed=True,
            approval_note=approval_note,
            idempotency_key=idempotency_key,
        ),
    )
    return job_service.to_read(db, row).model_dump(mode="json")


def get_security_scan(db: Session, project_id: int, actor: User, job_id: int) -> dict[str, Any]:
    """通过 ZAP 现有查询服务读取扫描状态，不直接连接 ZAP。"""
    from app.features.security_testing.zap.services import job_service

    return job_service.get_job(db, project_id, actor, job_id).model_dump(mode="json")
