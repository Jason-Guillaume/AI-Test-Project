"""Dagu OpenAPI v2.26.0 对齐、DNS 固定防重绑定与执行生命周期加固测试。"""
from __future__ import annotations

import socket
from datetime import datetime, timedelta

import httpx
import pytest

from app.core.config import settings
from app.features.automation_center.models.entities import AutomationExecution
from app.features.automation_center.providers.base import ProviderError
from app.features.automation_center.providers.dagu_client import DaguClient, _PinnedSyncBackend
from app.features.automation_center.providers.dagu_provider import DaguProvider
from app.features.automation_center.providers.factory import provider_factory
from app.features.automation_center.providers.status import map_external_status
from app.features.automation_center.services.center_service import AutomationCenterService
from tests.conftest import unique


def test_map_external_status_supports_all_dagu_v226_labels():
    assert map_external_status({"statusLabel": "not_started"}) == "PENDING"
    assert map_external_status({"statusLabel": "queued"}) == "PENDING"
    assert map_external_status({"statusLabel": "waiting"}) == "PENDING"
    assert map_external_status({"statusLabel": "running"}) == "RUNNING"
    assert map_external_status({"statusLabel": "succeeded"}) == "SUCCESS"
    assert map_external_status({"statusLabel": "failed"}) == "FAILED"
    assert map_external_status({"statusLabel": "rejected"}) == "FAILED"
    assert map_external_status({"statusLabel": "partially_succeeded"}) == "FAILED"
    assert map_external_status({"statusLabel": "aborted"}) == "FAILED"


def test_dagu_list_runs_passes_limit_and_follows_next_cursor():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        cursor = request.url.params.get("cursor")
        if not cursor:
            return httpx.Response(
                200,
                json={
                    "dagRuns": [{"dagRunId": f"r-{i}"} for i in range(100)],
                    "gridData": [],
                    "nextCursor": "page-2-cursor",
                },
            )
        return httpx.Response(
            200,
            json={
                "dagRuns": [{"dagRunId": f"r-{i}"} for i in range(100, 125)],
                "gridData": [],
                "nextCursor": "",
            },
        )

    client = DaguClient(
        "https://dagu.example.com",
        "dagu-test-key-1234",
        transport=httpx.MockTransport(handler),
    )
    runs = client.list_runs("nightly.yaml", limit=110)

    assert len(runs) == 110
    assert seen[0] == ("/api/v1/dags/nightly.yaml/dag-runs", {"limit": "100"})
    assert seen[1] == ("/api/v1/dags/nightly.yaml/dag-runs", {"limit": "10", "cursor": "page-2-cursor"})


def test_pinned_sync_backend_blocks_dns_rebinding_before_tcp_connect(monkeypatch):
    monkeypatch.setattr(settings, "DAGU_PRIVATE_HOST_ALLOWLIST", "")
    call_count = 0

    def rebinding_resolver(_host, _port):
        nonlocal call_count
        call_count += 1
        # Simulate resolution flip to loopback/metadata IP when TCP socket connects.
        if call_count == 1:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    client = DaguClient(
        "https://dagu.example.com",
        "dagu-test-key-1234",
        resolver=rebinding_resolver,
    )
    with pytest.raises(ProviderError, match="未授权的内网或保留地址"):
        client.get_health()
    client.close()


def test_pinned_sync_backend_directly_rejects_private_ip_without_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "DAGU_PRIVATE_HOST_ALLOWLIST", "")
    backend = _PinnedSyncBackend(
        expected_host="evil.example.com",
        resolver=lambda _h, _p: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))],
    )
    with pytest.raises(Exception, match="未授权的内网或保留地址"):
        backend.connect_tcp("evil.example.com", 443)


def test_provider_handles_not_started_waiting_stop_and_openapi_404():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/openapi.json":
            return httpx.Response(404, json={"message": "disabled"})
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "healthy", "version": "2.26.0"})
        if request.url.path == "/api/v1/dags":
            return httpx.Response(200, json={"dags": [{"fileName": "smoke.yaml"}], "pagination": {"hasNextPage": False}})
        if request.url.path.endswith("/dag-runs/smoke.yaml/run-wait"):
            return httpx.Response(200, json={"dagRunId": "run-wait", "statusLabel": "waiting"})
        if request.url.path.endswith("/dag-runs/smoke.yaml/run-init"):
            return httpx.Response(200, json={"dagRunId": "run-init", "statusLabel": "not_started"})
        if request.url.path.endswith("/stop") or request.url.path.endswith("/dequeue"):
            return httpx.Response(200, json={})
        return httpx.Response(404, json={})

    client = DaguClient(
        "https://dagu.example.com",
        "dagu-test-key-1234",
        transport=httpx.MockTransport(handler),
    )
    provider = DaguProvider(client)

    conn = provider.test_connection()
    assert conn.ok is True
    assert conn.service_version == "2.26.0"

    assert provider.stop_run("smoke.yaml", "run-wait") is True
    assert ("POST", "/api/v1/dag-runs/smoke.yaml/run-wait/stop") in calls

    assert provider.stop_run("smoke.yaml", "run-init") is True
    assert ("GET", "/api/v1/dag-runs/smoke.yaml/run-init/dequeue") in calls


def test_dispatch_timeout_and_cancel_preserve_intent_in_center_service(api, db, admin, monkeypatch):
    class TrackingClient:
        def __init__(self):
            self.stopped = []
            self.dequeued = []
            self.run_state = {"dagRunId": "automation-pending", "statusLabel": "running"}

        def close(self):
            pass

        def get_openapi(self):
            return {"info": {"version": "2.26.0"}}

        def get_health(self):
            return {"version": "2.26.0"}

        def list_dags(self):
            return [{"fileName": "automation-pytest-allure", "description": "Smoke"}]

        def get_dag_spec(self, name):
            return {"name": name}

        def list_runs(self, _name, *, limit=10):
            return []

        def enqueue(self, name, params, dag_run_id, queue):
            raise ProviderError("Dagu API 请求超时")

        def get_run(self, _name, _run_id):
            return dict(self.run_state, dagRunId=_run_id)

        def stop(self, name, run_id):
            self.stopped.append((name, run_id))

        def dequeue(self, name, run_id):
            self.dequeued.append((name, run_id))

    fake_client = TrackingClient()
    monkeypatch.setitem(provider_factory._builders, "DAGU", lambda _config: DaguProvider(fake_client))
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://platform.example.com")

    proj = api.post("/projects", username=admin, json={"name": unique("dagu-remed-p")}).json()
    integration = api.post(
        f"/projects/{proj['id']}/automation-integrations",
        username=admin,
        json={
            "provider_type": "DAGU",
            "name": unique("dagu-cfg"),
            "dagu_base_url": "https://dagu.example.com",
            "dagu_api_key": "dagu-secret-key-9999",
            "callback_secret": "cb-secret-9999",
        },
    )
    assert integration.status_code == 201, integration.text
    auto_proj = api.post(
        f"/projects/{proj['id']}/automation-projects",
        username=admin,
        json={
            "integration_config_id": integration.json()["id"],
            "name": unique("auto-proj"),
            "repository_url": "https://codeup.aliyun.com/acme/repo.git",
            "pipeline_id": "automation-pytest-allure",
            "default_branch": "main",
            "default_environment": "test",
            "timeout_seconds": 120,
        },
    )
    assert auto_proj.status_code == 201, auto_proj.text

    # Case 1: Uncertain timeout on trigger keeps PENDING dispatch, then expires to TIMEOUT once timeout_at passes.
    # Make get_run return 404 initially so trigger stays dispatch_state='PENDING' cleanly.
    def not_found_get_run(_name, _run_id):
        raise ProviderError("Dagu DAG 或运行实例不存在", 404)

    fake_client.get_run = not_found_get_run
    trig_pending = api.post(f"/automation-projects/{auto_proj.json()['id']}/executions", username=admin, json={})
    assert trig_pending.status_code == 201, trig_pending.text
    pending_id = trig_pending.json()["id"]

    row_pending = db.get(AutomationExecution, pending_id)
    assert row_pending.dispatch_state == "PENDING"
    assert row_pending.next_dispatch_at > datetime.now()
    service = AutomationCenterService()
    service.poll(db)
    db.refresh(row_pending)
    assert row_pending.dispatch_attempts == 1
    row_pending.timeout_at = datetime.now() - timedelta(minutes=5)
    db.commit()

    service = AutomationCenterService()
    service._dispatch_dagu(db, pending_id)
    db.expire_all()
    refreshed_pending = db.get(AutomationExecution, pending_id)
    assert refreshed_pending.status == "TIMEOUT"
    assert refreshed_pending.dispatch_state == "RECONCILING"
    assert refreshed_pending.stop_requested_at is not None
    assert "远端状态待确认" in refreshed_pending.error_message
    fake_client.get_run = lambda _name, _run_id: {"dagRunId": _run_id, "statusLabel": "running"}
    service._sync_one(db, pending_id, force=True)
    assert refreshed_pending.dispatch_state == "CONFIRMED"
    assert fake_client.stopped[-1][1] == f"automation-{pending_id}"
    fake_client.get_run = lambda _name, _run_id: {"dagRunId": _run_id, "statusLabel": "aborted"}
    service._sync_one(db, pending_id, force=True)
    assert refreshed_pending.status == "TIMEOUT"
    assert refreshed_pending.stop_requested_at is None

    # Case 2: Cancelled run stays stop_reason='CANCELLED' even if timeout_at passes before Dagu finishes stopping.
    fake_client.get_run = lambda _name, _run_id: {"dagRunId": _run_id, "statusLabel": "running"}
    fake_client.enqueue = lambda name, params, dag_run_id, queue: {"dagRunId": dag_run_id, "statusLabel": "queued"}
    trig_cancel = api.post(f"/automation-projects/{auto_proj.json()['id']}/executions", username=admin, json={})
    assert trig_cancel.status_code == 201, trig_cancel.text
    cancel_id = trig_cancel.json()["id"]

    assert api.post(f"/automation-executions/{cancel_id}/cancel", username=admin).status_code == 200
    row_cancel = db.get(AutomationExecution, cancel_id)
    row_cancel.timeout_at = datetime.now() - timedelta(seconds=5)
    row_cancel.last_sync_at = datetime.now() - timedelta(minutes=1)
    db.commit()

    service._sync_one(db, cancel_id, force=True)
    db.expire_all()
    refreshed_cancel = db.get(AutomationExecution, cancel_id)
    assert refreshed_cancel.stop_reason == "CANCELLED"
    assert refreshed_cancel.status != "TIMEOUT"


def test_poll_dispatches_due_run_behind_twenty_backed_off_runs(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite://")
    AutomationExecution.__table__.create(engine)
    now = datetime.now()
    with Session(engine) as db:
        for index in range(21):
            db.add(AutomationExecution(
                project_id=1, automation_project_id=1, provider_type="DAGU",
                dispatch_state="PENDING", status="PENDING", pipeline_run_id=f"automation-{index + 1}",
                next_dispatch_at=now + timedelta(minutes=1) if index < 20 else None,
            ))
        db.commit()
        service = AutomationCenterService()
        dispatched = []
        monkeypatch.setattr(service, "_dispatch_dagu", lambda _db, run_id: dispatched.append(run_id))
        monkeypatch.setattr(service, "_discover", lambda _db: None)
        service.poll(db)
        assert dispatched == [21]
    engine.dispose()
