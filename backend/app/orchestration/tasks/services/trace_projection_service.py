"""Durable, body-free projection of runtime facts to Langfuse."""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.database.session import SessionLocal
from app.orchestration.tasks.models import (
    RuntimeCallFact, RuntimeEventFact, RuntimeTraceProjection, Task, TaskAgentInstance,
    TaskAttempt, TaskRun, TaskWorkItem,
)

logger = logging.getLogger(__name__)
_MAX_ATTEMPTS = 8
_DELIVERY_LEASE = timedelta(minutes=2)
_READ_VISIBILITY_GRACE = timedelta(minutes=15)


def projection_key(source_type: str, source_key: str) -> str:
    """Return a stable, non-sensitive outbox key."""
    return hashlib.md5(f"{source_type}:{source_key}".encode()).hexdigest()


def enqueue_projection(
    db: Session, *, source_type: str, source_key: str, project_id: int, task_id: int,
    task_run_id: int, execution_root_run_id: int, trace_id: str | None, span_id: str | None,
) -> RuntimeTraceProjection | None:
    """Atomically register an existing runtime fact; no request/response body is copied."""
    if (not trace_id or not project_id or not task_id or not task_run_id or not execution_root_run_id
            or source_type not in {"AGENT_ATTEMPT", "MODEL_CALL", "RUNTIME_EVENT"}):
        return None
    key = projection_key(source_type, source_key)
    projection = next((item for item in db.new
                       if isinstance(item, RuntimeTraceProjection) and item.projection_key == key), None)
    if projection is None:
        projection = db.query(RuntimeTraceProjection).filter_by(projection_key=key).one_or_none()
    if projection is None:
        projection = RuntimeTraceProjection(
            projection_key=key, source_type=source_type, source_key=source_key,
            project_id=project_id, task_id=task_id, task_run_id=task_run_id,
            execution_root_run_id=execution_root_run_id, trace_id=trace_id, span_id=span_id,
            status="PENDING", next_attempt_at=datetime.now(),
        )
        db.add(projection)
    elif projection.span_id is None and span_id:
        projection.span_id = span_id
    return projection


def enqueue_attempt_projection(
    db: Session, *, task: Task, run: TaskRun, work: TaskWorkItem,
    attempt: TaskAttempt, agent: TaskAgentInstance | None,
) -> RuntimeTraceProjection | None:
    """Project one persisted Agent attempt without copying its checkpoint or message content."""
    checkpoint = attempt.checkpoint_json if isinstance(attempt.checkpoint_json, dict) else {}
    return enqueue_projection(
        db, source_type="AGENT_ATTEMPT", source_key=str(attempt.id),
        project_id=task.project_id, task_id=task.id, task_run_id=run.id,
        execution_root_run_id=run.execution_root_run_id or run.id,
        trace_id=run.trace_id, span_id=checkpoint.get("agent_span_id"),
    )


def _observation_dict(observation: Any) -> dict[str, Any]:
    if isinstance(observation, dict):
        return observation
    if hasattr(observation, "model_dump"):
        return observation.model_dump()
    if hasattr(observation, "dict"):
        return observation.dict()
    return {name: getattr(observation, name, None) for name in ("id", "metadata")}


def _existing_projection(client: Any, row: dict[str, Any]) -> bool:
    """Check Langfuse before retrying an ambiguous delivery to avoid duplicate spans."""
    observations = getattr(getattr(client, "api", None), "observations", None)
    get_many = getattr(observations, "get_many", None)
    if not callable(get_many):
        raise RuntimeError("LANGFUSE_RECONCILIATION_UNAVAILABLE")
    result = get_many(trace_id=row["trace_id"], limit=200)
    data = getattr(result, "data", None)
    if data is None and isinstance(result, dict):
        data = result.get("data", [])
    for raw in data or []:
        observation = _observation_dict(raw)
        metadata = observation.get("metadata") or {}
        if observation.get("id") == row.get("span_id"):
            return True
        if metadata.get("runtime_projection_key") == row["projection_key"]:
            return True
    return False


def _source_payload(db: Session, row: RuntimeTraceProjection) -> dict[str, Any] | None:
    if row.source_type == "AGENT_ATTEMPT":
        try:
            attempt_id = int(row.source_key)
        except ValueError:
            return None
        attempt = db.get(TaskAttempt, attempt_id)
        work = db.get(TaskWorkItem, attempt.work_item_id) if attempt is not None else None
        if attempt is None or work is None:
            return None
        agent = db.get(TaskAgentInstance, work.agent_instance_id) if work.agent_instance_id else None
        checkpoint = attempt.checkpoint_json if isinstance(attempt.checkpoint_json, dict) else {}
        end_time = attempt.finished_at or attempt.heartbeat_at or attempt.started_at
        duration_ms = max(0, int((end_time - attempt.started_at).total_seconds() * 1000)) if end_time and attempt.started_at else 0
        return {
            "name": "agent.attempt", "event_type": "AGENT_ATTEMPT", "event_name": work.kind,
            "status": attempt.status, "error_code": attempt.error_code, "duration_ms": duration_ms,
            "agent_instance_id": work.agent_instance_id,
            "agent_definition_id": agent.config_snapshot.get("agent_definition_id")
            if agent and isinstance(agent.config_snapshot, dict) else None,
            "agent_definition_revision_id": agent.agent_definition_revision_id if agent else None,
            "metadata": {"attempt_number": attempt.attempt_number, "work_item_id": work.id,
                         "agent_span_id": checkpoint.get("agent_span_id")},
        }
    if row.source_type == "MODEL_CALL":
        fact = db.query(RuntimeCallFact).filter_by(call_id=row.source_key).one_or_none()
        if fact is None:
            return None
        return {
            "name": "model.call", "event_type": "MODEL_CALL", "event_name": fact.model_name,
            "status": fact.status, "error_code": fact.error_code, "duration_ms": fact.duration_ms,
            "agent_instance_id": fact.agent_instance_id, "agent_definition_id": fact.agent_definition_id,
            "agent_definition_revision_id": fact.agent_definition_revision_id,
            "model_config_id": fact.model_config_id, "model_name": fact.model_name,
            "model_revision": fact.model_revision, "input_tokens": fact.input_tokens,
            "output_tokens": fact.output_tokens, "total_tokens": fact.total_tokens,
            "cost_amount": str(fact.cost_amount) if fact.cost_amount is not None else None,
            "cost_currency": fact.cost_currency,
        }
    fact = db.query(RuntimeEventFact).filter_by(event_id=row.source_key).one_or_none()
    if fact is None:
        return None
    from app.orchestration.tasks.services.runtime_fact_service import _safe_metadata

    return {
        "name": fact.event_type.lower(), "event_type": fact.event_type,
        "event_name": fact.event_name, "status": fact.status, "error_code": fact.error_code,
        "duration_ms": fact.duration_ms, "agent_instance_id": fact.agent_instance_id,
        "agent_definition_id": fact.agent_definition_id,
        "agent_definition_revision_id": fact.agent_definition_revision_id,
        "metadata": _safe_metadata(fact.event_metadata),
    }


class TraceProjectionWorker:
    """Claims outbox rows in short transactions, then delivers without holding a DB transaction."""

    def __init__(self, *, db_factory=SessionLocal, poll_seconds: float = 2.0, batch_size: int = 20):
        self._db_factory = db_factory
        self._poll_seconds = max(0.2, poll_seconds)
        self._batch_size = max(1, batch_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._owner = f"trace-projection:{uuid4().hex}"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="trace-projection", daemon=True)
        self._thread.start()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.1, timeout_seconds))

    def run_once(self) -> int:
        """Process one due batch; exposed for deterministic worker tests."""
        now = datetime.now()
        db = self._db_factory()
        claimed: list[int] = []
        try:
            rows = db.query(RuntimeTraceProjection).filter(or_(
                (RuntimeTraceProjection.status == "PENDING") & (RuntimeTraceProjection.next_attempt_at <= now),
                (RuntimeTraceProjection.status == "RETRYING") & (RuntimeTraceProjection.lease_expires_at <= now),
            )).order_by(RuntimeTraceProjection.next_attempt_at, RuntimeTraceProjection.id).with_for_update(
                skip_locked=True,
            ).limit(self._batch_size).all()
            for row in rows:
                row.status = "RETRYING"
                row.lease_owner = self._owner
                row.lease_expires_at = now + _DELIVERY_LEASE
                row.attempt_count += 1
                row.last_attempt_at = now
                claimed.append(row.id)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Langfuse 投影 outbox 领取失败")
            return 0
        finally:
            db.close()
        for projection_id in claimed:
            self._deliver(projection_id)
        return len(claimed)

    def _deliver(self, projection_id: int) -> None:
        db = self._db_factory()
        try:
            row = db.get(RuntimeTraceProjection, projection_id)
            if row is None or row.lease_owner != self._owner:
                return
            record = {
                "id": row.id, "projection_key": row.projection_key, "source_type": row.source_type,
                "source_key": row.source_key, "project_id": row.project_id, "task_id": row.task_id,
                "task_run_id": row.task_run_id, "execution_root_run_id": row.execution_root_run_id,
                "trace_id": row.trace_id, "span_id": row.span_id, "attempt_count": row.attempt_count,
                "last_attempt_at": row.last_attempt_at, "last_delivery_at": row.last_delivery_at,
                "created_at": row.created_at,
            }
            payload = _source_payload(db, row)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Langfuse 投影事实读取失败 projection_id=%s", projection_id)
            self._finish(projection_id, "SOURCE_READ_ERROR")
            return
        finally:
            db.close()
        if payload is None:
            self._finish(projection_id, "SOURCE_FACT_MISSING", terminal=True)
            return

        try:
            from app.llm.tracing import get_langfuse_client

            client = get_langfuse_client()
            if client is None:
                raise RuntimeError("LANGFUSE_DISABLED")
            if record["attempt_count"] > 1 or record["span_id"]:
                if _existing_projection(client, record):
                    self._finish(projection_id, None, succeeded=True)
                    return
                # SDK flush is asynchronous on the read side. Wait before replaying an ambiguous delivery.
                delivery_at = record["last_delivery_at"] or record["created_at"]
                if datetime.now() - delivery_at < _READ_VISIBILITY_GRACE:
                    self._defer(projection_id, delivery_at + _READ_VISIBILITY_GRACE, "LANGFUSE_READ_LAG")
                    return
            self._mark_delivery_started(projection_id)
            metadata = {
                "projection_key": record["projection_key"],
                "runtime_projection_key": record["projection_key"],
                "source_type": record["source_type"], "source_key": record["source_key"],
                "project_id": record["project_id"], "task_id": record["task_id"],
                "task_run_id": record["task_run_id"],
                "execution_root_run_id": record["execution_root_run_id"],
            }
            metadata.update({key: value for key, value in payload.items()
                             if key in {"event_type", "event_name", "agent_instance_id", "agent_definition_id",
                                        "agent_definition_revision_id", "model_config_id", "model_name",
                                        "model_revision", "metadata"}})
            output = {key: value for key, value in payload.items()
                      if key in {"status", "error_code", "duration_ms", "input_tokens", "output_tokens",
                                 "total_tokens", "cost_amount", "cost_currency"}}
            with client.start_as_current_observation(
                name="runtime.fact.recovery", as_type="span", metadata=metadata,
                trace_context={"trace_id": record["trace_id"]},
            ) as span:
                span.update(output=output)
                recovered_span_id = getattr(span, "id", None)
            client.flush()
            self._finish(projection_id, None, succeeded=True, span_id=recovered_span_id)
        except Exception as exc:  # noqa: BLE001 - Langfuse failure never affects the business task.
            error_code = str(exc) if str(exc).startswith("LANGFUSE_") else type(exc).__name__
            self._finish(projection_id, error_code)

    def _finish(self, projection_id: int, error_code: str | None, *, succeeded: bool = False,
                terminal: bool = False, span_id: str | None = None) -> None:
        db = self._db_factory()
        try:
            row = db.get(RuntimeTraceProjection, projection_id)
            if row is None or row.lease_owner != self._owner:
                return
            now = datetime.now()
            row.lease_owner = None
            row.lease_expires_at = None
            if succeeded:
                row.status = "SUCCEEDED"
                row.last_error_code = None
                row.projected_at = now
                if span_id:
                    row.span_id = span_id
            elif terminal or row.attempt_count >= _MAX_ATTEMPTS:
                row.status = "FAILED"
                row.last_error_code = (error_code or "PROJECTION_FAILED")[:80]
            else:
                row.status = "PENDING"
                row.last_error_code = (error_code or "PROJECTION_FAILED")[:80]
                delay = min(3600, 2 ** min(row.attempt_count, 10) * 5)
                row.next_attempt_at = now + timedelta(seconds=delay)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Langfuse 投影状态写入失败 projection_id=%s", projection_id)
        finally:
            db.close()

    def _defer(self, projection_id: int, when: datetime, reason: str) -> None:
        db = self._db_factory()
        try:
            row = db.get(RuntimeTraceProjection, projection_id)
            if row is None or row.lease_owner != self._owner:
                return
            row.status = "PENDING"
            row.next_attempt_at = min(when, datetime.now() + timedelta(seconds=60))
            row.last_error_code = reason
            row.lease_owner = None
            row.lease_expires_at = None
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Langfuse 投影延迟重试登记失败 projection_id=%s", projection_id)
        finally:
            db.close()

    def _mark_delivery_started(self, projection_id: int) -> None:
        db = self._db_factory()
        try:
            row = db.get(RuntimeTraceProjection, projection_id)
            if row is None or row.lease_owner != self._owner:
                raise RuntimeError("PROJECTION_LEASE_LOST")
            row.last_delivery_at = datetime.now()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.run_once()
            except Exception:
                logger.exception("Langfuse 投影 Worker 异常")
                processed = 0
            if processed == 0:
                self._stop.wait(self._poll_seconds)


def projection_status(db: Session, run_ids: list[int]) -> dict[str, Any]:
    rows = db.query(RuntimeTraceProjection.status, func.count(RuntimeTraceProjection.id)).filter(
        RuntimeTraceProjection.task_run_id.in_(run_ids),
    ).group_by(RuntimeTraceProjection.status).all() if run_ids else []
    counts = {status: 0 for status in ("PENDING", "RETRYING", "FAILED", "SUCCEEDED")}
    for status, count in rows:
        counts[status] = int(count)
    overall = "FAILED" if counts["FAILED"] else "RETRYING" if counts["RETRYING"] else (
        "PENDING" if counts["PENDING"] else "SUCCEEDED" if counts["SUCCEEDED"] else "UNAVAILABLE"
    )
    return {
        "status": overall, "counts": counts,
        "last_projected_at": db.query(func.max(RuntimeTraceProjection.projected_at)).filter(
            RuntimeTraceProjection.task_run_id.in_(run_ids),
        ).scalar() if run_ids else None,
        "last_error_code": db.query(RuntimeTraceProjection.last_error_code).filter(
            RuntimeTraceProjection.task_run_id.in_(run_ids),
            RuntimeTraceProjection.last_error_code.is_not(None),
        ).order_by(RuntimeTraceProjection.updated_at.desc(), RuntimeTraceProjection.id.desc()).limit(1).scalar()
        if run_ids else None,
    }


def projection_status_by_source(
    db: Session, sources: list[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    predicates = [and_(RuntimeTraceProjection.source_type == source_type,
                       RuntimeTraceProjection.source_key == source_key)
                  for source_type, source_key in sources]
    rows = db.query(RuntimeTraceProjection.source_type, RuntimeTraceProjection.source_key,
                    RuntimeTraceProjection.status).filter(or_(*predicates)).all() if predicates else []
    return {(source_type, source_key): status for source_type, source_key, status in rows}


def replay_run(db: Session, *, task_id: int, run_ids: list[int], root_id: int) -> dict[str, int]:
    """Register missing historical facts and requeue terminal failures without duplicating outbox rows."""
    calls = db.query(RuntimeCallFact).filter(
        RuntimeCallFact.task_id == task_id,
        or_(RuntimeCallFact.execution_root_run_id == root_id, RuntimeCallFact.task_run_id.in_(run_ids)),
        RuntimeCallFact.trace_id.is_not(None),
    ).all()
    events = db.query(RuntimeEventFact).filter(
        RuntimeEventFact.task_id == task_id,
        or_(RuntimeEventFact.execution_root_run_id == root_id, RuntimeEventFact.task_run_id.in_(run_ids)),
        RuntimeEventFact.trace_id.is_not(None),
    ).all()
    agent_attempts = db.query(TaskAttempt, TaskWorkItem, TaskRun).join(
        TaskWorkItem, TaskWorkItem.id == TaskAttempt.work_item_id,
    ).join(TaskRun, TaskRun.id == TaskWorkItem.task_run_id).filter(
        TaskRun.task_id == task_id, TaskRun.id.in_(run_ids), TaskRun.trace_id.is_not(None),
    ).all()
    task = db.get(Task, task_id)
    for fact in calls:
        enqueue_projection(
            db, source_type="MODEL_CALL", source_key=fact.call_id, project_id=fact.project_id,
            task_id=fact.task_id, task_run_id=fact.task_run_id, execution_root_run_id=fact.execution_root_run_id,
            trace_id=fact.trace_id, span_id=fact.span_id,
        )
    for fact in events:
        enqueue_projection(
            db, source_type="RUNTIME_EVENT", source_key=fact.event_id, project_id=fact.project_id,
            task_id=fact.task_id, task_run_id=fact.task_run_id,
            execution_root_run_id=fact.execution_root_run_id or fact.task_run_id,
            trace_id=fact.trace_id, span_id=fact.span_id,
        )
    if task is not None:
        for attempt, work, source_run in agent_attempts:
            checkpoint = attempt.checkpoint_json if isinstance(attempt.checkpoint_json, dict) else {}
            enqueue_projection(
                db, source_type="AGENT_ATTEMPT", source_key=str(attempt.id), project_id=task.project_id,
                task_id=task.id, task_run_id=source_run.id,
                execution_root_run_id=source_run.execution_root_run_id or source_run.id,
                trace_id=source_run.trace_id, span_id=checkpoint.get("agent_span_id"),
            )
    keys = [projection_key("MODEL_CALL", fact.call_id) for fact in calls]
    keys.extend(projection_key("RUNTIME_EVENT", fact.event_id) for fact in events)
    keys.extend(projection_key("AGENT_ATTEMPT", str(attempt.id)) for attempt, _, _ in agent_attempts)
    db.flush()
    rows = db.query(RuntimeTraceProjection).filter(RuntimeTraceProjection.projection_key.in_(keys)).all() if keys else []
    replayed = 0
    for row in rows:
        if row.status == "FAILED":
            row.status = "PENDING"
            row.attempt_count = 0
            row.next_attempt_at = datetime.now()
            row.last_error_code = None
            row.lease_owner = None
            row.lease_expires_at = None
            replayed += 1
    db.commit()
    return {"registered": len(rows), "requeued": replayed}
