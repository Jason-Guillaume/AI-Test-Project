"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.orchestration.tasks.services import assembly_service
from app.orchestration.tasks.services import state_service
import logging
import os
import platform
import secrets
import threading
from datetime import datetime
from typing import Callable
from sqlalchemy.orm import Session
from app.llm import LLMError
from app.llm.providers import ProductionLLMProvider
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskAttempt, TaskRun, TaskWorkItem
from app.orchestration.tasks.services.resource_service import TaskResourceService
from app.orchestration.tasks.runtime.contracts import TaskHandlerContext, TaskHandlerServices
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import User
from app.core.database.session import SessionLocal
from app.orchestration.tasks.runtime.contracts import ClaimedWork
from app.orchestration.tasks.runtime.access import assert_current_project_write
from app.orchestration.tasks.runtime.lease_service import claim_work
from app.orchestration.tasks.runtime.completion_service import complete_work
from app.orchestration.tasks.runtime.completion_service import defer_at_control_boundary
from app.orchestration.tasks.services.state_service import enqueue_work
from app.orchestration.tasks.runtime.completion_service import fail_work
from app.orchestration.tasks.runtime.handlers.api_execution import handle_api_execution
from app.orchestration.tasks.runtime.handlers.chat import handle_chat
from app.orchestration.tasks.runtime.handlers.finalizing import handle_finalize
from app.orchestration.tasks.runtime.handlers.planning import handle_plan
from app.orchestration.tasks.runtime.handlers.reporting import handle_report
from app.orchestration.tasks.runtime.handlers.reviewing import handle_review
from app.orchestration.tasks.runtime.handlers.security_execution import handle_security_execution
from app.orchestration.tasks.runtime.handlers.web_authoring import handle_web_authoring_start
from app.orchestration.tasks.runtime.lease_service import heartbeat_loop
from app.orchestration.tasks.runtime.lease_service import recover_expired


log = logging.getLogger(__name__)


_ACTIVE_STATUSES = ("RUNNING", "PAUSE_REQUESTED", "CANCEL_REQUESTED")


_RECOVERY_SECONDS = 300


class TaskWorker:
    """唯一调度生命周期与可信装配入口。"""

    def __init__(
        self,
        *,
        db_factory: Callable[[], Session] = SessionLocal,
        owner: str | None = None,
        poll_interval_seconds: float = 1.0,
        lease_seconds: int = _RECOVERY_SECONDS,
    ) -> None:
        """初始化进程内轮询器；空闲时按秒轮询以降低数据库空查，所有权与恢复数据保存在数据库。"""
        self._db_factory = db_factory
        self._owner = owner or f"{platform.node() or 'unknown'}:{os.getpid()}:{secrets.token_hex(4)}"
        self._poll_interval = max(0.2, poll_interval_seconds)
        self._lease_seconds = max(30, lease_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._processed = 0
        # 只把报告/审阅实际需要的有限能力传给处理器，不暴露整个 Worker。
        self._report_review_services = TaskHandlerServices(
            provider_for_agent=self._provider_for_agent,
            enqueue_work=enqueue_work,
            add_worker_resource=TaskResourceService.add_worker_resource_ref,
            append_event=state_service.append_event,
            defer_at_control_boundary=defer_at_control_boundary,
        )

    @property
    def is_running(self) -> bool:
        """读取守护线程是否仍在运行。"""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """应用启动时开始轮询；重复调用保持幂等。"""
        with self._lock:
            if self.is_running:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, name="task-scheduler", daemon=True)
            self._thread.start()
            log.info("统一任务调度器已启动 owner=%s", self._owner)

    def stop(self, timeout_seconds: float = 8.0) -> None:
        """应用关闭时等待当前安全边界并停止领取新工作。"""
        self._stop_event.set()
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, timeout_seconds))
        log.info("统一任务调度器已停止")

    def tick(self) -> int:
        """执行一轮过期租约恢复与工作项领取，供定向验证直接调用。"""
        recover_expired(db_factory=self._db_factory)
        claimed = claim_work(db_factory=self._db_factory, owner=self._owner, lease_seconds=self._lease_seconds)
        if claimed is None:
            return 0
        self._run_claimed(claimed)
        self._processed += 1
        return 1

    def _loop(self) -> None:
        """主循环；单轮数据库或工具异常不会永久打挂调度线程。"""
        while not self._stop_event.is_set():
            try:
                if self.tick() == 0:
                    self._stop_event.wait(self._poll_interval)
            except Exception:  # noqa: BLE001
                log.exception("统一任务调度轮询失败")
                self._stop_event.wait(self._poll_interval)

    def _run_claimed(self, claim: ClaimedWork) -> None:
        """运行已领取的工作项并启动独立心跳，避免长模型调用租约过期。"""
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=heartbeat_loop,
            args=(claim, heartbeat_stop),
            kwargs={"db_factory": self._db_factory, "owner": self._owner, "lease_seconds": self._lease_seconds},
            name=f"task-heartbeat-{claim.run_id}",
            daemon=True,
        )
        heartbeat.start()
        db = self._db_factory()
        try:
            work = db.get(TaskWorkItem, claim.work_item_id)
            run = db.get(TaskRun, claim.run_id)
            attempt = db.get(TaskAttempt, claim.attempt_id)
            if work is None or run is None or attempt is None:
                return
            if (run.lease_owner != self._owner or attempt.owner != self._owner
                    or work.attempt_count != attempt.lease_generation):
                return
            task = db.get(Task, run.task_id)
            actor = db.get(User, task.created_by) if task and task.created_by else None
            agent = db.get(TaskAgentInstance, work.agent_instance_id) if work.agent_instance_id else None
            if task is None or actor is None or not actor.is_active:
                raise RuntimeError("任务发起账号不可用，已停止新的业务操作")
            assert_current_project_write(db, task.project_id, actor)
            assembly_service.assert_agent_runtime_access(db, task, run, actor)
            if work.kind == "PLAN":
                handle_plan(db, task, run, work, attempt, agent, actor, provider_for_agent=self._provider_for_agent)
            elif work.kind == "EXECUTE_WEB_AUTHORING":
                handle_web_authoring_start(db, task, run, work, attempt, agent, actor)
            elif work.kind == "EXECUTE_SECURITY":
                handle_security_execution(db, task, run, work, attempt, agent, actor)
            elif work.kind in {"EXECUTE_API", "EXECUTE_WEB"}:
                handle_api_execution(db, task, run, work, attempt, agent, actor, provider_for_agent=self._provider_for_agent)
            elif work.kind == "SECURITY_SCAN":
                reason = "历史扫描器工作项已停用，未调用扫描器；请创建自研安全评估任务"
                work.status = "FAILED"
                work.error_code = "LEGACY_SECURITY_SCAN_DISABLED"
                work.error_message = reason
                work.finished_at = datetime.now()
                attempt.status = "FAILED"
                attempt.error_code = work.error_code
                attempt.error_message = reason
                attempt.finished_at = datetime.now()
                if agent is not None:
                    agent.status = "FAILED"
                run.status = "FAILED"
                run.stage = "LEGACY_SECURITY_SCAN_DISABLED"
                run.error_code = work.error_code
                run.error_message = reason
                run.finished_at = datetime.now()
                run.lease_owner = None
                run.lease_expires_at = None
                state_service.append_event(
                    db, run, "legacy_security_scan.disabled",
                    {"work_item_id": work.id}, actor_user_id=actor.id,
                )
                state_service.sync_task_status(db, task, run)
                db.commit()
                return
            elif work.kind == "REPORT":
                handle_report(TaskHandlerContext(db, task, run, work, attempt, agent, actor), self._report_review_services)
            elif work.kind == "REVIEW":
                handle_review(TaskHandlerContext(db, task, run, work, attempt, agent, actor), self._report_review_services)
            elif work.kind == "FINALIZE":
                handle_finalize(db, task, run, work, attempt, agent, actor, provider_for_agent=self._provider_for_agent)
            elif work.kind == "CHAT":
                handle_chat(db, task, run, work, attempt, agent, actor, provider_for_agent=self._provider_for_agent)
            else:
                raise RuntimeError(f"未知工作项类型：{work.kind}")
            complete_work(db, task, run, work, attempt, agent)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            fail_work(claim, exc, db_factory=self._db_factory)
            log.exception("任务工作项执行失败 run_id=%s work_item_id=%s", claim.run_id, claim.work_item_id)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2.0)
            db.close()

    def _provider_for_agent(
        self, db: Session, task: Task, run: TaskRun, work: TaskWorkItem,
        attempt: TaskAttempt, agent: TaskAgentInstance, actor: User,
    ) -> ProductionLLMProvider:
        """构造已授权的有序模型路由，并把每次调用记录到当前工作项检查点。"""
        snapshot = agent.config_snapshot or {}
        primary_id = agent.model_config_id or snapshot.get("model_config_id")
        configured_ids = [primary_id, *(snapshot.get("fallback_model_config_ids") or [])]
        candidate_ids: list[int] = []
        denied = False
        for config_id in dict.fromkeys(item for item in configured_ids if item is not None):
            model = db.get(ModelConfiguration, int(config_id))
            if model is None or not model.is_enabled:
                continue
            try:
                # 备用模型也必须在当前组织授权集合内，不能因主模型故障扩大模型权限。
                assembly_service.assert_agent_model_access(db, task.project_id, actor, model.id)
            except RuntimeError as exc:
                if any(word in str(exc) for word in ("组织", "授权", "开放")):
                    denied = True
                    continue
                raise
            candidate_ids.append(model.id)
        if not candidate_ids:
            if denied:
                raise RuntimeError("当前任务没有仍获授权的模型，已停止新的模型调用")
            raise LLMError("MODEL_UNAVAILABLE", "主模型及备用模型均未启用", retryable=True)

        def record_model_attempt(item: dict[str, object]) -> None:
            """将不含提示词和密钥的模型尝试持久化到当前执行检查点。"""
            history = [*(attempt.checkpoint_json or {}).get("model_attempts", []), item]
            attempt.checkpoint_json = {**(attempt.checkpoint_json or {}), "model_attempts": history}

        return ProductionLLMProvider(db, model_config_ids=candidate_ids, attempt_callback=record_model_attempt)
