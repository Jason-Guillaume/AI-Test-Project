"""Env-gated live Feishu webhook integration test (requires explicit isolated test webhook)."""
from __future__ import annotations

import os

import pytest

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
    assert webhook_url, "FEISHU_TEST_WEBHOOK_URL must be configured"

    import time

    ts = int(time.time())
    body: dict[str, object] = {
        "timestamp": str(ts),
        "msg_type": "text",
        "content": {"text": f"[质量验收探测] 飞书连通性与签名验证 ({os.getenv('FEISHU_TEST_KEYWORD', '验收')})"},
    }
    if secret:
        body["sign"] = FeishuNotificationService._sign(secret, ts)

    resp = httpx.post(webhook_url, json=body, headers={"Content-Type": "application/json"}, timeout=10, trust_env=False)
    assert resp.status_code == 200
    assert resp.json().get("code") == 0
