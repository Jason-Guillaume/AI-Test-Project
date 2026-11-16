"""Dagu callback idempotency and common CI status coverage."""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path


def _callback_module():
    """Load the standard-library callback helper without package-level side effects."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "automation_callback.py"
    spec = importlib.util.spec_from_file_location("automation_callback_dagu_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dagu_upload_uses_stable_run_id_idempotency_and_hmac(tmp_path, monkeypatch):
    """Create one signed callback and bind its idempotency key to Dagu's dagRunId."""
    callback = _callback_module()
    report = tmp_path / "report.zip"
    with zipfile.ZipFile(report, "w") as archive:
        archive.writestr("index.html", "<html>Allure</html>")
    results = tmp_path / "results.zip"
    with zipfile.ZipFile(results, "w") as archive:
        archive.writestr("allure-results/result.json", "{}")
    log_path = tmp_path / "run.log"
    log_path.write_text("pytest finished", encoding="utf-8")

    for key, value in {
        "AUTOMATION_CALLBACK_URL": "https://platform.example.com/api/v1/automation-callbacks/callback-key",
        "AUTOMATION_CALLBACK_ORIGIN": "https://platform.example.com",
        "AUTOMATION_CALLBACK_KEY": "callback-key",
        "AUTOMATION_CALLBACK_SECRET": "callback-secret-value",
        "AUTOMATION_PROJECT_ID": "8",
        "AUTOMATION_EXECUTION_ID": "12",
        "AUTOMATION_PROVIDER_TYPE": "DAGU",
        "DAG_RUN_ID": "automation-12",
        "AUTOMATION_PIPELINE_ID": "automation-pytest-allure",
        "AUTOMATION_STATUS": "SUCCESS",
        "BRANCH_NAME": "main",
        "TEST_ENV": "qa",
        "AUTOMATION_REPORT_ARCHIVE": str(report),
        "AUTOMATION_RESULTS_ARCHIVE": str(results),
        "AUTOMATION_LOG_FILE": str(log_path),
        "AUTOMATION_REPORT_DIR": str(tmp_path / "report-dir"),
        "AUTOMATION_START_MS": "0",
    }.items():
        monkeypatch.setenv(key, value)

    requests = []

    def capture_request(request_factory):
        request = request_factory()
        requests.append(request)
        return b"ok"

    monkeypatch.setattr(callback, "retry_request", capture_request)
    assert callback.upload() == 0
    request = requests[0]
    assert request.get_header("X-idempotency-key") == "dagu:automation-12:report-v1"
    assert request.get_header("X-automation-signature")
    payload = request.data.decode("utf-8", errors="replace")
    metadata = payload.split('name="metadata"\r\n\r\n', 1)[1].split("\r\n", 1)[0]
    parsed = json.loads(metadata)
    assert parsed["provider_type"] == "DAGU"
    assert parsed["dag_run_id"] == "automation-12"
    assert parsed["pipeline_id"] == "automation-pytest-allure"
    assert "callback-secret-value" not in payload


def test_callback_status_normalization_preserves_cancel_and_timeout_intent():
    """Keep explicit platform stop intent while normalizing Dagu result labels."""
    callback = _callback_module()
    assert callback.normalize_status("SUCCESS", "SUCCEEDED") == "SUCCESS"
    assert callback.normalize_status("FAILED", "SUCCEEDED") == "FAILED"
    assert callback.normalize_status("CANCELLED", "ABORTED") == "CANCELLED"
    assert callback.normalize_status("TIMEOUT", "ABORTED") == "TIMEOUT"
    assert callback.normalize_status("", "PARTIALLY_SUCCEEDED") == "FAILED"
