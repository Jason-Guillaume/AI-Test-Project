"""Langfuse projection outbox: atomic deduplication, recovery and sensitive-data filtering."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.database.session import SessionLocal
from app.core.models.identity import User
from app.orchestration.tasks.models import (
    RuntimeEventFact,
    RuntimeTraceProjection,
    Task,
    TaskRun,
)
from app.orchestration.tasks.services.trace_projection_service import (
    TraceProjectionWorker,
    enqueue_projection,
    projection_key,
)


class FakeSpan:
    def __init__(self, span_id="recovered-span"):
        self.id = span_id
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class FakeObservation:
    def __init__(self, span):
        self.span = span

    def __enter__(self):
        return self.span

    def __exit__(self, *exc_info):
        return False


class FakeLangfuse:
    def __init__(self, observations=None, flush_error=None):
        self.observations = observations or []
        self.flush_error = flush_error
        self.created = []
        self.span = FakeSpan()
        self.api = SimpleNamespace(observations=SimpleNamespace(get_many=self.get_many))

    def get_many(self, **kwargs):
        return {"data": self.observations}

    def start_as_current_observation(self, **kwargs):
        self.created.append(kwargs)
        return FakeObservation(self.span)

    def flush(self):
        if self.flush_error:
            raise self.flush_error


def _fact(db, api, admin):
    project = api.post("/projects", username=admin, json={"name": f"trace-projection-{datetime.now().timestamp()}"})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    user = db.query(User).filter_by(username=admin).one()
    task = Task(project_id=project_id, created_by=user.id, title="projection", goal="safe test")
    db.add(task)
    db.flush()
    run = TaskRun(task_id=task.id, run_number=1, goal_snapshot="safe test", trace_id="a" * 32)
    db.add(run)
    db.flush()
    run.execution_root_run_id = run.id
    fact = RuntimeEventFact(
        event_id=f"projection-{uuid4().hex}", project_id=project_id, task_id=task.id,
        task_run_id=run.id, execution_root_run_id=run.id, trace_id=run.trace_id,
        event_type="TOOL_CALL", event_name="tool.safe", status="SUCCEEDED", duration_ms=12,
        event_metadata={"tool_call_id": "tool-1", "secret": "must-not-leak"},
    )
    db.add(fact)
    db.flush()
    return task, run, fact


def _projection(db, task, run, fact):
    return enqueue_projection(
        db, source_type="RUNTIME_EVENT", source_key=fact.event_id,
        project_id=task.project_id, task_id=task.id, task_run_id=run.id,
        execution_root_run_id=run.id, trace_id=run.trace_id, span_id=fact.span_id,
    )


@pytest.fixture
def pause_projection_worker(api):
    from app.main import trace_projection_worker

    running = trace_projection_worker._thread is not None and trace_projection_worker._thread.is_alive()
    if running:
        trace_projection_worker.stop()
    yield
    if running:
        trace_projection_worker.start()


def test_task_trace_timeline_returns_projection_status(api, admin, db, pause_projection_worker):
    task, run, fact = _fact(db, api, admin)
    _projection(db, task, run, fact)
    db.commit()

    response = api.get(f"/task-runs/{run.id}/trace", username=admin)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["projection"]["status"] == "PENDING"
    assert payload["projection"]["counts"]["PENDING"] == 1
    tool_event = next(item for item in payload["items"] if item["event_name"] == "tool.safe")
    assert tool_event["projection_status"] == "PENDING"


def test_projection_outbox_deduplicates_and_projects_only_sanitized_fact(api, admin, db, monkeypatch, pause_projection_worker):
    task, run, fact = _fact(db, api, admin)
    first = _projection(db, task, run, fact)
    second = _projection(db, task, run, fact)
    assert first is second
    db.commit()
    row = db.query(RuntimeTraceProjection).filter_by(
        projection_key=projection_key("RUNTIME_EVENT", fact.event_id),
    ).one()
    assert row.status == "PENDING"
    worker = TraceProjectionWorker(db_factory=SessionLocal)
    client = FakeLangfuse()
    monkeypatch.setattr("app.llm.tracing.get_langfuse_client", lambda: client)
    with SessionLocal() as worker_db:
        claimed = worker_db.get(RuntimeTraceProjection, row.id)
        claimed.status = "RETRYING"
        claimed.lease_owner = worker._owner
        claimed.attempt_count = 1
        worker_db.commit()

    worker._deliver(row.id)

    with SessionLocal() as verify:
        projected = verify.get(RuntimeTraceProjection, row.id)
        assert projected.status == "SUCCEEDED"
        assert projected.span_id == "recovered-span"
        assert verify.query(RuntimeTraceProjection).filter_by(source_key=fact.event_id).count() == 1
    assert client.created[0]["trace_context"] == {"trace_id": run.trace_id}
    assert client.created[0]["metadata"]["runtime_projection_key"] == row.projection_key
    assert "secret" not in client.created[0]["metadata"].get("metadata", {})
    assert client.span.updates[0]["output"]["status"] == "SUCCEEDED"


def test_expired_projection_lease_reconciles_before_retrying_delivery(api, admin, db, monkeypatch, pause_projection_worker):
    task, run, fact = _fact(db, api, admin)
    row = _projection(db, task, run, fact)
    db.flush()
    row.status = "RETRYING"
    row.attempt_count = 2
    row.lease_owner = "crashed-worker"
    row.lease_expires_at = datetime.now() - timedelta(seconds=1)
    row.last_delivery_at = datetime.now() - timedelta(minutes=16)
    db.commit()
    worker = TraceProjectionWorker(db_factory=SessionLocal)
    client = FakeLangfuse(observations=[{
        "id": "recovered-span", "metadata": {"runtime_projection_key": row.projection_key},
    }])
    monkeypatch.setattr("app.llm.tracing.get_langfuse_client", lambda: client)
    with SessionLocal() as worker_db:
        reclaimed = worker_db.get(RuntimeTraceProjection, row.id)
        reclaimed.lease_owner = worker._owner
        worker_db.commit()

    worker._deliver(row.id)

    with SessionLocal() as verify:
        assert verify.get(RuntimeTraceProjection, row.id).status == "SUCCEEDED"
    assert client.created == []


def test_langfuse_failure_is_retryable_and_does_not_change_runtime_fact(api, admin, db, monkeypatch, pause_projection_worker):
    task, run, fact = _fact(db, api, admin)
    row = _projection(db, task, run, fact)
    db.flush()
    row.status = "RETRYING"
    worker = TraceProjectionWorker(db_factory=SessionLocal)
    row.lease_owner = worker._owner
    row.attempt_count = 1
    db.commit()
    monkeypatch.setattr(
        "app.llm.tracing.get_langfuse_client",
        lambda: FakeLangfuse(flush_error=TimeoutError()),
    )

    worker._deliver(row.id)

    with SessionLocal() as verify:
        assert verify.get(RuntimeTraceProjection, row.id).status == "PENDING"
        assert verify.query(RuntimeEventFact).filter_by(event_id=fact.event_id).one().status == "SUCCEEDED"
