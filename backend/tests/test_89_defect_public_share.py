"""缺陷免登录分享、飞书推送和外部修复闭环。"""

from __future__ import annotations

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx
import pytest

from app.core.config import settings
from app.core.database.session import SessionLocal
from app.core.models.notification import Notification
from app.features.defects.models.bug import Bug
from app.features.defects.models.share import DefectExternalAction, DefectShareLink
from app.features.defects.schemas_share import PublicResolveRequest
from app.features.defects.services.public_rate_limit import reset_public_share_limits
from app.features.defects.services.share_service import DefectShareService
from app.platform.notifications.models.notification_record import NotificationRecord
from tests.conftest import unique

_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_SECRET_TEXT = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz password=supersecretvalue /Users/a1/secret/db.conf postgres://user:pass@localhost/db"


@pytest.fixture(autouse=True)
def _public_limits():
    """每个用例单独计数，避免错误凭证测试影响正常访问。"""
    reset_public_share_limits()
    yield
    reset_public_share_limits()


@pytest.fixture(autouse=True)
def _public_base(monkeypatch):
    """飞书按钮需要绝对地址；测试不依赖真实域名。"""
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://platform.example.com")


def _create_project(api, actor):
    response = api.post("/projects", username=actor, json={"name": unique("proj"), "description": "share"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _register(api, username):
    response = api.register(username)
    assert response.status_code == 201, response.text
    api.login(username, "Init-Password-123")
    return response.json()["user"]["id"]


def _add_member(api, actor, project_id, user_id, role):
    response = api.put(
        f"/projects/{project_id}/members/{user_id}", username=actor, json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 200, response.text


def _channel(api, actor, project_id, name="研发缺陷群"):
    response = api.post(
        f"/projects/{project_id}/notification-channels", username=actor,
        json={"name": name, "webhook_url": _WEBHOOK, "secret": "unit-test-secret", "enabled": True},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _bug(api, actor, project_id, title="登录接口 500", *, expected_result=None, actual_result=None):
    response = api.post("/bugs", username=actor, json={
        "project_id": project_id, "title": title, "description": _SECRET_TEXT, "severity": 4,
        "status": "待确认", "steps_to_reproduce": "1. 调用登录接口\n2. 观察 500", "environment": "test",
        "expected_result": expected_result, "actual_result": actual_result,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _mock_feishu(monkeypatch, *, status_code=200, payload=None, error: Exception | None = None):
    calls = []

    def fake_post(url, json=None, **kwargs):
        calls.append({"url": url, "json": json})
        if error is not None:
            raise error

        class Response:
            def __init__(self):
                self.status_code = status_code
                self.text = "ok"

            def json(self):
                return payload or {"code": 0, "msg": "success"}

        return Response()

    monkeypatch.setattr("app.platform.notifications.services.feishu_service.httpx.post", fake_post)
    return calls


def _token(url: str) -> str:
    return url.split("#token=", 1)[1]


def _share(api, actor, bug_id, channel_id, **extra):
    body = {"channel_id": channel_id, "expires_in_days": 7, "allow_resolve": True}
    body.update(extra)
    response = api.post(f"/bugs/{bug_id}/shares", username=actor, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _public_get(api, share_id, token):
    return api.client.get(
        f"/api/v1/public/defect-shares/{share_id}",
        headers={"Authorization": f"Bearer {token}"},
    )


def _public_post(api, share_id, token, path, payload):
    return api.client.post(
        f"/api/v1/public/defect-shares/{share_id}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


def _assert_no_internal_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in {"id", "bug_id", "project_id", "channel_id", "user_id", "reporter_id", "assignee_id"}
            _assert_no_internal_keys(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_internal_keys(item)


def test_share_token_is_random_and_only_hash_is_stored(api, admin, db, monkeypatch):
    """创建分享后明文只出现在响应里，数据库保存哈希。"""
    calls = _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    bug = _bug(api, admin, project_id)
    first = _share(api, admin, bug["id"], channel_id)
    second = _share(api, admin, bug["id"], channel_id)
    assert first["share_url"] != second["share_url"]
    token = _token(first["share_url"])
    padding = "=" * (-len(token) % 4)
    assert len(base64.urlsafe_b64decode(token + padding)) >= 32
    db.expire_all()
    row = db.query(DefectShareLink).filter_by(share_id=first["share_id"]).one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in row.token_hash
    stored = str(db.query(NotificationRecord).filter_by(share_link_id=row.id).one().request_snapshot)
    assert token not in stored
    assert calls[0]["json"]["card"]["elements"]
    assert token in str(calls[0]["json"]["card"])


def test_single_share_request_key_prevents_duplicate_delivery(api, admin, db, monkeypatch):
    """重复确认复用创建结果，不重复写分享或调用飞书。"""
    calls = _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    bug = _bug(api, admin, project_id)
    payload = {"channel_id": channel_id, "request_key": "single-request-001"}
    first = api.post(f"/bugs/{bug['id']}/shares", username=admin, json=payload)
    duplicate = api.post(f"/bugs/{bug['id']}/shares", username=admin, json=payload)
    assert first.status_code == 200, first.text
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["share_id"] == first.json()["share_id"]
    assert duplicate.json()["share_url"] is None
    assert duplicate.json()["notification_status"] == "SUCCESS"
    assert len(calls) == 1
    assert db.query(DefectShareLink).filter_by(bug_id=bug["id"]).count() == 1

    changed = api.post(
        f"/bugs/{bug['id']}/shares", username=admin,
        json={**payload, "allow_resolve": False},
    )
    assert changed.status_code == 409
    assert len(calls) == 1


def test_batch_share_has_one_entry_and_scoped_public_attachments(api, admin, db, monkeypatch):
    """批次只投递一次；批次凭证只能访问快照授权且属于该缺陷的附件。"""
    calls = _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    first_bug = _bug(
        api, admin, project_id, "接口缺陷一",
        expected_result="应返回 200\n并包含有效数据", actual_result="实际返回 500",
    )
    second_bug = _bug(api, admin, project_id, "接口缺陷二")
    upload = api.post(
        f"/bugs/{first_bug['id']}/attachments", username=admin,
        files={"file": ("proof.txt", b"safe note\nsecond line", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    attachment_id = upload.json()["id"]
    body = {
        "bug_ids": [first_bug["id"], second_bug["id"]],
        "channel_id": channel_id,
        "request_key": "batch-request-0001",
    }
    created = api.post("/bugs/shares/batch", username=admin, json=body)
    assert created.status_code == 200, created.text
    result = created.json()
    assert result["card_count"] == 1
    assert len(result["items"]) == 2
    assert result["batch_share_url"].startswith("https://platform.example.com/public/defects/share/batch/")
    assert len(calls) == 1
    actions = [item for item in calls[0]["json"]["card"]["elements"] if item.get("tag") == "action"]
    assert len(actions) == 1
    assert len(actions[0]["actions"]) == 1

    duplicate = api.post("/bugs/shares/batch", username=admin, json=body)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate_request"] is True
    assert duplicate.json()["batch_share_id"] == result["batch_share_id"]
    assert duplicate.json()["batch_share_url"] is None
    assert len(calls) == 1
    changed = api.post(
        "/bugs/shares/batch", username=admin,
        json={**body, "allow_resolve": False},
    )
    assert changed.status_code == 409
    assert len(calls) == 1

    token = _token(result["batch_share_url"])
    headers = {"Authorization": f"Bearer {token}"}
    public_base = f"/api/v1/public/defect-shares/batches/{result['batch_share_id']}"
    overview = api.client.get(public_base, headers=headers)
    assert overview.status_code == 200, overview.text
    first_share_id = result["items"][0]["share_id"]
    first_detail = api.client.get(f"{public_base}/items/{first_share_id}", headers=headers)
    assert first_detail.status_code == 200, first_detail.text
    content = first_detail.json()["content"]
    assert content["expected_result"] == "应返回 200\n并包含有效数据"
    assert content["actual_result"] == "实际返回 500"
    assert content["attachments"][0]["id"] == attachment_id
    attachment = api.client.get(
        f"{public_base}/items/{first_share_id}/attachments/{attachment_id}", headers=headers,
    )
    assert attachment.status_code == 200
    assert attachment.content == b"safe note\nsecond line"
    assert attachment.headers["content-type"].startswith("text/plain")
    assert attachment.headers["content-disposition"].startswith("inline;")
    assert attachment.headers["x-content-type-options"] == "nosniff"
    downloaded = api.client.get(
        f"{public_base}/items/{first_share_id}/attachments/{attachment_id}?download=true", headers=headers,
    )
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    other_share_id = result["items"][1]["share_id"]
    crossed = api.client.get(
        f"{public_base}/items/{other_share_id}/attachments/{attachment_id}", headers=headers,
    )
    assert crossed.status_code == 404
    wrong_token = api.client.get(public_base, headers={"Authorization": "Bearer wrong-token"})
    assert wrong_token.status_code == 404


@pytest.mark.parametrize("count", [1, 8, 9, 30])
def test_batch_delivery_counts_make_one_post_and_one_button(api, admin, monkeypatch, count):
    """指定批量规模均只调用一次飞书，卡片只提供一个入口。"""
    calls = _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    bugs = [_bug(api, admin, project_id, f"批次缺陷 {count}-{index}") for index in range(count)]
    response = api.post("/bugs/shares/batch", username=admin, json={
        "bug_ids": [bug["id"] for bug in bugs],
        "channel_id": channel_id,
        "request_key": unique(f"batch-{count}"),
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["items"]) == count
    assert result["card_count"] == 1
    assert len(calls) == 1
    elements = calls[0]["json"]["card"]["elements"]
    actions = [item for item in elements if item.get("tag") == "action"]
    assert len(actions) == 1
    assert len(actions[0]["actions"]) == 1
    assert actions[0]["actions"][0]["url"] in (result.get("batch_share_url"), result.get("share_url"))


def test_public_view_filters_fields_and_masks_secrets(api, admin, db, monkeypatch):
    """未授权字段和敏感值不能从公开接口读出。"""
    _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    bug = _bug(api, admin, project_id)
    created = _share(api, admin, bug["id"], channel_id, visible_fields=["title", "description"])
    token = _token(created["share_url"])
    before = api.get(f"/bugs/{bug['id']}", username=admin).json()["status"]
    response = _public_get(api, created["share_id"], token)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "content-security-policy" in response.headers
    body = response.json()
    _assert_no_internal_keys(body)
    assert body["content"]["title"] == "登录接口 500"
    assert "steps_to_reproduce" not in body["content"]
    assert "abcdefghijklmnopqrstuvwxyz" not in response.text
    assert "supersecretvalue" not in response.text
    assert "/Users/a1" not in response.text
    assert "postgres://" not in response.text
    assert api.get(f"/bugs/{bug['id']}", username=admin).json()["status"] == before
    db.expire_all()
    assert db.get(DefectShareLink, db.query(DefectShareLink).filter_by(share_id=created["share_id"]).one().id).view_count == 0
    viewed = _public_post(api, created["share_id"], token, "/views", {})
    assert viewed.status_code == 204
    db.expire_all()
    assert db.query(DefectShareLink).filter_by(share_id=created["share_id"]).one().view_count == 1


def test_wrong_expired_revoked_and_isolated_links(api, admin, db, monkeypatch):
    """错误、过期、撤销和另一条分享都不能读到对方的缺陷。"""
    _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    first_channel = _channel(api, admin, project_id, "群一")
    second_channel = _channel(api, admin, project_id, "群二")
    bug = _bug(api, admin, project_id)
    other = _bug(api, admin, project_id, title="另一个缺陷")
    first = _share(api, admin, bug["id"], first_channel)
    second = _share(api, admin, other["id"], second_channel)
    wrong = _public_get(api, first["share_id"], "not-the-token")
    assert wrong.status_code == 404
    assert wrong.json()["message"] == "分享链接无效或无权访问"
    crossed = _public_get(api, second["share_id"], _token(first["share_url"]))
    assert crossed.status_code == 404
    db.expire_all()
    row = db.query(DefectShareLink).filter_by(share_id=first["share_id"]).one()
    row.expires_at = datetime.now() - timedelta(minutes=1)
    db.commit()
    expired = _public_get(api, first["share_id"], _token(first["share_url"]))
    assert expired.status_code == 403
    assert expired.json()["message"] == "分享链接已过期"
    revoked = api.post(f"/bugs/{other['id']}/shares/{second['share_id']}/revoke", username=admin)
    assert revoked.status_code == 200
    assert _public_get(api, second["share_id"], _token(second["share_url"])).json()["message"] == "分享链接已撤销"
    alive = _share(api, admin, bug["id"], second_channel)
    assert _public_get(api, alive["share_id"], _token(alive["share_url"])).status_code == 200


def test_resolve_updates_status_once_and_notifies_reporter(api, admin, db, monkeypatch):
    """开发提交已解决后回写状态、修复说明和站内通知，重复提交不新增记录。"""
    _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    bug = _bug(api, admin, project_id)
    created = _share(api, admin, bug["id"], channel_id)
    token = _token(created["share_url"])
    payload = {
        "repair_description": "已经修复登录接口异常处理逻辑，修复版本 v1.2.3。",
        "fix_version": "v1.2.3", "commit_sha": "abc1234", "reporter_name": "王开发",
    }
    response = _public_post(api, created["share_id"], token, "/resolve", payload)
    assert response.status_code == 200, response.text
    assert response.json()["idempotent"] is False
    assert response.json()["live_status"] == "已修复"
    again = _public_post(api, created["share_id"], token, "/resolve", payload)
    assert again.status_code == 200
    assert again.json()["idempotent"] is True
    db.expire_all()
    stored = db.get(Bug, bug["id"])
    assert stored.status == "已修复"
    actions = db.query(DefectExternalAction).filter_by(bug_id=bug["id"]).all()
    assert len(actions) == 1
    assert actions[0].old_status == "待确认"
    assert actions[0].actor_type == "EXTERNAL_SHARE"
    assert actions[0].actor_display_name == "王开发"
    assert actions[0].fix_version == "v1.2.3"
    assert actions[0].commit_sha == "abc1234"
    notes = db.query(Notification).filter_by(event_type="defect.external_resolved").all()
    assert notes
    assert all(item.payload["actor"] is None for item in notes)
    history = api.get(f"/bugs/{bug['id']}/shares", username=admin)
    assert history.status_code == 200
    assert history.json()["items"][0]["latest_resolution"]["repair_description"] == payload["repair_description"]
    detail = api.get(f"/bugs/{bug['id']}/shares/{created['share_id']}", username=admin)
    assert detail.status_code == 200
    assert "已经修复登录接口" in detail.text
    closed = api.put(f"/bugs/{bug['id']}", username=admin, json={"status": "已关闭"})
    assert closed.status_code == 200
    blocked = _public_post(api, created["share_id"], token, "/resolve", payload)
    assert blocked.status_code == 409


def test_resolve_rejects_closed_readonly_and_script(api, admin, db, monkeypatch):
    """关闭、拒绝、只读链接和脚本内容都不能通过公开接口改写缺陷。"""
    _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    bug = _bug(api, admin, project_id)
    readonly = _share(api, admin, bug["id"], channel_id, allow_resolve=False)
    denied = _public_post(api, readonly["share_id"], _token(readonly["share_url"]), "/resolve", {"repair_description": "不应该成功"})
    assert denied.status_code == 403
    rejected = api.put(f"/bugs/{bug['id']}", username=admin, json={"status": "已拒绝"})
    assert rejected.status_code == 200
    writable = _share(api, admin, bug["id"], channel_id)
    blocked = _public_post(api, writable["share_id"], _token(writable["share_url"]), "/resolve", {"repair_description": "不应该成功"})
    assert blocked.status_code == 409
    reopened = api.put(f"/bugs/{bug['id']}", username=admin, json={"status": "处理中"})
    assert reopened.status_code == 200
    scripted = _public_post(api, writable["share_id"], _token(writable["share_url"]), "/resolve", {
        "repair_description": "<script>alert(1)</script>已修复'; DROP TABLE bug; --",
    })
    assert scripted.status_code == 200, scripted.text
    assert "<script" not in scripted.text
    db.expire_all()
    assert db.get(Bug, bug["id"]).status == "已修复"
    assert db.query(Bug).count() >= 1


def test_permissions_batch_retry_and_feishu_failures(api, admin, db, monkeypatch):
    """权限、批量、失败重试和飞书异常都保持分享记录。"""
    calls = _mock_feishu(monkeypatch, payload={"code": 9499, "msg": "webhook invalid"})
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    bug = _bug(api, admin, project_id)
    other = _bug(api, admin, project_id, title="第二条缺陷")
    viewer_name = unique("viewer")
    member_name = unique("member")
    viewer_id = _register(api, viewer_name)
    member_id = _register(api, member_name)
    _add_member(api, admin, project_id, viewer_id, "viewer")
    _add_member(api, admin, project_id, member_id, "member")
    denied = api.post(f"/bugs/{bug['id']}/shares", username=viewer_name, json={"channel_id": channel_id})
    assert denied.status_code == 403
    permanent = api.post(
        f"/bugs/{bug['id']}/shares", username=member_name,
        json={"channel_id": channel_id, "permanent": True},
    )
    assert permanent.status_code == 403
    failed = _share(api, admin, bug["id"], channel_id)
    assert failed["notification_status"] == "FAILED"
    assert "webhook invalid" in failed["error_message"]
    calls.clear()
    _mock_feishu(monkeypatch)
    retried = api.post(
        f"/bugs/{bug['id']}/shares/{failed['share_id']}/retry", username=admin,
        json={"access_token": _token(failed["share_url"])},
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["notification_status"] == "SUCCESS"
    assert retried.json()["share_url"] == failed["share_url"]
    db.expire_all()
    assert db.query(DefectShareLink).filter_by(bug_id=bug["id"]).count() == 1
    preview = api.post("/bugs/shares/preview", username=admin, json={"bug_ids": [bug["id"], other["id"]], "channel_id": channel_id})
    assert preview.status_code == 200
    assert preview.json()["defect_count"] == 2
    batch = api.post("/bugs/shares/batch", username=admin, json={"bug_ids": [bug["id"], other["id"]], "channel_id": channel_id})
    assert batch.status_code == 200, batch.text
    assert batch.json()["card_count"] == 1
    assert len({item["share_id"] for item in batch.json()["items"]}) == 2
    timeout_calls = _mock_feishu(monkeypatch, error=httpx.TimeoutException("timeout"))
    timed = _share(api, admin, other["id"], channel_id)
    assert timed["notification_status"] == "UNCERTAIN"
    assert timeout_calls
    listed = api.get(f"/bugs/{bug['id']}", username=admin)
    assert listed.json()["active_share_count"] >= 1


def test_brute_force_archive_and_deleted_bug(api, admin, db, monkeypatch):
    """连续错误凭证会被限流；删除和归档后公开页立即失效。"""
    _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    bug = _bug(api, admin, project_id)
    created = _share(api, admin, bug["id"], channel_id, expires_in_days=7)
    statuses = [_public_get(api, created["share_id"], f"wrong-token-{index}").status_code for index in range(9)]
    assert statuses[:8] == [404] * 8
    assert statuses[8] == 429
    reset_public_share_limits()
    removed = api.delete(f"/bugs/{bug['id']}", username=admin)
    assert removed.status_code == 204
    deleted = _public_get(api, created["share_id"], _token(created["share_url"]))
    assert deleted.status_code == 404
    assert deleted.json()["message"] == "缺陷已删除"
    another = _bug(api, admin, project_id, title="待归档")
    expiring = _share(api, admin, another["id"], channel_id)
    db.expire_all()
    row = db.query(DefectShareLink).filter_by(share_id=expiring["share_id"]).one()
    row.expires_at = datetime.now() - timedelta(days=1)
    db.commit()
    archived = api.post("/bugs/shares/archive-expired", username=admin)
    assert archived.status_code == 200
    assert archived.json()["archived"] >= 1
    assert _public_get(api, expiring["share_id"], _token(expiring["share_url"])).status_code == 403
    traversal = api.client.get(
        "/api/v1/public/defect-shares/..%2F..%2Fetc%2Fpasswd",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert traversal.status_code in {404, 422}
    assert "root:" not in traversal.text


def test_concurrent_resolve_creates_one_action(api, admin, monkeypatch):
    """两个并发提交只有一次状态变更。"""
    _mock_feishu(monkeypatch)
    project_id = _create_project(api, admin)
    channel_id = _channel(api, admin, project_id)
    bug = _bug(api, admin, project_id)
    created = _share(api, admin, bug["id"], channel_id)
    token = _token(created["share_url"])
    service = DefectShareService()
    body = PublicResolveRequest(repair_description="并发修复登录接口异常处理。")

    def submit():
        session = SessionLocal()
        try:
            return service.resolve_public(session, created["share_id"], token, body)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: submit(), range(2)))
    assert sum(1 for item in results if item.idempotent is False) == 1
    session = SessionLocal()
    try:
        assert session.get(Bug, bug["id"]).status == "已修复"
        assert session.query(DefectExternalAction).filter_by(bug_id=bug["id"]).count() == 1
    finally:
        session.close()
