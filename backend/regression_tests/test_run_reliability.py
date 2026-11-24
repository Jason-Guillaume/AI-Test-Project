from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.features.test_management.models.execution import TestRun, CaseExecution
from app.features.test_management.models.test_plan import TestPlan
from app.features.test_management.schemas.executions import TestRunCreateRequest
from app.features.test_management.services.run_service import RunService
import app.features.test_management.services.run_service as runs


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}", connect_args={"check_same_thread": False})
    # SQLite permits unresolved foreign keys when enforcement is off; test only the relevant tables.
    for model in (TestPlan, TestRun, CaseExecution):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(TestPlan(id=1, project_id=1, name='plan', environment_id=1))
        db.commit()
    yield factory
    engine.dispose()


def test_concurrent_retry_reuses_committed_run(database, monkeypatch):
    service = RunService()
    entered, release = Event(), Event()
    calls = []
    def execute(db, run, project_id, cases, environment, actor):
        calls.append(run.id)
        entered.set()
        assert release.wait(5)
        run.status = 'SUCCESS'
        db.commit()
        return runs._response(run)
    monkeypatch.setattr(service, '_execute_existing_run', execute)
    monkeypatch.setattr(runs, 'require_writable_project', lambda *args: None)
    monkeypatch.setattr(runs, 'resolve_plan_project_id', lambda *args: 1)
    monkeypatch.setattr(runs, 'resolve_project_environment', lambda *args: SimpleNamespace(id=1))
    monkeypatch.setattr(service, '_collect_case_ids', lambda *args: [])
    actor = SimpleNamespace(id=7)
    body = TestRunCreateRequest(request_key='same-key')
    def submit():
        with database() as db:
            return service.create_and_execute_run(db, 1, body, actor=actor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit)
        assert entered.wait(5)
        second = pool.submit(submit).result(timeout=5)
        assert second.status == 'RUNNING'
        release.set()
        assert first.result(timeout=5).id == second.id
    assert calls == [second.id]
    with database() as db:
        assert service.create_and_execute_run(db, 1, body, actor=actor).id == second.id
        with pytest.raises(Exception) as exc:
            service.create_and_execute_run(db, 1, TestRunCreateRequest(request_key='same-key', environment_id=2), actor=actor)
        assert exc.value.status_code == 409


def test_pagination_and_direct_execution(database, monkeypatch):
    monkeypatch.setattr(runs, 'get_project_or_404', lambda db, project, user: None)
    service = RunService()
    with database() as db:
        run = TestRun(project_id=1, status='SUCCESS', total=300)
        db.add(run); db.flush()
        db.add_all([CaseExecution(test_run_id=run.id, status='FAILED' if n % 10 == 0 else 'PASSED') for n in range(300)])
        db.commit()
        first = service.list_case_executions(db, run.id, object(), page=1, page_size=20)
        failed = service.list_case_executions(db, run.id, object(), page=2, page_size=20, failed_only=True)
        assert (first.total, len(first.items)) == (300, 20)
        assert (failed.total, len(failed.items)) == (30, 10)
        target = db.query(CaseExecution).order_by(CaseExecution.id).offset(249).first()
        assert service.get_case_execution(db, run.id, target.id, object()).id == target.id
        with pytest.raises(Exception):
            service.get_case_execution(db, run.id + 1, target.id, object())
