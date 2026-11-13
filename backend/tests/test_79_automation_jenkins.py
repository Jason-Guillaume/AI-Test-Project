"""Jenkins Remote API client and unified automation lifecycle tests."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import settings
from app.core.database.session import SessionLocal
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
from app.features.automation_center.providers.jenkins_provider import JenkinsProvider
from app.features.automation_center.services.center_service import AutomationCenterService, sign_callback
from app.features.automation_center.validation import validate_pipeline_parameters
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
    assert callback.normalize_status("SUCCESS", "SUCCESS") == "SUCCESS"
    assert callback.normalize_status("FAILED", "SUCCESS") == "FAILED"
    assert callback.normalize_status("SUCCESS", "ABORTED") == "FAILED"
    assert callback.normalize_status("TIMEOUT", "ABORTED") == "TIMEOUT"
    assert callback.normalize_status("CANCELLED", "FAILURE") == "CANCELLED"
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


def test_runner_persists_live_log_and_callback_bounds_large_log(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("automation_run_tests_log", root / "scripts/automation_run_tests.py")
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.chdir(tmp_path)

    class FinishedProcess:
        stdout = BytesIO(b"pytest started\nFAILED test_example.py\n")

        @staticmethod
        def wait():
            return 1

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: FinishedProcess())
    assert runner.main() == 1
    assert "FAILED test_example.py" in (tmp_path / "run.log").read_text()

    callback_spec = importlib.util.spec_from_file_location("automation_callback_log", root / "scripts/automation_callback.py")
    assert callback_spec and callback_spec.loader
    callback = importlib.util.module_from_spec(callback_spec)
    callback_spec.loader.exec_module(callback)
    valid_report = tmp_path / "report.zip"
    valid_report.write_bytes(_allure_zip())
    invalid_report = tmp_path / "partial-report.zip"
    invalid_report.write_bytes(b"not a complete report")
    assert callback._valid_report_archive(valid_report) is True
    assert callback._valid_report_archive(invalid_report) is False
    large_log = tmp_path / "large.log"
    large_log.write_bytes(b"a" * (callback.MAX_LOG_BYTES + 100) + b"tail")
    body, _content_type = callback._multipart({}, [("log", large_log)])
    assert len(body) < callback.MAX_LOG_BYTES + 1000
    assert callback._read_tail(large_log, 4) == b"tail"


def test_callback_retries_transient_failures_with_a_fixed_attempt_limit(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("automation_callback_retries", root / "scripts/automation_callback.py")
    assert spec and spec.loader
    callback = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(callback)
    waits = []
    monkeypatch.setattr(callback.time, "sleep", waits.append)
    attempts = 0

    def transient_then_success(_request, *, timeout=20):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise callback.urllib.error.URLError(TimeoutError("temporary timeout"))
        return b"ok"

    monkeypatch.setattr(callback, "open_request", transient_then_success)
    assert callback.retry_request(lambda: object()) == b"ok"
    assert attempts == 3
    assert len(waits) == 2

    attempts = 0

    def always_times_out(_request, *, timeout=20):
        nonlocal attempts
        attempts += 1
        raise callback.urllib.error.URLError(TimeoutError("timeout"))

    monkeypatch.setattr(callback, "open_request", always_times_out)
    with pytest.raises(RuntimeError, match="4 次尝试"):
        callback.retry_request(lambda: object())
    assert attempts == callback.RETRIES == 4


def test_callback_aborted_status_preserves_explicit_cancel_intent():
    execution = SimpleNamespace(
        provider_type="JENKINS", branch="", environment_name="", git_commit="", log_excerpt="",
        duration_ms=None, started_at=None, external_build_number=None, external_run_url="",
        external_status="", stop_reason=None, stop_requested_at=datetime.now(), status="RUNNING",
        finished_at=None,
    )
    AutomationCenterService()._apply_callback_metadata(
        execution, {"status": "CANCELLED", "jenkins_result": "ABORTED"}, None,
    )
    assert execution.status == "CANCELLED"
    assert execution.external_status == "ABORTED"
    assert execution.stop_requested_at is None

    failed_callback = SimpleNamespace(
        provider_type="JENKINS", branch="", environment_name="", git_commit="", log_excerpt="",
        duration_ms=None, started_at=None, external_build_number=None, external_run_url="",
        external_status="", stop_reason=None, stop_requested_at=None, status="RUNNING", finished_at=None,
    )
    AutomationCenterService()._apply_callback_metadata(
        failed_callback, {"status": "FAILED", "jenkins_result": "SUCCESS"}, None,
    )
    assert failed_callback.status == "FAILED"


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
        self.build_result = "SUCCESS"
        self.discovered_runs: list[ProviderExecution] = []
        self.discovery_barrier: Barrier | None = None

    def test_connection(self, resource_id=None):
        return ProviderConnectionResult(True, "Jenkins 已连接", 1)

    def list_items(self, folder_path=""):
        return [{"name": "suite", "job_path": f"{folder_path}/suite".strip("/"), "url": "", "is_folder": True, "buildable": False, "color": ""}]

    def inspect_job(self, job_path):
        return {"name": "automation", "job_path": job_path, "url": "", "is_folder": False, "buildable": True, "concurrent_build": True, "parameters": [{"name": "BRANCH_NAME"}]}

    def trigger_build(self, resource_id, params):
        self.trigger_count += 1
        return ProviderExecution("JENKINS", queue_id=str(734 + self.trigger_count), status="PENDING", external_status="QUEUED")

    def get_queue_item(self, queue_id, resource_id=None):
        number = int(queue_id) - 716
        return ProviderExecution("JENKINS", queue_id=queue_id, build_number=number,
                                 build_url=f"{JENKINS_URL}/job/folder/job/automation/{number}/",
                                 status="RUNNING", external_status="BUILDING", started_at=datetime.now())

    def get_build(self, resource_id, external_run_id=None, build_number=None):
        status = "SUCCESS" if self.build_result == "SUCCESS" else "FAILED"
        return ProviderExecution(
            "JENKINS", external_run_id=str(build_number), build_number=build_number,
            build_url=f"{JENKINS_URL}/job/folder/job/automation/{build_number}/",
            status=status, external_status=self.build_result, started_at=datetime.now(),
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
        if self.discovery_barrier is not None:
            self.discovery_barrier.wait(timeout=10)
        return self.discovered_runs[:per_page]


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
    callback_again = api.client.post(
        f"{API}/automation-callbacks/{config.callback_key}",
        headers={"X-Automation-Timestamp": timestamp, "X-Automation-Signature": signature, "X-Idempotency-Key": idempotency},
        data={"metadata": metadata}, files={"report": ("report.zip", report_zip, "application/zip")},
    )
    assert callback_again.status_code == 200, callback_again.text
    assert callback_again.json()["duplicate"] is True
    report = db.get(AutomationReport, callback.json()["report_id"])
    report_response = api.get(f"/automation-reports/{report.id}", username=owner)
    assert report_response.status_code == 200, report_response.text
    assert report_response.json()["provider_type"] == "JENKINS"
    assert report_response.json()["build_number"] == 19
    assert report_response.json()["external_run_url"].endswith("/19/")

    queued_again = api.post(f"/automation-projects/{automation_id}/executions", username=owner, json={})
    assert queued_again.status_code == 201, queued_again.text
    provider.build_result = "ABORTED"
    cancelled = api.post(f"/automation-executions/{queued_again.json()['id']}/cancel", username=owner)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "PENDING"
    assert cancelled.json()["stop_requested"] is True
    assert provider.stopped[-1]["queue_id"] == "736"
    confirmed = api.post(f"/automation-executions/{queued_again.json()['id']}/sync", username=owner)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CANCELLED"
    assert confirmed.json()["stop_requested"] is False

    timed_out_run = api.post(f"/automation-projects/{automation_id}/executions", username=owner, json={})
    assert timed_out_run.status_code == 201, timed_out_run.text
    timeout_row = db.get(AutomationExecution, timed_out_run.json()["id"])
    timeout_row.timeout_at = datetime.now() - timedelta(seconds=1)
    db.commit()
    timed_out = api.post(f"/automation-executions/{timeout_row.id}/sync", username=owner)
    assert timed_out.status_code == 200, timed_out.text
    assert timed_out.json()["status"] == "TIMEOUT"
    assert timed_out.json()["stop_requested"] is True
    confirmed_timeout = api.post(f"/automation-executions/{timeout_row.id}/sync", username=owner)
    assert confirmed_timeout.status_code == 200, confirmed_timeout.text
    assert confirmed_timeout.json()["status"] == "TIMEOUT"
    assert confirmed_timeout.json()["stop_requested"] is False


def test_jenkins_parameter_contract_and_platform_owned_values():
    """Reject reserved/case-conflicting values and retain safe custom Job variables."""
    assert validate_pipeline_parameters({"TEST_SUITE": "smoke"}, reject_reserved=True) == {"TEST_SUITE": "smoke"}
    for invalid in (
        {"automation_execution_id": "spoof"},
        {"path": "/tmp/attacker-bin"},
        {"SUITE": "one", "suite": "two"},
        {"bad-name": "value"},
        {"SUITE": "smoke; touch /tmp/pwned"},
        {"SUITE": "x" * 2001},
        {"SUITE": 3},
        {f"PARAM_{index}": "value" for index in range(51)},
    ):
        with pytest.raises(ValueError):
            validate_pipeline_parameters(invalid, reject_reserved=True)
    assert validate_pipeline_parameters(None) == {}

    class CaptureClient:
        parameters = None

        @staticmethod
        def validate_parameters(parameters):
            return JenkinsClient.validate_parameters(parameters)

        def trigger_build(self, _resource_id, parameters):
            self.parameters = parameters
            return "987"

    capture = CaptureClient()
    provider = JenkinsProvider(capture)
    result = provider.trigger_build("folder/job", {
        "branch": "main", "environment_name": "qa", "pytest_args": "-q",
        "execution_id": 7, "automation_project_id": 4, "callback_key": "key",
        "callback_url": "https://platform.example/api/callback", "history_url": "https://platform.example/history",
        "repository_url": "https://codeup.aliyun.com/team/repo.git", "repository_id": "repo-1",
        "timeout_seconds": 61, "variables": {"TEST_SUITE": "smoke", "DEPLOY_TOKEN": "private"},
    })
    assert result.queue_id == "987"
    assert capture.parameters["TEST_SUITE"] == "smoke"
    assert capture.parameters["AUTOMATION_EXECUTION_ID"] == "7"
    assert capture.parameters["BUILD_TIMEOUT_MINUTES"] == "2"
    assert "DEPLOY_TOKEN" not in capture.parameters
    with pytest.raises(Exception, match="保留参数"):
        provider.trigger_build("folder/job", {
            "execution_id": 7, "automation_project_id": 4, "timeout_seconds": 3600,
            "variables": {"automation_execution_id": "spoof"},
        })
    with pytest.raises(Exception, match="超时必须是整数"):
        provider.trigger_build("folder/job", {
            "execution_id": 7, "automation_project_id": 4, "timeout_seconds": "invalid",
        })


def test_jenkins_queue_404_recovers_only_exact_queue_id():
    """A missing Queue item matches a Build only by its recorded Queue ID."""
    def handler(request: httpx.Request) -> httpx.Response:
        if "/queue/item/735/" in request.url.path:
            return httpx.Response(404, request=request)
        if request.url.path.endswith("/19/api/json"):
            return httpx.Response(200, json={
                "number": 19, "queueId": 735, "building": True, "result": None,
                "timestamp": 1_800_000_000_000, "duration": 10, "url": f"{JENKINS_URL}/job/folder/job/automation/19/",
            }, request=request)
        if "/queue/item/999/" in request.url.path:
            return httpx.Response(404, request=request)
        if request.url.path.endswith("/api/json"):
            return httpx.Response(200, json={"builds": [
                {"number": 19, "queueId": 735}, {"number": 18, "queueId": 734},
            ]}, request=request)
        raise AssertionError(f"unexpected Jenkins request {request.url}")

    http = _mock_client(handler)
    client = JenkinsClient(JENKINS_URL, "ci-user", API_TOKEN, allow_private_network=True, client=http)
    provider = JenkinsProvider(client)
    try:
        found = provider.get_queue_item("735", "folder/automation")
        assert found is not None and found.build_number == 19
        assert found.external_status == "BUILDING"
        missing = provider.get_queue_item("999", "folder/automation")
        assert missing is not None and missing.external_status == "QUEUE_MISSING"
    finally:
        http.close()


@pytest.mark.parametrize(
    ("raw_result", "building", "expected"),
    [
        (None, True, "RUNNING"),
        ("SUCCESS", False, "SUCCESS"),
        ("FAILURE", False, "FAILED"),
        ("UNSTABLE", False, "FAILED"),
        ("ABORTED", False, "FAILED"),
        (None, False, "FAILED"),
    ],
)
def test_jenkins_build_status_mapping_and_unknown_result(raw_result, building, expected):
    class BuildClient:
        def get_build(self, _resource_id, _build_number):
            return {
                "number": 19, "queueId": 735, "building": building, "result": raw_result,
                "timestamp": 1_800_000_000_000, "duration": 50,
            }

    result = JenkinsProvider(BuildClient()).get_build("folder/automation", build_number=19)
    assert result.status == expected
    assert result.external_status == (raw_result or ("BUILDING" if building else "UNKNOWN"))
    if not building and raw_result is None:
        assert result.error_message == "Jenkins 构建状态未返回结果"


def test_jenkins_provider_close_releases_owned_http_pool():
    client = JenkinsClient("https://1.1.1.1/jenkins", "ci-user", API_TOKEN)
    provider = JenkinsProvider(client)
    assert not client._client.is_closed
    provider.close()
    assert client._client.is_closed


def test_jenkins_platform_trigger_is_updated_not_duplicated_by_discovery(api, db, monkeypatch):
    """Polling discovers the exact Queue/Build identity and updates platform-triggered rows."""
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://platform.example.com")
    owner = unique("jenkins-discovery-owner")
    _register(api, owner)
    project = api.post("/projects", username=owner, json={"name": unique("jenkins-discovery-project")})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    config_response = api.post(f"/projects/{project_id}/automation-integrations", username=owner, json={
        "provider_type": "JENKINS", "name": unique("jenkins-ci"), "jenkins_base_url": JENKINS_URL,
        "jenkins_username": "ci-user", "jenkins_api_token": API_TOKEN,
        "allow_private_network": True, "callback_secret": CALLBACK_SECRET,
    })
    assert config_response.status_code == 201, config_response.text
    config_id = config_response.json()["id"]
    automation = api.post(f"/projects/{project_id}/automation-projects", username=owner, json={
        "integration_config_id": config_id, "name": unique("jenkins-suite"),
        "repository_url": "https://codeup.aliyun.com/org/demo.git", "pipeline_id": "folder/automation",
        "default_branch": "main", "timeout_seconds": 3600,
    })
    assert automation.status_code == 201, automation.text
    automation_id = automation.json()["id"]
    provider = FakeJenkinsProvider()
    monkeypatch.setitem(provider_factory._builders, "JENKINS", lambda _config: provider)
    triggered = api.post(f"/automation-projects/{automation_id}/executions", username=owner, json={})
    assert triggered.status_code == 201, triggered.text
    provider.discovered_runs = [ProviderExecution(
        "JENKINS", external_run_id="19", queue_id="735", build_number=19,
        build_url=f"{JENKINS_URL}/job/folder/job/automation/19/", status="RUNNING",
        external_status="BUILDING", started_at=datetime.now(), trigger_source="EXTERNAL",
    )]
    service = AutomationCenterService()
    service._discover(db)
    service._discover(db)
    db.expire_all()
    rows = db.query(AutomationExecution).filter_by(
        integration_config_id=config_id, provider_type="JENKINS", external_build_number=19,
    ).all()
    assert len(rows) == 1
    assert rows[0].id == triggered.json()["id"]

    provider.discovered_runs = [
        ProviderExecution(
            "JENKINS", external_run_id="20", queue_id="736", build_number=20,
            status="RUNNING", external_status="BUILDING", started_at=datetime.now(),
        ),
        ProviderExecution(
            "JENKINS", external_run_id="21", queue_id="737", build_number=21,
            status="RUNNING", external_status="BUILDING", started_at=datetime.now(),
        ),
    ]
    provider.discovery_barrier = Barrier(2)

    def discover_concurrently():
        with SessionLocal() as session:
            service._discover(session)

    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(lambda _index: discover_concurrently(), range(2)))
    provider.discovery_barrier = None
    db.expire_all()
    for build_number in (20, 21):
        concurrent_rows = db.query(AutomationExecution).filter_by(
            integration_config_id=config_id, provider_type="JENKINS", external_build_number=build_number,
        ).all()
        assert len(concurrent_rows) == 1

    provider.build_result = "ABORTED"
    stop_response = api.post(
        f"/automation-executions/{triggered.json()['id']}/cancel", username=owner,
    )
    assert stop_response.status_code == 200, stop_response.text
    provider.discovered_runs = [ProviderExecution(
        "JENKINS", external_run_id="19", queue_id="735", build_number=19,
        status="FAILED", external_status="ABORTED", started_at=datetime.now(), finished_at=datetime.now(),
    )]
    service._discover(db)
    db.refresh(rows[0])
    assert rows[0].status == "CANCELLED"
