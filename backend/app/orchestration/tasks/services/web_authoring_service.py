"""任务运行内的 Web 交互式编写：会话身份、步骤审核和草稿来源由任务服务维护。"""

from __future__ import annotations

from app.orchestration.tasks.services import assembly_service
from datetime import datetime, timedelta, timezone
import threading
from typing import Any
from uuid import uuid4
from sqlalchemy.orm import Session
from app.agents.workflows.legacy.graph import run_agent
from app.agents.models.session import AgentSession
from app.llm.providers import ProductionLLMProvider
from app.agents.session_schemas import AgentMessageResponse, AgentSessionResponse
from app.agents.services import session_service
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskMessage, TaskRun
from app.orchestration.tasks.schemas import TaskWebAuthoringTurn
from app.orchestration.tasks.services.access import TaskAccessService
from app.orchestration.tasks.services.serializers import TaskSerializers
from app.orchestration.tasks.services.resource_service import TaskResourceService
from app.orchestration.tasks.services import state_service
from app.orchestration.tasks.services.web_session_binding import validate_task_web_session_binding
from app.features.web_testing.models import WebAgentSession
from app.features.web_testing.schemas import PromoteInput, SessionStartInput
from app.features.web_testing.services.web_ui_service import WebUIService
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import User
from app.core.http.errors import bad_request, conflict, not_found


class TaskWebAuthoringService:
    """把既有 Web Agent 图限制在真实 UI Worker、任务运行和受控浏览器会话内。"""

    def __init__(self) -> None:
        self.web = WebUIService()

    def workspace(self, db: Session, run_id: int, actor: User) -> dict[str, Any]:
        run, task, agent, conversation, browser = self._bound_context(db, run_id, actor)
        from app.agents.services.workspace_response import build_workspace

        state = session_service.load_state(db, conversation)
        messages = session_service.list_messages(db, conversation.id)
        return {
            "task_id": task.id,
            "project_id": task.project_id,
            "run": TaskSerializers.run_response(run),
            "agent": {
                "id": agent.id,
                "role": agent.role,
                "display_name": agent.display_name,
                "model_config_id": agent.model_config_id,
                "status": agent.status,
            },
            "agent_session": AgentSessionResponse.model_validate(conversation),
            "web_session": self.web.get_session(db, browser.id, actor, task_run_id=run.id),
            "messages": [AgentMessageResponse.model_validate(item) for item in messages],
            "workspace": build_workspace(state, conversation),
        }

    def start_or_restart(self, db: Session, run_id: int, actor: User) -> dict[str, Any]:
        run, task, agent = self._authoring_run(db, run_id, actor, write=True)
        if run.status not in {"WAITING_CONFIRMATION", "PAUSED"} or run.stage not in {
            "WEB_AUTHORING", "WEB_STEP_REVIEW", "WEB_SESSION_CLOSED", "WEB_DRAFT_REVIEW",
        }:
            raise conflict("当前任务阶段不能启动或重启浏览器会话")
        conversation = db.query(AgentSession).filter(AgentSession.task_run_id == run.id).first()
        if conversation is None or conversation.task_agent_instance_id != agent.id:
            raise conflict("任务内 UI Worker 对话尚未初始化")
        assembly_service.assert_agent_runtime_access(db, task, run, actor)
        self._require_tool(run, agent, "web-authoring.start")
        from app.execution.browser.session_manager import registry

        existing_browser = db.query(WebAgentSession).filter(
            WebAgentSession.task_run_id == run.id,
        ).order_by(WebAgentSession.id.desc()).first()
        if (
            existing_browser is not None
            and existing_browser.status == "ACTIVE"
            and registry.get_session(existing_browser.id) is not None
        ):
            return self.workspace(db, run.id, actor)
        selection = run.input_snapshot.get("web_authoring") or {}
        browser_json = self.web.start_session(
            db, task.project_id,
            SessionStartInput(
                environment_id=int(run.input_snapshot["environment_id"]),
                auth_profile_id=selection.get("auth_profile_id"),
                target_page_path=selection.get("target_page_path") or "",
                step_budget=int(selection.get("step_budget") or 20),
            ), actor,
            task_run_id=run.id,
            task_agent_instance_id=agent.id,
            task_binding_validator=validate_task_web_session_binding,
        )
        browser = db.get(WebAgentSession, browser_json["id"])
        browser.agent_session_id = conversation.id
        run.status = "WAITING_CONFIRMATION"
        run.stage = "WEB_AUTHORING"
        agent.status = "ACTIVE"
        TaskResourceService.add_resource_ref(
            db, run, "OUTPUT", "WEB_AGENT_SESSION", str(browser.id),
            agent_instance_id=agent.id,
            metadata={"purpose": "interactive_web_authoring", "agent_session_id": conversation.id},
        )
        state_service.append_event(
            db, run, "web.authoring.session_restarted",
            {"web_session_id": browser.id, "agent_session_id": conversation.id},
            actor_user_id=actor.id,
        )
        db.commit()
        return self.workspace(db, run.id, actor)

    def close_session(self, db: Session, run_id: int, actor: User) -> dict[str, Any]:
        run, task, agent, _conversation, browser = self._bound_context(db, run_id, actor, write=True)
        if run.status == "WAITING_CONFIRMATION" and run.stage == "WEB_SESSION_CLOSED" and browser.status != "ACTIVE":
            return self.workspace(db, run.id, actor)
        if run.status != "WAITING_CONFIRMATION" or run.stage not in {"WEB_AUTHORING", "WEB_STEP_REVIEW", "WEB_DRAFT_REVIEW"}:
            raise conflict("当前阶段不能关闭任务浏览器会话")
        self.web.close_session(db, browser.id, actor, task_run_id=run.id)
        run.status = "WAITING_CONFIRMATION"
        run.stage = "WEB_SESSION_CLOSED"
        agent.status = "PAUSED"
        state_service.append_event(
            db, run, "web.authoring.session_closed", {"web_session_id": browser.id}, actor_user_id=actor.id,
        )
        db.commit()
        return self.workspace(db, run.id, actor)

    def turn(self, db: Session, run_id: int, body: TaskWebAuthoringTurn, actor: User) -> dict[str, Any]:
        run, task, agent, conversation, browser = self._bound_context(db, run_id, actor, write=True)
        prior = db.query(TaskMessage).filter(
            TaskMessage.task_run_id == run.id,
            TaskMessage.client_message_id == body.request_key,
        ).first()
        if prior is not None:
            metadata = prior.metadata_json or {}
            if (
                prior.message_type != "WEB_TURN"
                or metadata.get("action") != body.action
                or metadata.get("web_session_id") != browser.id
                or prior.content != (body.content or body.action or "Web 操作")
            ):
                raise conflict("request_key 已用于不同的 Web 操作")
            if prior.status != "PROCESSED":
                raise conflict("相同 Web 操作仍在处理或需要人工核对")
            return self._turn_payload(db, run.id, actor, [])
        if run.status != "WAITING_CONFIRMATION" or run.stage not in {"WEB_AUTHORING", "WEB_STEP_REVIEW"}:
            raise conflict("当前任务不在交互式 Web 编写阶段")
        if body.web_session_id is not None and body.web_session_id != browser.id:
            raise not_found("任务浏览器会话不存在")
        if body.action not in {None, "confirm_web_step", "reject_web_step"}:
            raise bad_request("任务 Web 工作区只支持发送目标、确认步骤或驳回步骤")
        if body.action and run.stage != "WEB_STEP_REVIEW":
            raise conflict("当前没有待审核的 Web 步骤")
        if not body.action and not (body.content or "").strip():
            raise bad_request("请输入网页目标或补充要求")
        if browser.status != "ACTIVE":
            raise conflict("浏览器会话已关闭或失效，请从任务工作区重新启动")
        from app.execution.browser.session_manager import registry

        if registry.get_session(browser.id) is None:
            browser.status = "FAILED"
            browser.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            raise conflict("浏览器句柄已失效，请从任务工作区重新启动")

        assembly_service.assert_agent_runtime_access(db, task, run, actor)
        self._require_tool(run, agent, "web-authoring.turn")

        # 每个任务运行最多一轮并发交互；消息唯一键也负责客户端重试去重。
        active = db.query(TaskMessage.id).filter(
            TaskMessage.task_run_id == run.id,
            TaskMessage.message_type == "WEB_TURN",
            TaskMessage.status.in_(("RECEIVED", "PROCESSING")),
        ).first()
        if active:
            raise conflict("任务 UI Worker 正在处理上一条 Web 操作")
        prior_state = session_service.load_state(db, conversation)
        if body.action and prior_state.get("web_agent_session_id") != browser.id:
            raise conflict("浏览器会话已重新启动，请先发送新的网页目标以刷新步骤提案")
        message = TaskMessage(
            task_run_id=run.id,
            agent_instance_id=agent.id,
            sender_type="USER",
            sender_user_id=actor.id,
            message_type="WEB_TURN",
            content=body.content or body.action or "Web 操作",
            metadata_json={"action": body.action, "web_session_id": browser.id},
            status="PROCESSING",
            client_message_id=body.request_key,
        )
        db.add(message)
        run.status = "RUNNING"
        run.stage = "WEB_STEP_REVIEW_TURN" if body.action else "WEB_AUTHORING_TURN"
        run.lease_owner = f"web-authoring:{actor.id}:{uuid4().hex}"
        run.lease_expires_at = datetime.now() + timedelta(minutes=10)
        agent.status = "PROCESSING"
        db.commit()

        lease_owner = run.lease_owner
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(run.id, lease_owner, heartbeat_stop),
            name=f"web-authoring-heartbeat-{run.id}",
            daemon=True,
        )
        heartbeat.start()

        try:
            provider = self._provider(db, task.project_id, actor, agent)
            web_action_executor = None
            if body.action == "confirm_web_step":
                web_action_executor = lambda **action: self._execute_controlled_web_action(  # noqa: E731
                    db, run.id, **action,
                )
            final_state, emitted = run_agent(
                db, conversation, actor, provider,
                content=body.content,
                action=body.action,
                web_session_id=browser.id,
                web_action_executor=web_action_executor,
            )
            db.refresh(run, with_for_update=True)
            if run.status == "CANCEL_REQUESTED":
                self.web.close_session(db, browser.id, actor, task_run_id=run.id)
                run.status = "CANCELLED"
                run.stage = "CANCELLED"
                run.finished_at = datetime.now()
                agent.status = "CANCELLED"
                state_service.append_event(db, run, "run.cancelled", {"safe_boundary_reached": True})
            elif run.status == "PAUSE_REQUESTED":
                stage = str(final_state.get("current_stage") or "WEB_AUTHORING")
                run.status = "PAUSED"
                run.stage = "WEB_STEP_REVIEW" if stage == "WEB_STEP_REVIEW" else "WEB_AUTHORING"
                agent.status = "PAUSED"
                state_service.append_event(db, run, "run.paused", {"safe_boundary_reached": True})
            else:
                stage = str(final_state.get("current_stage") or "WEB_AUTHORING")
                run.status = "WAITING_CONFIRMATION"
                run.stage = "WEB_STEP_REVIEW" if stage == "WEB_STEP_REVIEW" else "WEB_DRAFT_REVIEW" if stage == "COMPLETED" else "WEB_AUTHORING"
                agent.status = "WAITING_APPROVAL" if stage in {"WEB_STEP_REVIEW", "COMPLETED"} else "ACTIVE"
                event_type = "web.authoring.step_proposed" if stage == "WEB_STEP_REVIEW" else "web.authoring.turn_completed"
                state_service.append_event(
                    db, run, event_type,
                    {"request_key": body.request_key, "stage": run.stage, "model_config_id": getattr(provider, "last_model_config_id", None)},
                    agent_instance_id=agent.id,
                )
            run.lease_owner = None
            run.lease_expires_at = None
            state_service.sync_task_status(db, task, run)
            message.status = "PROCESSED"
            message.processed_at = datetime.now()
            if emitted:
                message.metadata_json = {**(message.metadata_json or {}), "agent_message_ids": [item.id for item in emitted]}
            db.commit()
        except Exception:
            db.rollback()
            pending = db.query(TaskMessage).filter(
                TaskMessage.task_run_id == run_id,
                TaskMessage.client_message_id == body.request_key,
            ).first()
            if pending is not None:
                pending.status = "FAILED"
                pending.processed_at = datetime.now()
            run = db.query(TaskRun).filter(TaskRun.id == run_id).with_for_update().first()
            agent = db.query(TaskAgentInstance).filter_by(task_run_id=run_id, role="UI_WORKER").first()
            if run is not None and run.status == "CANCEL_REQUESTED":
                run.status = "CANCELLED"
                run.stage = "CANCELLED"
                run.finished_at = datetime.now()
                state_service.append_event(db, run, "run.cancelled", {"safe_boundary_reached": True})
                if agent is not None:
                    agent.status = "CANCELLED"
            elif run is not None and run.status == "PAUSE_REQUESTED":
                run.status = "PAUSED"
                run.stage = "WEB_AUTHORING"
                if agent is not None:
                    agent.status = "PAUSED"
                state_service.append_event(db, run, "run.paused", {"safe_boundary_reached": True})
            elif run is not None and run.status == "RUNNING":
                run.status = "WAITING_CONFIRMATION"
                run.stage = "WEB_AUTHORING"
                run.error_code = "WEB_TURN_FAILED"
                run.error_message = "Web 编写操作未完成，请检查当前页面后重试。"
                if agent is not None:
                    agent.status = "ACTIVE"
            if run is not None:
                run.lease_owner = None
                run.lease_expires_at = None
                task = db.get(Task, run.task_id)
                if task is not None:
                    state_service.sync_task_status(db, task, run)
            db.commit()
            raise
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2.0)
        return self._turn_payload(db, run.id, actor, emitted)

    def _execute_controlled_web_action(
        self,
        db: Session,
        run_id: int,
        *,
        agent_session_id: int,
        web_session_id: int,
        proposal: dict[str, Any],
        step: dict[str, Any],
        sort: int,
        actor: User,
    ) -> dict[str, Any]:
        """在任务行锁范围内执行浏览器动作，并在提交执行留痕前重获行锁。"""
        from app.execution.browser.session_manager import registry

        run = (
            db.query(TaskRun)
            .filter(TaskRun.id == run_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if run is None or run.status in {
            "PAUSE_REQUESTED", "PAUSED", "CANCEL_REQUESTED", "CANCELLED",
        }:
            return {"_control_error": "任务已暂停或取消；当前 Web 步骤未执行"}

        browser = registry.get_session(web_session_id)
        if browser is None:
            result = {
                "status": "ERROR", "error_code": "WEB_SESSION_CLOSED",
                "error_message": "浏览器会话已断开，请重新启动会话",
            }
        else:
            try:
                result = browser.execute_step(step)
            except Exception as exc:  # noqa: BLE001 — 执行异常也要终结已领取步骤
                result = {
                    "status": "ERROR", "error_code": "WEB_STEP_FAILED",
                    "error_message": f"操作失败（{type(exc).__name__}）",
                }

        step_status = "ACCEPTED" if result.get("status") == "PASSED" else "FAILED"
        session_service.finish_web_proposal(
            db, agent_session_id, proposal["message_id"], status=step_status,
        )

        # finish_web_proposal 保持既有提交点；提交后立即重新获取运行行锁，
        # 让任务控制命令继续等到加密步骤回执写入并提交后再生效。
        locked_run = (
            db.query(TaskRun)
            .filter(TaskRun.id == run_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if locked_run is None:
            raise conflict("任务运行已不存在，无法保存 Web 步骤回执")
        self.web.record_agent_step(
            db, web_session_id, sort=sort, step=step, result=result,
            status=step_status, actor=actor,
        )
        return result

    def promote(self, db: Session, run_id: int, body: PromoteInput, actor: User) -> dict[str, Any]:
        run, task, agent, conversation, browser = self._bound_context(db, run_id, actor, write=True)
        if run.status == "SUCCEEDED" and run.stage == "WEB_DRAFT_CREATED":
            raise conflict("该任务运行已生成 Web 用例草稿，不会重复创建")
        if run.status != "WAITING_CONFIRMATION" or run.stage != "WEB_DRAFT_REVIEW":
            raise conflict("只有已完成交互探索的任务可以生成 Web 用例草稿")
        assembly_service.assert_agent_runtime_access(db, task, run, actor)
        self._require_tool(run, agent, "web-case.draft")
        case = self.web.promote_session(db, browser.id, body, actor, task_run_id=run.id)
        TaskResourceService.add_resource_ref(
            db, run, "OUTPUT", "TEST_CASE", str(case["id"]),
            agent_instance_id=agent.id,
            metadata={"confirmed": False, "source": "interactive_web_authoring", "agent_session_id": conversation.id},
        )
        from app.execution.browser.session_manager import registry

        registry.close_session(browser.id)
        browser.status = "CLOSED"
        browser.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run.status = "SUCCEEDED"
        run.stage = "WEB_DRAFT_CREATED"
        run.finished_at = datetime.now()
        agent.status = "COMPLETED"
        state_service.append_event(
            db, run, "web.authoring.draft_created",
            {"test_case_id": case["id"], "confirmed": False},
            actor_user_id=actor.id, agent_instance_id=agent.id,
        )
        task.status = run.status
        db.commit()
        return case

    def _authoring_run(self, db: Session, run_id: int, actor: User, *, write: bool):
        run, task = (
            TaskAccessService.get_run_for_write(db, run_id, actor, lock=True)
            if write else TaskAccessService.get_run_for_read(db, run_id, actor)
        )
        if (run.input_snapshot or {}).get("target_type") != "WEB_AUTHORING" or task.task_mode != "WEB_AUTHORING":
            raise not_found("任务 Web 工作区不存在")
        agent = state_service.agent_by_role(db, run.id, "UI_WORKER")
        if (
            write and run.status == "RUNNING"
            and (run.lease_owner or "").startswith("web-authoring:")
            and run.lease_expires_at is not None and run.lease_expires_at < datetime.now()
        ):
            pending = db.query(TaskMessage).filter(
                TaskMessage.task_run_id == run.id,
                TaskMessage.message_type == "WEB_TURN",
                TaskMessage.status == "PROCESSING",
            ).all()
            for message in pending:
                message.status = "FAILED"
                message.processed_at = datetime.now()
            run.status = "WAITING_CONFIRMATION"
            run.stage = "WEB_AUTHORING"
            run.error_code = "WEB_TURN_INTERRUPTED"
            run.error_message = "Web 操作进程已中断；请重新启动浏览器并检查页面后继续。"
            run.lease_owner = None
            run.lease_expires_at = None
            agent.status = "ACTIVE"
            from app.execution.browser.session_manager import registry

            for browser in db.query(WebAgentSession).filter(
                WebAgentSession.task_run_id == run.id,
                WebAgentSession.status == "ACTIVE",
            ).all():
                registry.close_session(browser.id)
                browser.status = "FAILED"
                browser.closed_at = datetime.now()
            state_service.append_event(db, run, "web.authoring.turn_interrupted", {"recovered": True})
            state_service.sync_task_status(db, task, run)
            db.commit()
        return run, task, agent

    @staticmethod
    def _heartbeat_loop(run_id: int, lease_owner: str, stop_event: threading.Event) -> None:
        """仅在这条 Web turn 仍持有租约时续租；进程退出后由恢复流程识别中断。"""
        from app.core.database.session import SessionLocal

        while not stop_event.wait(20):
            db = SessionLocal()
            try:
                changed = db.query(TaskRun).filter(
                    TaskRun.id == run_id,
                    TaskRun.lease_owner == lease_owner,
                    TaskRun.status.in_(("RUNNING", "PAUSE_REQUESTED", "CANCEL_REQUESTED")),
                ).update(
                    {TaskRun.lease_expires_at: datetime.now() + timedelta(minutes=10)},
                    synchronize_session=False,
                )
                db.commit()
                if not changed:
                    return
            except Exception:
                db.rollback()
            finally:
                db.close()

    def _bound_context(self, db: Session, run_id: int, actor: User, *, write: bool = False):
        run, task, agent = self._authoring_run(db, run_id, actor, write=write)
        conversation = db.query(AgentSession).filter(AgentSession.task_run_id == run.id).first()
        browser = db.query(WebAgentSession).filter(
            WebAgentSession.task_run_id == run.id,
        ).order_by(WebAgentSession.id.desc()).first()
        if (
            conversation is None or browser is None
            or conversation.project_id != task.project_id
            or conversation.task_agent_instance_id != agent.id
            or browser.project_id != task.project_id
            or browser.task_agent_instance_id != agent.id
            or browser.agent_session_id != conversation.id
        ):
            raise conflict("任务 Web 工作区尚未启动")
        return run, task, agent, conversation, browser

    def _turn_payload(self, db: Session, run_id: int, actor: User, emitted: list[Any]) -> dict[str, Any]:
        workspace = self.workspace(db, run_id, actor)
        conversation = db.query(AgentSession).filter(AgentSession.task_run_id == run_id).one()
        from app.agents.services.workspace_response import build_workspace

        state = session_service.load_state(db, conversation)
        return {
            "session": workspace["agent_session"],
            "messages": [AgentMessageResponse.model_validate(item) for item in emitted],
            "workspace": build_workspace(state, conversation),
        }

    @staticmethod
    def _require_tool(run: TaskRun, agent: TaskAgentInstance, tool: str) -> None:
        if (run.input_snapshot or {}).get("agent_definition") and tool not in (agent.tool_allowlist_json or []):
            raise conflict(f"任务内 UI Worker 未获授权使用 {tool}")

    @staticmethod
    def _provider(db: Session, project_id: int, actor: User, agent: TaskAgentInstance) -> ProductionLLMProvider:
        snapshot = agent.config_snapshot or {}
        model_ids = [agent.model_config_id or snapshot.get("model_config_id"), *(snapshot.get("fallback_model_config_ids") or [])]
        allowed: list[int] = []
        for candidate in dict.fromkeys(item for item in model_ids if item is not None):
            model = db.get(ModelConfiguration, int(candidate))
            if model is None or not model.is_enabled:
                continue
            try:
                assembly_service.assert_agent_model_access(db, project_id, actor, model.id)
            except RuntimeError as exc:
                if any(word in str(exc) for word in ("组织", "授权", "开放")):
                    continue
                raise
            allowed.append(model.id)
        if not allowed:
            raise conflict("任务内 UI Worker 没有可用且获授权的模型")
        return ProductionLLMProvider(db, model_config_ids=allowed)
