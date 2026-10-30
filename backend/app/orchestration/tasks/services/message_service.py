"""任务消息写入与处理协调。

本服务保留消息接收者校验、客户端幂等键、事件和事务提交；创建新运行及入队动作通过
明确的单项回调注入，避免消息服务反向依赖 TaskService 外观。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.http.errors import bad_request, conflict, not_found
from app.core.models.identity import User
from app.core.security.sanitizer import sanitize_text
from app.orchestration.tasks.models import TaskAgentInstance, TaskMessage, TaskRun, TaskWorkItem
from app.orchestration.tasks.schemas import TaskMessageCreate
from app.orchestration.tasks.services.access import TaskAccessService
from app.orchestration.tasks.services.serializers import TaskSerializers
from app.orchestration.tasks.services.contracts import RunCreator, WorkEnqueuer, EventAppender


class TaskMessageService:
    """执行任务消息的校验、去重、入队与有界事务提交。"""

    @staticmethod
    def send_message(
        db: Session, run_id: int, body: TaskMessageCreate, *, actor: User,
        create_run: RunCreator, enqueue_work: WorkEnqueuer, append_event: EventAppender,
    ) -> dict[str, Any]:
        """向主 Agent 或明确指定的 Worker 投递消息；目标更新沿用新运行版本语义。"""
        # 同一运行行锁串行化事件游标和去重键，避免并发重复创建工作项或新运行。
        run, task = TaskAccessService.get_run_for_write(db, run_id, actor, lock=True)
        prior = db.query(TaskMessage).filter(
            TaskMessage.task_run_id == run.id,
            TaskMessage.client_message_id == body.client_message_id,
        ).first()
        if prior is not None:
            if (
                prior.message_type != body.message_type
                or prior.content != sanitize_text(body.content)
                or (body.recipient_instance_id is not None and prior.agent_instance_id != body.recipient_instance_id)
            ):
                raise conflict("相同 client_message_id 已用于不同消息内容")
            return {"message": prior, "run": TaskSerializers.run_response(run), "created_run_id": (prior.metadata_json or {}).get("created_run_id")}

        if body.message_type in {"TEXT", "GOAL_UPDATE"}:
            recipient = TaskMessageService._agent_by_role(db, run.id, "MAIN")
            if body.recipient_instance_id is not None and body.recipient_instance_id != recipient.id:
                raise bad_request("任务级消息必须发送给任务主 Agent")
        else:
            if body.recipient_instance_id is None:
                raise bad_request("补充要求必须指定接收的 Worker")
            recipient = db.get(TaskAgentInstance, body.recipient_instance_id)
            if recipient is None or recipient.task_run_id != run.id or recipient.role not in {"API_WORKER", "UI_WORKER"}:
                raise not_found("指定的执行 Worker 不存在")
            accepting_work = db.query(TaskWorkItem.id).filter(
                TaskWorkItem.task_run_id == run.id,
                TaskWorkItem.agent_instance_id == recipient.id,
                TaskWorkItem.kind.in_(("EXECUTE_API", "EXECUTE_WEB")),
                TaskWorkItem.status.in_(("PENDING", "FAILED")),
            ).first()
            if accepting_work is None:
                raise conflict("指定的 Worker 当前没有可接收要求的执行工作")

        created_run_id = None
        message = TaskMessage(
            task_run_id=run.id,
            agent_instance_id=recipient.id,
            sender_type="USER",
            sender_user_id=actor.id,
            message_type=body.message_type,
            content=sanitize_text(body.content),
            metadata_json={},
            status="RECEIVED",
            client_message_id=body.client_message_id,
        )
        db.add(message)
        db.flush()

        if body.message_type == "GOAL_UPDATE":
            task.goal = sanitize_text(body.content).strip()
            if run.lease_owner and run.lease_expires_at and run.lease_expires_at > datetime.now():
                # 有在途副作用时让旧运行走安全边界收尾，新目标使用独立运行保存事实。
                run.status = "CANCEL_REQUESTED"
            else:
                run.status = "SUPERSEDED"
                db.query(TaskWorkItem).filter(
                    TaskWorkItem.task_run_id == run.id,
                    TaskWorkItem.status == "PENDING",
                ).update({TaskWorkItem.status: "CANCELLED"}, synchronize_session=False)
            next_number = int(db.query(func.max(TaskRun.run_number)).filter(TaskRun.task_id == task.id).scalar() or 0) + 1
            from app.features.test_management.models.test_case import TestCase

            case = db.query(TestCase).filter(TestCase.id.in_(task.input_case_ids or [])).first()
            target_type = (
                "WEB_AUTHORING" if task.task_mode == "WEB_AUTHORING"
                else "SECURITY" if task.security_assessment_json
                else (case.target_type if case is not None else "API")
            )
            new_run = create_run(db, task, actor, run_number=next_number, target_type=target_type)
            task.status = new_run.status
            created_run_id = new_run.id
            message.status = "PROCESSED"
            message.processed_at = datetime.now()
            message.metadata_json = {"created_run_id": new_run.id}
            append_event(db, run, "goal.updated", {"new_run_id": new_run.id}, actor_user_id=actor.id)
        elif recipient.role == "MAIN":
            # HTTP 请求只持久化邮箱和工作项，模型回复仍由后台 Worker 执行。
            enqueue_work(
                db, run, recipient, work_key=f"chat:{message.id}", kind="CHAT",
                input_json={"message_id": message.id}, sequence=1000 + message.id,
            )
            append_event(db, run, "message.received", {"message_id": message.id, "role": recipient.role}, actor_user_id=actor.id)
        else:
            append_event(
                db, run, "message.received",
                {"message_id": message.id, "role": recipient.role, "agent_instance_id": recipient.id},
                actor_user_id=actor.id,
            )
        # 消息、关联事件和可能的新运行沿用同一个调用方事务，不拆成独立提交。
        db.commit()
        db.refresh(message)
        return {"message": message, "run": TaskSerializers.run_response(run), "created_run_id": created_run_id}

    @staticmethod
    def _agent_by_role(db: Session, run_id: int, role: str) -> TaskAgentInstance:
        """读取运行内固定角色实例；缺失时作为完整性错误返回 404。"""
        agent = db.query(TaskAgentInstance).filter(
            TaskAgentInstance.task_run_id == run_id, TaskAgentInstance.role == role,
        ).first()
        if agent is None:
            raise not_found("任务参与者不存在")
        return agent
