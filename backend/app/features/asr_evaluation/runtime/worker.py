"""ASR 持久任务与夜间计划 Worker。

Worker 与 Web 服务分开启动；队列领取使用短事务、SKIP LOCKED、租约代次和独立心跳 Session。
提交响应丢失时转待核实状态，不按超时盲目重复收费请求；轮询失败只延后同一个远端任务。
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database.session import SessionLocal
from app.core.config import settings
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret
from app.platform.projects.services.access_service import require_writable_project
from app.features.asr_evaluation.models import (
    AsrConnection, AsrContentReviewJob, AsrJob, AsrModelRun, AsrProcessingRun, AsrProcessingWorkItem, AsrSchedule,
    AsrSuggestionJob, AsrWorkItem, AsrWorkerHeartbeat,
)
from app.features.asr_evaluation.providers.generic_json import (
    AsrProviderError, AsrRateLimited, AsrRemoteFailure, AsrSubmissionUncertain,
    DiarizationJsonProvider, GenericJsonProvider,
)
from app.features.asr_evaluation.schemas import JobCreate
from app.features.asr_evaluation.services.assets_service import _next_daily, _validate_schedule_assets
from app.features.asr_evaluation.services.comparison_service import record_run_result
from app.features.asr_evaluation.services.evaluation_artifact_service import recover_pending_artifacts, save_provider_response
from app.features.asr_evaluation.services.content_review_service import (
    claim_review, execute_review, extend_review_lease, recover_expired_reviews,
)
from app.features.asr_evaluation.services.job_service import create_job
from app.features.asr_evaluation.services.diarization_service import record_diarization_result
from app.features.asr_evaluation.services.suggestion_job_service import (
    execute_suggestion_job, extend_suggestion_lease, recover_expired_suggestion_jobs,
)
from app.features.asr_evaluation.runtime.request_slots import asr_request_slot
from app.platform.model_configuration.models import ModelTaskSlot, ModelResource, ModelRevision

logger = logging.getLogger(__name__)


def _as_utc(value: datetime | None) -> datetime | None:
    """把数据库返回的带时区或无时区时间统一解释成 UTC。"""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AsrWorker:
    """可运行多个实例的领域队列 Worker，租约防止同一运行被并发领取。"""

    def __init__(
        self, *, worker_id: str | None = None, poll_seconds: float = 1.0,
        max_concurrency: int = 2, max_diarization_concurrency: int = 1, lease_seconds: int = 90,
    ) -> None:
        """保存进程级限制与心跳身份；网络调用期间不持有数据库事务。"""
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.poll_seconds = max(0.1, poll_seconds)
        self.max_concurrency = max(1, min(max_concurrency, 16))
        self.max_diarization_concurrency = max(1, min(max_diarization_concurrency, 4))
        self.lease_seconds = max(30, lease_seconds)
        self._stop = threading.Event()
        self._futures: set[Future] = set()
        self._diarization_futures: set[Future] = set()
        self._media_futures: set[Future] = set()
        self._suggestion_futures: set[Future] = set()
        self._review_futures: set[Future] = set()
        self._provider = GenericJsonProvider()
        self._diarization_provider = DiarizationJsonProvider()

    def stop(self) -> None:
        """请求停止领取新任务，并等待当前短轮询/HTTP 请求正常收尾。"""
        self._stop.set()

    def run_forever(self) -> None:
        """循环触发夜间计划、领取持久任务并定期写入 Worker 心跳。"""
        with (
            ThreadPoolExecutor(max_workers=self.max_concurrency, thread_name_prefix="asr-run") as asr_pool,
            ThreadPoolExecutor(
                max_workers=self.max_diarization_concurrency, thread_name_prefix="asr-diarization",
            ) as diarization_pool,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr-media") as media_pool,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr-suggestions") as suggestion_pool,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr-content-review") as review_pool,
        ):
            while not self._stop.is_set():
                if not self._business_dependencies_ready():
                    self._write_heartbeat(business_ready=False)
                    self._stop.wait(self.poll_seconds)
                    continue
                try:
                    self._process_due_schedules()
                    self._recover_expired_suggestions()
                    self._recover_expired_reviews()
                    self._recover_pending_artifacts()
                except Exception:
                    # Keep the process alive for the next cycle; Docker remains the outer crash restarter.
                    self._write_heartbeat(business_ready=False)
                    logger.exception("ASR Worker 本轮计划调度失败，将在下一轮恢复")
                self._futures = {future for future in self._futures if not future.done()}
                self._diarization_futures = {
                    future for future in self._diarization_futures if not future.done()
                }
                self._media_futures = {future for future in self._media_futures if not future.done()}
                self._suggestion_futures = {future for future in self._suggestion_futures if not future.done()}
                self._review_futures = {future for future in self._review_futures if not future.done()}
                while len(self._futures) < self.max_concurrency and not self._stop.is_set():
                    claim = self._claim_next()
                    if claim is None:
                        break
                    self._futures.add(asr_pool.submit(self._process_claim, claim))
                while len(self._diarization_futures) < self.max_diarization_concurrency and not self._stop.is_set():
                    processing_claim = self._claim_next_processing("DIARIZATION")
                    if processing_claim is None:
                        break
                    self._diarization_futures.add(
                        diarization_pool.submit(self._process_processing_claim, processing_claim),
                    )
                if not self._media_futures and not self._stop.is_set():
                    media_claim = self._claim_next_processing("MEDIA_ANALYSIS")
                    if media_claim is not None:
                        self._media_futures.add(media_pool.submit(self._process_media_claim, media_claim))
                if not self._suggestion_futures and not self._stop.is_set():
                    suggestion_claim = self._claim_next_suggestion()
                    if suggestion_claim is not None:
                        self._suggestion_futures.add(suggestion_pool.submit(self._process_suggestion_claim, suggestion_claim))
                if settings.ASR_CONTENT_REVIEW_ENABLED and not self._review_futures and not self._stop.is_set():
                    db = SessionLocal()
                    try:
                        review_claim = claim_review(db, self.worker_id)
                    except Exception:
                        db.rollback()
                        logger.exception("领取 ASR 内容评审任务失败")
                        review_claim = None
                    finally:
                        db.close()
                    if review_claim is not None:
                        self._review_futures.add(review_pool.submit(self._process_review_claim, review_claim))
                active_count = len(self._futures) + len(self._diarization_futures) + len(self._media_futures) + len(self._suggestion_futures) + len(self._review_futures)
                # Recheck after this cycle: a process can still be alive while its
                # database/schema dependency has become unavailable.
                self._write_heartbeat(
                    active_count=active_count,
                    business_ready=self._business_dependencies_ready(),
                )
                active = self._futures | self._diarization_futures | self._media_futures | self._suggestion_futures | self._review_futures
                if active:
                    wait(active, timeout=self.poll_seconds, return_when=FIRST_COMPLETED)
                else:
                    self._stop.wait(self.poll_seconds)
        self._write_heartbeat(active_count=0, business_ready=False)

    def _recover_expired_suggestions(self) -> None:
        """Move abandoned model calls to review instead of automatically risking a duplicate bill."""
        db = SessionLocal()
        try:
            recover_expired_suggestion_jobs(db)
        finally:
            db.close()

    def _recover_expired_reviews(self) -> None:
        """过期评审只转待核实，不自动重复外部调用。"""
        db = SessionLocal()
        try:
            recover_expired_reviews(db)
        finally:
            db.close()

    def _recover_pending_artifacts(self) -> None:
        """校验中断的产物登记，避免待处理状态永久占用或错误显示成功。"""
        db = SessionLocal()
        try:
            recover_pending_artifacts(db)
        finally:
            db.close()

    def _process_review_claim(self, claim: tuple[int, str, int]) -> None:
        """运行评审并以独立会话保持租约，完成后停止心跳。"""
        review_id, owner, generation = claim
        stop = threading.Event()

        def pulse() -> None:
            """续约失败时停止心跳，结果写入仍由代次校验保护。"""
            while not stop.wait(20):
                if not extend_review_lease(review_id, owner, generation):
                    return

        thread = threading.Thread(target=pulse, name=f"asr-review-lease-{review_id}", daemon=True)
        thread.start()
        try:
            execute_review(review_id, owner, generation)
        finally:
            stop.set()
            thread.join(timeout=2)

    def _business_dependencies_ready(self) -> bool:
        """Check the database and every durable queue table before reporting readiness."""
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            for model in (AsrWorkItem, AsrProcessingWorkItem, AsrSchedule, AsrSuggestionJob, AsrContentReviewJob):
                db.query(model.id).limit(1).all()
            return True
        except Exception:
            logger.warning("ASR Worker 业务依赖尚未就绪", exc_info=True)
            return False
        finally:
            db.close()

    def _claim_next_suggestion(self) -> tuple[int, str, int] | None:
        """Claim one durable suggestion job with a renewable lease and monotonic generation."""
        db = SessionLocal()
        try:
            row = db.query(AsrSuggestionJob).filter(AsrSuggestionJob.status == "QUEUED").order_by(
                AsrSuggestionJob.created_at, AsrSuggestionJob.id,
            ).with_for_update(skip_locked=True).first()
            if row is None:
                return None
            row.status = "RUNNING"
            row.attempts += 1
            row.lease_generation += 1
            row.lease_owner = f"{self.worker_id}:{uuid.uuid4().hex[:8]}"
            row.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=120)
            row.started_at = datetime.now(timezone.utc)
            claim = (row.id, row.lease_owner, row.lease_generation)
            db.commit()
            return claim
        except Exception:
            db.rollback()
            logger.exception("领取 ASR 调参建议任务失败")
            return None
        finally:
            db.close()

    def _process_suggestion_claim(self, claim: tuple[int, str, int]) -> None:
        """Run a model suggestion in the background while heartbeating its lease."""
        job_id, owner, generation = claim
        stop_pulse = threading.Event()

        def pulse_lease() -> None:
            while not stop_pulse.wait(20):
                if not extend_suggestion_lease(job_id, owner, generation):
                    return

        pulse = threading.Thread(target=pulse_lease, name=f"asr-suggestion-lease-{job_id}", daemon=True)
        pulse.start()
        try:
            execute_suggestion_job(job_id, owner, generation)
        finally:
            stop_pulse.set()
            pulse.join(timeout=2)

    def _write_heartbeat(self, *, active_count: int | None = None, business_ready: bool = True) -> None:
        """以独立 Session 更新 Worker 最近存活时间，供页面明确展示离线状态。"""
        db = SessionLocal()
        try:
            row = db.get(AsrWorkerHeartbeat, self.worker_id)
            if row is None:
                row = AsrWorkerHeartbeat(worker_id=self.worker_id, last_seen_at=datetime.now(timezone.utc))
                db.add(row)
            row.last_seen_at = datetime.now(timezone.utc)
            row.active_count = active_count if active_count is not None else sum(not item.done() for item in self._futures)
            row.business_ready = business_ready
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("ASR Worker 心跳写入失败")
        finally:
            db.close()

    def _process_due_schedules(self) -> None:
        """领取到期计划并在同一事务中推进触发时间，防止多个 Worker 重复建批次。"""
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            for _ in range(10):
                schedule = db.query(AsrSchedule).filter(
                    AsrSchedule.enabled.is_(True), AsrSchedule.next_run_at.is_not(None),
                    AsrSchedule.next_run_at <= now,
                ).order_by(AsrSchedule.next_run_at, AsrSchedule.id).with_for_update(
                    skip_locked=True,
                ).first()
                if schedule is None:
                    break
                self._trigger_schedule(db, schedule, now)
        except Exception:
            db.rollback()
            logger.exception("ASR 夜间计划触发失败")
        finally:
            db.close()

    def _trigger_schedule(self, db: Session, schedule: AsrSchedule, now: datetime) -> None:
        """按计划时区创建唯一评测批次；默认不补跑长时间错过的收费任务。"""
        scheduled_for = _as_utc(schedule.next_run_at)
        if scheduled_for is None:
            return
        if schedule.schedule_type == "DAILY":
            schedule.next_run_at = _next_daily(now, schedule.timezone, schedule.local_time)
        else:
            schedule.next_run_at = None
            schedule.enabled = False
        schedule.last_trigger_at = now
        if now - scheduled_for > timedelta(minutes=5):
            schedule.last_trigger_status = "MISSED"
            db.commit()
            return
        overlapping = db.query(AsrJob.id).filter(
            AsrJob.schedule_id == schedule.id, AsrJob.status.in_(["QUEUED", "RUNNING"]),
        ).first()
        if overlapping:
            schedule.last_trigger_status = "SKIPPED_OVERLAP"
            db.commit()
            return
        actor = db.get(User, schedule.created_by) if schedule.created_by else None
        if actor is None or not actor.is_active:
            schedule.last_trigger_status = "AUTHORIZATION_REVOKED"
            schedule.enabled = False
            db.commit()
            return
        saved_slots = db.query(ModelTaskSlot).filter(
            ModelTaskSlot.task_kind == "ASR_SCHEDULE", ModelTaskSlot.task_id == schedule.id,
        ).order_by(ModelTaskSlot.id).all()
        if saved_slots:
            payload = JobCreate(
                project_id=schedule.project_id, audio_ids=schedule.audio_ids,
                model_slots=[{
                    "slot": item.slot, "resource_id": item.resource_id,
                    "revision_id": item.revision_id, "profile_id": item.profile_id,
                } for item in saved_slots],
            )
        else:
            payload = JobCreate(
                project_id=schedule.project_id, audio_ids=schedule.audio_ids,
                connection_ids=schedule.connection_ids, parameter_set_id=schedule.parameter_set_id,
            )
        try:
            if not saved_slots:
                _validate_schedule_assets(
                    db, schedule.project_id, schedule.audio_ids, schedule.connection_ids, schedule.parameter_set_id,
                )
            # 资源权限和连接启用态在每次收费提交前重新检查，不依赖计划创建时的授权。
            require_writable_project(db, schedule.project_id, actor)
            create_job(db, payload, actor, schedule_id=schedule.id, scheduled_for=scheduled_for)
            schedule.last_trigger_status = "QUEUED"
            db.commit()
        except IntegrityError:
            # 唯一触发约束是并发 Worker 或重启后重复 tick 的最后一道幂等防线。
            db.rollback()
            existing = db.query(AsrJob.id).filter(
                AsrJob.schedule_id == schedule.id, AsrJob.scheduled_for == scheduled_for,
            ).first()
            if existing:
                current = db.get(AsrSchedule, schedule.id)
                if current and current.schedule_type == "DAILY":
                    current.next_run_at = _next_daily(now, current.timezone, current.local_time)
                    current.last_trigger_status = "ALREADY_QUEUED"
                    db.commit()
        except Exception:
            db.rollback()
            current = db.get(AsrSchedule, schedule.id)
            if current:
                current.last_trigger_status = "AUTHORIZATION_OR_CONFIGURATION_ERROR"
                current.enabled = False
                db.commit()
            logger.warning("ASR 计划 %s 因权限或配置问题未触发", schedule.id)

    def _claim_next(self) -> tuple[int, int, str, int, bool] | None:
        """短事务领取一项任务；过期提交意图转待核实而不是重复发送。"""
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            query = db.query(AsrWorkItem, AsrModelRun).join(
                AsrModelRun, AsrModelRun.id == AsrWorkItem.run_id,
            ).filter(
                AsrWorkItem.available_at <= now,
                ((AsrWorkItem.lease_expires_at.is_(None)) | (AsrWorkItem.lease_expires_at <= now)),
                AsrModelRun.status.in_(["PENDING", "SUBMITTING", "REMOTE_RUNNING"]),
            ).order_by(AsrWorkItem.available_at, AsrWorkItem.id).with_for_update(
                of=AsrWorkItem, skip_locked=True,
            ).first()
            if query is None:
                return None
            item, run = query
            if run.status == "SUBMITTING":
                # A prior process may have reached the provider before it exited.
                # Without a returned remote task ID, replaying the POST could charge twice.
                record_run_result(
                    db, run.id, status="RECONCILIATION_REQUIRED",
                    error_message="Worker 在提交窗口退出；远端是否已接收无法确认，未自动重复提交",
                    commit=False,
                )
                db.delete(item)
                db.commit()
                return None
            if run.status == "REMOTE_RUNNING" and not run.remote_task_id:
                record_run_result(
                    db, run.id, status="RECONCILIATION_REQUIRED",
                    error_message="已提交运行缺少远端任务 ID，无法安全恢复轮询",
                    commit=False,
                )
                db.delete(item)
                db.commit()
                return None
            created_at = _as_utc(run.created_at)
            if item.attempts >= 200 or (
                created_at is not None and now - created_at > timedelta(hours=24)
            ):
                # 轮询次数与期限在领取处统一检查，正常 RUNNING 响应不能绕过上限。
                terminal = "RECONCILIATION_REQUIRED" if run.status == "SUBMITTING" else "FAILED"
                record_run_result(
                    db, run.id, status=terminal,
                    error_message="后台任务超过 24 小时或 200 次请求上限，停止自动处理", commit=False,
                )
                db.delete(item)
                db.commit()
                return None
            owner = f"{self.worker_id}:{uuid.uuid4().hex[:8]}"
            item.lease_owner = owner
            item.lease_generation += 1
            item.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            item.attempts += 1
            job = db.get(AsrJob, run.job_id)
            if job is not None:
                job.status = "RUNNING"
                if job.started_at is None:
                    job.started_at = now
            submitting = run.status == "PENDING"
            if submitting:
                run.status = "SUBMITTING"
                run.submit_intent_at = now
                run.started_at = run.started_at or now
            claim = (item.id, run.id, owner, item.lease_generation, submitting)
            db.commit()
            return claim
        except Exception:
            db.rollback()
            logger.exception("领取 ASR 工作项失败")
            return None
        finally:
            db.close()

    def _claim_next_processing(self, task_type: str) -> tuple[int, int, str, int, bool] | None:
        """领取指定独立处理阶段并以自己的租约和限额恢复，不触碰 ASR 工作项。"""
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            pair = db.query(AsrProcessingWorkItem, AsrProcessingRun).join(
                AsrProcessingRun, AsrProcessingRun.id == AsrProcessingWorkItem.processing_run_id,
            ).filter(
                AsrProcessingRun.task_type == task_type,
                AsrProcessingWorkItem.available_at <= now,
                (
                    AsrProcessingWorkItem.lease_expires_at.is_(None)
                    | (AsrProcessingWorkItem.lease_expires_at <= now)
                ),
                AsrProcessingRun.status.in_(["PENDING", "SUBMITTING", "REMOTE_RUNNING"]),
            ).order_by(AsrProcessingWorkItem.available_at, AsrProcessingWorkItem.id).with_for_update(
                of=AsrProcessingWorkItem, skip_locked=True,
            ).first()
            if pair is None:
                return None
            item, run = pair
            if run.status == "SUBMITTING":
                # 提交结果不确定时停止自动调用，必须人工对照幂等键核实远端任务。
                self._complete_processing_state(
                    db, item, run, "RECONCILIATION_REQUIRED",
                    "Worker 在说话人提交窗口退出；远端状态待核实，未自动重复提交",
                )
                return None
            if run.status == "REMOTE_RUNNING" and not run.remote_task_id:
                self._complete_processing_state(
                    db, item, run, "RECONCILIATION_REQUIRED",
                    "说话人任务缺少已保存的远端任务 ID，不能安全恢复轮询",
                )
                return None
            deadline = _as_utc(run.deadline_at)
            if item.attempts >= 200 or deadline is None or now >= deadline:
                self._complete_processing_state(
                    db, item, run, "FAILED", "说话人任务超过 24 小时或 200 次请求上限，已停止处理",
                )
                return None
            owner = f"{self.worker_id}:{uuid.uuid4().hex[:8]}"
            item.lease_owner = owner
            item.lease_generation += 1
            item.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            item.attempts += 1
            run.attempts = item.attempts
            submitting = run.status == "PENDING"
            if submitting:
                run.status = "SUBMITTING"
                run.submit_intent_at = now
                run.started_at = run.started_at or now
            claim = (item.id, run.id, owner, item.lease_generation, submitting)
            db.commit()
            return claim
        except Exception:
            db.rollback()
            logger.exception("领取说话人处理工作项失败")
            return None
        finally:
            db.close()

    def _process_processing_claim(self, claim: tuple[int, int, str, int, bool]) -> None:
        """以独立心跳续约执行说话人请求，阶段失败不会改写 ASR 批次或转写结果。"""
        item_id, run_id, owner, generation, submitting = claim
        pulse_stop = threading.Event()
        pulse = threading.Thread(
            target=self._renew_processing_lease, args=(item_id, owner, generation, pulse_stop),
            name="asr-processing-lease-heartbeat", daemon=True,
        )
        pulse.start()
        try:
            self._execute_processing_claim(item_id, run_id, owner, generation, submitting)
        except Exception:
            logger.exception("说话人处理工作项执行失败，处理 ID=%s", run_id)
            if submitting:
                self._finish_processing(
                    item_id, run_id, owner, generation, "RECONCILIATION_REQUIRED",
                    "Worker 执行异常，远端提交状态待核实",
                )
            else:
                self._reschedule_processing(item_id, run_id, owner, generation, delay_seconds=30)
        finally:
            pulse_stop.set()
            pulse.join(timeout=2)

    def _process_media_claim(self, claim: tuple[int, int, str, int, bool]) -> None:
        """在单独有界线程池处理媒体任务，避免大文件解析占满远端识别轮询线程。"""
        item_id, run_id, owner, generation, _ = claim
        pulse_stop = threading.Event()
        pulse = threading.Thread(
            target=self._renew_processing_lease, args=(item_id, owner, generation, pulse_stop),
            name="asr-media-lease-heartbeat", daemon=True,
        )
        pulse.start()
        try:
            from app.features.asr_evaluation.services.media_analysis_service import record_media_analysis
            from app.features.asr_evaluation.services.media_service import analyze_audio_version

            db = SessionLocal()
            try:
                run = db.get(AsrProcessingRun, run_id)
                item = db.get(AsrProcessingWorkItem, item_id)
                actor = db.get(User, run.created_by) if run and run.created_by else None
                if (
                    run is None or item is None or actor is None or not actor.is_active
                    or item.lease_owner != owner or item.lease_generation != generation
                ):
                    self._finish_processing(item_id, run_id, owner, generation, "FAILED", "媒体任务发起人或租约不可用")
                    return
                try:
                    require_writable_project(db, run.project_id, actor)
                except Exception:
                    self._finish_processing(item_id, run_id, owner, generation, "FAILED", "发起人的项目权限已撤销")
                    return
                db.commit()
                analysis = analyze_audio_version(db, run)
                current = db.get(AsrProcessingRun, run_id)
                current_item = db.get(AsrProcessingWorkItem, item_id)
                if (
                    current is None or current_item is None or current_item.lease_owner != owner
                    or current_item.lease_generation != generation
                ):
                    return
                record_media_analysis(db, run_id, analysis, commit=False)
                removed = db.query(AsrProcessingWorkItem).filter(
                    AsrProcessingWorkItem.id == item_id,
                    AsrProcessingWorkItem.lease_owner == owner,
                    AsrProcessingWorkItem.lease_generation == generation,
                ).delete(synchronize_session=False)
                if removed != 1:
                    db.rollback()
                    return
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        except Exception:
            logger.exception("后台音频分析执行失败，处理 ID=%s", run_id)
            self._reschedule_processing(item_id, run_id, owner, generation, delay_seconds=30)
        finally:
            pulse_stop.set()
            pulse.join(timeout=2)

    def _renew_processing_lease(
        self, item_id: int, owner: str, generation: int, stop: threading.Event,
    ) -> None:
        """用独立短 Session 续约说话人运行租约，避免远端等待期间被重复领取。"""
        while not stop.wait(max(10, self.lease_seconds // 3)):
            db = SessionLocal()
            try:
                row = db.get(AsrProcessingWorkItem, item_id)
                if row is None or row.lease_owner != owner or row.lease_generation != generation:
                    return
                row.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("说话人处理租约续约失败，工作项 ID=%s", item_id)
                return
            finally:
                db.close()

    def _execute_processing_claim(
        self, item_id: int, run_id: int, owner: str, generation: int, submitting: bool,
    ) -> None:
        """每次外呼前重验权限与连接快照，成功时原子写结果并完成独立工作项。"""
        db = SessionLocal()
        try:
            item = db.get(AsrProcessingWorkItem, item_id)
            run = db.get(AsrProcessingRun, run_id)
            actor = db.get(User, run.created_by) if run and run.created_by else None
            if (
                item is None or run is None or item.lease_owner != owner
                or item.lease_generation != generation
            ):
                return
            if actor is None or not actor.is_active:
                self._finish_processing(item_id, run_id, owner, generation, "FAILED", "任务发起人已不可用")
                return
            try:
                require_writable_project(db, run.project_id, actor)
            except Exception:
                self._finish_processing(item_id, run_id, owner, generation, "FAILED", "发起人的项目权限已撤销")
                return
            connection = db.get(AsrConnection, run.connection_id) if run.connection_id else None
            canonical_slots = db.query(ModelTaskSlot).filter_by(legacy_connection_id=run.connection_id).all()
            canonical_revisions = db.query(ModelRevision).filter_by(legacy_connection_id=run.connection_id).all()
            resource_ids = {slot.resource_id for slot in canonical_slots} | {rev.resource_id for rev in canonical_revisions}
            model_disabled = any((resource := db.get(ModelResource, ident, populate_existing=True)) is None or resource.status != 'ACTIVE' or resource.visibility != 'PLATFORM' for ident in resource_ids)
            if model_disabled or connection is None or not connection.enabled or connection.task_type != "DIARIZATION":
                self._finish_processing(item_id, run_id, owner, generation, "FAILED", "说话人连接已停用或不存在")
                return
            try:
                execution = json.loads(decrypt_secret(run.execution_ciphertext or ""))
            except (ValueError, TypeError):
                self._finish_processing(item_id, run_id, owner, generation, "FAILED", "加密的说话人执行快照无法读取")
                return
            db.commit()
            with asr_request_slot(db.get_bind()):
                if submitting:
                    response = self._diarization_provider.submit(
                        db, project_id=run.project_id, execution=execution,
                        idempotency_key=f"asr-processing-{run.id}",
                    )
                else:
                    response = self._diarization_provider.poll(
                        db, project_id=run.project_id, execution=execution, remote_task_id=run.remote_task_id,
                    )
            db.rollback()
            db.expire_all()
            current_item = db.get(AsrProcessingWorkItem, item_id)
            current_run = db.get(AsrProcessingRun, run_id)
            if (
                current_item is None or current_run is None or current_item.lease_owner != owner
                or current_item.lease_generation != generation
            ):
                return
            if response["state"] == "SUCCEEDED":
                record_diarization_result(
                    db, run_id, turns=response["turns"], timeline=response["timeline"],
                    raw_response=response.get("raw_response"), model_version=response.get("model_version"),
                    duration_ms=response.get("response_time_ms"), commit=False,
                )
                removed = db.query(AsrProcessingWorkItem).filter(
                    AsrProcessingWorkItem.id == item_id,
                    AsrProcessingWorkItem.lease_owner == owner,
                    AsrProcessingWorkItem.lease_generation == generation,
                ).delete(synchronize_session=False)
                if removed != 1:
                    db.rollback()
                    return
                db.commit()
                return
            if submitting and response.get("remote_task_id"):
                current_run.remote_task_id = response["remote_task_id"]
            current_run.status = "REMOTE_RUNNING"
            current_run.duration_ms = response.get("response_time_ms")
            current_item.available_at = datetime.now(timezone.utc) + timedelta(seconds=self._poll_delay(
                current_item.attempts,
            ))
            current_item.lease_owner = None
            current_item.lease_expires_at = None
            db.commit()
        except AsrSubmissionUncertain as exc:
            self._finish_processing(item_id, run_id, owner, generation, "RECONCILIATION_REQUIRED", str(exc))
        except AsrRateLimited as exc:
            self._reschedule_processing(
                item_id, run_id, owner, generation,
                delay_seconds=exc.retry_after_seconds or self._poll_delay(1), reset_submit=submitting,
            )
        except AsrRemoteFailure as exc:
            self._finish_processing(item_id, run_id, owner, generation, "FAILED", str(exc))
        except AsrProviderError as exc:
            if submitting:
                self._finish_processing(item_id, run_id, owner, generation, "FAILED", str(exc))
            else:
                self._reschedule_processing(item_id, run_id, owner, generation, delay_seconds=self._poll_delay(1))
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _complete_processing_state(
        self, db: Session, item: AsrProcessingWorkItem, run: AsrProcessingRun, status: str, message: str,
    ) -> None:
        """在领取事务中原子保存处理终态并移除独立队列项。"""
        run.status = status
        run.error_message = message
        run.finished_at = datetime.now(timezone.utc)
        db.delete(item)
        db.commit()

    def _finish_processing(
        self, item_id: int, run_id: int, owner: str, generation: int, status: str, message: str,
    ) -> None:
        """核验独立租约代次后同事务结束说话人处理运行与队列项。"""
        db = SessionLocal()
        try:
            item = db.query(AsrProcessingWorkItem).filter(
                AsrProcessingWorkItem.id == item_id,
                AsrProcessingWorkItem.lease_owner == owner,
                AsrProcessingWorkItem.lease_generation == generation,
            ).with_for_update().first()
            run = db.get(AsrProcessingRun, run_id)
            if item is None or run is None:
                return
            run.status = status
            run.error_message = message
            run.finished_at = datetime.now(timezone.utc)
            db.delete(item)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("保存说话人处理终态失败，处理 ID=%s", run_id)
        finally:
            db.close()

    def _reschedule_processing(
        self, item_id: int, run_id: int, owner: str, generation: int, *,
        delay_seconds: int, reset_submit: bool = False,
    ) -> None:
        """保存说话人阶段下一次安全轮询时间，并在统一分支执行尝试数和期限上限。"""
        db = SessionLocal()
        try:
            item = db.query(AsrProcessingWorkItem).filter(
                AsrProcessingWorkItem.id == item_id,
                AsrProcessingWorkItem.lease_owner == owner,
                AsrProcessingWorkItem.lease_generation == generation,
            ).with_for_update().first()
            run = db.get(AsrProcessingRun, run_id)
            if item is None or run is None:
                return
            deadline = _as_utc(run.deadline_at)
            if item.attempts >= 200 or deadline is None or datetime.now(timezone.utc) >= deadline:
                self._complete_processing_state(
                    db, item, run, "FAILED", "说话人任务超过 24 小时或 200 次请求上限，已停止处理",
                )
                return
            item.available_at = datetime.now(timezone.utc) + timedelta(
                seconds=min(max(delay_seconds, 1), 3600),
            )
            item.lease_owner = None
            item.lease_expires_at = None
            if reset_submit:
                run.status = "PENDING"
                run.submit_intent_at = None
            else:
                run.status = "REMOTE_RUNNING"
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("延后说话人处理工作项失败，处理 ID=%s", run_id)
        finally:
            db.close()

    def _process_claim(self, claim: tuple[int, int, str, int, bool]) -> None:
        """在线程执行 HTTP 时启动独立租约续约，完成后核验所有者与代次。"""
        item_id, run_id, owner, generation, submitting = claim
        pulse_stop = threading.Event()
        pulse = threading.Thread(
            target=self._renew_lease, args=(item_id, owner, generation, pulse_stop),
            name="asr-lease-heartbeat", daemon=True,
        )
        pulse.start()
        try:
            self._execute_claim(item_id, run_id, owner, generation, submitting)
        except Exception:
            logger.exception("ASR 工作项执行失败，运行 ID=%s", run_id)
            if submitting:
                self._finish(run_id, item_id, owner, generation, "RECONCILIATION_REQUIRED",
                             "Worker 执行异常，提交状态待核实")
            else:
                self._reschedule(item_id, run_id, owner, generation, delay_seconds=30)
        finally:
            pulse_stop.set()
            pulse.join(timeout=2)

    def _renew_lease(self, item_id: int, owner: str, generation: int, stop: threading.Event) -> None:
        """用独立短 Session 续约，长音频响应等待期间不会被其他 Worker 重领。"""
        while not stop.wait(max(10, self.lease_seconds // 3)):
            db = SessionLocal()
            try:
                row = db.get(AsrWorkItem, item_id)
                if row is None or row.lease_owner != owner or row.lease_generation != generation:
                    return
                row.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("ASR 租约心跳失败，工作项 ID=%s", item_id)
                return
            finally:
                db.close()

    def _execute_claim(self, item_id: int, run_id: int, owner: str, generation: int, submitting: bool) -> None:
        """复核发起人和连接状态后提交或轮询一个 ASR 运行。"""
        db = SessionLocal()
        try:
            item = db.get(AsrWorkItem, item_id)
            run = db.get(AsrModelRun, run_id)
            job = db.get(AsrJob, run.job_id) if run else None
            if item is None or run is None or job is None or item.lease_owner != owner or item.lease_generation != generation:
                return
            if job.cancel_requested and submitting:
                db.commit()
                self._finish(run_id, item_id, owner, generation, "CANCELLED", "本地已停止新提交")
                return
            actor = db.get(User, job.created_by) if job.created_by else None
            if actor is None or not actor.is_active:
                db.commit()
                self._finish(run_id, item_id, owner, generation, "FAILED", "任务发起人已不可用，已阻止新请求")
                return
            try:
                require_writable_project(db, job.project_id, actor)
            except Exception:
                db.commit()
                self._finish(run_id, item_id, owner, generation, "FAILED", "发起人的项目权限已撤销，已阻止新请求")
                return
            from app.features.asr_evaluation.models import AsrConnection
            connection = db.get(AsrConnection, run.connection_id)
            canonical_slots = db.query(ModelTaskSlot).filter_by(legacy_connection_id=run.connection_id).all()
            canonical_revisions = db.query(ModelRevision).filter_by(legacy_connection_id=run.connection_id).all()
            resource_ids = {slot.resource_id for slot in canonical_slots} | {rev.resource_id for rev in canonical_revisions}
            model_disabled = any((resource := db.get(ModelResource, ident, populate_existing=True)) is None or resource.status != 'ACTIVE' or resource.visibility != 'PLATFORM' for ident in resource_ids)
            if model_disabled or connection is None or not connection.enabled:
                db.commit()
                self._finish(run_id, item_id, owner, generation, "FAILED", "接口连接已停用，已阻止新请求")
                return
            try:
                execution = json.loads(decrypt_secret(run.execution_ciphertext))
            except (ValueError, TypeError):
                db.commit()
                self._finish(run_id, item_id, owner, generation, "FAILED", "加密的执行快照无法读取")
                return
            if submitting:
                # 结束领取事务，避免在模型接口响应期间持有批次工作项的数据库事务。
                db.commit()
                with asr_request_slot(db.get_bind()):
                    response = self._provider.submit(
                        db, project_id=job.project_id, execution=execution, idempotency_key=run.idempotency_key,
                    )
            else:
                # 轮询前同样释放 ASR 工作项读取事务；共享出站策略仍在每次请求前复核白名单。
                db.commit()
                with asr_request_slot(db.get_bind()):
                    response = self._provider.poll(
                        db, project_id=job.project_id, execution=execution, remote_task_id=run.remote_task_id,
                    )
            # 共享出站策略的只读查询事务不需要跟着本次网络响应继续存在。
            db.rollback()
            db.expire_all()
            # HTTP 请求期间没有行锁；写回前必须验证租约代次，旧 Worker 不可覆盖新结果。
            if not self._owns(db, item_id, owner, generation):
                return
            if response.get("response_capture") is not None:
                # 响应在短事务中持久化后再次检查租约；提交事务期间旧 Worker 可能已失去所有权。
                current = db.get(AsrModelRun, run_id)
                if current is None:
                    return
                if submitting and response.get("remote_task_id"):
                    # 即便回执文件写入失败，也保留已知远端任务号供人工核实。
                    current.remote_task_id = response["remote_task_id"]
                    db.commit()
                    db.expire_all()
                    if not self._owns(db, item_id, owner, generation):
                        return
                    current = db.get(AsrModelRun, run_id)
                    if current is None:
                        return
                save_provider_response(db, current, response["response_kind"], response["response_capture"])
                db.expire_all()
                if not self._owns(db, item_id, owner, generation):
                    return
            if response["state"] == "SUCCEEDED":
                record_run_result(
                    db, run_id, status="SUCCEEDED", transcript=response["transcript"],
                    segments=response.get("segments") or [], duration_ms=response.get("response_time_ms"),
                    commit=False,
                )
                # 结果、对比、批次状态与队列完成使用同一事务，失败后工作项仍可恢复。
                deleted = db.query(AsrWorkItem).filter(
                    AsrWorkItem.id == item_id, AsrWorkItem.lease_owner == owner,
                    AsrWorkItem.lease_generation == generation,
                ).delete(synchronize_session=False)
                if deleted != 1:
                    db.rollback()
                    return
                db.commit()
            else:
                current = db.get(AsrModelRun, run_id)
                work = db.get(AsrWorkItem, item_id)
                job = db.get(AsrJob, current.job_id) if current else None
                if current is None or work is None:
                    return
                if submitting and response.get("remote_task_id"):
                    current.remote_task_id = response["remote_task_id"]
                if job is not None and job.cancel_requested:
                    record_run_result(
                        db, run_id, status="CANCELLED",
                        error_message="本地已停止跟踪；远端任务可能仍在运行", commit=False,
                    )
                    db.delete(work)
                    db.commit()
                    return
                created_at = _as_utc(current.created_at)
                if work.attempts >= 200 or (
                    created_at is not None and datetime.now(timezone.utc) - created_at > timedelta(hours=24)
                ):
                    # 即使远端每次正常返回 RUNNING，也必须在同一写回路径执行总期限限制。
                    record_run_result(
                        db, run_id, status="FAILED",
                        error_message="远端任务超过 24 小时或 200 次请求上限，已停止轮询", commit=False,
                    )
                    db.delete(work)
                    db.commit()
                    return
                current.status = "REMOTE_RUNNING"
                current.duration_ms = response.get("response_time_ms")
                work.available_at = datetime.now(timezone.utc) + timedelta(seconds=self._poll_delay(work.attempts))
                work.lease_owner = None
                work.lease_expires_at = None
                db.commit()
        except AsrSubmissionUncertain as exc:
            self._finish(run_id, item_id, owner, generation, "RECONCILIATION_REQUIRED", str(exc))
        except AsrRateLimited as exc:
            self._reschedule(
                item_id, run_id, owner, generation,
                delay_seconds=exc.retry_after_seconds or self._poll_delay(1), reset_submit=submitting,
            )
        except AsrRemoteFailure as exc:
            self._finish(run_id, item_id, owner, generation, "FAILED", str(exc))
        except AsrProviderError as exc:
            if submitting:
                self._finish(run_id, item_id, owner, generation, "FAILED", str(exc))
            else:
                self._reschedule(item_id, run_id, owner, generation, delay_seconds=self._poll_delay(1))
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _owns(self, db: Session, item_id: int, owner: str, generation: int) -> bool:
        """检查当前数据库租约所有者与代次是否仍匹配。"""
        row = db.get(AsrWorkItem, item_id)
        return bool(row and row.lease_owner == owner and row.lease_generation == generation)

    def _finish(
        self, run_id: int, item_id: int, owner: str, generation: int,
        status: str, message: str,
    ) -> None:
        """栅栏校验后结束运行并删除其工作项，保留待核实状态。"""
        db = SessionLocal()
        try:
            item = db.query(AsrWorkItem).filter(
                AsrWorkItem.id == item_id, AsrWorkItem.lease_owner == owner,
                AsrWorkItem.lease_generation == generation,
            ).with_for_update().first()
            if item is None:
                return
            record_run_result(db, run_id, status=status, error_message=message, commit=False)
            db.delete(item)
            # 结果写回失败会整体回滚，过期租约和工作项仍能由下一 Worker 领取。
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("保存 ASR 运行终态失败，运行 ID=%s", run_id)
        finally:
            db.close()

    def _reschedule(
        self, item_id: int, run_id: int, owner: str, generation: int, *,
        delay_seconds: int, reset_submit: bool = False,
    ) -> None:
        """保存下一次安全轮询或明确被 429 拒绝的提交时刻，不占用线程 sleep。"""
        db = SessionLocal()
        try:
            if not self._owns(db, item_id, owner, generation):
                return
            run = db.get(AsrModelRun, run_id)
            item = db.get(AsrWorkItem, item_id)
            if run is None or item is None:
                return
            created_at = _as_utc(run.created_at)
            if item.attempts >= 200 or (created_at is not None and datetime.now(timezone.utc) - created_at > timedelta(hours=24)):
                record_run_result(
                    db, run_id, status="FAILED", error_message="远端任务超过 24 小时或 200 次请求上限，已停止处理",
                    commit=False,
                )
                db.delete(item)
                db.commit()
                return
            item.available_at = datetime.now(timezone.utc) + timedelta(seconds=min(max(delay_seconds, 1), 3600))
            item.lease_owner = None
            item.lease_expires_at = None
            if reset_submit:
                run.status = "PENDING"
                run.submit_intent_at = None
            else:
                run.status = "REMOTE_RUNNING"
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("延后 ASR 工作项失败，运行 ID=%s", run_id)
        finally:
            db.close()

    @staticmethod
    def _poll_delay(attempts: int) -> int:
        """按 5 秒起步的指数退避计算轮询间隔，上限 15 分钟。"""
        return min(900, 5 * (2 ** min(max(attempts - 1, 0), 8)))


__all__ = ["AsrWorker"]
