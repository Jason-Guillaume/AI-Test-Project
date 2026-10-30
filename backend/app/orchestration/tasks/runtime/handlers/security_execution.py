"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.core.http.errors import AppError
from app.orchestration.tasks.services import state_service
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.security.sanitizer import sanitize_context
from app.features.api_catalog.models.api_interface import ApiInterface
from app.orchestration.tasks.adapters import execute_security_cases
from app.orchestration.tasks.models import (
    Task,
    TaskAgentInstance,
    TaskAttempt,
    TaskMessage,
    TaskRun,
    TaskToolInvocation,
    TaskWorkItem,
)
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.orchestration.tasks.runtime.contracts import require_agent_tool
from app.features.test_management.models.test_case import TestCase
from app.features.security_testing.models import SecurityPlan
from app.core.models.identity import User
from app.orchestration.tasks.runtime.resources import add_resource
from app.orchestration.tasks.runtime.completion_service import defer_at_control_boundary
from app.orchestration.tasks.runtime.handlers.report_queue import queue_report


def handle_security_execution(db: Session, task: Task, run: TaskRun, work: TaskWorkItem, attempt: TaskAttempt, agent: TaskAgentInstance | None, actor: User) -> None:
    """只执行人工确认的安全用例，并把结果接回统一报告与审阅链。"""
    if agent is None:
        raise RuntimeError("安全执行 Worker 实例不存在")
    require_agent_tool(run, agent, "security-case.run")
    invocation_key = f"security-case-run:{run.id}:{work.id}"
    invocation = db.query(TaskToolInvocation).filter(
        TaskToolInvocation.task_run_id == run.id,
        TaskToolInvocation.invocation_key == invocation_key,
    ).with_for_update().first()
    if invocation is not None:
        if invocation.status == "SUCCEEDED":
            db.refresh(run, with_for_update=True)
            if defer_at_control_boundary(db, run, work, attempt, agent):
                return
            queue_report(db, run, work, agent, attempt, invocation.result_json or {})
            return
        if invocation.status in {"STARTED", "NEEDS_RECONCILIATION"}:
            raise RuntimeError("安全 TestRun 回执状态不明，请先从执行中心核对后再重试")
        raise RuntimeError("安全 TestRun 执行失败，请核对执行中心后再重新规划")

    from app.features.security_testing.models import SecurityCase

    security_case_ids = list(dict.fromkeys(int(i) for i in work.input_json.get("security_case_ids") or []))
    if not security_case_ids:
        raise RuntimeError("安全 Worker 没有收到已批准的安全用例")
    cases = db.query(SecurityCase).filter(
        SecurityCase.id.in_(security_case_ids),
        SecurityCase.project_id == task.project_id,
    ).all()
    if len(cases) != len(security_case_ids):
        raise RuntimeError("已批准的安全用例已删除或不属于当前项目")
    expected_plan_ids = list(dict.fromkeys(
        int(item) for item in (work.input_json.get("security_plan_ids") or [work.input_json.get("security_plan_id")]) if item
    ))
    expected_api_ids = list(dict.fromkeys(
        int(item) for item in (work.input_json.get("api_ids") or [work.input_json.get("api_id")]) if item
    ))
    security_plans = db.query(SecurityPlan).filter(
        SecurityPlan.id.in_(expected_plan_ids or [-1]),
        SecurityPlan.project_id == task.project_id,
        SecurityPlan.status == "CONFIRMED",
    ).all()
    if len(security_plans) != len(expected_plan_ids):
        raise RuntimeError("已批准的安全计划已删除、未确认或不属于当前项目")
    plan_api_by_id = {item.id: item.api_id for item in security_plans}
    if not set(plan_api_by_id.values()).issubset(set(expected_api_ids)):
        raise RuntimeError("安全计划中的 API 范围与批准范围不一致")
    api_rows = db.query(ApiInterface).filter(
        ApiInterface.id.in_(expected_api_ids or [-1]),
        ApiInterface.project_id == task.project_id,
        ApiInterface.status == "ACTIVE",
    ).all()
    if len(api_rows) != len(expected_api_ids):
        raise RuntimeError("部分安全评估目标 API 已删除、停用或不属于当前项目")
    if any(
        row.plan_id not in plan_api_by_id
        or row.api_id not in expected_api_ids
        or plan_api_by_id.get(row.plan_id) != row.api_id
        or (row.confirmation_required and not (row.confirmed_by and row.confirmed_at))
        for row in cases
    ):
        raise RuntimeError("安全用例的来源计划、接口范围或高风险确认状态已改变")
    enabled_case_ids = {
        row.id for row in db.query(TestCase.id).filter(
            TestCase.id.in_([item.test_case_id for item in cases]),
            TestCase.project_id == task.project_id,
            TestCase.enabled.is_(True),
            TestCase.status == "ACTIVE",
        ).all()
    }
    if enabled_case_ids != {row.test_case_id for row in cases}:
        raise RuntimeError("已批准的安全用例已停用或不再处于 ACTIVE 状态")
    environment_id = int(work.input_json["environment_id"])
    try:
        environment = resolve_project_environment(db, task.project_id, environment_id)
    except AppError as exc:
        raise RuntimeError("已批准的安全评估环境未关联当前项目或已停用") from exc
    if environment is None:
        raise RuntimeError("已批准的安全评估环境未关联当前项目或已停用")

    invocation = TaskToolInvocation(
        task_run_id=run.id,
        work_item_id=work.id,
        agent_instance_id=agent.id,
        invocation_key=invocation_key,
        tool_name="security.execute_cases",
        status="STARTED",
        input_json={
            "security_plan_ids": expected_plan_ids,
            "security_case_ids": security_case_ids,
            "environment_id": environment.id,
            "api_ids": expected_api_ids,
        },
    )
    db.add(invocation)
    db.commit()
    result = execute_security_cases(
        db,
        task.project_id,
        actor,
        security_case_ids=security_case_ids,
        environment_id=environment.id,
        task_run_id=run.id,
    )
    db.refresh(run, with_for_update=True)
    if defer_at_control_boundary(db, run, work, attempt, agent):
        return
    test_run_id = int(result["id"])
    invocation = db.query(TaskToolInvocation).filter(
        TaskToolInvocation.task_run_id == run.id,
        TaskToolInvocation.invocation_key == invocation_key,
    ).with_for_update().one()
    invocation.status = "SUCCEEDED"
    invocation.result_json = sanitize_context(result)
    invocation.finished_at = datetime.now()
    add_resource(
        db, run, agent, "OUTPUT", "TEST_RUN", str(test_run_id),
        {"status": result.get("status"), "security_case_ids": security_case_ids},
    )
    from app.features.security_testing.models import SecurityFinding

    findings = db.query(SecurityFinding).filter(
        SecurityFinding.project_id == task.project_id,
        SecurityFinding.test_run_id == test_run_id,
    ).order_by(SecurityFinding.id.asc()).limit(500).all()
    for finding in findings:
        add_resource(
            db, run, agent, "OUTPUT", "SECURITY_FINDING", str(finding.id),
            {
                "test_run_id": test_run_id,
                "severity": finding.severity,
                "status": finding.status,
            },
        )
    for security_case_id in security_case_ids:
        security_case = next(item for item in cases if item.id == security_case_id)
        add_resource(
            db, run, agent, "INPUT", "SECURITY_CASE", str(security_case_id),
            {"security_plan_id": security_case.plan_id, "api_id": security_case.api_id},
        )
    db.add(TaskMessage(
        task_run_id=run.id,
        agent_instance_id=agent.id,
        sender_type="AGENT",
        sender_instance_id=agent.id,
        message_type="RESULT",
        content=f"自研安全评估已通过现有执行服务完成，TestRun #{test_run_id} 状态为 {result.get('status')}。",
        metadata_json={
            "test_run_id": test_run_id,
            "status": result.get("status"),
            "security_case_ids": security_case_ids,
            "api_ids": expected_api_ids,
        },
        status="PROCESSED",
        client_message_id=f"agent:security-result:{work.id}",
        processed_at=datetime.now(),
    ))
    agent.status = "COMPLETED"
    queue_report(db, run, work, agent, attempt, result)
    state_service.append_event(
        db, run, "business.security_assessment.completed",
        {"test_run_id": test_run_id, "status": result.get("status"), "security_case_count": len(security_case_ids), "api_ids": expected_api_ids},
        agent_instance_id=agent.id,
    )
