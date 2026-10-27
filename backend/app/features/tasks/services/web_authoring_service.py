"""任务运行内的 Web 交互式编写：会话身份、步骤审核和草稿来源由任务服务维护。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.features.agent.graph import run_agent
from app.features.agent.models.agent_session import AgentSession
from app.features.agent.providers.llm_provider import ProductionLLMProvider
from app.features.agent.schemas import AgentMessageResponse, AgentSessionResponse
from app.features.agent.services import session_service
from app.features.tasks.models import Task, TaskAgentInstance, TaskMessage, TaskRun
from app.features.tasks.schemas import TaskWebAuthoringTurn
from app.features.tasks.services.task_service import TaskService
from app.features.web_ui.models import WebAgentSession
from app.features.web_ui.schemas import PromoteInput, SessionStartInput
from app.features.web_ui.services.web_ui_service import WebUIService
from app.models.configuration import ModelConfiguration
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found


class TaskWebAuthoringService:
    """把既有 Web Agent 图限制在真实 UI Worker、任务运行和受控浏览器会话内。"""

    def __init__(self) -> None:
        self.tasks = TaskService()
        self.web = WebUIService()

    def workspace(self, db: Session, run_id: int, actor: User) -> dict[str, Any]:
        run, task, agent, conversation, browser = self._bound_context(db, run_id, actor)
        from app.features.agent.router import _build_workspace

        state = session_service.load_state(db, conversation)
        messages = session_service.list_messages(db, conversation.id)
        return {
            "task_id": task.id,
            "project_id": task.project_id,
            "run": self.tasks._run_response(run),
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
            "workspace": _build_workspace(state, conversation),
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
        self.tasks.assert_agent_runtime_access(db, task, run, actor)
        self._require_tool(run, agent, "web-authoring.start")
        from app.features.web_ui.runtime.session_manager import registry

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
            ), actor, task_run_id=run.id, task_agent_instance_id=agent.id,
        )
        browser = db.get(WebAgentSession, browser_json["id"])
        browser.agent_session_id = conversation.id
        run.status = "WAITING_CONFIRMATION"
        run.stage = "WEB_AUTHORING"
        agent.status = "ACTIVE"
        self.tasks._add_resource_ref(
            db, run, "OUTPUT", "WEB_AGENT_SESSION", str(browser.id),
            agent_instance_id=agent.id,
            metadata={"purpose": "interactive_web_authoring", "agent_session_id": conversation.id},
        )
        self.tasks._append_event(
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
        self.tasks._append_event(
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
        from app.features.web_ui.runtime.session_manager import registry

        if registry.get_session(browser.id) is None:
            browser.status = "FAILED"
            browser.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            raise conflict("浏览器句柄已失效，请从任务工作区重新启动")

        self.tasks.assert_agent_runtime_access(db, task, run, actor)
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
            final_state, emitted = run_agent(
                db, conversation, actor, provider,
                content=body.content,
                action=body.action,
                web_session_id=browser.id,
            )
            db.refresh(run, with_for_update=True)
            if run.status == "CANCEL_REQUESTED":
                self.web.close_session(db, browser.id, actor, task_run_id=run.id)
                run.status = "CANCELLED"
                run.stage = "CANCELLED"
                run.finished_at = datetime.now()
                agent.status = "CANCELLED"
                self.tasks._append_event(db, run, "run.cancelled", {"safe_boundary_reached": True})
            elif run.status == "PAUSE_REQUESTED":
                stage = str(final_state.get("current_stage") or "WEB_AUTHORING")
                run.status = "PAUSED"
                run.stage = "WEB_STEP_REVIEW" if stage == "WEB_STEP_REVIEW" else "WEB_AUTHORING"
                agent.status = "PAUSED"
                self.tasks._append_event(db, run, "run.paused", {"safe_boundary_reached": True})
            else:
                stage = str(final_state.get("current_stage") or "WEB_AUTHORING")
                run.status = "WAITING_CONFIRMATION"
                run.stage = "WEB_STEP_REVIEW" if stage == "WEB_STEP_REVIEW" else "WEB_DRAFT_REVIEW" if stage == "COMPLETED" else "WEB_AUTHORING"
                agent.status = "WAITING_APPROVAL" if stage in {"WEB_STEP_REVIEW", "COMPLETED"} else "ACTIVE"
                event_type = "web.authoring.step_proposed" if stage == "WEB_STEP_REVIEW" else "web.authoring.turn_completed"
                self.tasks._append_event(
                    db, run, event_type,
                    {"request_key": body.request_key, "stage": run.stage, "model_config_id": getattr(provider, "last_model_config_id", None)},
                    agent_instance_id=agent.id,
                )
            run.lease_owner = None
            run.lease_expires_at = None
            self.tasks._sync_task_status(db, task, run)
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
                self.tasks._append_event(db, run, "run.cancelled", {"safe_boundary_reached": True})
                if agent is not None:
                    agent.status = "CANCELLED"
            elif run is not None and run.status == "PAUSE_REQUESTED":
                run.status = "PAUSED"
                run.stage = "WEB_AUTHORING"
                if agent is not None:
                    agent.status = "PAUSED"
                self.tasks._append_event(db, run, "run.paused", {"safe_boundary_reached": True})
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
                    self.tasks._sync_task_status(db, task, run)
            db.commit()
            raise
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2.0)
        return self._turn_payload(db, run.id, actor, emitted)

    def promote(self, db: Session, run_id: int, body: PromoteInput, actor: User) -> dict[str, Any]:
        run, task, agent, conversation, browser = self._bound_context(db, run_id, actor, write=True)
        if run.status == "SUCCEEDED" and run.stage == "WEB_DRAFT_CREATED":
            raise conflict("该任务运行已生成 Web 用例草稿，不会重复创建")
        if run.status != "WAITING_CONFIRMATION" or run.stage != "WEB_DRAFT_REVIEW":
            raise conflict("只有已完成交互探索的任务可以生成 Web 用例草稿")
        self.tasks.assert_agent_runtime_access(db, task, run, actor)
        self._require_tool(run, agent, "web-case.draft")
        case = self.web.promote_session(db, browser.id, body, actor, task_run_id=run.id)
        self.tasks._add_resource_ref(
            db, run, "OUTPUT", "TEST_CASE", str(case["id"]),
            agent_instance_id=agent.id,
            metadata={"confirmed": False, "source": "interactive_web_authoring", "agent_session_id": conversation.id},
        )
        from app.features.web_ui.runtime.session_manager import registry

        registry.close_session(browser.id)
        browser.status = "CLOSED"
        browser.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run.status = "SUCCEEDED"
        run.stage = "WEB_DRAFT_CREATED"
        run.finished_at = datetime.now()
        agent.status = "COMPLETED"
        self.tasks._append_event(
            db, run, "web.authoring.draft_created",
            {"test_case_id": case["id"], "confirmed": False},
            actor_user_id=actor.id, agent_instance_id=agent.id,
        )
        task.status = run.status
        db.commit()
        return case

    def _authoring_run(self, db: Session, run_id: int, actor: User, *, write: bool):
        run, task = (
            self.tasks._get_run_for_write(db, run_id, actor, lock=True)
            if write else self.tasks._get_run_for_read(db, run_id, actor)
        )
        if (run.input_snapshot or {}).get("target_type") != "WEB_AUTHORING" or task.task_mode != "WEB_AUTHORING":
            raise not_found("任务 Web 工作区不存在")
        agent = self.tasks._agent_by_role(db, run.id, "UI_WORKER")
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
            from app.features.web_ui.runtime.session_manager import registry

            for browser in db.query(WebAgentSession).filter(
                WebAgentSession.task_run_id == run.id,
                WebAgentSession.status == "ACTIVE",
            ).all():
                registry.close_session(browser.id)
                browser.status = "FAILED"
                browser.closed_at = datetime.now()
            self.tasks._append_event(db, run, "web.authoring.turn_interrupted", {"recovered": True})
            self.tasks._sync_task_status(db, task, run)
            db.commit()
        return run, task, agent

    @staticmethod
    def _heartbeat_loop(run_id: int, lease_owner: str, stop_event: threading.Event) -> None:
        """仅在这条 Web turn 仍持有租约时续租；进程退出后由恢复流程识别中断。"""
        from app.shared.database import SessionLocal

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
        from app.features.agent.router import _build_workspace

        state = session_service.load_state(db, conversation)
        return {
            "session": workspace["agent_session"],
            "messages": [AgentMessageResponse.model_validate(item) for item in emitted],
            "workspace": _build_workspace(state, conversation),
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
                TaskService.assert_agent_model_access(db, project_id, actor, model.id)
            except RuntimeError as exc:
                if any(word in str(exc) for word in ("组织", "授权", "开放")):
                    continue
                raise
            allowed.append(model.id)
        if not allowed:
            raise conflict("任务内 UI Worker 没有可用且获授权的模型")
        return ProductionLLMProvider(db, model_config_ids=allowed)
