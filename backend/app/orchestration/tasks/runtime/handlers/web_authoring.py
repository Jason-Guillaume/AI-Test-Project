"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.orchestration.tasks.services import state_service
from datetime import datetime
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import (
    Task,
    TaskAgentInstance,
    TaskAttempt,
    TaskMessage,
    TaskPlan,
    TaskRun,
    TaskWorkItem,
)
from app.orchestration.tasks.runtime.contracts import require_agent_tool
from app.core.models.identity import User
from app.orchestration.tasks.runtime.resources import add_resource
from app.orchestration.tasks.services.web_session_binding import validate_task_web_session_binding


def handle_web_authoring_start(db: Session, task: Task, run: TaskRun, work: TaskWorkItem, attempt: TaskAttempt, agent: TaskAgentInstance | None, actor: User) -> None:
    """经任务内 UI Worker 启动绑定此运行的受控浏览器和独立对话。"""
    if agent is None or agent.role != "UI_WORKER":
        raise RuntimeError("任务内 UI Worker 实例不存在")
    if run.input_snapshot.get("target_type") != "WEB_AUTHORING":
        raise RuntimeError("工作项与任务类型不匹配")
    require_agent_tool(run, agent, "web-authoring.start")
    plan = db.query(TaskPlan).filter(
        TaskPlan.task_run_id == run.id,
        TaskPlan.version == run.current_plan_version,
        TaskPlan.status == "ACCEPTED",
    ).first()
    if plan is None:
        raise RuntimeError("Web 编写方案尚未由用户批准")
    selection = run.input_snapshot.get("web_authoring") or {}
    environment_id = int(run.input_snapshot.get("environment_id") or 0)
    if environment_id <= 0 or environment_id != int(work.input_json.get("environment_id") or 0):
        raise RuntimeError("Web 编写环境与批准方案不一致")

    from app.features.web_testing.models import WebAgentSession
    from app.features.web_testing.schemas import SessionStartInput
    from app.features.web_testing.services.web_ui_service import WebUIService

    session_service = WebUIService()
    browser = session_service.start_session(
        db, task.project_id,
        SessionStartInput(
            environment_id=environment_id,
            auth_profile_id=selection.get("auth_profile_id"),
            target_page_path=selection.get("target_page_path") or "",
            step_budget=int(selection.get("step_budget") or 20),
        ),
        actor,
        task_run_id=run.id,
        task_agent_instance_id=agent.id,
        task_binding_validator=validate_task_web_session_binding,
    )
    browser_row = db.get(WebAgentSession, browser["id"])
    if browser_row is None or browser_row.task_run_id != run.id or browser_row.task_agent_instance_id != agent.id:
        raise RuntimeError("受控浏览器会话关联校验失败")

    from app.agents.models.session import AgentSession

    conversation = db.query(AgentSession).filter(AgentSession.task_run_id == run.id).first()
    if conversation is None:
        conversation = AgentSession(
            project_id=task.project_id,
            user_id=actor.id,
            title=f"任务 {task.id} · Web 编写运行 #{run.run_number}",
            task_run_id=run.id,
            task_agent_instance_id=agent.id,
        )
        db.add(conversation)
        db.flush()
    elif conversation.project_id != task.project_id or conversation.task_agent_instance_id != agent.id:
        raise RuntimeError("任务对话关联到其他项目或 Worker")
    browser_row.agent_session_id = conversation.id
    browser_row.task_agent_instance_id = agent.id
    agent.status = "ACTIVE"
    run.status = "WAITING_CONFIRMATION"
    run.stage = "WEB_AUTHORING"
    run.error_code = None
    run.error_message = None
    add_resource(
        db, run, agent, "OUTPUT", "WEB_AGENT_SESSION", str(browser_row.id),
        {"purpose": "interactive_web_authoring", "agent_session_id": conversation.id},
    )
    db.add(TaskMessage(
        task_run_id=run.id,
        agent_instance_id=agent.id,
        sender_type="AGENT",
        sender_instance_id=agent.id,
        message_type="RESULT",
        content="任务内 UI Worker 已启动受控浏览器工作区。页面步骤仍需逐项人工确认。",
        metadata_json={"web_session_id": browser_row.id, "agent_session_id": conversation.id},
        status="PROCESSED",
        client_message_id=f"agent:web-authoring-start:{work.id}",
        processed_at=datetime.now(),
    ))
    state_service.append_event(
        db, run, "web.authoring.started",
        {"work_item_id": work.id, "web_session_id": browser_row.id, "agent_session_id": conversation.id},
        agent_instance_id=agent.id,
    )
