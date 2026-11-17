"""Dagu integration, project trigger and cancellation service coverage."""

from __future__ import annotations

import hashlib
import json
import time

from app.core.config import settings
from app.core.models.project import ProjectMember
from app.core.security.crypto import decrypt_secret
from app.features.automation_center.models.entities import AutomationExecution, AutomationIntegrationConfig, AutomationReport
from app.features.automation_center.services.center_service import sign_callback
from app.features.automation_center.providers.dagu_provider import DaguProvider
from app.features.automation_center.providers.factory import provider_factory
from tests.conftest import unique

API = "/api/v1"
CALLBACK_SECRET = "dagu-callback-secret-value"
DAGU_API_KEY = "dagu-private-api-key-value"


class FakeDaguClient:
    """Provide deterministic Dagu responses while exercising the real provider and service."""

    def __init__(self):
        self.enqueued = []
        self.stopped = []
        self.dequeued = []
        self.run = {"dagRunId": "automation-1", "statusLabel": "running"}

    def close(self):
        """Satisfy the Provider lifecycle without opening a network connection."""

    def get_openapi(self):
        """Return an OpenAPI response for connection verification."""
        return {"info": {"version": "2.0.0"}}

    def get_health(self):
        """Return the deployed service version."""
        return {"version": "2.0.1"}

    def list_dags(self):
        """Return the configured pytest DAG."""
        return [{"fileName": "automation-pytest-allure", "description": "pytest + Allure"}]

    def get_dag_spec(self, name):
        """Return an existing DAG spec."""
        return {"name": name}

    def enqueue(self, name, params, run_id, queue):
        """Keep a copy of submitted non-secret Dagu parameters."""
        self.enqueued.append({"name": name, "params": params, "run_id": run_id, "queue": queue})
        self.run = {"dagRunId": run_id, "statusLabel": "queued"}
        return {"dagRunId": run_id, "statusLabel": "queued"}

    def get_run(self, _name, _run_id):
        """Return the mutable fake run state."""
        return dict(self.run)

    def stop(self, name, run_id):
        """Capture a stop request for a running DAG."""
        self.stopped.append((name, run_id))

    def dequeue(self, name, run_id):
        """Capture removal of a queued DAG."""
        self.dequeued.append((name, run_id))

    def get_log(self, _name, _run_id, **_kwargs):
        """Return a safe test log."""
        return "pytest started"

    def list_runs(self, _name, *, limit):
        """Return no historic runs for test setup."""
        return []


def test_dagu_integration_is_encrypted_admin_only_and_public_http_rejected(api, db, admin, monkeypatch):
    """Protect Dagu API configuration and reject the provided public HTTP endpoint."""
    owner = admin
    member = unique("dagu-member")
    assert api.register(member).status_code == 201
    api.login(member)
    project = api.post("/projects", username=owner, json={"name": unique("dagu-project")})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    member_id = api.get("/me", username=member).json()["id"]
    owner_id = api.get("/me", username=owner).json()["id"]
    db.add(ProjectMember(project_id=project_id, user_id=member_id, role="member", created_by=owner_id))
    db.commit()

    payload = {
        "provider_type": "DAGU", "name": unique("Dagu"),
        "dagu_base_url": "https://dagu.example.com/api/v1", "dagu_api_key": DAGU_API_KEY,
        "callback_secret": CALLBACK_SECRET,
    }
    denied = api.post(f"/projects/{project_id}/automation-integrations", username=member, json=payload)
    assert denied.status_code == 403, denied.text
    created = api.post(f"/projects/{project_id}/automation-integrations", username=owner, json=payload)
    assert created.status_code == 201, created.text
    response = created.json()
    assert response["provider_type"] == "DAGU"
    assert response["dagu_api_key_configured"] is True
    assert DAGU_API_KEY not in created.text and CALLBACK_SECRET not in created.text
    stored = db.get(AutomationIntegrationConfig, response["id"])
    assert stored.dagu_api_key_encrypted != DAGU_API_KEY
    assert decrypt_secret(stored.dagu_api_key_encrypted) == DAGU_API_KEY
    assert decrypt_secret(stored.callback_secret_encrypted) == CALLBACK_SECRET
    denied_test = api.post(f"/automation-integrations/{stored.id}/test-connection", username=member)
    denied_dags = api.get(f"/automation-integrations/{stored.id}/dags", username=member)
    assert denied_test.status_code == 403, denied_test.text
    assert denied_dags.status_code == 403, denied_dags.text

    monkeypatch.setattr(settings, "DAGU_ALLOW_INSECURE_HTTP", False)
    insecure = api.post(f"/projects/{project_id}/automation-integrations", username=owner, json={
        **payload, "name": unique("Dagu-http"), "dagu_base_url": "http://gold1.mczbc.cn:45394",
    })
    assert insecure.status_code == 422, insecure.text


def test_dagu_project_trigger_list_cancel_and_manual_sync(api, db, admin, monkeypatch):
    """Exercise the common service lifecycle through the real Dagu adapter."""
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://platform.example.com")
    owner = admin
    project = api.post("/projects", username=owner, json={"name": unique("dagu-project")})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    client = FakeDaguClient()
    monkeypatch.setitem(provider_factory._builders, "DAGU", lambda _config: DaguProvider(client))

    integration = api.post(f"/projects/{project_id}/automation-integrations", username=owner, json={
        "provider_type": "DAGU", "name": unique("Dagu"),
        "dagu_base_url": "https://dagu.example.com", "dagu_api_key": DAGU_API_KEY,
        "callback_secret": CALLBACK_SECRET,
    })
    assert integration.status_code == 201, integration.text
    integration_id = integration.json()["id"]
    test_connection = api.post(f"/automation-integrations/{integration_id}/test-connection", username=owner)
    assert test_connection.status_code == 200, test_connection.text
    assert test_connection.json()["service_version"] == "2.0.1"
    dags = api.get(f"/automation-integrations/{integration_id}/dags", username=owner)
    assert dags.status_code == 200, dags.text
    assert dags.json()["items"] == [{"name": "automation-pytest-allure", "description": "pytest + Allure"}]

    automation = api.post(f"/projects/{project_id}/automation-projects", username=owner, json={
        "integration_config_id": integration_id, "name": unique("pytest-suite"),
        "repository_url": "https://codeup.aliyun.com/66cc480801205f48f8ba4715/testing/site-genius-test-backed.git",
        "pipeline_id": "automation-pytest-allure", "default_branch": "main", "default_environment": "qa",
        "pytest_args": "-q", "test_tags": "smoke", "test_scope": "tests", "timeout_seconds": 3600,
    })
    assert automation.status_code == 201, automation.text
    triggered = api.post(f"/automation-projects/{automation.json()['id']}/executions", username=owner, json={})
    assert triggered.status_code == 201, triggered.text
    execution = triggered.json()
    assert execution["provider_type"] == "DAGU"
    assert execution["pipeline_run_id"] == f"automation-{execution['id']}"
    submitted = client.enqueued[0]
    assert submitted["name"] == "automation-pytest-allure"
    assert submitted["params"]["repository_url"].endswith("site-genius-test-backed.git")
    assert not {"callback_key", "callback_url", "callback_secret", "history_url"} & set(submitted["params"])
    assert DAGU_API_KEY not in str(submitted["params"])

    cancelled = api.post(f"/automation-executions/{execution['id']}/cancel", username=owner)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["stop_requested"] is True
    assert client.dequeued == [("automation-pytest-allure", execution["pipeline_run_id"])]
    client.run = {"dagRunId": execution["pipeline_run_id"], "statusLabel": "aborted"}
    synced = api.post(f"/automation-executions/{execution['id']}/sync", username=owner)
    assert synced.status_code == 200, synced.text
    assert synced.json()["status"] == "CANCELLED"
    assert synced.json()["stop_requested"] is False


def _signed_callback(api, key: str, secret: str, metadata: dict, idempotency: str):
    """按平台 HMAC 契约回传一份不带报告的元数据。"""
    metadata_text = json.dumps(metadata, ensure_ascii=False)
    stamp = str(int(time.time()))
    headers = {
        "X-Automation-Timestamp": stamp,
        "X-Idempotency-Key": idempotency,
        "X-Automation-Signature": sign_callback(
            secret, stamp, key, idempotency,
            hashlib.sha256(b"").hexdigest(),
            hashlib.sha256(metadata_text.encode("utf-8")).hexdigest(),
        ),
        "Content-Type": "application/json",
    }
    return api.client.post(f"{API}/automation-callbacks/{key}", headers=headers, content=metadata_text)


def test_dagu_idempotency_whitelist_and_callback_ownership(api, db, admin, monkeypatch):
    """相同幂等键不重复入队，非白名单 DAG 和跨执行回调都被拒绝。"""
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://platform.example.com")
    owner = admin
    project = api.post("/projects", username=owner, json={"name": unique("dagu-guard")})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    client = FakeDaguClient()
    monkeypatch.setitem(provider_factory._builders, "DAGU", lambda _config: DaguProvider(client))
    integration = api.post(f"/projects/{project_id}/automation-integrations", username=owner, json={
        "provider_type": "DAGU", "name": unique("Dagu-guard"),
        "dagu_base_url": "https://dagu.example.com", "dagu_api_key": DAGU_API_KEY,
        "callback_secret": CALLBACK_SECRET,
    })
    assert integration.status_code == 201, integration.text
    config = integration.json()
    blocked = api.post(f"/projects/{project_id}/automation-projects", username=owner, json={
        "integration_config_id": config["id"], "name": unique("other-dag"),
        "repository_url": "https://codeup.aliyun.com/org/demo.git",
        "pipeline_id": "deploy-production", "default_branch": "main",
    })
    assert blocked.status_code == 400, blocked.text
    automation = api.post(f"/projects/{project_id}/automation-projects", username=owner, json={
        "integration_config_id": config["id"], "name": unique("allowed-dag"),
        "repository_url": "https://codeup.aliyun.com/org/demo.git",
        "pipeline_id": "automation-pytest-allure", "default_branch": "main",
    })
    assert automation.status_code == 201, automation.text
    automation_id = automation.json()["id"]
    first = api.post(
        f"/automation-projects/{automation_id}/executions", username=owner,
        json={"idempotency_key": "run-key-001"},
    )
    assert first.status_code == 201, first.text
    second = api.post(
        f"/automation-projects/{automation_id}/executions", username=owner,
        json={"idempotency_key": "run-key-001"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert len(client.enqueued) == 1
    conflict = api.post(
        f"/automation-projects/{automation_id}/executions", username=owner,
        json={"idempotency_key": "run-key-001", "branch": "other"},
    )
    assert conflict.status_code == 409, conflict.text

    execution = first.json()
    forged = _signed_callback(api, config["callback_key"], CALLBACK_SECRET, {
        "execution_id": execution["id"], "automation_project_id": automation_id,
        "dag_run_id": "automation-forged", "status": "SUCCESS",
        "stats": {"failed": 9, "broken": 0},
    }, "callback-forged")
    assert forged.status_code == 400, forged.text
    db.expire_all()
    stored = db.get(AutomationExecution, execution["id"])
    assert stored.status == "PENDING"
    assert db.query(AutomationReport).filter_by(execution_id=execution["id"]).count() == 0
    accepted = _signed_callback(api, config["callback_key"], CALLBACK_SECRET, {
        "execution_id": execution["id"], "automation_project_id": automation_id,
        "dag_run_id": execution["pipeline_run_id"], "status": "SUCCESS",
    }, "callback-ok")
    assert accepted.status_code == 200, accepted.text
    duplicate = _signed_callback(api, config["callback_key"], CALLBACK_SECRET, {
        "execution_id": execution["id"], "automation_project_id": automation_id,
        "dag_run_id": execution["pipeline_run_id"], "status": "FAILED",
    }, "callback-ok")
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate"] is True
