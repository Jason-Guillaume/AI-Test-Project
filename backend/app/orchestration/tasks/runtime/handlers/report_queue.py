"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import (
    TaskAgentInstance,
    TaskAttempt,
    TaskRun,
    TaskWorkItem,
    TaskWorkItemDependency,
)
from app.orchestration.tasks.services.state_service import enqueue_work


def queue_report(db: Session, run: TaskRun, work: TaskWorkItem, agent: TaskAgentInstance, attempt: TaskAttempt, result: dict) -> None:
    """执行回执持久化后登记依赖该执行结果的报告工作项。"""
    work.status = "SUCCEEDED"
    work.output_json = {"test_run_id": result.get("id"), "status": result.get("status")}
    work.finished_at = datetime.now()
    attempt.status = "SUCCEEDED"
    attempt.finished_at = datetime.now()
    enqueue_report_after(db, run, work, agent, int(result["id"]))


def enqueue_report_after(db: Session, run: TaskRun, dependency_work: TaskWorkItem, agent: TaskAgentInstance, test_run_id: int) -> None:
    """为报告登记唯一工作项，并明确依赖测试或安全评估执行的终态。"""
    from app.orchestration.tasks.models import TaskWorkItemDependency

    report_agent = db.query(TaskAgentInstance).filter(TaskAgentInstance.task_run_id == run.id, TaskAgentInstance.role == "REPORT_AGENT").first()
    if report_agent is None:
        raise RuntimeError("报告 Agent 实例不存在")
    report_work = enqueue_work(
        db, run, report_agent, work_key=f"report:{test_run_id}", kind="REPORT",
        input_json={"test_run_id": test_run_id}, sequence=30,
    )
    if not db.query(TaskWorkItemDependency.id).filter(
        TaskWorkItemDependency.work_item_id == report_work.id,
        TaskWorkItemDependency.depends_on_id == dependency_work.id,
    ).first():
        db.add(TaskWorkItemDependency(work_item_id=report_work.id, depends_on_id=dependency_work.id))
    report_agent.status = "QUEUED"
    run.stage = "REPORTING"
