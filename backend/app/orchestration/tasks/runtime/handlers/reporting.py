"""正式报告处理器。

处理器以 TestRun 为事实源调用既有报告服务，持久化原有 STARTED/成功回执、资源引用、
消息、审阅依赖和事件；回执 key 与提交顺序沿用 Worker 的既有行为。
"""

import json
from datetime import datetime

from app.agents.assembly.context import build_agent_guidance
from app.core.security.sanitizer import sanitize_context
from app.orchestration.tasks.adapters import build_test_report
from app.orchestration.tasks.models import (
    TaskAgentInstance,
    TaskMessage,
    TaskPlan,
    TaskToolInvocation,
    TaskWorkItemDependency,
)
from app.orchestration.tasks.runtime.contracts import TaskHandlerContext, TaskHandlerServices, require_agent_tool
from app.features.reports.models.report import TestReport


def handle_report(context: TaskHandlerContext, services: TaskHandlerServices) -> None:
    """汇总真实 TestRun 并创建正式报告，再登记依赖该报告的审阅工作项。"""
    db = context.db
    task, run, work, attempt, actor = context.task, context.run, context.work, context.attempt, context.actor
    agent = context.agent
    if agent is None:
        raise RuntimeError("报告 Agent 实例不存在")
    require_agent_tool(run, agent, "report.generate")
    require_agent_tool(run, agent, "test-run.read")
    test_run_id = int(work.input_json["test_run_id"])
    existing = db.query(TaskToolInvocation).filter(
        TaskToolInvocation.task_run_id == run.id,
        TaskToolInvocation.invocation_key == f"report:{test_run_id}",
    ).with_for_update().first()
    if existing is None:
        existing = TaskToolInvocation(
            task_run_id=run.id,
            work_item_id=work.id,
            agent_instance_id=agent.id,
            invocation_key=f"report:{test_run_id}",
            tool_name="report.generate",
            status="STARTED",
            input_json={"test_run_id": test_run_id},
        )
        db.add(existing)
        # STARTED 回执先于外部报告服务提交，重试可据此核对结果而不是换用新 key。
        db.commit()
    provider = services.provider_for_agent(db, task, run, work, attempt, agent, actor)
    profile = (run.input_snapshot or {}).get("agent_definition") or {}
    report_instructions = build_agent_guidance(profile)
    if run.input_snapshot.get("target_type") == "SECURITY":
        approved_plan = db.query(TaskPlan).filter(
            TaskPlan.task_run_id == run.id,
            TaskPlan.version == run.current_plan_version,
        ).first()
        web_inspection = (
            (approved_plan.plan_json.get("security_assessment_preview") or {}).get("web_inspection")
            if approved_plan else None
        )
        if web_inspection:
            report_instructions = "\n\n".join(filter(None, [
                report_instructions,
                "只读 Web 页面安全观察信号（不是漏洞确认；统计仅覆盖 API TestRun）：\n"
                + json.dumps(sanitize_context(web_inspection), ensure_ascii=False),
            ]))
    result = build_test_report(
        db, test_run_id, actor, provider=provider,
        ai_summary_instructions=report_instructions,
    )
    db.refresh(run, with_for_update=True)
    report_id = int(result["report_id"])
    report = db.get(TestReport, report_id)
    existing = db.query(TaskToolInvocation).filter(TaskToolInvocation.id == existing.id).with_for_update().one()
    existing.status = "SUCCEEDED"
    existing.result_json = sanitize_context(result)
    existing.finished_at = datetime.now()
    services.add_worker_resource(
        db, run, "OUTPUT", "REPORT", str(report_id),
        agent_instance_id=agent.id,
        metadata={"report_no": report.report_no if report else None, "status": result.get("status"), "test_run_id": test_run_id},
    )
    if report is not None:
        message_content = f"已创建正式测试报告 {report.report_no}，执行状态汇总为 {report.risk_level} 风险。"
        message_metadata = {"report_id": report.id, "report_no": report.report_no, "test_run_id": test_run_id, "risk_level": report.risk_level}
    else:
        message_content = f"已创建正式测试报告 #{report_id}。"
        message_metadata = {"report_id": report_id, "test_run_id": test_run_id}
    db.add(TaskMessage(
        task_run_id=run.id,
        agent_instance_id=agent.id,
        sender_type="AGENT",
        sender_instance_id=agent.id,
        message_type="REPORT",
        content=message_content,
        metadata_json=message_metadata,
        status="PROCESSED",
        client_message_id=f"agent:report:{work.id}",
        processed_at=datetime.now(),
    ))
    reviewer = db.query(TaskAgentInstance).filter(
        TaskAgentInstance.task_run_id == run.id, TaskAgentInstance.role == "REVIEWER",
    ).first()
    review_work = services.enqueue_work(
        db, run, reviewer, work_key=f"review:{test_run_id}", kind="REVIEW",
        input_json={"test_run_id": test_run_id, "report_id": report_id}, sequence=40,
    )
    if not db.query(TaskWorkItemDependency.id).filter(
        TaskWorkItemDependency.work_item_id == review_work.id,
        TaskWorkItemDependency.depends_on_id == work.id,
    ).first():
        db.add(TaskWorkItemDependency(work_item_id=review_work.id, depends_on_id=work.id))
    agent.status = "COMPLETED"
    run.stage = "REVIEWING"
    services.append_event(
        db, run, "business.report.created", {"report_id": report_id, "test_run_id": test_run_id},
        agent_instance_id=agent.id,
    )
