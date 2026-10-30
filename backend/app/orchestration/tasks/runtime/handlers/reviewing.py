"""正式事实审阅处理器。

模型输出只作为建议；最终结论由批准范围、TestRun 与正式报告计数、安全执行事实及
模型调用后的暂停/取消边界共同决定。
"""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.features.reports.models.report import TestReport
from app.features.security_testing.models import SecurityFinding
from app.orchestration.tasks.models import (
    TaskAgentInstance,
    TaskMessage,
    TaskPlan,
    TaskWorkItem,
    TaskWorkItemDependency,
)
from app.orchestration.tasks.runtime.contracts import TaskHandlerContext, TaskHandlerServices, require_agent_tool
from app.orchestration.tasks.schemas import TaskReviewOutput
from app.agents.services.task_decision_service import _REVIEWER_SYSTEM, generate_structured_candidate
from app.features.test_management.models.execution import TestRun


def reconcile_review_facts(
    review: TaskReviewOutput, test_run: TestRun, report: TestReport,
    approved_case_ids: list[int], *, security_status: str | None = None,
) -> tuple[bool, list[str]]:
    """用正式执行与报告事实约束模型结论，并返回去重后的审阅发现。"""
    findings = [sanitize_text(item) for item in review.findings]
    if security_status is not None and security_status != "COMPLETED":
        findings.append(f"安全评估未完成：{security_status or 'UNKNOWN'}")
        findings = findings[:12]
    counts_match = (
        report.status == "COMPLETED"
        and report.total_cases == test_run.total
        and report.passed_cases == test_run.passed
        and report.failed_cases == test_run.failed
        and report.skipped_cases == test_run.skipped
        and report.error_cases == test_run.error
    )
    if test_run.total != len(approved_case_ids):
        findings.append(f"执行覆盖 {test_run.total}/{len(approved_case_ids)} 个已批准用例")
    if not counts_match:
        findings.append("正式报告未完成或其计数与 TestRun 不一致")
    security_complete = security_status is None or security_status == "COMPLETED"
    approved = bool(
        review.approved and test_run.total == len(approved_case_ids)
        and counts_match and security_complete
    )
    return approved, list(dict.fromkeys(findings))


def handle_review(context: TaskHandlerContext, services: TaskHandlerServices) -> None:
    """依据已批准范围、正式 TestRun/报告及安全事实生成受约束审阅结论。"""
    db = context.db
    task, run, work, attempt, actor = context.task, context.run, context.work, context.attempt, context.actor
    agent = context.agent
    if agent is None:
        raise RuntimeError("审阅 Agent 实例不存在")
    require_agent_tool(run, agent, "report.review")
    require_agent_tool(run, agent, "test-run.read")
    test_run = db.get(TestRun, int(work.input_json["test_run_id"]))
    report = db.get(TestReport, int(work.input_json["report_id"]))
    plan = db.query(TaskPlan).filter(
        TaskPlan.task_run_id == run.id,
        TaskPlan.version == run.current_plan_version,
        TaskPlan.status == "ACCEPTED",
    ).first()
    if test_run is None or report is None or plan is None:
        raise RuntimeError("审阅所需的执行、报告或已批准方案不存在")
    target_type = run.input_snapshot.get("target_type", "API")
    execution_work = None
    if target_type == "SECURITY":
        execution_work = db.query(TaskWorkItem).filter(
            TaskWorkItem.task_run_id == run.id,
            TaskWorkItem.kind == "EXECUTE_SECURITY",
            TaskWorkItem.status == "SUCCEEDED",
        ).order_by(TaskWorkItem.id.desc()).first()
        approved_case_ids = list((execution_work.input_json or {}).get("security_case_ids") or []) if execution_work else []
    else:
        approved_case_ids = list(plan.plan_json.get("case_ids", []))
    facts = {
        "goal": run.goal_snapshot,
        "approved_case_ids": approved_case_ids,
        "acceptance_criteria": plan.plan_json.get("acceptance_criteria", []),
        "test_run": {"id": test_run.id, "status": test_run.status, "total": test_run.total, "passed": test_run.passed, "failed": test_run.failed, "error": test_run.error},
        "report": {"id": report.id, "status": report.status, "total": report.total_cases, "passed": report.passed_cases, "failed": report.failed_cases, "skipped": report.skipped_cases, "error": report.error_cases, "summary": report.summary},
    }
    if target_type == "SECURITY":
        finding_rows = db.query(SecurityFinding).filter(
            SecurityFinding.project_id == task.project_id,
            SecurityFinding.test_run_id == test_run.id,
        ).order_by(SecurityFinding.id.asc()).limit(100).all()
        facts["security_assessment"] = {
            "status": "COMPLETED" if execution_work is not None else "MISSING",
            "api_ids": (run.input_snapshot.get("security_assessment") or {}).get("api_ids")
            or [(run.input_snapshot.get("security_assessment") or {}).get("api_id")],
            "security_case_count": len(approved_case_ids),
            "findings": [
                {"id": row.id, "title": row.title, "severity": row.severity, "status": row.status, "mutation_type": row.mutation_type}
                for row in finding_rows
            ],
            "web_inspection": (plan.plan_json.get("security_assessment_preview") or {}).get("web_inspection"),
        }
    # 模型调用前提交既有读取阶段的会话状态，保持原来的长 IO 事务边界。
    db.commit()
    provider = services.provider_for_agent(db, task, run, work, attempt, agent, actor)
    profile = (run.input_snapshot or {}).get("agent_definition") or {}
    output = generate_structured_candidate(
        provider, _REVIEWER_SYSTEM, profile,
        json.dumps(sanitize_context(facts), ensure_ascii=False, default=str),
        schema=TaskReviewOutput.model_json_schema(), kind="task_reviewer",
        validator=TaskReviewOutput.model_validate, always_wrap=True,
    )
    review = TaskReviewOutput.model_validate(output)
    security_fact = facts.get("security_assessment")
    db.refresh(run, with_for_update=True)
    if services.defer_at_control_boundary(db, run, work, attempt, agent):
        return
    review_approved, findings = reconcile_review_facts(
        review, test_run, report, approved_case_ids,
        security_status=security_fact.get("status") if security_fact else None,
    )
    final_agent = db.query(TaskAgentInstance).filter(
        TaskAgentInstance.task_run_id == run.id, TaskAgentInstance.role == "MAIN",
    ).first()
    final_work = services.enqueue_work(
        db, run, final_agent, work_key=f"finalize:{test_run.id}", kind="FINALIZE",
        input_json={"test_run_id": test_run.id, "report_id": report.id}, sequence=50,
    )
    if not db.query(TaskWorkItemDependency.id).filter(
        TaskWorkItemDependency.work_item_id == final_work.id,
        TaskWorkItemDependency.depends_on_id == work.id,
    ).first():
        db.add(TaskWorkItemDependency(work_item_id=final_work.id, depends_on_id=work.id))
    agent.status = "COMPLETED"
    db.add(TaskMessage(
        task_run_id=run.id,
        agent_instance_id=agent.id,
        sender_type="AGENT",
        sender_instance_id=agent.id,
        message_type="REVIEW",
        content="审阅通过" if review_approved else "审阅发现问题",
        metadata_json={"approved": review_approved, "findings": findings, "test_run_id": test_run.id, "report_id": report.id},
        status="PROCESSED",
        client_message_id=f"agent:review:{work.id}",
        processed_at=datetime.now(),
    ))
    services.append_event(
        db, run, "review.completed",
        {"approved": review_approved, "findings_count": len(findings), "work_item_id": work.id},
        agent_instance_id=agent.id,
    )

