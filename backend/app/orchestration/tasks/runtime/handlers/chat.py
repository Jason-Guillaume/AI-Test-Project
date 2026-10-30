"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.orchestration.tasks.services import state_service
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskAttempt, TaskMessage, TaskRun, TaskWorkItem
from app.core.models.identity import User
from app.orchestration.tasks.runtime.contracts import ProviderFactory
from app.agents.services.task_decision_service import _MAIN_SYSTEM, generate_text_candidate
from app.orchestration.tasks.runtime.completion_service import defer_at_control_boundary


def handle_chat(db: Session, task: Task, run: TaskRun, work: TaskWorkItem, attempt: TaskAttempt, agent: TaskAgentInstance | None, actor: User, *, provider_for_agent: ProviderFactory) -> None:
    """在独立主 Agent 会话中回复普通消息；此轮没有工具或状态修改权限。"""
    if agent is None:
        raise RuntimeError("任务主 Agent 实例不存在")
    message_id = int(work.input_json["message_id"])
    user_message = db.query(TaskMessage).filter(
        TaskMessage.id == message_id, TaskMessage.task_run_id == run.id,
        TaskMessage.agent_instance_id == agent.id,
    ).with_for_update().first()
    if user_message is None:
        raise RuntimeError("待处理消息不存在")
    user_message.status = "PROCESSING"
    db.commit()
    history_rows = db.query(TaskMessage).filter(
        TaskMessage.task_run_id == run.id,
        TaskMessage.agent_instance_id == agent.id,
        TaskMessage.id < message_id,
        TaskMessage.status == "PROCESSED",
        TaskMessage.sender_type.in_(("USER", "AGENT")),
    ).order_by(TaskMessage.id.asc()).all()
    history = [
        {"role": "USER" if row.sender_type == "USER" else "ASSISTANT", "content": sanitize_text(row.content)}
        for row in history_rows[-8:]
    ]
    context = {
        "goal": run.goal_snapshot,
        "status": run.status,
        "stage": run.stage,
        "current_plan_version": run.current_plan_version,
        "question": user_message.content,
    }
    provider = provider_for_agent(db, task, run, work, attempt, agent, actor)
    answer = generate_text_candidate(
        provider, _MAIN_SYSTEM, (run.input_snapshot or {}).get("agent_definition") or {},
        json.dumps(sanitize_context(context), ensure_ascii=False, default=str), history=history,
    )
    db.refresh(run, with_for_update=True)
    user_message = db.query(TaskMessage).filter(TaskMessage.id == message_id).with_for_update().one()
    if defer_at_control_boundary(db, run, work, attempt, agent, messages=[user_message]):
        return
    user_message.status = "PROCESSED"
    user_message.processed_at = datetime.now()
    db.add(TaskMessage(
        task_run_id=run.id,
        agent_instance_id=agent.id,
        sender_type="AGENT",
        sender_instance_id=agent.id,
        message_type="TEXT",
        content=sanitize_text(answer),
        metadata_json={"reply_to": message_id},
        status="PROCESSED",
        client_message_id=f"agent:chat:{work.id}",
        processed_at=datetime.now(),
    ))
    agent.status = "READY" if run.status not in {"SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED", "SUPERSEDED"} else "COMPLETED"
    state_service.append_event(db, run, "message.processed", {"message_id": message_id, "role": "MAIN"}, agent_instance_id=agent.id)
