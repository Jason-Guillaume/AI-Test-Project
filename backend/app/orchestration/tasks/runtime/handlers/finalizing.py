"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.orchestration.tasks.services import state_service
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskAttempt, TaskMessage, TaskRun, TaskWorkItem
from app.features.test_management.models.execution import TestRun
from app.features.reports.models.report import TestReport
from app.core.models.identity import User
from app.orchestration.tasks.runtime.contracts import ProviderFactory
from app.agents.services.task_decision_service import _MAIN_SYSTEM, generate_text_candidate
from app.orchestration.tasks.runtime.completion_service import defer_at_control_boundary


def handle_finalize(db: Session, task: Task, run: TaskRun, work: TaskWorkItem, attempt: TaskAttempt, agent: TaskAgentInstance | None, actor: User, *, provider_for_agent: ProviderFactory) -> None:
    """任务主 Agent 只基于已生成报告总结，不自行更改业务或运行状态。"""
    if agent is None:
        raise RuntimeError("任务主 Agent 实例不存在")
    test_run_id = int(work.input_json["test_run_id"])
    report_id = int(work.input_json["report_id"])
    test_run = db.get(TestRun, test_run_id)
    report = db.get(TestReport, report_id)
    if test_run is None or report is None or test_run.project_id != task.project_id or report.project_id != task.project_id:
        raise RuntimeError("测试执行或报告已不存在，任务不能宣称成功")
    facts = {
        "goal": run.goal_snapshot,
        "test_run_id": test_run.id,
        "test_run_status": test_run.status,
        "total": test_run.total,
        "passed": test_run.passed,
        "failed": test_run.failed,
        "error": test_run.error,
        "report_id": report.id,
        "report_no": report.report_no,
        "risk_level": report.risk_level,
        "ai_summary": report.ai_summary,
    }
    review_message = db.query(TaskMessage).filter(
        TaskMessage.task_run_id == run.id,
        TaskMessage.message_type == "REVIEW",
        TaskMessage.status == "PROCESSED",
    ).order_by(TaskMessage.id.desc()).first()
    review = review_message.metadata_json if review_message else {"approved": False, "findings": ["缺少审阅结论"]}
    facts["review"] = review
    provider = provider_for_agent(db, task, run, work, attempt, agent, actor)
    reply = generate_text_candidate(
        provider, _MAIN_SYSTEM, (run.input_snapshot or {}).get("agent_definition") or {},
        json.dumps(sanitize_context(facts), ensure_ascii=False, default=str),
    )
    db.refresh(run, with_for_update=True)
    if defer_at_control_boundary(db, run, work, attempt, agent):
        return
    db.add(TaskMessage(
        task_run_id=run.id,
        agent_instance_id=agent.id,
        sender_type="AGENT",
        sender_instance_id=agent.id,
        message_type="RESULT",
        content=sanitize_text(reply),
        metadata_json={"test_run_id": test_run.id, "report_id": report.id},
        status="PROCESSED",
        client_message_id=f"agent:final:{work.id}",
        processed_at=datetime.now(),
    ))
    agent.status = "COMPLETED"
    run.stage = "COMPLETED"
    run.status = "SUCCEEDED" if test_run.status == "SUCCESS" and review.get("approved") else "SUCCEEDED_WITH_ISSUES"
    run.finished_at = datetime.now()
    state_service.append_event(db, run, "run.completed", {"status": run.status, "test_run_id": test_run.id, "report_id": report.id}, agent_instance_id=agent.id)
