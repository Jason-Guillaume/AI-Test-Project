"""缺陷分享安全、分布式限流、可信代理 IP、定时归档与生产域名校验专项测试。"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import redis as redis_lib

from app.core.config import settings
from app.features.defects.models.share import DefectExternalAction, DefectShareLink
from app.features.defects.services import public_rate_limit
from app.features.defects.services.public_rate_limit import (
    enforce_public_share_limit,
    extract_client_ip,
    reset_public_share_limits,
)
from app.features.defects.services.share_archive_worker import DefectShareArchiveWorker
from app.features.defects.services.share_service import archive_expired_shares
from app.platform.notifications.models.notification_record import NotificationRecord
from tests.conftest import unique

_WEBHOOK_FEISHU = "https://open.feishu.cn/open-apis/bot/v2/hook/unit-test"


@pytest.fixture(autouse=True)
def _clean_limits_and_base(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://platform.example.com")
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "")
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(settings, "PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED", False)
    reset_public_share_limits()
    yield
    reset_public_share_limits()


def _mock_feishu(monkeypatch, *, status_code=200, payload=None):
    calls = []

    def fake_post(url, json=None, **kwargs):
        calls.append({"url": url, "json": json})

        class Resp:
            def __init__(self):
                self.status_code = status_code
                self.text = "ok"

            def json(self):
                return payload or {"code": 0, "msg": "success"}

        return Resp()

    monkeypatch.setattr("app.platform.notifications.services.feishu_service.httpx.post", fake_post)
    return calls


def _setup_bug_and_channel(api, actor, webhook_url: str = _WEBHOOK_FEISHU):
    proj = api.post("/projects", username=actor, json={"name": unique("sec-proj")}).json()
    ch = api.post(
        f"/projects/{proj['id']}/notification-channels",
        username=actor,
        json={"name": "安全验证群", "webhook_url": webhook_url, "secret": "s1", "enabled": True},
    ).json()
    bug = api.post(
        "/bugs",
        username=actor,
        json={
            "project_id": proj["id"],
            "title": unique("安全缺陷"),
            "description": "token=SensitiveValueDoNotLeak",
            "severity": 4,
            "status": "待确认",
        },
    ).json()
    return proj["id"], ch["id"], bug["id"]


def _token(url: str) -> str:
    return url.split("#token=", 1)[1]


def _fake_request(peer_host: str, *, xff: str | None = None, x_real_ip: str | None = None):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    if x_real_ip is not None:
        headers["x-real-ip"] = x_real_ip
    return SimpleNamespace(client=SimpleNamespace(host=peer_host), headers=headers)


def test_trusted_proxy_ip_extraction_ipv4_ipv6_and_spoofing_protection(monkeypatch):
    # Without TRUSTED_PROXY_CIDRS configured, spoofed forwarding headers are ignored.
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "")
    req_untrusted = _fake_request("198.51.100.4", xff="203.0.113.99", x_real_ip="203.0.113.77")
    assert extract_client_ip(req_untrusted) == "198.51.100.4"

    # With trusted proxies configured (IPv4 + IPv6 CIDRs), right-to-left stripping skips proxies only.
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8, fc00::/7")
    req_spoofed_left = _fake_request(
        "10.1.2.3",
        xff="1.2.3.4, 203.0.113.55:44123, 10.9.8.7",
    )
    assert extract_client_ip(req_spoofed_left) == "203.0.113.55"

    req_ipv6_client = _fake_request(
        "fc00::10",
        xff="[2001:0db8:0000:0000:0000:0000:0000:0001]:51234, fc00::2",
    )
    assert extract_client_ip(req_ipv6_client) == "2001:db8::1"

    req_fallback_real_ip = _fake_request("10.0.0.5", xff="", x_real_ip="2001:db8:0:0::9")
    assert extract_client_ip(req_fallback_real_ip) == "2001:db8::9"


@pytest.fixture()
def ephemeral_redis_url():
    existing = (os.getenv("TEST_REDIS_URL") or os.getenv("REDIS_URL") or "").strip()
    if existing:
        client = redis_lib.Redis.from_url(existing, socket_connect_timeout=1.5)
        try:
            client.ping()
            yield existing
            return
        except Exception:
            pass

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    container_name = f"test-redis-rl-{os.getpid()}-{port}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", container_name, "-p", f"127.0.0.1:{port}:6379", "redis:7-alpine"],
        check=True,
        capture_output=True,
        text=True,
    )
    url = f"redis://127.0.0.1:{port}/0"
    try:
        client = redis_lib.Redis.from_url(url, socket_connect_timeout=1.0)
        for _ in range(30):
            try:
                if client.ping():
                    break
            except Exception:
                time.sleep(0.1)
        else:
            pytest.fail("ephemeral redis container did not become ready")
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


def test_redis_distributed_rate_limiting_dimensions_ttl_and_key_privacy(monkeypatch, ephemeral_redis_url):
    monkeypatch.setattr(settings, "REDIS_URL", ephemeral_redis_url)
    reset_public_share_limits()

    raw_ip = "203.0.113.77"
    share_id = "share_secret_target_01"
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8")

    # Exceed IP failure bucket (limit=8) across 9 attempts -> 9th blocked with 429.
    req = _fake_request("10.0.0.2", xff=raw_ip)
    for _ in range(8):
        enforce_public_share_limit(req, "failure", share_id=share_id)
    with pytest.raises(Exception) as exc_info:
        enforce_public_share_limit(req, "failure", share_id=share_id)
    assert getattr(exc_info.value, "status_code", None) == 429

    # Confirm simulated second app instance clearing in-process cache still shares Redis counts.
    with public_rate_limit._lock:
        public_rate_limit._events.clear()
    with pytest.raises(Exception) as second_inst_exc:
        enforce_public_share_limit(req, "failure", share_id=share_id)
    assert getattr(second_inst_exc.value, "status_code", None) == 429

    # Inspect Redis directly: keys must have bounded TTL and must NOT expose raw IP or share_id.
    client = redis_lib.Redis.from_url(ephemeral_redis_url, decode_responses=True)
    keys = client.keys("public-share:rl:*")
    assert len(keys) >= 2
    for key in keys:
        assert raw_ip not in key
        assert share_id not in key
        ttl = client.ttl(key)
        assert 0 < ttl <= 70

    # Share-level failure limit (20) blocks distributed attackers across distinct IPs hitting same share_id.
    reset_public_share_limits()
    for idx in range(20):
        enforce_public_share_limit(_fake_request("10.0.0.2", xff=f"198.51.100.{idx + 1}"), "failure", share_id=share_id)
    with pytest.raises(Exception) as share_exc:
        enforce_public_share_limit(_fake_request("10.0.0.2", xff="198.51.100.250"), "failure", share_id=share_id)
    assert getattr(share_exc.value, "status_code", None) == 429


def test_redis_unavailable_degradation_modes(monkeypatch):
    # Force invalid closed port for Redis URL.
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:63999/0")
    reset_public_share_limits()
    req = _fake_request("198.51.100.19")

    # fail_closed=False falls back cleanly to in-process bounded rate limiting.
    monkeypatch.setattr(settings, "PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED", False)
    for _ in range(8):
        enforce_public_share_limit(req, "failure", share_id="fallback-share")
    with pytest.raises(Exception) as exc_fallback:
        enforce_public_share_limit(req, "failure", share_id="fallback-share")
    assert getattr(exc_fallback.value, "status_code", None) == 429

    # fail_closed=True returns 503 Service Unavailable immediately.
    monkeypatch.setattr(settings, "PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED", True)
    with pytest.raises(Exception) as exc_closed:
        enforce_public_share_limit(_fake_request("198.51.100.20"), "view", share_id="fallback-share")
    assert getattr(exc_closed.value, "status_code", None) == 503


def test_reissue_invalidates_old_token_and_retry_failure_is_audited(api, admin, db, monkeypatch):
    # 只有推送失败的分享可以重推：重推会轮换凭证，并记录这次新的失败。推送成功的分享见下一个用例。
    _mock_feishu(monkeypatch, payload={"code": 9999, "msg": "rate limit"})
    _proj_id, ch_id, bug_id = _setup_bug_and_channel(api, admin)

    created = api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id}).json()
    assert created["notification_status"] == "FAILED"
    old_token = _token(created["share_url"])
    share_id = created["share_id"]

    # Retry without sending the old access_token rotates the hash and records another failure.
    retried = api.post(f"/bugs/{bug_id}/shares/{share_id}/retry", username=admin, json={})
    assert retried.status_code == 200, retried.text
    retry_body = retried.json()
    new_token = _token(retry_body["share_url"])
    assert new_token != old_token
    assert retry_body["notification_status"] == "FAILED"
    assert retry_body["retry_count"] == 1

    # Old token is immediately invalid (404), new token works even when push failed.
    assert api.client.get(f"/api/v1/public/defect-shares/{share_id}", headers={"Authorization": f"Bearer {old_token}"}).status_code == 404
    assert api.client.get(f"/api/v1/public/defect-shares/{share_id}", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200

    # Share detail never leaks tokens and preserves both notification attempts cleanly.
    detail = api.get(f"/bugs/{bug_id}/shares/{share_id}", username=admin).json()
    assert old_token not in str(detail)
    assert new_token not in str(detail)
    assert len(detail["notifications"]) == 2
    assert {n["status"] for n in detail["notifications"]} == {"FAILED"}

    # Revoked shares cannot be retried or un-revoked.
    assert api.post(f"/bugs/{bug_id}/shares/{share_id}/revoke", username=admin).status_code == 200
    assert api.post(f"/bugs/{bug_id}/shares/{share_id}/retry", username=admin, json={}).status_code == 409


def test_successful_share_is_not_repushed_and_first_link_stays_valid(api, admin, db, monkeypatch):
    """推送成功后重推会在群里多发一张卡片，并让第一张卡片的链接失效，所以后端必须拒绝。"""
    _mock_feishu(monkeypatch)
    _proj_id, ch_id, bug_id = _setup_bug_and_channel(api, admin)
    created = api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id}).json()
    assert created["notification_status"] == "SUCCESS"
    share_id = created["share_id"]
    token = _token(created["share_url"])
    retried = api.post(f"/bugs/{bug_id}/shares/{share_id}/retry", username=admin, json={})
    assert retried.status_code == 409
    assert retried.json()["message"] == "上次投递已成功，无需重新推送"
    assert api.client.get(f"/api/v1/public/defect-shares/{share_id}", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_archive_worker_idempotent_preserves_audit_and_retries_on_failure(api, admin, db, monkeypatch, caplog):
    _mock_feishu(monkeypatch)
    proj_id, ch_id, bug_id = _setup_bug_and_channel(api, admin)
    created = api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id}).json()
    tok = _token(created["share_url"])
    share_id = created["share_id"]

    # Submit resolve before expiry to populate audit + notification rows.
    resolved = api.client.post(
        f"/api/v1/public/defect-shares/{share_id}/resolve",
        json={"repair_description": "已定位修复"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resolved.status_code == 200

    share_row = db.query(DefectShareLink).filter(DefectShareLink.share_id == share_id).one()
    share_row.expires_at = datetime.now() - timedelta(hours=2)
    db.commit()

    # Worker failure logs error and records retry state cleanly, then next run succeeds idempotently.
    def broken_session():
        raise RuntimeError("simulated db transient disconnect")

    worker = DefectShareArchiveWorker(session_factory=broken_session)
    with caplog.at_level(logging.ERROR):
        assert worker.run_once() == 0
    assert worker.consecutive_failures == 1
    assert "RuntimeError" in (worker.last_error or "")

    from app.core.database.session import SessionLocal

    worker._session_factory = SessionLocal
    assert worker.run_once() >= 1
    assert worker.consecutive_failures == 0
    assert worker.last_error is None
    # Idempotent second pass does not re-archive already archived records.
    assert archive_expired_shares(db) == 0

    db.expire_all()
    archived_row = db.query(DefectShareLink).filter(DefectShareLink.share_id == share_id).one()
    assert archived_row.archived_at is not None
    # Audit & notification records remain intact after archiving.
    assert db.query(DefectExternalAction).filter(DefectExternalAction.share_link_id == archived_row.id).count() == 1
    assert db.query(NotificationRecord).filter(NotificationRecord.share_link_id == archived_row.id).count() >= 1
    assert api.client.get(f"/api/v1/public/defect-shares/{share_id}", headers={"Authorization": f"Bearer {tok}"}).status_code == 403
    assert api.post(f"/bugs/{bug_id}/shares/{share_id}/retry", username=admin, json={}).status_code == 409

    # Deleted bug immediately invalidates share, active_counts, and retry.
    active = api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id}).json()
    active_tok = _token(active["share_url"])
    assert api.delete(f"/bugs/{bug_id}", username=admin).status_code == 204
    assert api.client.get(f"/api/v1/public/defect-shares/{active['share_id']}", headers={"Authorization": f"Bearer {active_tok}"}).status_code == 404
    assert api.client.post(
        f"/api/v1/public/defect-shares/{active['share_id']}/resolve",
        json={"repair_description": "after delete"},
        headers={"Authorization": f"Bearer {active_tok}"},
    ).status_code == 404
    # Bug list active_share_count is zero / absent cleanly.
    db.expire_all()
    from app.features.defects.services.share_service import DefectShareService
    assert DefectShareService().active_counts(db, [bug_id]).get(bug_id, 0) == 0


def test_public_app_base_url_validation_and_body_limit(api, admin, monkeypatch):
    _mock_feishu(monkeypatch)
    proj_id, ch_id, bug_id = _setup_bug_and_channel(api, admin, webhook_url=_WEBHOOK_FEISHU)

    # Empty PUBLIC_APP_BASE_URL must NOT fake push success with relative path.
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "")
    prev_empty = api.post("/bugs/shares/preview", username=admin, json={"bug_ids": [bug_id], "channel_id": ch_id})
    assert prev_empty.status_code == 200
    assert prev_empty.json()["public_url_valid"] is False
    assert "PUBLIC_APP_BASE_URL" in prev_empty.json()["public_url_error"]
    assert api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id}).status_code == 400

    # Dev localhost URL cannot be pushed to real external Feishu webhook.
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "http://127.0.0.1:5173")
    assert api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id}).status_code == 400

    # Production APP_ENV rejects HTTP or localhost even on non-Feishu webhooks.
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "http://qa.company.com")
    assert api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id}).status_code == 400
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://localhost:8443")
    assert api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id}).status_code == 400

    # Valid production HTTPS domain succeeds.
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://qa.company.com")
    ok = api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id})
    assert ok.status_code == 200
    share_id = ok.json()["share_id"]

    # Oversized public resolve payload is rejected before hitting DB.
    oversized = api.client.post(
        f"/api/v1/public/defect-shares/{share_id}/resolve",
        headers={
            "Authorization": f"Bearer {_token(ok.json()['share_url'])}",
            "Content-Type": "application/json",
            "Content-Length": "20000",
        },
        content=b"{}",
    )
    assert oversized.status_code == 400


def test_cross_project_and_concurrent_public_views(api, admin, db, monkeypatch):
    _mock_feishu(monkeypatch)
    _p1, ch_id, bug_id = _setup_bug_and_channel(api, admin)
    created = api.post(f"/bugs/{bug_id}/shares", username=admin, json={"channel_id": ch_id}).json()
    tok = _token(created["share_url"])
    share_id = created["share_id"]

    outsider = unique("share_outsider")
    assert api.register(outsider).status_code == 201
    api.login(outsider)
    assert api.get(f"/bugs/{bug_id}/shares", username=outsider).status_code == 404
    assert api.post(f"/bugs/{bug_id}/shares/{share_id}/revoke", username=outsider).status_code == 404

    # Concurrent view tracking increments consistently without 500 errors.
    def hit_view(_i):
        return api.client.post(
            f"/api/v1/public/defect-shares/{share_id}/views",
            headers={"Authorization": f"Bearer {tok}"},
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(hit_view, range(5)))
    assert all(code == 204 for code in statuses)
    summary = api.get(f"/bugs/{bug_id}/shares", username=admin).json()["items"][0]
    assert summary["view_count"] == 5
