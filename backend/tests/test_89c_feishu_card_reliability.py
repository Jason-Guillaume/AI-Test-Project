"""飞书卡片内容安全、签名、长文本边界、超时/失败重试及幂等性专项测试。"""
from __future__ import annotations

import base64
import hashlib
import hmac

import httpx

from app.core.config import settings
from app.orchestration.report_delivery.card_builder import build_defect_share_card
from app.platform.notifications.models.notification_record import NotificationRecord
from tests.conftest import unique


def test_defect_share_card_sanitizes_chinese_special_chars_and_bounds_long_text():
    sample_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    long_title = "【紧急】支付链路 <script>alert(1)</script> " + "异常详情" * 80
    long_summary = (
        f"步骤：\n1. **加粗注入**\n2. token=secret_abc_123 Bearer raw_bearer_secret_456 JWT={sample_jwt} "
        + "日志内容" * 300
    )
    card = build_defect_share_card(
        [
            {
                "bug_no": "BUG-42",
                "title": long_title,
                "severity_label": "P1",
                "status": "待确认",
                "project_name": "核心交易",
                "summary": long_summary,
                "steps_summary": "1. 打开页面\n2. 点击提交",
                "created_at": "2026-11-17 12:00:00",
                "share_url": "https://qa.company.com/public/defects/share/s1#token=tok_hidden",
            }
        ],
        channel_name="产研协同群",
        pusher_name="tester_a",
        expires_label="7 天有效",
        allow_resolve=True,
        keyword="测试告警",
        part=1,
        parts=1,
    )

    serialized = str(card)
    assert "<script>" not in serialized
    assert "raw_bearer_secret_456" not in serialized
    assert sample_jwt not in serialized
    assert "secret_abc_123" not in serialized
    assert len(serialized) < 25_000
    assert "产研协同群" in serialized
    assert "tester_a" in serialized
    assert "https://qa.company.com/public/defects/share/s1#token=tok_hidden" in serialized


def test_batch_cards_keep_one_button_for_all_supported_batch_sizes():
    """1、2、8、30 条缺陷都只展示一个批次入口按钮。"""
    base = {
        "bug_no": "BUG-42", "title": "批量缺陷", "severity_label": "高", "status": "待确认",
        "project_name": "核心交易", "summary": "已脱敏摘要", "steps_summary": "1. 重现",
        "created_at": "2026-11-18", "share_url": "https://qa.company.com/public/defects/share/batch/b1#token=tok",
    }
    for count in (1, 2, 8, 30):
        card = build_defect_share_card(
            [base.copy() for _ in range(count)], channel_name="研发群", pusher_name="tester",
            expires_label="7 天有效", allow_resolve=True,
        )
        actions = [item for item in card["elements"] if item.get("tag") == "action"]
        assert len(actions) == 1
        assert len(actions[0]["actions"]) == 1
        assert f"{count} 条" in card["header"]["title"]["content"]


def test_feishu_delivery_signature_timeout_and_retry_idempotency(api, db, admin, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_APP_BASE_URL", "https://qa.company.com")
    proj = api.post("/projects", username=admin, json={"name": unique("feishu-rel")}).json()
    secret = "feishu-signing-secret-xyz"
    channel = api.post(
        f"/projects/{proj['id']}/notification-channels",
        username=admin,
        json={
            "name": "质量通报群",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/rel-test",
            "secret": secret,
            "enabled": True,
        },
    ).json()
    bug = api.post(
        "/bugs",
        username=admin,
        json={"project_id": proj["id"], "title": "中文及特殊符号 '#@& 测试缺陷", "severity": 3},
    ).json()

    captured_requests = []

    def timeout_post(url, json=None, **kwargs):
        captured_requests.append(json)
        raise httpx.TimeoutException("read timeout")

    monkeypatch.setattr("app.platform.notifications.services.feishu_service.httpx.post", timeout_post)
    first = api.post(f"/bugs/{bug['id']}/shares", username=admin, json={"channel_id": channel["id"]})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["notification_status"] == "UNCERTAIN"
    assert first_body["retry_count"] == 0
    assert len(captured_requests) == 1

    # Verify Feishu HMAC-SHA256 signature matches exact Feishu formula: base64(hmac_sha256("{timestamp}\n{secret}", "")).
    ts = captured_requests[0]["timestamp"]
    expected_sign = base64.b64encode(
        hmac.new(f"{ts}\n{secret}".encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    ).decode("utf-8")
    assert captured_requests[0]["sign"] == expected_sign

    guarded = api.post(
        f"/bugs/{bug['id']}/shares/{first_body['share_id']}/retry", username=admin, json={},
    )
    assert guarded.status_code == 409
    assert "结果待确认" in guarded.json()["message"]
    assert len(captured_requests) == 1

    # Next attempt with Feishu code != 0 followed by 200 success creates distinct idempotent records.
    def error_code_post(url, json=None, **kwargs):
        captured_requests.append(json)

        class Resp:
            status_code = 200
            text = '{"code":19021,"msg":"sign fail"}'

            def json(self):
                return {"code": 19021, "msg": "sign fail"}

        return Resp()

    monkeypatch.setattr("app.platform.notifications.services.feishu_service.httpx.post", error_code_post)
    retry1 = api.post(
        f"/bugs/{bug['id']}/shares/{first_body['share_id']}/retry", username=admin,
        json={"confirm_uncertain": True},
    )
    assert retry1.status_code == 200
    assert retry1.json()["notification_status"] == "FAILED"
    assert retry1.json()["retry_count"] == 1

    def ok_post(url, json=None, **kwargs):
        captured_requests.append(json)

        class Resp:
            status_code = 200
            text = '{"code":0,"msg":"success"}'

            def json(self):
                return {"code": 0, "msg": "success"}

        return Resp()

    monkeypatch.setattr("app.platform.notifications.services.feishu_service.httpx.post", ok_post)
    retry2 = api.post(f"/bugs/{bug['id']}/shares/{first_body['share_id']}/retry", username=admin, json={})
    assert retry2.status_code == 200
    assert retry2.json()["notification_status"] == "SUCCESS"
    assert retry2.json()["retry_count"] == 2

    records = (
        db.query(NotificationRecord)
        .filter(NotificationRecord.bug_id == bug["id"])
        .order_by(NotificationRecord.id.asc())
        .all()
    )
    assert len(records) == 3
    assert records[0].idempotency_key.startswith("defect-share:")
    assert [r.idempotency_key for r in records[1:]] == [
        f"defect-share-retry:{first_body['share_id']}:1",
        f"defect-share-retry:{first_body['share_id']}:2",
    ]
    assert [r.status for r in records] == ["UNCERTAIN", "FAILED", "SUCCESS"]
    # Neither NotificationRecord snapshot nor error fields contain webhook secret.
    for rec in records:
        assert secret not in str(rec.request_snapshot or "")
        assert secret not in str(rec.response_snapshot or "")
        assert secret not in str(rec.error_message or "")
