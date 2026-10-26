"""统一任务读写、权限、可靠命令与审计事件服务。

路由层仅处理参数和身份依赖；本服务拥有任务事务边界，并通过项目角色校验保护运行、消息和产物引用。
后台执行由 tasks.runtime.worker 驱动，业务执行仍委托给现有 API 测试与报告能力。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.tasks.models import (
    Task,
    TaskAgentInstance,
    TaskCommand,
    TaskEvent,
    TaskMessage,
    TaskPlan,
    TaskResourceRef,
    TaskRun,
    TaskWorkItem,
)
from app.features.tasks.schemas import TaskCreate, TaskMessageCreate, TaskCommandCreate
from app.features.test_management.models.test_case import TestCase
from app.models.configuration import Environment, ModelConfiguration
from app.models.identity import OrganizationMember, User
from app.models.project import Project
from app.shared.errors import bad_request, conflict, forbidden, not_found
from app.shared.roles import (
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    accessible_project_ids,
    has_project_role,
    is_platform_admin,
    project_role_for,
)
from app.features.agent.providers.sanitizer import sanitize_context, sanitize_text


RUN_TERMINAL_STATUSES = frozenset({"SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "CANCELLED", "SUPERSEDED"})
RUN_PAUSE_STATUSES = frozenset({"PAUSED", "PAUSE_REQUESTED"})


class TaskService:
    """统一任务服务；实例无状态，可在路由间安全复用。"""

    def create_task(self, db: Session, project_id: int, body: TaskCreate, *, actor: User) -> dict[str, Any]:
        """校验已确认 API 用例并创建任务、首个运行、独立角色会话与规划工作项。"""
        project = self._get_project_for_write(db, project_id, actor)
        case_ids = list(dict.fromkeys(body.case_ids))
        cases = db.query(TestCase).filter(TestCase.id.in_(case_ids)).all()
        if len(cases) != len(case_ids):
            raise not_found("部分测试用例不存在")
        case_by_id = {case.id: case for case in cases}
        for case_id in case_ids:
            case = case_by_id[case_id]
            # 任务只允许显式引用已确认的 API 用例，避免把草稿或其它执行器类型误送入 API Worker。
            if case.project_id != project.id:
                raise not_found("测试用例不存在")
            if not case.enabled or case.status != "ACTIVE" or case.target_type != "API" or case.api_id is None:
                raise bad_request("任务仅支持已启用且已确认的 API 测试用例")
        environment = db.get(Environment, body.environment_id)
        if environment is None or not environment.is_active:
            raise not_found("环境不存在或已停用")

        goal = sanitize_text(body.goal).strip()
        title = sanitize_text(body.title or "").strip() or goal[:80]

        if body.request_key:
            existing = (
                db.query(Task)
                .filter(Task.created_by == actor.id, Task.request_key == body.request_key)
                .first()
            )
            if existing is not None:
                if (
                    existing.project_id != project.id
                    or existing.goal != goal
                    or existing.title != title[:200]
                    or existing.environment_id != environment.id
                    or existing.input_case_ids != case_ids
                ):
                    raise conflict("相同 request_key 已用于不同任务内容")
                return self._task_detail(db, existing)

        task = Task(
            project_id=project.id,
            created_by=actor.id,
            title=title[:200],
            goal=goal,
            environment_id=environment.id,
            input_case_ids=case_ids,
            request_key=body.request_key,
        )
        db.add(task)
        db.flush()
        run = self._create_run(db, task, actor, run_number=1)
        task.status = run.status
        try:
            db.commit()
        except IntegrityError:
            # 同一用户并发重放相同 request_key 时由唯一约束裁决，回读胜出的任务而不重复排程。
            db.rollback()
            if body.request_key:
                existing = db.query(Task).filter(
                    Task.created_by == actor.id, Task.request_key == body.request_key,
                ).first()
                if existing is not None and (
                    existing.project_id == project.id
                    and existing.goal == goal
                    and existing.title == title[:200]
                    and existing.environment_id == environment.id
                    and existing.input_case_ids == case_ids
                ):
                    return self._task_detail(db, existing)
            raise
        db.refresh(task)
        return self._task_detail(db, task)

    def list_tasks(
        self, db: Session, user: User, *, page: int, page_size: int,
        project_id: int | None = None, status: str | None = None,
    ) -> dict[str, Any]:
        """列出当前用户可见项目的任务，采用仓库统一分页形状。"""
        visible_ids = accessible_project_ids(db, user)
        query = db.query(Task)
        if project_id is not None:
            self._get_project_for_read(db, project_id, user)
            query = query.filter(Task.project_id == project_id)
        elif visible_ids is not None:
            # 空可见集合用 [-1] 占位，避免 IN () 在不同数据库上行为不一致。
            query = query.filter(Task.project_id.in_(visible_ids or [-1]))
        if status:
            query = query.filter(Task.status == status)
        total = int(query.order_by(None).with_entities(func.count()).scalar() or 0)
        rows = query.order_by(Task.updated_at.desc(), Task.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        latest_by_task = self._latest_runs(db, [row.id for row in rows])
        items = [self._task_response(row, latest_by_task.get(row.id)) for row in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_task(self, db: Session, task_id: int, user: User) -> dict[str, Any]:
        """读取任务与最新运行；跨项目不可见统一返回 404。"""
        task = self._get_task_for_read(db, task_id, user)
        return self._task_detail(db, task)

    def get_run_detail(self, db: Session, run_id: int, user: User) -> dict[str, Any]:
        """读取运行、方案、独立参与者和子任务。"""
        run, _ = self._get_run_for_read(db, run_id, user)
        # 各查询在 READ COMMITTED 下可能跨过 Planner 的一次提交；最后刷新运行权威状态，
        # 避免同一响应同时出现“方案已持久化、运行仍在规划中”的短暂混合视图。
        plans = db.query(TaskPlan).filter(TaskPlan.task_run_id == run.id).order_by(TaskPlan.version.asc()).all()
        agents = db.query(TaskAgentInstance).filter(TaskAgentInstance.task_run_id == run.id).order_by(TaskAgentInstance.id.asc()).all()
        work_items = db.query(TaskWorkItem).filter(TaskWorkItem.task_run_id == run.id).order_by(TaskWorkItem.sequence.asc(), TaskWorkItem.id.asc()).all()
        db.refresh(run)
        return {
            "run": run,
            "plans": plans,
            "agents": agents,
            "work_items": work_items,
        }

    def list_messages(self, db: Session, run_id: int, user: User) -> list[TaskMessage]:
        """读取所选运行内的全部参与者会话消息。"""
        run, _ = self._get_run_for_read(db, run_id, user)
        return db.query(TaskMessage).filter(TaskMessage.task_run_id == run.id).order_by(TaskMessage.id.asc()).all()

    def send_message(
        self, db: Session, run_id: int, body: TaskMessageCreate, *, actor: User,
    ) -> dict[str, Any]:
        """向主 Agent 或明确指定的 Worker 投递消息；目标更新形成新的运行版本。"""
        # 消息事件序号按运行行串行递增；请求去重也在同一锁内完成。
        run, task = self._get_run_for_write(db, run_id, actor, lock=True)
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
            return {"message": prior, "run": run, "created_run_id": prior.metadata_json.get("created_run_id")}

        if body.message_type in {"TEXT", "GOAL_UPDATE"}:
            recipient = self._agent_by_role(db, run.id, "MAIN")
            if body.recipient_instance_id is not None and body.recipient_instance_id != recipient.id:
                raise bad_request("任务级消息必须发送给任务主 Agent")
        else:
            if body.recipient_instance_id is None:
                raise bad_request("补充要求必须指定接收的 Worker")
            recipient = db.get(TaskAgentInstance, body.recipient_instance_id)
            if recipient is None or recipient.task_run_id != run.id or recipient.role != "API_WORKER":
                raise not_found("指定的 API Worker 不存在")
            accepting_work = db.query(TaskWorkItem.id).filter(
                TaskWorkItem.task_run_id == run.id,
                TaskWorkItem.agent_instance_id == recipient.id,
                TaskWorkItem.kind == "EXECUTE_API",
                TaskWorkItem.status.in_(("PENDING", "FAILED")),
            ).first()
            if accepting_work is None:
                raise conflict("指定的 API Worker 当前没有可接收要求的执行工作")

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
                # 有在途操作时先请求其在安全边界收尾；新目标使用独立运行，不覆盖旧产物。
                run.status = "CANCEL_REQUESTED"
            else:
                run.status = "SUPERSEDED"
                db.query(TaskWorkItem).filter(
                    TaskWorkItem.task_run_id == run.id,
                    TaskWorkItem.status == "PENDING",
                ).update({TaskWorkItem.status: "CANCELLED"}, synchronize_session=False)
            next_number = int(db.query(func.max(TaskRun.run_number)).filter(TaskRun.task_id == task.id).scalar() or 0) + 1
            new_run = self._create_run(db, task, actor, run_number=next_number)
            task.status = new_run.status
            created_run_id = new_run.id
            message.status = "PROCESSED"
            message.processed_at = datetime.now()
            message.metadata_json = {"created_run_id": new_run.id}
            self._append_event(db, run, "goal.updated", {"new_run_id": new_run.id}, actor_user_id=actor.id)
        elif recipient.role == "MAIN":
            # 普通消息由后台主 Agent 回复，HTTP 请求只持久化邮箱和工作项后立即返回。
            self._enqueue_work(
                db, run, recipient, work_key=f"chat:{message.id}", kind="CHAT",
                input_json={"message_id": message.id}, sequence=1000 + message.id,
            )
            self._append_event(db, run, "message.received", {"message_id": message.id, "role": recipient.role}, actor_user_id=actor.id)
        else:
            self._append_event(
                db, run, "message.received",
                {"message_id": message.id, "role": recipient.role, "agent_instance_id": recipient.id},
                actor_user_id=actor.id,
            )
        db.commit()
        db.refresh(message)
        return {"message": message, "run": run, "created_run_id": created_run_id}

    def create_command(
        self, db: Session, run_id: int, body: TaskCommandCreate, *, actor: User,
    ) -> TaskCommand:
        """持久化并原子应用幂等控制命令。"""
        run, task = self._get_run_for_write(db, run_id, actor, lock=True)
        prior = db.query(TaskCommand).filter(
            TaskCommand.task_run_id == run.id,
            TaskCommand.idempotency_key == body.idempotency_key,
        ).first()
        if prior is not None:
            expected_payload = {"work_item_id": body.work_item_id} if body.work_item_id else {}
            if prior.command_type != body.command_type or prior.payload != expected_payload:
                raise conflict("相同 idempotency_key 已用于不同命令")
            return prior

        command = TaskCommand(
            task_run_id=run.id,
            requested_by=actor.id,
            command_type=body.command_type,
            idempotency_key=body.idempotency_key,
            payload={"work_item_id": body.work_item_id} if body.work_item_id else {},
        )
        db.add(command)
        db.flush()

        if body.command_type == "APPROVE_PLAN":
            self._approve_plan(db, run, actor)
        elif body.command_type == "PAUSE":
            self._pause(db, run, actor)
        elif body.command_type == "RESUME":
            self._resume(db, run, actor)
        elif body.command_type == "CANCEL":
            self._cancel(db, run, actor)
        elif body.command_type == "RETRY":
            self._retry(db, run, actor, body.work_item_id)

        command.status = "COMPLETED"
        command.response_json = {"status": run.status, "stage": run.stage}
        command.processed_at = datetime.now()
        self._sync_task_status(db, task, run)
        db.commit()
        db.refresh(command)
        return command

    def list_events(self, db: Session, run_id: int, user: User, *, after_seq: int, limit: int = 200) -> list[TaskEvent]:
        """按游标续读已提交事件；重复轮询不会改变运行状态。"""
        run, _ = self._get_run_for_read(db, run_id, user)
        return (
            db.query(TaskEvent)
            .filter(TaskEvent.task_run_id == run.id, TaskEvent.event_seq > after_seq)
            .order_by(TaskEvent.event_seq.asc()).limit(min(max(limit, 1), 200)).all()
        )

    def list_resources(self, db: Session, run_id: int, user: User) -> list[TaskResourceRef]:
        """读取运行输入和产物引用，业务资源仍由原管理模块提供详情。"""
        run, _ = self._get_run_for_read(db, run_id, user)
        return db.query(TaskResourceRef).filter(TaskResourceRef.task_run_id == run.id).order_by(TaskResourceRef.id.asc()).all()

    def find_tasks_for_resource(
        self, db: Session, user: User, *, resource_type: str, resource_id: str,
        project_id: int | None = None,
    ) -> list[TaskResourceRef]:
        """按原业务资源反查其来源任务，供管理页显示双向关联。"""
        visible_ids = accessible_project_ids(db, user)
        query = (
            db.query(TaskResourceRef)
            .join(TaskRun, TaskRun.id == TaskResourceRef.task_run_id)
            .join(Task, Task.id == TaskRun.task_id)
            .filter(TaskResourceRef.resource_type == resource_type, TaskResourceRef.resource_id == resource_id)
        )
        if project_id is not None:
            self._get_project_for_read(db, project_id, user)
            query = query.filter(Task.project_id == project_id)
        elif visible_ids is not None:
            query = query.filter(Task.project_id.in_(visible_ids or [-1]))
        return query.order_by(TaskResourceRef.created_at.desc()).limit(50).all()

    # ------------------------------------------------------------------ 任务与运行构造

    def _create_run(self, db: Session, task: Task, actor: User, *, run_number: int) -> TaskRun:
        """创建一个隔离运行及其角色实例；模型凭据不会进入角色配置快照。"""
        model = self._resolve_authorized_model(db, task.project_id, actor)
        model_snapshot = self._model_snapshot(model)
        run = TaskRun(
            task_id=task.id,
            run_number=run_number,
            created_by=actor.id,
            status="QUEUED",
            stage="PLANNING",
            goal_snapshot=task.goal,
            input_snapshot={"project_id": task.project_id, "environment_id": task.environment_id, "case_ids": list(task.input_case_ids or [])},
        )
        db.add(run)
        db.flush()

        roles = (
            ("MAIN", "任务主 Agent", "READY", ["task.chat", "task.goal.update"]),
            ("PLANNER", "Planner", "QUEUED", []),
            ("API_WORKER", "API Worker", "WAITING_APPROVAL", ["test-run.create"]),
            ("REVIEWER", "审阅 Agent", "WAITING_DEPENDENCY", ["report.review"]),
            ("REPORT_AGENT", "报告 Agent", "WAITING_DEPENDENCY", ["report.generate"]),
        )
        agents: dict[str, TaskAgentInstance] = {}
        for role, name, state, tools in roles:
            instance = TaskAgentInstance(
                task_run_id=run.id,
                instance_key=role.lower(),
                role=role,
                display_name=name,
                status=state,
                model_config_id=model.id if model else None,
                config_snapshot=model_snapshot,
                skills_json=[],
                tool_allowlist_json=tools,
            )
            db.add(instance)
            agents[role] = instance
        db.flush()

        plan_work = self._enqueue_work(
            db, run, agents["PLANNER"], work_key="plan:v1", kind="PLAN",
            input_json={"case_ids": list(task.input_case_ids or []), "environment_id": task.environment_id}, sequence=10,
        )
        for case_id in task.input_case_ids or []:
            self._add_resource_ref(db, run, "INPUT", "TEST_CASE", str(case_id), metadata={"confirmed": True})
        if task.environment_id is not None:
            self._add_resource_ref(db, run, "INPUT", "ENVIRONMENT", str(task.environment_id), metadata={})
        self._append_event(
            db, run, "run.created",
            {"run_number": run.run_number, "plan_work_item_id": plan_work.id, "roles": [role[0] for role in roles]},
            actor_user_id=actor.id,
        )
        return run

    @staticmethod
    def _resolve_authorized_model(db: Session, project_id: int, actor: User) -> ModelConfiguration:
        """按现有组织智能体开关与模型白名单选择任务模型。"""
        project = db.get(Project, project_id)
        if project is None:
            raise not_found("项目不存在")
        query = db.query(ModelConfiguration).filter(ModelConfiguration.is_enabled.is_(True))
        if is_platform_admin(actor):
            # 平台管理员沿用全平台模型管理权限，优先使用现有默认模型。
            model = query.order_by(ModelConfiguration.is_default.desc(), ModelConfiguration.sort_order.asc(), ModelConfiguration.id.asc()).first()
        else:
            if project.organization_id is None:
                raise forbidden("当前项目未配置组织级智能体模型授权")
            membership = db.query(OrganizationMember).filter(
                OrganizationMember.organization_id == project.organization_id,
                OrganizationMember.user_id == actor.id,
            ).first()
            if membership is None or not membership.agent_enabled:
                raise forbidden("当前组织未向你开放智能体能力")
            allowed_ids = [str(item) for item in (membership.allowed_model_ids or [])]
            if not allowed_ids:
                raise forbidden("当前组织未向你分配智能体模型")
            model = query.filter(ModelConfiguration.domain_id.in_(allowed_ids)).order_by(
                ModelConfiguration.is_default.desc(), ModelConfiguration.sort_order.asc(), ModelConfiguration.id.asc(),
            ).first()
        if model is None:
            raise bad_request("没有可用的智能体模型配置")
        return model

    @staticmethod
    def assert_agent_model_access(
        db: Session, project_id: int, actor: User, model_config_id: int | None,
    ) -> ModelConfiguration:
        """每轮后台模型调用前复核配置启用态与发起人的当前组织授权。"""
        if model_config_id is None:
            raise RuntimeError("任务未绑定模型配置，已停止智能体调用")
        model = db.get(ModelConfiguration, model_config_id)
        if model is None or not model.is_enabled:
            raise RuntimeError("任务模型配置已删除或停用，已停止智能体调用")
        project = db.get(Project, project_id)
        if project is None:
            raise RuntimeError("任务项目不存在")
        if is_platform_admin(actor):
            return model
        if project.organization_id is None:
            raise RuntimeError("任务项目未配置组织级智能体模型授权")
        membership = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.user_id == actor.id,
        ).first()
        allowed_ids = {str(item) for item in (membership.allowed_model_ids or [])} if membership else set()
        if membership is None or not membership.agent_enabled or model.domain_id not in allowed_ids:
            raise RuntimeError("任务发起人的智能体模型授权已撤销，已停止新的智能体调用")
        return model

    @staticmethod
    def _model_snapshot(model: ModelConfiguration | None) -> dict[str, Any]:
        """只快照非敏感模型身份与调用参数；密钥仍由现有模型配置加密管理。"""
        if model is None:
            return {"binding": "default", "available": False}
        return {
            "binding": "explicit",
            "model_config_id": model.id,
            "domain_id": model.domain_id,
            "label": model.label,
            "provider": model.provider,
            "model_name": model.model_name,
            "temperature": model.temperature,
            "max_tokens": model.max_tokens,
            "timeout": model.timeout,
        }

    @staticmethod
    def _enqueue_work(
        db: Session, run: TaskRun, agent: TaskAgentInstance | None, *, work_key: str,
        kind: str, input_json: dict[str, Any], sequence: int,
    ) -> TaskWorkItem:
        """按运行内键去重登记工作项，重复 HTTP 命令不会复制任务副作用。"""
        existing = db.query(TaskWorkItem).filter(
            TaskWorkItem.task_run_id == run.id, TaskWorkItem.work_key == work_key,
        ).first()
        if existing is not None:
            return existing
        work = TaskWorkItem(
            task_run_id=run.id,
            agent_instance_id=agent.id if agent else None,
            work_key=work_key,
            kind=kind,
            sequence=sequence,
            status="PENDING",
            input_json=sanitize_context(input_json),
            idempotency_key=f"run:{run.id}:{work_key}",
        )
        db.add(work)
        db.flush()
        return work

    # ------------------------------------------------------------------ 命令与状态转换

    def _approve_plan(self, db: Session, run: TaskRun, actor: User) -> None:
        """只有已持久化的 Planner 方案可被成员明确批准并排入测试执行。"""
        if run.status != "WAITING_CONFIRMATION" or run.stage != "PLAN_REVIEW":
            raise conflict("当前运行没有待确认的测试方案")
        plan = db.query(TaskPlan).filter(TaskPlan.task_run_id == run.id, TaskPlan.version == run.current_plan_version).with_for_update().first()
        if plan is None or plan.status != "PROPOSED":
            raise conflict("当前测试方案已被处理")
        api_agent = self._agent_by_role(db, run.id, "API_WORKER")
        plan_work = db.query(TaskWorkItem).filter(TaskWorkItem.task_run_id == run.id, TaskWorkItem.kind == "PLAN").order_by(TaskWorkItem.id.desc()).first()
        work = self._enqueue_work(
            db, run, api_agent, work_key=f"api-execution:v{plan.version}", kind="EXECUTE_API",
            input_json={"plan_id": plan.id, "case_ids": list(run.input_snapshot.get("case_ids", [])), "environment_id": run.input_snapshot.get("environment_id")},
            sequence=20,
        )
        if plan_work is not None:
            from app.features.tasks.models import TaskWorkItemDependency
            db.add(TaskWorkItemDependency(work_item_id=work.id, depends_on_id=plan_work.id))
        plan.status = "ACCEPTED"
        plan.accepted_at = datetime.now()
        run.status = "QUEUED"
        run.stage = "API_EXECUTION"
        api_agent.status = "QUEUED"
        self._append_event(db, run, "plan.accepted", {"plan_id": plan.id, "work_item_id": work.id}, actor_user_id=actor.id)

    def _pause(self, db: Session, run: TaskRun, actor: User) -> None:
        """运行中的暂停在当前工作项安全边界生效，待确认状态可立即暂停。"""
        if run.status in RUN_TERMINAL_STATUSES or run.status in RUN_PAUSE_STATUSES:
            raise conflict("当前运行不能重复暂停")
        run.status = "PAUSE_REQUESTED" if run.status == "RUNNING" else "PAUSED"
        self._append_event(db, run, "run.pause_requested", {"effective_at": "安全边界"}, actor_user_id=actor.id)

    def _resume(self, db: Session, run: TaskRun, actor: User) -> None:
        """恢复暂停运行；方案仍待审阅时回到确认态，不越过人工确认。"""
        if run.status != "PAUSED":
            raise conflict("当前运行未暂停")
        has_pending = db.query(TaskWorkItem.id).filter(TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "PENDING").first()
        if run.stage == "PLAN_REVIEW":
            run.status = "WAITING_CONFIRMATION"
        elif has_pending:
            run.status = "QUEUED"
        else:
            raise conflict("当前运行没有可继续的工作项")
        self._append_event(db, run, "run.resumed", {"status": run.status}, actor_user_id=actor.id)

    def _cancel(self, db: Session, run: TaskRun, actor: User) -> None:
        """取消在途工作采用协作式标记；未领取工作立即终止。"""
        if run.status in RUN_TERMINAL_STATUSES or run.status == "CANCEL_REQUESTED":
            raise conflict("当前运行不能重复取消")
        if run.status == "RUNNING":
            run.status = "CANCEL_REQUESTED"
        else:
            run.status = "CANCELLED"
            run.finished_at = datetime.now()
            db.query(TaskWorkItem).filter(
                TaskWorkItem.task_run_id == run.id, TaskWorkItem.status == "PENDING",
            ).update({TaskWorkItem.status: "CANCELLED"}, synchronize_session=False)
        self._append_event(db, run, "run.cancel_requested", {"status": run.status}, actor_user_id=actor.id)

    def _retry(self, db: Session, run: TaskRun, actor: User, work_item_id: int | None) -> None:
        """仅重试明确失败且副作用可判定的工作项；未知回执必须人工核对。"""
        if work_item_id is None:
            raise bad_request("重试必须指定失败的工作项")
        if run.status not in {"FAILED", "RECONCILIATION_REQUIRED", "SUCCEEDED_WITH_ISSUES"}:
            raise conflict("当前运行状态不支持重试")
        work = db.query(TaskWorkItem).filter(
            TaskWorkItem.id == work_item_id, TaskWorkItem.task_run_id == run.id,
        ).with_for_update().first()
        if work is None or work.status != "FAILED":
            raise not_found("可重试的失败工作项不存在")
        if work.kind == "EXECUTE_API":
            from app.features.tasks.models import TaskToolInvocation
            invocation = db.query(TaskToolInvocation).filter(TaskToolInvocation.work_item_id == work.id).first()
            if invocation is not None and invocation.status in {"STARTED", "NEEDS_RECONCILIATION"}:
                raise conflict("API 执行回执状态不明，请先从执行中心核对，不能自动重放")
        if work.kind not in {"PLAN", "CHAT", "REPORT", "FINALIZE"} and work.kind != "EXECUTE_API":
            raise conflict("该类工作项尚未接入安全重试")
        if work.attempt_count >= work.max_attempts:
            raise conflict("工作项已达到最大重试次数")
        work.status = "PENDING"
        work.error_code = None
        work.error_message = None
        work.finished_at = None
        run.status = "QUEUED"
        run.error_code = None
        run.error_message = None
        self._append_event(db, run, "work_item.retry_queued", {"work_item_id": work.id}, actor_user_id=actor.id)

    # ------------------------------------------------------------------ 权限、事件与响应组装

    def _get_project_for_read(self, db: Session, project_id: int, user: User) -> Project:
        """读取项目并按 viewer+ 校验；不可见与不存在统一 404。"""
        project = db.get(Project, project_id)
        if project is None or not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
            raise not_found("项目不存在")
        return project

    def _get_project_for_write(self, db: Session, project_id: int, user: User) -> Project:
        """写任务至少需要项目 member；项目不可见仍统一 404。"""
        project = self._get_project_for_read(db, project_id, user)
        if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_MEMBER):
            raise forbidden("需要项目成员权限")
        return project

    def _get_task_for_read(self, db: Session, task_id: int, user: User) -> Task:
        """读取任务并回查所属项目权限。"""
        task = db.get(Task, task_id)
        if task is None:
            raise not_found("任务不存在")
        self._get_project_for_read(db, task.project_id, user)
        return task

    def _get_run_for_read(self, db: Session, run_id: int, user: User) -> tuple[TaskRun, Task]:
        """读取运行并校验所属任务项目权限。"""
        run = db.get(TaskRun, run_id)
        if run is None:
            raise not_found("任务运行不存在")
        task = self._get_task_for_read(db, run.task_id, user)
        return run, task

    def _get_run_for_write(
        self, db: Session, run_id: int, actor: User, *, lock: bool = False,
    ) -> tuple[TaskRun, Task]:
        """读取可写运行；状态变更调用方可要求行锁避免并发命令覆盖。"""
        query = db.query(TaskRun).filter(TaskRun.id == run_id)
        if lock:
            query = query.with_for_update()
        run = query.first()
        if run is None:
            raise not_found("任务运行不存在")
        task = db.get(Task, run.task_id)
        if task is None:
            raise not_found("任务不存在")
        self._get_project_for_write(db, task.project_id, actor)
        return run, task

    @staticmethod
    def _agent_by_role(db: Session, run_id: int, role: str) -> TaskAgentInstance:
        """取运行内固定角色实例；不存在时按数据完整性错误处理。"""
        agent = db.query(TaskAgentInstance).filter(
            TaskAgentInstance.task_run_id == run_id, TaskAgentInstance.role == role,
        ).first()
        if agent is None:
            raise not_found("任务参与者不存在")
        return agent

    @staticmethod
    def _append_event(
        db: Session, run: TaskRun, event_type: str, payload: dict[str, Any], *,
        actor_user_id: int | None = None, agent_instance_id: int | None = None,
    ) -> TaskEvent:
        """同事务递增运行游标并记录实际状态变化。"""
        run.event_seq += 1
        event = TaskEvent(
            task_run_id=run.id,
            event_seq=run.event_seq,
            event_type=event_type,
            actor_user_id=actor_user_id,
            agent_instance_id=agent_instance_id,
            payload=sanitize_context(payload),
        )
        db.add(event)
        return event

    @staticmethod
    def _add_resource_ref(
        db: Session, run: TaskRun, direction: str, resource_type: str, resource_id: str,
        *, agent_instance_id: int | None = None, version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskResourceRef:
        """按运行、方向、类型和资源 ID 去重引用，业务主表仍保持唯一事实源。"""
        existing = db.query(TaskResourceRef).filter(
            TaskResourceRef.task_run_id == run.id,
            TaskResourceRef.direction == direction,
            TaskResourceRef.resource_type == resource_type,
            TaskResourceRef.resource_id == resource_id,
        ).first()
        if existing is not None:
            return existing
        ref = TaskResourceRef(
            task_run_id=run.id,
            agent_instance_id=agent_instance_id,
            direction=direction,
            resource_type=resource_type,
            resource_id=resource_id,
            version=version,
            metadata_json=sanitize_context({**(metadata or {}), "task_id": run.task_id}),
        )
        db.add(ref)
        return ref

    @staticmethod
    def _sync_task_status(db: Session, task: Task, run: TaskRun) -> None:
        """只让最新 run 更新任务列表状态，旧运行收尾不覆盖新目标。"""
        latest_id = db.query(TaskRun.id).filter(TaskRun.task_id == task.id).order_by(TaskRun.run_number.desc()).limit(1).scalar()
        if latest_id == run.id:
            task.status = run.status

    def _task_detail(self, db: Session, task: Task) -> dict[str, Any]:
        """组装任务与最新运行响应。"""
        latest = db.query(TaskRun).filter(TaskRun.task_id == task.id).order_by(TaskRun.run_number.desc()).first()
        return self._task_response(task, latest)

    @staticmethod
    def _task_response(task: Task, run: TaskRun | None) -> dict[str, Any]:
        """生成稳定任务 DTO，避免响应 ORM 关系或秘密配置。"""
        return {
            "id": task.id,
            "project_id": task.project_id,
            "created_by": task.created_by,
            "title": task.title,
            "goal": task.goal,
            "environment_id": task.environment_id,
            "input_case_ids": task.input_case_ids or [],
            "status": task.status,
            "archived": task.archived,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "latest_run": run,
        }

    @staticmethod
    def _latest_runs(db: Session, task_ids: list[int]) -> dict[int, TaskRun]:
        """批量取每个任务最新运行，避免列表页对每行单独查库。"""
        if not task_ids:
            return {}
        rows = (
            db.query(TaskRun)
            .filter(TaskRun.task_id.in_(task_ids))
            .order_by(TaskRun.task_id.asc(), TaskRun.run_number.desc())
            .all()
        )
        result: dict[int, TaskRun] = {}
        for row in rows:
            result.setdefault(row.task_id, row)
        return result
