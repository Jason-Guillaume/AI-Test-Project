"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from sqlalchemy.orm import Session
from app.core.security.sanitizer import sanitize_context
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskRun, TaskToolInvocation, TaskWorkItem
from app.orchestration.tasks.runtime.contracts import require_agent_tool
from app.features.security_testing.models import SecurityPlan
from app.core.models.identity import User


def security_plan_preview(db: Session, task: Task, run: TaskRun, work: TaskWorkItem, agent: TaskAgentInstance, actor: User, selection: dict) -> dict:
    """以运行版本为幂等键预览受控安全计划，并记录工具回执。"""
    require_agent_tool(run, agent, "security-plan.preview")
    from app.tools.builtin.security_testing.security_tool import preview_plan

    api_id = int(selection["api_id"])
    plan_name = f"TaskRun-{run.id}-SecurityPlan-v{run.current_plan_version + 1}-API-{api_id}"
    invocation_key = f"security-plan-preview:{run.id}:v{run.current_plan_version + 1}:api:{api_id}"
    invocation = db.query(TaskToolInvocation).filter(
        TaskToolInvocation.task_run_id == run.id,
        TaskToolInvocation.invocation_key == invocation_key,
    ).with_for_update().first()
    if invocation is not None and invocation.status == "SUCCEEDED" and invocation.result_json:
        return dict(invocation.result_json)

    plan = db.query(SecurityPlan).filter(
        SecurityPlan.project_id == task.project_id,
        SecurityPlan.created_by == actor.id,
        SecurityPlan.name == plan_name,
    ).order_by(SecurityPlan.id.desc()).first()
    if invocation is None:
        invocation = TaskToolInvocation(
            task_run_id=run.id,
            work_item_id=work.id,
            agent_instance_id=agent.id,
            invocation_key=invocation_key,
            tool_name="security.preview_plan",
            status="STARTED",
            input_json={
                "api_id": int(selection["api_id"]),
                "strategy_ids": list(selection.get("strategy_ids") or []),
                "environment_id": run.input_snapshot.get("environment_id"),
            },
        )
        db.add(invocation)
        db.commit()
    elif invocation.status != "STARTED":
        invocation.status = "STARTED"
        invocation.error_code = None
        invocation.error_message = None
        invocation.finished_at = None
        db.commit()

    try:
        if plan is not None:
            preview = {
                "plan_id": plan.id,
                "api_id": plan.api_id,
                "status": plan.status,
                "estimated_count": plan.estimated_count,
                "truncated": bool((plan.preview_json or {}).get("truncated")),
                "items": list((plan.preview_json or {}).get("items") or []),
                "baseline_case_id": plan.baseline_case_id,
            }
        else:
            preview = preview_plan(
                db, task.project_id, actor,
                api_id=int(selection["api_id"]),
                strategy_ids=list(selection.get("strategy_ids") or []),
                environment_id=int(run.input_snapshot["environment_id"]),
                name=plan_name,
            )
    except Exception as exc:  # noqa: BLE001 - 回执只记录错误类型，不存请求或凭据。
        db.rollback()
        failed_invocation = db.query(TaskToolInvocation).filter(
            TaskToolInvocation.task_run_id == run.id,
            TaskToolInvocation.invocation_key == invocation_key,
        ).with_for_update().first()
        if failed_invocation is not None:
            failed_invocation.status = "FAILED"
            failed_invocation.error_code = type(exc).__name__[:80]
            failed_invocation.error_message = "安全计划预览工具调用失败"
            failed_invocation.finished_at = datetime.now()
            db.commit()
        raise RuntimeError("安全计划预览工具调用失败") from exc

    invocation = db.query(TaskToolInvocation).filter(
        TaskToolInvocation.task_run_id == run.id,
        TaskToolInvocation.invocation_key == invocation_key,
    ).with_for_update().one()
    invocation.status = "SUCCEEDED"
    invocation.result_json = sanitize_context(preview)
    invocation.finished_at = datetime.now()
    db.commit()
    return preview


def security_read_tool(db: Session, task: Task, run: TaskRun, work: TaskWorkItem, agent: TaskAgentInstance, actor: User, *, tool_key: str, runtime_name: str, invocation_key: str, input_json: dict, call: Callable[[], Any]) -> Any:
    """执行 Planner 的只读安全工具，并以幂等回执记录输入和脱敏结果。"""
    require_agent_tool(run, agent, runtime_name)
    invocation = db.query(TaskToolInvocation).filter(
        TaskToolInvocation.task_run_id == run.id,
        TaskToolInvocation.invocation_key == invocation_key,
    ).with_for_update().first()
    if invocation is not None and invocation.status == "SUCCEEDED" and invocation.result_json is not None:
        return invocation.result_json
    if invocation is None:
        invocation = TaskToolInvocation(
            task_run_id=run.id,
            work_item_id=work.id,
            agent_instance_id=agent.id,
            invocation_key=invocation_key,
            tool_name=tool_key,
            status="STARTED",
            input_json=sanitize_context(input_json),
        )
        db.add(invocation)
        db.commit()
    else:
        invocation.status = "STARTED"
        invocation.error_code = None
        invocation.error_message = None
        invocation.finished_at = None
        db.commit()
    try:
        result = sanitize_context(call())
    except Exception as exc:  # noqa: BLE001
        invocation = db.query(TaskToolInvocation).filter(
            TaskToolInvocation.task_run_id == run.id,
            TaskToolInvocation.invocation_key == invocation_key,
        ).with_for_update().one()
        invocation.status = "FAILED"
        invocation.error_code = type(exc).__name__[:80]
        invocation.error_message = "安全上下文只读工具调用失败"
        invocation.finished_at = datetime.now()
        db.commit()
        raise RuntimeError("安全上下文只读工具调用失败") from exc
    invocation = db.query(TaskToolInvocation).filter(
        TaskToolInvocation.task_run_id == run.id,
        TaskToolInvocation.invocation_key == invocation_key,
    ).with_for_update().one()
    invocation.status = "SUCCEEDED"
    invocation.result_json = result
    invocation.finished_at = datetime.now()
    db.commit()
    return result
