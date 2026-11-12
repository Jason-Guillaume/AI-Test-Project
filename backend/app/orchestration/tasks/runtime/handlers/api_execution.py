"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.core.http.errors import AppError
from app.orchestration.tasks.services import assembly_service
from app.orchestration.tasks.services import state_service
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.orchestration.tasks.adapters import execute_api_cases, execute_confirmed_web_cases
from app.orchestration.tasks.models import (
    Task,
    TaskAgentInstance,
    TaskAttempt,
    TaskMessage,
    TaskPlan,
    TaskRun,
    TaskToolInvocation,
    TaskWorkItem,
)
from app.orchestration.tasks.schemas import ApiWorkerSelection
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.orchestration.tasks.runtime.contracts import require_agent_tool
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_plan import TestPlanSuite
from app.core.models.identity import User
from app.orchestration.tasks.runtime.contracts import ProviderFactory
from app.agents.services.task_decision_service import (
    _API_WORKER_SYSTEM, _UI_WORKER_SYSTEM, generate_structured_candidate,
)
from app.orchestration.tasks.runtime.resources import add_resource
from app.orchestration.tasks.runtime.access import assert_current_project_write
from app.orchestration.tasks.runtime.completion_service import defer_at_control_boundary
from app.orchestration.tasks.runtime.handlers.report_queue import queue_report


def handle_api_execution(db: Session, task: Task, run: TaskRun, work: TaskWorkItem, attempt: TaskAttempt, agent: TaskAgentInstance | None, actor: User, *, provider_for_agent: ProviderFactory) -> None:
    """API / UI Worker 只筛选已批准范围，再走对应的既有执行适配器。"""
    if agent is None:
        raise RuntimeError("执行 Worker 实例不存在")
    target_type = "API" if work.kind == "EXECUTE_API" else "WEB"
    require_agent_tool(run, agent, "test-run.create" if target_type == "API" else "web-test-run.create")
    invocation_key = "api_test_run" if target_type == "API" else "web_test_run"
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
            raise RuntimeError(f"{target_type} 执行回执状态不明，必须从执行中心人工核对后继续")
        raise RuntimeError(f"{target_type} 执行已失败，需使用带幂等保护的重试命令")

    plan = db.query(TaskPlan).filter(
        TaskPlan.task_run_id == run.id,
        TaskPlan.version == run.current_plan_version,
        TaskPlan.status == "ACCEPTED",
    ).first()
    if plan is None:
        raise RuntimeError("没有已批准的测试方案")
    allowed_ids = list(dict.fromkeys(plan.plan_json.get("case_ids", [])))
    cases = db.query(TestCase).filter(TestCase.id.in_(allowed_ids), TestCase.project_id == task.project_id).all()
    if len(cases) != len(allowed_ids) or any(not row.enabled or row.status != "ACTIVE" or row.target_type != target_type for row in cases):
        raise RuntimeError("已批准的测试用例发生变化或已停用，请重新规划")
    if target_type == "WEB":
        from app.features.web_testing.models import WebCase
        from app.features.web_testing.services.web_ui_service import case_response
        if any(db.get(WebCase, row.id) is None or not case_response(db, row).get("confirmed") for row in cases):
            raise RuntimeError("Web 用例或页面对象已变化，必须重新人工确认")
    environment_id = plan.plan_json.get("environment_id")
    try:
        environment = resolve_project_environment(db, task.project_id, environment_id) if environment_id else None
    except AppError as exc:
        raise RuntimeError("已批准的执行环境未关联当前项目或已停用") from exc
    if environment is None:
        raise RuntimeError("已批准的执行环境未关联当前项目或已停用")

    pending_messages = (
        db.query(TaskMessage)
        .filter(
            TaskMessage.task_run_id == run.id,
            TaskMessage.agent_instance_id == agent.id,
            TaskMessage.message_type == "REQUIREMENT",
            TaskMessage.status == "RECEIVED",
        )
        .order_by(TaskMessage.id.asc())
        .all()
    )
    for message in pending_messages:
        message.status = "PROCESSING"
    db.commit()
    requirements = [message.content for message in pending_messages]
    prompt = json.dumps(
        sanitize_context({
            "goal": run.goal_snapshot,
            "approved_plan": plan.plan_json,
            "allowed_case_ids": allowed_ids,
            "additional_requirements": requirements,
        }),
        ensure_ascii=False,
        default=str,
    )
    worker_system = _API_WORKER_SYSTEM if target_type == "API" else _UI_WORKER_SYSTEM
    model_kind = "task_api_worker" if target_type == "API" else "task_ui_worker"
    provider = provider_for_agent(db, task, run, work, attempt, agent, actor)
    selection_raw = generate_structured_candidate(
        provider, worker_system, (run.input_snapshot or {}).get("agent_definition") or {}, prompt,
        schema=ApiWorkerSelection.model_json_schema(), kind=model_kind,
        validator=ApiWorkerSelection.model_validate,
    )
    selection = ApiWorkerSelection.model_validate(selection_raw)
    selected_ids = list(dict.fromkeys(selection.case_ids))
    if not selected_ids or any(case_id not in set(allowed_ids) for case_id in selected_ids):
        raise RuntimeError("执行 Worker 返回了超出已批准范围的用例，执行已阻止")

    db.refresh(run, with_for_update=True)
    if defer_at_control_boundary(db, run, work, attempt, agent, messages=pending_messages):
        return

    assert_current_project_write(db, task.project_id, actor)
    assembly_service.assert_agent_runtime_access(db, task, run, actor)
    assembly_service.assert_agent_model_access(
        db, task.project_id, actor, getattr(provider, "last_model_config_id", agent.model_config_id),
    )

    invocation = TaskToolInvocation(
        task_run_id=run.id,
        work_item_id=work.id,
        agent_instance_id=agent.id,
        invocation_key=invocation_key,
        tool_name="test-run.create" if target_type == "API" else "web-test-run.create",
        status="STARTED",
        input_json={"case_ids": selected_ids, "environment_id": environment.id, "requirements_message_ids": [message.id for message in pending_messages]},
    )
    db.add(invocation)
    db.commit()
    # API 与 Web 共用真实 TestRun 编排，但 Web 再经独立适配器复核确认指纹、目标策略和浏览器出站边界。
    execute = execute_api_cases if target_type == "API" else execute_confirmed_web_cases
    result = execute(db, task.project_id, actor, case_ids=selected_ids, environment_id=environment.id, task_run_id=run.id)
    # 既有执行服务会自行提交；重读运行以避开旧事件序号和并发控制命令。
    db.refresh(run, with_for_update=True)
    test_run_id = int(result["id"])
    invocation = db.query(TaskToolInvocation).filter(TaskToolInvocation.id == invocation.id).with_for_update().one()
    invocation.status = "SUCCEEDED"
    invocation.result_json = sanitize_context(result)
    invocation.finished_at = datetime.now()
    for message in pending_messages:
        message.status = "PROCESSED"
        message.processed_at = datetime.now()
    add_resource(db, run, agent, "OUTPUT", "TEST_RUN", str(test_run_id), {"status": result.get("status"), "case_ids": selected_ids})
    if result.get("plan_id"):
        add_resource(db, run, agent, "OUTPUT", "TEST_PLAN", str(result["plan_id"]), {"temporary": True})
        plan_suite = db.query(TestPlanSuite).filter(TestPlanSuite.plan_id == int(result["plan_id"])).first()
        if plan_suite is not None:
            add_resource(db, run, agent, "OUTPUT", "TEST_SUITE", str(plan_suite.suite_id), {"temporary": True})
    worker_message = TaskMessage(
        task_run_id=run.id,
        agent_instance_id=agent.id,
        sender_type="AGENT",
        sender_instance_id=agent.id,
        message_type="RESULT",
        content=f"{target_type} 测试已通过现有执行服务完成，TestRun #{test_run_id} 状态为 {result.get('status')}。",
        metadata_json={"test_run_id": test_run_id, "status": result.get("status"), "selected_case_ids": selected_ids, "selection_summary": sanitize_text(selection.explanation)},
        status="PROCESSED",
        client_message_id=f"agent:{target_type.lower()}-result:{work.id}",
        processed_at=datetime.now(),
    )
    db.add(worker_message)
    agent.status = "COMPLETED"
    queue_report(db, run, work, agent, attempt, result)
    state_service.append_event(db, run, "business.test_run.created", {"target_type": target_type, "test_run_id": test_run_id, "status": result.get("status")}, agent_instance_id=agent.id)
