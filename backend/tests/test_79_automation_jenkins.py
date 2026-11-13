"""Jenkins Remote API client and unified automation lifecycle tests."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import time
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.core.models.project import ProjectMember
from app.core.security.crypto import decrypt_secret
from app.features.automation_center.models.entities import (
    AutomationExecution,
    AutomationIntegrationConfig,
    AutomationJenkinsCredential,
    AutomationReport,
)
from app.features.automation_center.providers.base import ProviderConnectionResult, ProviderExecution
from app.features.automation_center.providers.factory import provider_factory
from app.features.automation_center.providers.jenkins_client import JenkinsClient
from app.features.automation_center.services.center_service import sign_callback
from tests.conftest import unique

API = "/api/v1"
CALLBACK_SECRET = "jenkins-callback-secret"
API_TOKEN = "jenkins-api-token-value"
JENKINS_URL = "https://192.168.20.10:8443/jenkins"


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), auth=("ci-user", API_TOKEN))


def test_jenkins_client_auth_job_build_queue_and_console():
    """Exercise authenticated Remote API calls, nested folders, queue IDs and bounded logs."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["authorization"] == "Basic " + base64.b64encode(f"ci-user:{API_TOKEN}".encode()).decode()
        if request.url.path.endswith("/whoAmI/api/json"):
            return httpx.Response(200, json={"name": "ci-user", "authenticated": True}, request=request)
        if "/queue/item/735/" in request.url.path:
            return httpx.Response(200, json={"id": 735, "executable": {"number": 19, "url": f"{JENKINS_URL}/job/folder/job/automation-test/19/"}}, request=request)
        if request.url.path.endswith("/api/json") and request.method == "GET":
            return httpx.Response(200, json={
                "name": "automation-test", "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
                "buildable": True,
                "property": [{"parameterDefinitions": [{"name": "BRANCH_NAME"}, {"name": "TEST_ENV"}]}],
                "builds": [],
            }, request=request)
        if request.method == "POST":
            return httpx.Response(201, headers={"Location": f"{JENKINS_URL}/queue/item/735/"}, request=request)
        if request.url.path.endswith("/consoleText"):
            return httpx.Response(200, content=b"123456789", request=request)
        raise AssertionError(f"unexpected Jenkins request: {request.method} {request.url}")

    http = _mock_client(handler)
    client = JenkinsClient(JENKINS_URL, "ci-user", API_TOKEN, allow_private_network=True, client=http)
    try:
        assert client.test_connection()["name"] == "ci-user"
        job = client.get_item("folder/automation-test")
        assert job["buildable"] is True
        queue_id = client.trigger_build("folder/automation-test", {"BRANCH_NAME": "main", "TEST_ENV": "qa"})
        assert queue_id == "735"
        queued = client.get_queue_item(queue_id)
        assert queued["executable"]["number"] == 19
        assert client.get_console_log("folder/automation-test", 19, max_bytes=6) == "456789"
        assert all(request.url.host == "192.168.20.10" for request in calls)
        assert any(request.url.path.endswith("/job/folder/job/automation-test/buildWithParameters") for request in calls)
    finally:
        http.close()


def test_jenkins_client_security_checks_and_crumb_retry():
    """Reject insecure targets and external redirects; acquire a crumb only after 403."""
    with pytest.raises(Exception, match="HTTPS"):
        JenkinsClient("http://192.168.20.10:8080", "user", API_TOKEN, allow_private_network=True)
    with pytest.raises(Exception, match="管理员明确授权"):
        JenkinsClient.validate_base_url("https://192.168.20.10:8443/jenkins")
    with pytest.raises(Exception, match="Job 路径不合法"):
        JenkinsClient.validate_job_path("folder/../job")

    post_count = 0
    crumb_headers: list[str | None] = []

    def crumb_handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.url.path.endswith("/crumbIssuer/api/json"):
            return httpx.Response(200, json={"crumbRequestField": "Jenkins-Crumb", "crumb": "crumb-value"}, request=request)
        if request.method == "POST":
            post_count += 1
            crumb_headers.append(request.headers.get("Jenkins-Crumb"))
            return httpx.Response(403 if post_count == 1 else 201, headers={"Location": f"{JENKINS_URL}/queue/item/2/"}, request=request)
        if request.url.path.endswith("/api/json"):
            return httpx.Response(200, json={"name": "job", "_class": "WorkflowJob", "buildable": True, "property": []}, request=request)
        raise AssertionError(request.url)

    http = _mock_client(crumb_handler)
    client = JenkinsClient(JENKINS_URL, "ci-user", API_TOKEN, allow_private_network=True, client=http)
    try:
        assert client.trigger_build("job") == "2"
        assert crumb_headers == [None, "crumb-value"]
    finally:
        http.close()


def test_callback_signing_and_runner_argument_allowlist():
    """The stdlib helper matches the live callback HMAC and rejects shell-style pytest flags."""
    root = Path(__file__).resolve().parents[2]
    callback_spec = importlib.util.spec_from_file_location("automation_callback", root / "scripts/automation_callback.py")
    runner_spec = importlib.util.spec_from_file_location("automation_run_tests", root / "scripts/automation_run_tests.py")
    assert callback_spec and callback_spec.loader and runner_spec and runner_spec.loader
    callback = importlib.util.module_from_spec(callback_spec)
    runner = importlib.util.module_from_spec(runner_spec)
    callback_spec.loader.exec_module(callback)
    runner_spec.loader.exec_module(runner)

    report = b"allure-report"
    metadata = '{"execution_id":7}'
    headers = callback.signed_headers(CALLBACK_SECRET, "callback-key", "jenkins:job:7", report, metadata)
    expected = sign_callback(
        CALLBACK_SECRET, headers["X-Automation-Timestamp"], "callback-key", "jenkins:job:7",
        hashlib.sha256(report).hexdigest(), hashlib.sha256(metadata.encode()).hexdigest(),
    )
    assert headers["X-Automation-Signature"] == expected
    command = runner.build_command(Path("/workspace/repository"), {
        "PYTEST_ARGS": "-q --maxfail=2", "TEST_TAGS": "smoke and not slow", "TEST_SCOPE": "tests/smoke",
    })
    assert "--alluredir=allure-results" in command
    assert "tests/smoke" in command
    with pytest.raises(ValueError, match="不在允许列表"):
        runner.build_command(Path("/workspace/repository"), {"PYTEST_ARGS": "--junitxml=/tmp/result.xml"})
    with pytest.raises(ValueError, match="仓库目录内"):
        runner.build_command(Path("/workspace/repository"), {"TEST_SCOPE": "../outside"})

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://attacker.example/collect"}, request=request)

    http = _mock_client(redirect_handler)
    client = JenkinsClient(JENKINS_URL, "ci-user", API_TOKEN, allow_private_network=True, client=http)
    try:
        with pytest.raises(Exception, match="不可信的重定向目标"):
            client.test_connection()
    finally:
        http.close()


def _register(api, username: str) -> int:
    registered = api.register(username)
    assert registered.status_code == 201, registered.text
    api.login(username)
    return registered.json()["user"]["id"]


def _allure_zip() -> bytes:
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("index.html", "<html>allure</html>")
        archive.writestr("widgets/summary.json", json.dumps({"statistic": {
            "total": 1, "passed": 1, "failed": 0, "broken": 0, "skipped": 0, "unknown": 0,
        }}))
        archive.writestr("widgets/suites.json", "{\"items\": []}")
    return payload.getvalue()


class FakeJenkinsProvider:
    provider_type = "JENKINS"

    def __init__(self):
        self.stopped: list[dict] = []
        self.trigger_count = 0

    def test_connection(self, resource_id=None):
        return ProviderConnectionResult(True, "Jenkins 已连接", 1)

    def list_items(self, folder_path=""):
        return [{"name": "suite", "job_path": f"{folder_path}/suite".strip("/"), "url": "", "is_folder": True, "buildable": False, "color": ""}]

    def inspect_job(self, job_path):
        return {"name": "automation", "job_path": job_path, "url": "", "is_folder": False, "buildable": True, "concurrent_build": True, "parameters": [{"name": "BRANCH_NAME"}]}

    def trigger_build(self, resource_id, params):
        self.trigger_count += 1
        return ProviderExecution("JENKINS", queue_id=str(734 + self.trigger_count), status="PENDING", external_status="QUEUED")

    def get_queue_item(self, queue_id):
        number = int(queue_id) - 716
        return ProviderExecution("JENKINS", queue_id=queue_id, build_number=number,
                                 build_url=f"{JENKINS_URL}/job/folder/job/automation/{number}/",
                                 status="RUNNING", external_status="BUILDING", started_at=datetime.now())

    def get_build(self, resource_id, external_run_id=None, build_number=None):
        return ProviderExecution(
            "JENKINS", external_run_id=str(build_number), build_number=build_number,
            build_url=f"{JENKINS_URL}/job/folder/job/automation/{build_number}/",
            status="SUCCESS", external_status="SUCCESS", started_at=datetime.now(),
            finished_at=datetime.now(), duration_ms=3210, raw={"git_commit": "abc123"},
        )

    def stop_build(self, resource_id, external_run_id=None, *, queue_id=None, build_number=None):
        self.stopped.append({"queue_id": queue_id, "build_number": build_number})
        return True

    def get_console_log(self, resource_id, external_run_id=None, build_number=None, *, max_bytes=200_000):
        return f"token=pt-secret-value {CALLBACK_SECRET}"

    def get_build_url(self, resource_id, external_run_id=None, build_number=None):
        return f"{JENKINS_URL}/job/folder/job/automation/{build_number}/"

    def list_runs(self, resource_id, *, per_page=10):
        return []


def test_jenkins_config_lifecycle_and_callback(api, db, monkeypatch, tmp_path):
    """Persist encrypted credentials, enforce admin access, sync Queue/Build and ingest Allure."""
    monkeypatch.setattr(settings, "AUTOMATION_REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://platform.example.com")
    owner = unique("jenkins-owner")
    member = unique("jenkins-member")
    owner_id = _register(api, owner)
    member_id = _register(api, member)
    project = api.post("/projects", username=owner, json={"name": unique("jenkins-project")})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    db.add(ProjectMember(project_id=project_id, user_id=member_id, role="member", created_by=owner_id))
    db.commit()

    body = {
        "provider_type": "JENKINS", "name": "CI Jenkins", "jenkins_base_url": JENKINS_URL,
        "jenkins_username": "ci-user", "jenkins_api_token": API_TOKEN,
        "allow_private_network": True, "callback_secret": CALLBACK_SECRET,
        "default_timeout_seconds": 3600,
    }
    denied = api.post(f"/projects/{project_id}/automation-integrations", username=member, json=body)
    assert denied.status_code == 403, denied.text
    created = api.post(f"/projects/{project_id}/automation-integrations", username=owner, json=body)
    assert created.status_code == 201, created.text
    config_json = created.json()
    assert config_json["provider_type"] == "JENKINS"
    assert config_json["api_token_configured"] is True
    assert API_TOKEN not in json.dumps(config_json)
    assert CALLBACK_SECRET not in json.dumps(config_json)
    config = db.get(AutomationIntegrationConfig, config_json["id"])
    credential = db.get(AutomationJenkinsCredential, config_json["id"])
    assert credential.api_token_encrypted != API_TOKEN
    assert decrypt_secret(credential.api_token_encrypted) == API_TOKEN

    provider = FakeJenkinsProvider()
    monkeypatch.setitem(provider_factory._builders, "JENKINS", lambda _config: provider)
    listed = api.get(f"/automation-integrations/{config.id}/jenkins-jobs", username=owner)
    assert listed.status_code == 200, listed.text
    inspected = api.get(f"/automation-integrations/{config.id}/jenkins-jobs/inspect", username=owner, params={"job_path": "folder/automation"})
    assert inspected.status_code == 200, inspected.text
    tested = api.post(f"/automation-integrations/{config.id}/test-connection", username=owner, params={"pipeline_id": "folder/automation"})
    assert tested.status_code == 200, tested.text

    automation = api.post(f"/projects/{project_id}/automation-projects", username=owner, json={
        "integration_config_id": config.id, "name": "Jenkins suite", "repository_url": "https://codeup.aliyun.com/org/demo.git",
        "pipeline_id": "folder/automation", "default_branch": "main", "default_environment": "qa",
        "pytest_args": "-q", "test_tags": "smoke", "timeout_seconds": 3600,
    })
    assert automation.status_code == 201, automation.text
    automation_id = automation.json()["id"]
    triggered = api.post(f"/automation-projects/{automation_id}/executions", username=owner, json={})
    assert triggered.status_code == 201, triggered.text
    assert triggered.json()["status"] == "PENDING"
    assert triggered.json()["queue_id"] == "735"
    assert triggered.json()["build_number"] is None
    execution_id = triggered.json()["id"]
    synced = api.post(f"/automation-executions/{execution_id}/sync", username=owner)
    assert synced.status_code == 200, synced.text
    assert synced.json()["status"] == "SUCCESS"
    assert synced.json()["build_number"] == 19
    assert synced.json()["external_run_url"].endswith("/19/")
    stored = db.get(AutomationExecution, execution_id)
    assert stored.provider_type == "JENKINS"
    assert stored.integration_config_id == config.id
    assert stored.duration_ms == 3210

    console = api.get(f"/automation-executions/{execution_id}/console-log", username=owner)
    assert console.status_code == 200, console.text
    assert CALLBACK_SECRET not in console.json()["content"]
    assert "pt-secret-value" not in console.json()["content"]

    report_zip = _allure_zip()
    metadata = json.dumps({
        "execution_id": execution_id, "automation_project_id": automation_id,
        "provider_type": "JENKINS", "build_number": 19,
        "build_url": f"{JENKINS_URL}/job/folder/job/automation/19/",
        "status": "SUCCESS", "branch": "main", "environment": "qa", "git_commit": "abc123",
    }, separators=(",", ":"))
    timestamp = str(int(time.time()))
    idempotency = "jenkins:job-19"
    signature = sign_callback(CALLBACK_SECRET, timestamp, config.callback_key, idempotency,
                              hashlib.sha256(report_zip).hexdigest(), hashlib.sha256(metadata.encode()).hexdigest())
    callback = api.client.post(
        f"{API}/automation-callbacks/{config.callback_key}",
        headers={"X-Automation-Timestamp": timestamp, "X-Automation-Signature": signature, "X-Idempotency-Key": idempotency},
        data={"metadata": metadata}, files={"report": ("report.zip", report_zip, "application/zip")},
    )
    assert callback.status_code == 200, callback.text
    report = db.get(AutomationReport, callback.json()["report_id"])
    report_response = api.get(f"/automation-reports/{report.id}", username=owner)
    assert report_response.status_code == 200, report_response.text
    assert report_response.json()["provider_type"] == "JENKINS"
    assert report_response.json()["build_number"] == 19
    assert report_response.json()["external_run_url"].endswith("/19/")

    queued_again = api.post(f"/automation-projects/{automation_id}/executions", username=owner, json={})
    assert queued_again.status_code == 201, queued_again.text
    cancelled = api.post(f"/automation-executions/{queued_again.json()['id']}/cancel", username=owner)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    assert provider.stopped[-1]["queue_id"] == "736"
