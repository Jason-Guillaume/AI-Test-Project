"""Env-gated live Feishu webhook integration test (requires explicit isolated test webhook)."""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

import pytest

from app.core.security.crypto import encrypt_secret
from app.core.security.sanitizer import sanitize_context
from app.orchestration.report_delivery.card_builder import build_defect_share_card
from app.platform.notifications.services.feishu_service import FeishuNotificationService


def _enabled() -> bool:
    return os.getenv("FEISHU_INTEGRATION_ENABLED", "").strip().lower() == "true"


@pytest.mark.skipif(
    not _enabled(),
    reason="BLOCKED: 需要显式设置 FEISHU_INTEGRATION_ENABLED=true 及受控隔离测试群 FEISHU_TEST_WEBHOOK_URL",
)
def test_live_feishu_webhook_card_delivery():
    import httpx

    webhook_url = (os.getenv("FEISHU_TEST_WEBHOOK_URL") or "").strip()
    secret = (os.getenv("FEISHU_TEST_SECRET") or "").strip()
    keyword = (os.getenv("FEISHU_TEST_KEYWORD") or "验收").strip()
    assert webhook_url, "FEISHU_TEST_WEBHOOK_URL must be configured"

    ts = int(time.time())
    body: dict[str, object] = {
        "timestamp": str(ts),
        "msg_type": "text",
        "content": {"text": f"[质量验收探测] 飞书连通性与签名验证 ({keyword})"},
    }
    if secret:
        body["sign"] = FeishuNotificationService._sign(secret, ts)

    resp = httpx.post(webhook_url, json=body, headers={"Content-Type": "application/json"}, timeout=10, trust_env=False)
    assert resp.status_code == 200
    assert resp.json().get("code") == 0

    # 验证真实交互卡片（含中文长文本、HTML 转义、JWT/Bearer 脱敏及按钮分享链接）投递成功
    sample_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0In0.sig1234567890"
    share_token = "live-test-ephemeral-token-0001"
    card = build_defect_share_card(
        [
            {
                "bug_no": "BUG-LIVE-VERIFY",
                "title": "【飞书群真实联调】中文长文本与 <script> 转义卡片验证",
                "severity_label": "P1",
                "status": "待确认",
                "project_name": "AI-Test-Project",
                "summary": f"校验 Bearer live_bearer_secret_xyz 与 {sample_jwt} 脱敏，" + ("中文长文本展示与截断校验。" * 15),
                "steps_summary": "1. 推送交互卡片\n2. 点击查看缺陷详情跳转按钮",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "share_url": f"https://qa.example.com/public/defects/share/live-demo#token={share_token}",
            }
        ],
        channel_name="飞书隔离测试群",
        pusher_name="integration-test",
        expires_label="7 天",
        allow_resolve=True,
        keyword=keyword,
    )
    rendered = json.dumps(card, ensure_ascii=False)
    assert sample_jwt not in rendered
    assert "live_bearer_secret_xyz" not in rendered
    assert "<script>" not in rendered
    assert f"#token={share_token}" in rendered

    snapshot = json.dumps(sanitize_context(card), ensure_ascii=False)
    assert share_token not in snapshot

    channel = SimpleNamespace(
        id=1,
        project_id=1,
        config_json={
            "webhook_url_encrypted": encrypt_secret(webhook_url),
            "secret_encrypted": encrypt_secret(secret) if secret else "",
        },
    )
    service = FeishuNotificationService()
    status, resp_data, error = service._deliver(channel, card)
    assert status == "SUCCESS", (status, resp_data, error)
    assert resp_data and resp_data.get("code") in (0, None)
