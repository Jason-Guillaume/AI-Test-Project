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
