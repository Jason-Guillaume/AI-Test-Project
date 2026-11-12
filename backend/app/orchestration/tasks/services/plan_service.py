"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import TaskPlan, TaskRun, TaskToolInvocation, TaskWorkItem
from app.features.test_management.models.test_case import TestCase
from app.core.models.identity import User
from app.core.http.errors import bad_request, conflict
from app.orchestration.tasks.services.state_service import agent_by_role
from app.orchestration.tasks.services.state_service import append_event
from app.orchestration.tasks.services.state_service import enqueue_work


def approve_plan(db: Session, run: TaskRun, actor: User, *, security_risk_confirmed: bool = False,
) -> None:
    """人工确认持久化方案后，只派发其固定范围内的执行工作。"""
    if run.status != "WAITING_CONFIRMATION" or run.stage != "PLAN_REVIEW":
        raise conflict("当前运行没有待确认的测试方案")
    plan = db.query(TaskPlan).filter(TaskPlan.task_run_id == run.id, TaskPlan.version == run.current_plan_version).with_for_update().first()
    if plan is None or plan.status != "PROPOSED":
        raise conflict("当前测试方案已被处理")
    target_type = run.input_snapshot.get("target_type", "API")
    project_id = int(run.input_snapshot["project_id"])
    plan_work = db.query(TaskWorkItem).filter(TaskWorkItem.task_run_id == run.id, TaskWorkItem.kind == "PLAN").order_by(TaskWorkItem.id.desc()).first()
    if target_type == "WEB_AUTHORING":
        if security_risk_confirmed:
            raise bad_request("交互式 Web 编写不接受安全风险确认参数")
        selection = run.input_snapshot.get("web_authoring") or {}
        if run.input_snapshot.get("task_mode") != "WEB_AUTHORING" or not selection:
            raise conflict("Web 编写任务缺少服务端记录的会话范围")
        worker_agent = agent_by_role(db, run.id, "UI_WORKER")
        work = enqueue_work(
            db, run, worker_agent, work_key=f"web-authoring-start:v{plan.version}",
            kind="EXECUTE_WEB_AUTHORING",
            input_json={
                "plan_id": plan.id,
                "environment_id": run.input_snapshot.get("environment_id"),
                "web_authoring": selection,
            }, sequence=20,
        )
        run.stage = "WEB_AUTHORING_START"
        worker_agent.status = "QUEUED"
    elif target_type == "SECURITY":
        selection = run.input_snapshot.get("security_assessment") or {}
        from app.features.api_catalog.models.api_interface import ApiInterface

        api_ids = list(dict.fromkeys(
            int(item) for item in (selection.get("api_ids") or [selection.get("api_id")]) if item
        ))
        api_rows = db.query(ApiInterface).filter(
            ApiInterface.id.in_(api_ids or [-1]), ApiInterface.project_id == project_id,
        ).all()
        if len(api_rows) != len(api_ids) or any(item.status != "ACTIVE" for item in api_rows):
            raise conflict("部分安全评估目标 API 已删除、停用或不属于当前项目")
        preview = plan.plan_json.get("security_assessment_preview") or {}
        preview_plans = list(preview.get("plans") or [])
        if not selection or not preview_plans or set(preview.get("api_ids") or []) != set(api_ids):
            raise conflict("安全评估方案缺少已登记策略的预览结果")
        if preview.get("truncated"):
            raise conflict("安全计划超过单次预览上限，请减少策略后重新规划")

        from app.features.security_testing.models import SecurityCase, SecurityPlan
        from app.features.security_testing.services.case_service import SecurityCaseService
        from app.tools.builtin.security_testing.security_tool import confirm_plan

        confirmed_plan_ids: list[int] = []
        accepted_indexes_by_plan: dict[int, list[int]] = {}
        runnable_item_count = 0
        runnable_high_risk_count = 0
        for api_plan in preview_plans:
            api_id = int((api_plan.get("api") or {}).get("id") or 0)
            plan_preview = api_plan.get("plan") or {}
            plan_items = list(plan_preview.get("items") or [])
            if api_id not in api_ids:
                raise conflict("安全计划中的 API 范围无效")
            if plan_preview.get("truncated") or int(plan_preview.get("estimated_count") or 0) > len(plan_items):
                raise conflict("单个 API 的安全计划超过预览上限，请减少策略后重新规划")
            runnable_items = [item for item in plan_items if not item.get("blocked_reason")]
            runnable_item_count += len(runnable_items)
            runnable_high_risk_count += sum(bool(item.get("confirmation_required")) for item in runnable_items)
            accepted_items = [
                item for item in runnable_items
                if security_risk_confirmed or not item.get("confirmation_required")
            ]
            plan_id = int(plan_preview.get("plan_id") or 0)
            security_plan = db.get(SecurityPlan, plan_id)
            if security_plan is None or security_plan.project_id != project_id or security_plan.api_id != api_id:
                raise conflict("安全计划已不存在或目标 API 不匹配")
            expected_strategy_ids = set(int(item) for item in selection.get("strategy_ids", []))
            if set(int(item) for item in (security_plan.strategy_ids or [])) != expected_strategy_ids:
                raise conflict("安全计划策略与任务批准范围不一致")
            if security_plan.status == "DRAFT":
                if accepted_items:
                    indexes = [int(item["index"]) for item in accepted_items]
                    confirm_plan(db, security_plan.id, actor, accepted_item_indexes=indexes)
                    accepted_indexes_by_plan[security_plan.id] = indexes
                    confirmed_plan_ids.append(security_plan.id)
            elif security_plan.status == "CONFIRMED":
                accepted_indexes_by_plan[security_plan.id] = [int(item["index"]) for item in accepted_items]
                confirmed_plan_ids.append(security_plan.id)
            else:
                raise conflict("安全计划已被丢弃或不能确认")

        if runnable_high_risk_count and not security_risk_confirmed and runnable_item_count == runnable_high_risk_count:
            raise bad_request("当前批次只有高风险变异，请在确认方案时显式授权")
        if not confirmed_plan_ids:
            raise bad_request("当前安全计划没有可执行项")

        security_cases = db.query(SecurityCase).filter(
            SecurityCase.plan_id.in_(confirmed_plan_ids),
            SecurityCase.test_case_id.in_(db.query(TestCase.id).filter(TestCase.project_id == project_id)),
        ).all()
        if security_risk_confirmed:
            for security_case in security_cases:
                if security_case.confirmation_required and not (security_case.confirmed_by and security_case.confirmed_at):
                    SecurityCaseService.confirm_risk(db, security_case.id, actor=actor)
        enabled_case_ids = {
            row.id for row in db.query(TestCase).filter(
                TestCase.id.in_([item.test_case_id for item in security_cases]),
                TestCase.project_id == project_id,
                TestCase.enabled.is_(True),
                TestCase.status == "ACTIVE",
            ).all()
        }
        eligible_security_case_ids = [
            row.id for row in security_cases
            if row.test_case_id in enabled_case_ids
            and (not row.confirmation_required or bool(row.confirmed_by and row.confirmed_at))
        ]
        if not eligible_security_case_ids:
            raise bad_request("确认后没有可执行的安全用例")

        security_agent = agent_by_role(db, run.id, "SECURITY_WORKER")
        if security_agent is None:
            raise conflict("安全执行 Worker 实例不存在")
        for security_plan_id in confirmed_plan_ids:
            invocation_key = f"security-plan-confirm:{security_plan_id}"
            invocation = db.query(TaskToolInvocation).filter(
                TaskToolInvocation.task_run_id == run.id,
                TaskToolInvocation.invocation_key == invocation_key,
            ).first()
            if invocation is None:
                db.add(TaskToolInvocation(
                    task_run_id=run.id,
                    work_item_id=plan_work.id if plan_work else None,
                    agent_instance_id=security_agent.id,
                    invocation_key=invocation_key,
                    tool_name="security.confirm_plan",
                    status="SUCCEEDED",
                    input_json={
                        "security_plan_id": security_plan_id,
                        "accepted_indexes": accepted_indexes_by_plan.get(security_plan_id, []),
                        "confirmed_by": actor.id,
                    },
                    result_json={
                        "security_case_ids": [item.id for item in security_cases if item.plan_id == security_plan_id],
                    },
                    finished_at=datetime.now(),
                ))
        work = enqueue_work(
            db, run, security_agent, work_key=f"security-execution:v{plan.version}", kind="EXECUTE_SECURITY",
            input_json={
                "security_plan_ids": confirmed_plan_ids,
                "security_case_ids": eligible_security_case_ids,
                "environment_id": run.input_snapshot.get("environment_id"),
                "api_ids": api_ids,
            },
            sequence=20,
        )
        run.input_snapshot = {
            **dict(run.input_snapshot or {}),
            "security_assessment_approval": {
                "confirmed_by": actor.id,
                "confirmed_at": datetime.now().isoformat(),
                "risk_confirmed": bool(security_risk_confirmed),
                "security_plan_ids": confirmed_plan_ids,
            },
        }
        run.stage = "SECURITY_EXECUTION"
        security_agent.status = "QUEUED"
    else:
        if security_risk_confirmed:
            raise bad_request("当前任务没有待确认的高风险安全用例")
        if run.input_snapshot.get("security_scan"):
            raise conflict("历史 ZAP 任务已停用；请创建自研安全评估任务")
        worker_role = "API_WORKER" if target_type == "API" else "UI_WORKER"
        worker_kind = "EXECUTE_API" if target_type == "API" else "EXECUTE_WEB"
        worker_agent = agent_by_role(db, run.id, worker_role)
        work = enqueue_work(
            db, run, worker_agent, work_key=f"{target_type.lower()}-execution:v{plan.version}", kind=worker_kind,
            input_json={"plan_id": plan.id, "case_ids": list(run.input_snapshot.get("case_ids", [])), "environment_id": run.input_snapshot.get("environment_id"), "target_type": target_type},
            sequence=20,
        )
        run.stage = "API_EXECUTION" if target_type == "API" else "WEB_EXECUTION"
        worker_agent.status = "QUEUED"
    if plan_work is not None:
        from app.orchestration.tasks.models import TaskWorkItemDependency
        db.add(TaskWorkItemDependency(work_item_id=work.id, depends_on_id=plan_work.id))
    plan.status = "ACCEPTED"
    plan.accepted_at = datetime.now()
    run.status = "QUEUED"
    append_event(
        db, run, "plan.accepted",
        {"plan_id": plan.id, "work_item_id": work.id, "security_assessment": target_type == "SECURITY"},
        actor_user_id=actor.id,
    )
