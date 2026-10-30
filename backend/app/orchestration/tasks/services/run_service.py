"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.agents.assembly.snapshot import build_agent_run_snapshot
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskRun
from app.skills.models import SkillDefinition, SkillUsageEvent
from app.core.models.identity import User
from app.orchestration.tasks.services.resource_service import TaskResourceService
from app.orchestration.tasks.services.state_service import append_event
from app.orchestration.tasks.services.state_service import enqueue_work
from app.orchestration.tasks.services.assembly_service import model_snapshot
from app.orchestration.tasks.services.assembly_service import resolve_agent_profile
from app.orchestration.tasks.services.assembly_service import resolve_authorized_model
from app.orchestration.tasks.services.assembly_service import role_tools_for_agent


def create_run(db: Session, task: Task, actor: User, *, run_number: int, target_type: str,
    agent_bundle: dict[str, Any] | None = None,
) -> TaskRun:
    """创建隔离运行并固定 Agent、Skill、工具与模型快照；模型凭据不会进入快照。"""
    if task.agent_definition_id is not None and agent_bundle is None:
        agent_bundle = resolve_agent_profile(
            db,
            project_id=task.project_id,
            agent_definition_id=task.agent_definition_id,
            actor=actor,
            target_type="WEB" if target_type == "WEB_AUTHORING" else target_type,
        )
    model = agent_bundle["model"] if agent_bundle else resolve_authorized_model(db, task.project_id, actor)
    frozen_model = model_snapshot(model)
    agent_snapshot = build_agent_run_snapshot(agent_bundle)
    run = TaskRun(
        task_id=task.id,
        run_number=run_number,
        created_by=actor.id,
        status="QUEUED",
        stage="PLANNING",
        goal_snapshot=task.goal,
        input_snapshot={
            "project_id": task.project_id,
            "environment_id": task.environment_id,
            "case_ids": list(task.input_case_ids or []),
            "target_type": target_type,
            "task_mode": task.task_mode,
            "web_authoring": dict(task.web_authoring_json) if task.web_authoring_json else None,
            "security_assessment": dict(task.security_assessment_json) if task.security_assessment_json else None,
            # 仅供已经排队的历史运行恢复；新 API 不再接受 ZAP 扫描配置。
            "security_scan": dict(task.security_scan_json) if task.security_scan_json else None,
            "agent_definition": agent_snapshot,
        },
    )
    db.add(run)
    db.flush()
    if agent_snapshot and agent_snapshot.get("skills"):
        skill_keys = [item["key"] for item in agent_snapshot["skills"]]
        skill_ids = db.query(SkillDefinition.id, SkillDefinition.key).filter(SkillDefinition.key.in_(skill_keys)).all()
        db.add_all([
            SkillUsageEvent(
                skill_definition_id=skill_id,
                agent_definition_id=agent_snapshot["id"],
                task_run_id=run.id,
            )
            for skill_id, _ in skill_ids
        ])

    if target_type == "SECURITY":
        roles = [
            ("MAIN", "任务主 Agent", "READY", ["task.chat", "task.goal.update"]),
            ("PLANNER", "Security Planner", "QUEUED", ["security-plan.preview"]),
            ("SECURITY_WORKER", "安全执行 Worker", "WAITING_APPROVAL", ["security-plan.confirm", "security-case.run"]),
        ]
    elif target_type == "WEB_AUTHORING":
        roles = [
            ("MAIN", "任务主 Agent", "READY", ["task.chat", "task.goal.update"]),
            ("PLANNER", "Web 编写 Planner", "QUEUED", []),
            ("UI_WORKER", "任务内 UI Worker", "WAITING_APPROVAL", ["web-authoring.start", "web-authoring.turn", "web-case.draft"]),
        ]
    else:
        roles = [
            ("MAIN", "任务主 Agent", "READY", ["task.chat", "task.goal.update"]),
            ("PLANNER", "Planner", "QUEUED", []),
            (("API_WORKER", "API Worker", "WAITING_APPROVAL", ["test-run.create"])
             if target_type == "API" else
             ("UI_WORKER", "UI Worker", "WAITING_APPROVAL", ["web-test-run.create"])),
        ]
    if target_type != "WEB_AUTHORING":
        roles.extend([
            ("REVIEWER", "审阅 Agent", "WAITING_DEPENDENCY", ["report.review"]),
            ("REPORT_AGENT", "报告 Agent", "WAITING_DEPENDENCY", ["report.generate"]),
        ])
    agents: dict[str, TaskAgentInstance] = {}
    for role, name, state, tools in roles:
        role_tools = (
            list(tools) if target_type == "WEB_AUTHORING" and role == "UI_WORKER"
            else role_tools_for_agent(role, tools, agent_snapshot)
        )
        instance = TaskAgentInstance(
            task_run_id=run.id,
            instance_key=role.lower(),
            role=role,
            display_name=name,
            status=state,
            model_config_id=model.id if model else None,
            config_snapshot={
                **frozen_model,
                "agent_version": agent_snapshot["version"] if agent_snapshot else None,
                "agent_name": agent_snapshot["name"] if agent_snapshot else None,
            },
            skills_json=[skill["key"] for skill in agent_snapshot["skills"]] if agent_snapshot else [],
            tool_allowlist_json=role_tools,
        )
        db.add(instance)
        agents[role] = instance
    for child in (agent_snapshot or {}).get("child_agents", []):
        db.add(TaskAgentInstance(
            task_run_id=run.id,
            instance_key=f"child_agent:{child['id']}",
            role="SUB_AGENT",
            display_name=child["name"],
            status="WAITING_DEPENDENCY",
            model_config_id=child["model_config_id"],
            config_snapshot={"agent_version": child["version"], "agent_name": child["name"]},
            skills_json=[item["key"] for item in child.get("skills", [])],
            tool_allowlist_json=[],
        ))
    db.flush()

    plan_work = enqueue_work(
        db, run, agents["PLANNER"], work_key="plan:v1", kind="PLAN",
        input_json={
            "case_ids": list(task.input_case_ids or []),
            "environment_id": task.environment_id,
            "target_type": target_type,
            "security_assessment": dict(task.security_assessment_json) if task.security_assessment_json else None,
            "web_authoring": dict(task.web_authoring_json) if task.web_authoring_json else None,
        }, sequence=10,
    )
    for case_id in task.input_case_ids or []:
        TaskResourceService.add_resource_ref(db, run, "INPUT", "TEST_CASE", str(case_id), metadata={"confirmed": True})
    if task.environment_id is not None:
        TaskResourceService.add_resource_ref(db, run, "INPUT", "ENVIRONMENT", str(task.environment_id), metadata={})
    if task.security_assessment_json:
        api_ids = task.security_assessment_json.get("api_ids") or [task.security_assessment_json.get("api_id")]
        for api_id in dict.fromkeys(int(item) for item in api_ids if item):
            TaskResourceService.add_resource_ref(
                db, run, "INPUT", "API", str(api_id),
                metadata={"security_assessment": True},
            )
        for strategy_id in task.security_assessment_json.get("strategy_ids", []):
            TaskResourceService.add_resource_ref(
                db, run, "INPUT", "SECURITY_STRATEGY", str(strategy_id), metadata={},
            )
        if task.security_assessment_json.get("web_session_id"):
            TaskResourceService.add_resource_ref(
                db, run, "INPUT", "WEB_AGENT_SESSION",
                str(task.security_assessment_json["web_session_id"]),
                metadata={"passive_security_inspection": True},
            )
    append_event(
        db, run, "run.created",
        {"run_number": run.run_number, "plan_work_item_id": plan_work.id, "roles": [role[0] for role in roles] + ["SUB_AGENT"] * len((agent_snapshot or {}).get("child_agents", []))},
        actor_user_id=actor.id,
    )
    return run
