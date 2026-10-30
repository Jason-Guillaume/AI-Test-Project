"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.orchestration.tasks.services import assembly_service
from app.orchestration.tasks.services import state_service
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.llm import LLMError
from app.llm.providers import ProductionLLMProvider
from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.features.api_catalog.models.api_interface import ApiInterface
from app.tools.adapters.mcp import build_mcp_function_tools
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
from app.orchestration.tasks.schemas import TaskPlanOutput
from app.orchestration.tasks.runtime.contracts import require_agent_tool
from app.agents.runtime.subagents import run_subagent_graph
from app.features.test_management.models.test_case import TestCase
from app.features.security_testing.models import SecurityStrategy
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import User
from app.orchestration.tasks.runtime.contracts import ProviderFactory
from app.agents.services.task_decision_service import (
    _PLANNER_SYSTEM, _SECURITY_PLANNER_SYSTEM, _WEB_AUTHORING_PLANNER_SYSTEM,
    generate_structured_candidate,
)
from app.orchestration.tasks.runtime.completion_service import defer_at_control_boundary
from app.orchestration.tasks.runtime.handlers.security_planning import security_plan_preview
from app.orchestration.tasks.runtime.handlers.security_planning import security_read_tool


def handle_plan(db: Session, task: Task, run: TaskRun, work: TaskWorkItem, attempt: TaskAttempt, agent: TaskAgentInstance | None, actor: User, *, provider_for_agent: ProviderFactory) -> None:
    """调用真实 Planner LLM 形成可审阅方案；资产与用例选择由服务端锁定。"""
    if agent is None:
        raise RuntimeError("Planner 实例不存在")
    target_type = run.input_snapshot.get("target_type", "API")
    if run.input_snapshot.get("security_scan"):
        raise RuntimeError("历史 ZAP 任务已停用；请创建自研安全评估任务")
    if target_type == "SECURITY":
        require_agent_tool(run, agent, "security-plan.preview")
        for runtime_tool in (
            "security-strategy.read", "security-context.read",
            "security-findings.read",
        ):
            require_agent_tool(run, agent, runtime_tool)
    elif target_type != "WEB_AUTHORING":
        require_agent_tool(run, agent, "test-asset.read")
    case_ids = list(run.input_snapshot.get("case_ids", []))
    cases = db.query(TestCase).filter(TestCase.id.in_(case_ids), TestCase.project_id == task.project_id).all()
    if len(cases) != len(case_ids):
        raise RuntimeError("方案引用的测试用例已删除或不属于当前项目")
    if target_type == "API":
        require_agent_tool(run, agent, "api-catalog.search")
    assessment = run.input_snapshot.get("security_assessment") or None
    api_ids = [case.api_id for case in cases if case.api_id]
    assessment_api_ids: list[int] = []
    if assessment:
        assessment_api_ids = list(dict.fromkeys(
            int(item) for item in (assessment.get("api_ids") or [assessment.get("api_id")]) if item
        ))
        api_ids.extend(assessment_api_ids)
    api_rows = db.query(ApiInterface).filter(ApiInterface.id.in_(api_ids or [-1])).all()
    api_map = {row.id: row for row in api_rows}
    asset_summary = [
        {
            "case_id": case.id,
            "target_type": case.target_type,
            "name": case.name,
            "description": case.description,
            "api": ({"id": api_map[case.api_id].id, "name": api_map[case.api_id].name, "method": api_map[case.api_id].method, "path": api_map[case.api_id].path} if case.api_id in api_map else None),
        }
        for case in cases
    ]
    security_assessment_preview = None
    if assessment:
        if not assessment_api_ids or len(assessment_api_ids) > 10:
            raise RuntimeError("安全评估目标 API 数量无效")
        if any(
            api_map.get(api_id) is None
            or api_map[api_id].project_id != task.project_id
            or api_map[api_id].status != "ACTIVE"
            for api_id in assessment_api_ids
        ):
            raise RuntimeError("部分安全评估目标接口已删除、停用或不属于当前项目")
        from app.tools.builtin import security_tool

        plan_version = int(run.current_plan_version or 0) + 1
        api_context = security_read_tool(
            db, task, run, work, agent, actor,
            tool_key="security.read_api_context",
            runtime_name="security-context.read",
            invocation_key=f"security-api-context:{run.id}:v{plan_version}",
            input_json={"api_ids": assessment_api_ids},
            call=lambda: security_tool.read_api_context(
                db, task.project_id, actor, api_ids=assessment_api_ids,
            ),
        )
        strategy_context = security_read_tool(
            db, task, run, work, agent, actor,
            tool_key="security.list_strategies",
            runtime_name="security-strategy.read",
            invocation_key=f"security-strategies:{run.id}:v{plan_version}",
            input_json={"enabled": True},
            call=lambda: security_tool.list_strategies(db, task.project_id, actor),
        )
        selected_strategy_ids = {int(item) for item in (assessment.get("strategy_ids") or [])}
        strategy_context = [
            item for item in strategy_context if int(item.get("id") or 0) in selected_strategy_ids
        ]
        findings_context = security_read_tool(
            db, task, run, work, agent, actor,
            tool_key="security.read_findings",
            runtime_name="security-findings.read",
            invocation_key=f"security-findings:{run.id}:v{plan_version}",
            input_json={"api_ids": assessment_api_ids, "limit": 20},
            call=lambda: security_tool.read_findings(
                db, task.project_id, actor, api_ids=assessment_api_ids, limit=20,
            ),
        )
        web_session_id = int(assessment["web_session_id"]) if assessment.get("web_session_id") else None
        web_inspection = None
        if web_session_id is not None:
            require_agent_tool(run, agent, "security-web.inspect")
            web_inspection = security_read_tool(
                db, task, run, work, agent, actor,
                tool_key="security.inspect_web_session",
                runtime_name="security-web.inspect",
                invocation_key=f"security-web-inspection:{run.id}:v{plan_version}",
                input_json={"web_session_id": web_session_id},
                call=lambda: security_tool.inspect_web_session(
                    db, task.project_id, actor, web_session_id=web_session_id,
                ),
            )
            if int(web_inspection.get("environment_id") or 0) != int(run.input_snapshot.get("environment_id") or 0):
                raise RuntimeError("受控 Web 会话与安全评估环境不一致")
        strategy_rows = db.query(SecurityStrategy).filter(
            SecurityStrategy.id.in_(assessment.get("strategy_ids") or [-1]),
        ).all()
        strategy_map = {row.id: row for row in strategy_rows}
        api_plans = []
        for api_id in assessment_api_ids:
            api = api_map[api_id]
            selection = {**assessment, "api_id": api_id}
            preview = security_plan_preview(
                db, task, run, work, agent, actor, selection,
            )
            preview["api_id"] = api_id
            api_plans.append({
                "api": {"id": api.id, "name": api.name, "method": api.method, "path": api.path},
                "plan": preview,
                "strategies": [
                    {"id": strategy_id, "name": strategy_map[strategy_id].name}
                    for strategy_id in assessment.get("strategy_ids", [])
                    if strategy_id in strategy_map
                ],
            })
        estimated_count = sum(int(item["plan"].get("estimated_count") or 0) for item in api_plans)
        remaining_preview_items = 500
        aggregate_truncated = False
        for api_plan in api_plans:
            preview_items = list(api_plan["plan"].get("items") or [])
            if len(preview_items) > remaining_preview_items:
                api_plan["plan"]["items"] = preview_items[:remaining_preview_items]
                api_plan["plan"]["truncated"] = True
                aggregate_truncated = True
            remaining_preview_items = max(0, remaining_preview_items - len(api_plan["plan"].get("items") or []))
        security_assessment_preview = {
            "api_ids": assessment_api_ids,
            "estimated_count": estimated_count,
            "truncated": aggregate_truncated or estimated_count > 500 or any(bool(item["plan"].get("truncated")) for item in api_plans),
            "plans": api_plans,
            "web_inspection": web_inspection,
        }
        scope_context = {
            "registered_api_context": api_context,
            "selected_strategy_context": strategy_context,
            "open_findings": findings_context,
            "web_inspection": web_inspection,
            "api_plans": [
                {
                    "api": item["api"],
                    "strategies": item["strategies"],
                    "preview": [
                        {
                            key: plan_item.get(key)
                            for key in (
                                "index", "name", "mutation_type", "method", "location", "field",
                                "expectation", "severity", "risk_level", "confirmation_required", "blocked_reason",
                            )
                        }
                        for plan_item in (item["plan"].get("items") or [])
                    ],
                }
                for item in api_plans
            ],
        }
        asset_summary = []
    else:
        scope_context = None
    authoring = run.input_snapshot.get("web_authoring") or None
    prompt = json.dumps(
        sanitize_context({
            "goal": run.goal_snapshot,
            "allowed_case_ids": case_ids,
            "selected_assets": asset_summary,
            "security_assessment_scope": scope_context,
            "web_authoring_scope": ({
                "environment_id": run.input_snapshot.get("environment_id"),
                "target_page_path": authoring.get("target_page_path", ""),
                "step_budget": authoring.get("step_budget", 20),
                "login_state_selected": bool(authoring.get("auth_profile_id")),
            } if target_type == "WEB_AUTHORING" and authoring else None),
        }),
        ensure_ascii=False,
        default=str,
    )
    # LLM 调用前结束只读事务；模型请求失败会作为可重试的 Planner 失败记录。
    db.commit()
    provider = provider_for_agent(db, task, run, work, attempt, agent, actor)
    profile = (run.input_snapshot or {}).get("agent_definition") or {}
    children = profile.get("child_agents") or []
    if children:
        def child_provider(child: dict[str, object]) -> ProductionLLMProvider:
            """为各子 Agent 创建独立模型路由，且逐一复核当前项目授权。"""
            candidate_ids = [child.get("model_config_id"), *(child.get("fallback_model_config_ids") or [])]
            allowed_ids: list[int] = []
            denied = False
            for config_id in dict.fromkeys(item for item in candidate_ids if item is not None):
                model = db.get(ModelConfiguration, int(config_id))
                if model is None or not model.is_enabled:
                    continue
                try:
                    assembly_service.assert_agent_model_access(db, task.project_id, actor, model.id)
                except RuntimeError as exc:
                    if any(word in str(exc) for word in ("组织", "授权", "开放")):
                        denied = True
                        continue
                    raise
                allowed_ids.append(model.id)
            if not allowed_ids:
                if denied:
                    raise RuntimeError("子 Agent 模型未获当前组织授权")
                raise LLMError("MODEL_UNAVAILABLE", "子 Agent 没有仍启用的模型")

            def record_child_attempt(item: dict[str, object]) -> None:
                """将子节点模型选择写入当前 Planner 尝试的检查点。"""
                history = [*(attempt.checkpoint_json or {}).get("model_attempts", []), {**item, "agent_role": str(child.get("name") or "child")}]
                attempt.checkpoint_json = {**(attempt.checkpoint_json or {}), "model_attempts": history}

            return ProductionLLMProvider(db, model_config_ids=allowed_ids, attempt_callback=record_child_attempt)

        def update_child_status(child: dict[str, object], status: str) -> None:
            """将动态 LangGraph 子节点状态投影到任务参与者面板。"""
            instance = db.query(TaskAgentInstance).filter(
                TaskAgentInstance.task_run_id == run.id,
                TaskAgentInstance.instance_key == f"child_agent:{int(child['id'])}",
            ).with_for_update().first()
            if instance is not None:
                instance.status = status
                db.commit()

        child_insights = run_subagent_graph(children, prompt, child_provider, update_child_status)
        prompt = json.dumps({
            "task_context": json.loads(prompt),
            "child_agent_insights": child_insights,
        }, ensure_ascii=False, default=str)

    planner_prompt = (
        _SECURITY_PLANNER_SYSTEM if target_type == "SECURITY"
        else _WEB_AUTHORING_PLANNER_SYSTEM if target_type == "WEB_AUTHORING"
        else _PLANNER_SYSTEM
    )
    mcp_tools = profile.get("mcp_tools") or []
    tool_definitions = None
    execute_mcp_tool = None
    if mcp_tools:
        by_function, tool_definitions = build_mcp_function_tools(mcp_tools)
        call_number = 0

        def execute_mcp_tool(function_name: str, arguments: dict[str, object]) -> dict[str, object]:
            """记录一次受审批的只读 MCP 工具调用，并在调用前复核服务端审批。"""
            nonlocal call_number
            item = by_function.get(function_name)
            if item is None:
                raise RuntimeError("MCP 工具不在本次运行白名单中")
            db.refresh(run, with_for_update=True)
            if run.status in {"PAUSE_REQUESTED", "CANCEL_REQUESTED"}:
                defer_at_control_boundary(db, run, work, attempt, agent)
                db.commit()
                raise RuntimeError("任务收到暂停或取消命令，未开始 MCP 工具调用")
            tool_key = str(item["key"])
            require_agent_tool(run, agent, tool_key)
            call_number += 1
            invocation_key = f"mcp:{attempt.attempt_number}:{call_number}:{function_name}"
            existing = db.query(TaskToolInvocation).filter(
                TaskToolInvocation.task_run_id == run.id,
                TaskToolInvocation.invocation_key == invocation_key,
            ).first()
            if existing is not None:
                if existing.status == "SUCCEEDED" and existing.result_json is not None:
                    return existing.result_json
                raise RuntimeError("MCP 工具已有未完成回执，需核对后再重试")
            invocation = TaskToolInvocation(
                task_run_id=run.id,
                work_item_id=work.id,
                agent_instance_id=agent.id,
                invocation_key=invocation_key,
                tool_name=tool_key[:80],
                status="STARTED",
                input_json=sanitize_context({"server_id": item["server_id"], "tool_name": item["tool_name"], "arguments": arguments}),
            )
            db.add(invocation)
            db.commit()
            db.refresh(run, with_for_update=True)
            if run.status in {"PAUSE_REQUESTED", "CANCEL_REQUESTED"}:
                pending = db.query(TaskToolInvocation).filter(
                    TaskToolInvocation.task_run_id == run.id,
                    TaskToolInvocation.invocation_key == invocation_key,
                ).with_for_update().one()
                pending.status = "CANCELLED"
                pending.error_code = "CONTROL_REQUESTED"
                pending.error_message = "任务控制命令在 MCP 调用开始前到达"
                pending.finished_at = datetime.now()
                defer_at_control_boundary(db, run, work, attempt, agent)
                db.commit()
                raise RuntimeError("任务收到暂停或取消命令，未开始 MCP 工具调用")
            try:
                from app.mcp.services import invoke_approved_mcp_tool

                result = invoke_approved_mcp_tool(
                    db, int(item["server_id"]), str(item["tool_name"]), arguments,
                )
            except Exception as exc:  # noqa: BLE001 — 持久化错误类型，不保存远端异常正文。
                db.rollback()
                failed = db.query(TaskToolInvocation).filter(
                    TaskToolInvocation.task_run_id == run.id,
                    TaskToolInvocation.invocation_key == invocation_key,
                ).with_for_update().one()
                failed.status = "FAILED"
                failed.error_code = type(exc).__name__[:80]
                failed.error_message = "MCP 工具调用失败，详细错误已脱敏"
                failed.finished_at = datetime.now()
                db.commit()
                raise RuntimeError("MCP 工具调用失败") from exc
            completed = db.query(TaskToolInvocation).filter(
                TaskToolInvocation.task_run_id == run.id,
                TaskToolInvocation.invocation_key == invocation_key,
            ).with_for_update().one()
            completed.status = "SUCCEEDED"
            completed.result_json = result
            completed.finished_at = datetime.now()
            db.commit()
            return result

    output = generate_structured_candidate(
        provider, planner_prompt, profile, prompt,
        schema=TaskPlanOutput.model_json_schema(), kind="task_planner",
        validator=TaskPlanOutput.model_validate,
        tools=tool_definitions, tool_executor=execute_mcp_tool,
    )
    plan_output = TaskPlanOutput.model_validate(output)
    db.refresh(run, with_for_update=True)
    if defer_at_control_boundary(db, run, work, attempt, agent):
        return
    current_version = int(run.current_plan_version or 0) + 1
    if target_type == "WEB_AUTHORING":
        work_items = [
            {"key": "web_authoring", "role": "UI_WORKER", "depends_on": [], "required": True},
        ]
    elif target_type == "SECURITY":
        work_items = [
            {"key": "security_assessment", "role": "SECURITY_WORKER", "depends_on": [], "required": True},
        ]
    else:
        worker_role = "API_WORKER" if target_type == "API" else "UI_WORKER"
        work_key = "api_test" if target_type == "API" else "web_test"
        work_items = [
            {"key": work_key, "role": worker_role, "depends_on": [], "required": True},
        ]
    if target_type != "WEB_AUTHORING":
        report_dependency = "security_assessment" if target_type == "SECURITY" else work_key
        work_items.extend([
            {"key": "report", "role": "REPORT_AGENT", "depends_on": [report_dependency], "required": True},
            {"key": "review", "role": "REVIEWER", "depends_on": ["report"], "required": True},
        ])
    plan_json = {
        "version": current_version,
        "summary": sanitize_text(plan_output.summary),
        "case_ids": case_ids,
        "environment_id": run.input_snapshot.get("environment_id"),
        "acceptance_criteria": [sanitize_text(item) for item in plan_output.acceptance_criteria],
        "work_items": work_items,
        "requires_human_confirmation": True,
        "security_assessment_preview": security_assessment_preview,
    }
    plan = TaskPlan(task_run_id=run.id, version=current_version, status="PROPOSED", plan_json=sanitize_context(plan_json), created_by=actor.id)
    db.add(plan)
    db.flush()
    run.current_plan_version = current_version
    run.status = "WAITING_CONFIRMATION"
    run.stage = "PLAN_REVIEW"
    work.status = "SUCCEEDED"
    work.output_json = {"plan_id": plan.id, "version": current_version}
    work.finished_at = datetime.now()
    attempt.status = "SUCCEEDED"
    attempt.finished_at = datetime.now()
    agent.status = "WAITING_CONFIRMATION"
    message = TaskMessage(
        task_run_id=run.id,
        agent_instance_id=agent.id,
        sender_type="AGENT",
        sender_instance_id=agent.id,
        message_type="PLAN",
        content=sanitize_text(plan_output.summary),
        metadata_json={"plan_id": plan.id, "version": current_version, "acceptance_criteria": plan_json["acceptance_criteria"]},
        status="PROCESSED",
        client_message_id=f"agent:plan:{work.id}",
        processed_at=datetime.now(),
    )
    db.add(message)
    state_service.append_event(db, run, "plan.proposed", {"plan_id": plan.id, "version": current_version}, agent_instance_id=agent.id)
