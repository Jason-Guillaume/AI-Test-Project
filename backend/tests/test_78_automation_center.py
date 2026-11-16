"""云效自动化测试中心。

覆盖真实客户端的请求形态、报告隔离、签名、幂等、权限和通过率。
外部 HTTP 只替换传输层，业务服务仍走 YunxiaoClient。
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.features.automation_center.models.entities import AutomationExecution, AutomationReport
from app.features.automation_center.services.center_service import sign_callback
from app.features.automation_center.services.stats import pass_rate
from app.features.automation_center.services.storage import safe_extract
from tests.conftest import unique

API = "/api/v1"
_TOKEN = "pt-test-token-value"
_SECRET = "callback-secret-1"


def test_pass_rate_excludes_skipped_cases():
    """跳过用例不进入分母，也不能把整份报告判成失败。"""
    assert pass_rate(passed=0, failed=0, broken=0, skipped=4, unknown=0) == Decimal("100.00")
    assert pass_rate(passed=1, failed=1, broken=0, skipped=2, unknown=0) == Decimal("50.00")
    assert pass_rate(passed=1, failed=0, broken=1, skipped=0, unknown=0) == Decimal("50.00")


def test_zip_slip_is_rejected(tmp_path):
    """压缩包中的父目录条目不能写到目标目录之外。"""
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../evil.txt", "nope")
    with pytest.raises(HTTPException):
        safe_extract(payload.getvalue(), tmp_path / "report")
    assert not (tmp_path / "evil.txt").exists()


def _register(api, username: str) -> int:
    """注册并登录测试用户。"""
    response = api.register(username)
    assert response.status_code == 201, response.text
    api.login(username)
    return response.json()["user"]["id"]


def _project(api, actor: str) -> int:
    """创建业务项目。"""
    response = api.post("/projects", username=actor, json={"name": unique("auto-project")})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _install_yunxiao(monkeypatch):
    """用官方路径的假传输层替换网络，不替换业务客户端。"""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=len([item for item in calls if item.method == "POST"]))
        if request.method == "PUT":
            return httpx.Response(200, json=True)
        if request.url.path.endswith("/runs"):
            return httpx.Response(200, json=[{
                "pipelineRunId": 1, "status": "RUNNING", "triggerMode": 3,
                "startTime": int(time.time() * 1000),
            }])
        return httpx.Response(200, json={"status": "SUCCESS", "pipelineRunId": 1})

    def factory(timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(
        "app.features.automation_center.providers.yunxiao_client.http_client", factory,
    )
    return calls


def _allure_zip(*, passed: int, failed: int, skipped: int, broken: int = 0, history: bool = False) -> bytes:
    """构造一份最小但可浏览的 Allure HTML 压缩包。"""
    stats = {
        "total": passed + failed + skipped + broken, "passed": passed, "failed": failed,
        "broken": broken, "skipped": skipped, "unknown": 0,
    }
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("index.html", "<!doctype html><title>Allure</title><script src='app.js'></script>")
        archive.writestr("app.js", "window.allureLoaded = true;")
        archive.writestr("data/suites.json", "{}")
        archive.writestr("widgets/summary.json", json.dumps({"statistic": stats}))
        archive.writestr("widgets/suites.json", json.dumps({"items": [{"name": "登录", "statistic": stats}]}))
        if history:
            archive.writestr("history/history-trend.json", json.dumps([{"data": stats}]))
    return payload.getvalue()


def _signed_headers(key: str, idempotency: str, metadata_text: str, report: bytes) -> dict[str, str]:
    """生成回调签名头。"""
    stamp = str(int(time.time()))
    return {
        "X-Automation-Timestamp": stamp,
        "X-Idempotency-Key": idempotency,
        "X-Automation-Signature": sign_callback(
            _SECRET, stamp, key, idempotency,
            hashlib.sha256(report).hexdigest(),
            hashlib.sha256(metadata_text.encode("utf-8")).hexdigest(),
        ),
    }


def _callback(api, key: str, metadata: dict, report: bytes | None, idempotency: str):
    """按约定对元数据和压缩包签名后回传。"""
    metadata_text = json.dumps(metadata, ensure_ascii=False)
    report_bytes = report or b""
    headers = _signed_headers(key, idempotency, metadata_text, report_bytes)
    if report is None:
        return api.client.post(
            f"{API}/automation-callbacks/{key}",
            headers={**headers, "Content-Type": "application/json"},
            content=metadata_text,
        )
    return api.client.post(
        f"{API}/automation-callbacks/{key}",
        headers=headers,
        data={"metadata": metadata_text},
        files={"report": ("allure.zip", report_bytes, "application/zip")},
    )


def _history_headers(key: str, automation_project_id: int) -> dict[str, str]:
    """history 下载把项目 ID 当作签名元数据。"""
    return _signed_headers(key, "history-1", str(automation_project_id), b"")


def test_yunxiao_trigger_report_permission_and_idempotency(api, db, monkeypatch, tmp_path):
    """触发真实客户端、回传报告、权限隔离和重复回调都不覆盖历史。"""
    monkeypatch.setattr(settings, "AUTOMATION_REPORT_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://qa.example.com")
    calls = _install_yunxiao(monkeypatch)
    sent = []

    def fake_post(url, json=None, **kwargs):
        sent.append(json)

        class _Response:
            status_code = 200
            text = ""

            def json(self):
                return {"code": 0, "msg": "success"}

        return _Response()

    monkeypatch.setattr("app.platform.notifications.services.feishu_service.httpx.post", fake_post)
    owner = unique("owner")
    outsider = unique("outsider")
    _register(api, owner)
    outsider_id = _register(api, outsider)
    project_id = _project(api, owner)
    channel = api.post(
        f"/projects/{project_id}/notification-channels", username=owner,
        json={"name": "测试群", "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/deadbeef"},
    )
    assert channel.status_code == 201, channel.text
    created = api.post(f"/projects/{project_id}/automation-integrations", username=owner, json={
        "name": "云效", "organization_id": "5ebbc0228123212b59abcde",
        "access_token": _TOKEN, "callback_secret": _SECRET,
    })
    assert created.status_code == 201, created.text
    config = created.json()
    assert _TOKEN not in json.dumps(config)
    assert "callback_secret" not in config
    checked = api.post(
        f"/automation-integrations/{config['id']}/test-connection", username=owner, params={"pipeline_id": "321"},
    )
    assert checked.status_code == 200, checked.text
    assert calls[-1].url.path == "/oapi/v1/flow/organizations/5ebbc0228123212b59abcde/pipelines/321/runs"
    automated = api.post(f"/projects/{project_id}/automation-projects", username=owner, json={
        "integration_config_id": config["id"], "name": "登录回归",
        "repository_url": "https://codeup.aliyun.com/org/demo.git", "repository_id": "42",
        "pipeline_id": "321", "default_branch": "master", "default_environment": "staging",
        "pytest_args": "-q", "test_tags": "smoke", "notification_channel_id": channel.json()["id"],
        "pipeline_params": {"PYTEST_WORKERS": "2", "ACCESS_TOKEN": "must-not-pass"},
    })
    assert automated.status_code == 201, automated.text
    automation_id = automated.json()["id"]
    first = api.post(f"/automation-projects/{automation_id}/executions", username=owner, json={"branch": "release"})
    assert first.status_code == 201, first.text
    body = json.loads(calls[-1].content)
    params = json.loads(body["params"])
    assert params["runningBranchs"]["https://codeup.aliyun.com/org/demo.git"] == "release"
    assert "ACCESS_TOKEN" not in params["envs"]
    assert _SECRET not in body["params"]
    assert calls[-1].headers["x-yunxiao-token"] == _TOKEN
    execution_id = first.json()["id"]
    stored = db.get(AutomationExecution, execution_id)
    assert stored.pipeline_run_id == "1"
    report_bytes = _allure_zip(passed=1, failed=1, skipped=2, history=True)
    callback = _callback(api, config["callback_key"], {
        "execution_id": execution_id, "automation_project_id": automation_id,
        "pipeline_run_id": "1", "status": "SUCCESS", "git_commit": "abc123",
        "branch": "release", "environment": "staging", "duration_ms": 1500,
        "log_excerpt": "token=pt-should-hide",
    }, report_bytes, "run-1")
    assert callback.status_code == 200, callback.text
    assert callback.json()["duplicate"] is False
    db.expire_all()
    report = db.get(AutomationReport, callback.json()["report_id"])
    assert report.failed_cases == 1
    assert report.skipped_cases == 2
    assert float(report.pass_rate) == 50.0
    assert db.get(AutomationExecution, execution_id).status == "FAILED"
    assert "pt-should-hide" not in db.get(AutomationExecution, execution_id).log_excerpt
    again = _callback(api, config["callback_key"], {
        "execution_id": execution_id, "automation_project_id": automation_id, "status": "SUCCESS",
    }, report_bytes, "run-1")
    assert again.status_code == 200, again.text
    assert again.json()["duplicate"] is True
    assert len(sent) == 1
    assert "查看 Allure 报告" in json.dumps(sent[0], ensure_ascii=False)
    assert _TOKEN not in json.dumps(sent[0])
    grant = api.post(f"/automation-reports/{report.id}/view-grant", username=owner)
    assert grant.status_code == 200, grant.text
    page = api.client.get(grant.json()["index_url"])
    assert page.status_code == 200
    assert "Allure" in page.text
    script = api.client.get(grant.json()["index_url"].replace("index.html", "app.js"))
    assert script.status_code == 200
    assert "allureLoaded" in script.text
    denied = api.post(f"/automation-reports/{report.id}/view-grant", username=outsider)
    assert denied.status_code == 404
    missing = api.client.get(f"{API}/automation-reports/{report.id}/content/not-a-token/index.html")
    assert missing.status_code == 404
    assert (tmp_path / str(project_id) / str(execution_id) / "html" / "index.html").is_file()
    history = api.client.get(
        f"{API}/automation-callbacks/{config['callback_key']}/history",
        params={"automation_project_id": automation_id},
        headers=_history_headers(config["callback_key"], automation_id),
    )
    assert history.status_code == 200, history.text
    with zipfile.ZipFile(io.BytesIO(history.content)) as archive:
        assert "history/history-trend.json" in archive.namelist()
    second = api.post(f"/automation-projects/{automation_id}/executions", username=owner, json={})
    assert second.status_code == 201, second.text
    assert second.json()["id"] != execution_id
    assert db.get(AutomationExecution, execution_id) is not None
    outsider_execution = api.get(f"/automation-executions/{execution_id}", username=outsider)
    assert outsider_execution.status_code == 404
    assert outsider_id
