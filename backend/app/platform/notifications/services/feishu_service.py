"""飞书通知传输服务（§十六/§十九/§二十）。

职责：解密 webhook → 签名 → httpx POST → 记录 NotificationRecord。
- 消息进本服务前必须经 SensitiveDataMasker（§二十）；webhook URL / secret 绝不入
  NotificationRecord.request_snapshot、日志、报告、Agent Prompt（§十五/§三一）。
- 发送失败只记 NotificationRecord.status=FAILED，**不改 TestRun / Report 状态**（§二十八 三者独立）。
- 不在 Agent Node 内写飞书 HTTP 逻辑（§三二）：Agent 只调用本服务的工具包装。

本服务接收已授权的通知渠道和脱敏后的消息卡片；报告规则及卡片内容归报告投递用例。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.security.sanitizer import sanitize_context
from app.platform.notifications.models.channel import NotificationChannel
from app.platform.notifications.models.notification_record import NotificationRecord
from app.core.security.crypto import decrypt_secret

logger = logging.getLogger(__name__)
class FeishuNotificationService:
    """飞书 Webhook 传输与发送审计；业务卡片由调用方提供。"""

    def send_card(
        self, db: Session, channel: NotificationChannel, report_id: int | None,
        card: dict[str, Any], *, actor_id: int | None = None,
        bug_id: int | None = None, share_link_id: int | None = None,
        event_type: str | None = None, idempotency_key: str | None = None,
        retry_count: int = 0,
    ) -> NotificationRecord:
        """发送已由业务用例构建的卡片，并记录传输结果。"""
        status, response, error = self._deliver(channel, card)
        return self._record(
            db, channel, report_id, status, card, response, error, actor_id,
            bug_id=bug_id, share_link_id=share_link_id, event_type=event_type,
            idempotency_key=idempotency_key, retry_count=retry_count,
        )

    def _deliver(
        self, channel: NotificationChannel, card: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None, str | None]:
        """把卡片 POST 到已解密的飞书 Webhook。不写库，供单条和批量共用。"""
        config = self._config(channel)
        webhook_url = decrypt_secret(config.get("webhook_url_encrypted"))
        secret = decrypt_secret(config.get("secret_encrypted"))
        if not webhook_url:
            return "FAILED", None, "webhook 配置无效或解密失败"

        timestamp = int(time.time())
        body: dict[str, Any] = {
            "timestamp": str(timestamp),
            "msg_type": "interactive",
            "card": card,
        }
        if secret:
            body["sign"] = self._sign(secret, timestamp)
        try:
            # trust_env=False：直连 webhook，不继承环境代理，也不把代理账号带进请求。
            resp = httpx.post(
                webhook_url, json=body,
                headers={"Content-Type": "application/json"}, timeout=10, trust_env=False,
            )
        except Exception as exc:  # noqa: BLE001 — 网络和依赖异常都只记 FAILED。
            logger.warning("飞书通知发送网络异常 channel=%s: %s", channel.id, type(exc).__name__)
            return "FAILED", None, f"网络异常：{type(exc).__name__}"
        try:
            resp_data = resp.json()
        except ValueError:
            resp_data = {"status_code": resp.status_code, "text": resp.text[:300]}
        # 飞书成功响应：{"code":0,"msg":"success",...}；code 缺省兼容旧版成功。
        if resp.status_code < 400 and resp_data.get("code") in (0, None):
            return "SUCCESS", resp_data, None
        err = resp_data.get("msg") or resp_data.get("text") or f"HTTP {resp.status_code}"
        return "FAILED", resp_data, f"飞书返回失败：{err}"

    def send_test_card(
        self, db: Session, channel: NotificationChannel, *, actor_id: int | None = None,
    ) -> NotificationRecord:
        """发送测试卡片（连通性验证），不关联报告。"""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "接口测试平台 · 渠道连通性测试"},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": "这是一条测试消息，确认该飞书机器人配置正常。"}},
            ],
        }
        config = self._config(channel)
        webhook_url = decrypt_secret(config.get("webhook_url_encrypted"))
        secret = decrypt_secret(config.get("secret_encrypted"))
        if not webhook_url:
            return self._record(db, channel, None, "FAILED", card, None, "webhook 配置无效或解密失败", actor_id)
        timestamp = int(time.time())
        body: dict[str, Any] = {"timestamp": str(timestamp), "msg_type": "interactive", "card": card}
        if secret:
            body["sign"] = self._sign(secret, timestamp)
        try:
            resp = httpx.post(
                webhook_url, json=body,
                headers={"Content-Type": "application/json"}, timeout=10, trust_env=False,
            )
            resp_data = resp.json()
        except Exception as exc:  # noqa: BLE001 — 测试发送失败也只落审计记录。
            return self._record(db, channel, None, "FAILED", card, None, f"发送异常：{exc}", actor_id)
        if resp.status_code < 400 and resp_data.get("code") in (0, None):
            return self._record(db, channel, None, "SUCCESS", card, resp_data, None, actor_id)
        return self._record(db, channel, None, "FAILED", card, resp_data, f"飞书返回失败：{resp_data.get('msg')}", actor_id)

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _config(channel: NotificationChannel) -> dict[str, Any]:
        """读取飞书通知配置。"""
        return channel.config_json or {}

    @staticmethod
    def _sign(secret: str, timestamp: int) -> str:
        """飞书官方签名算法：HMAC-SHA256(key="timestamp\\nsecret", msg="") → base64。"""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    @staticmethod
    def _record(
        db: Session, channel: NotificationChannel, report_id: int | None,
        status: str, card: dict[str, Any] | None, response: dict[str, Any] | None,
        error: str | None, actor_id: int | None, *,
        bug_id: int | None = None, share_link_id: int | None = None,
        event_type: str | None = None, idempotency_key: str | None = None,
        retry_count: int = 0,
    ) -> NotificationRecord:
        """落库发送审计记录；webhook URL 绝不入 request_snapshot。"""
        rec = NotificationRecord(
            project_id=channel.project_id,
            channel_id=channel.id,
            report_id=report_id,
            bug_id=bug_id,
            share_link_id=share_link_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            retry_count=retry_count,
            status=status,
            # 快照会掩掉卡片里的分享凭证；真正发给飞书的卡片仍保留按钮链接。
            request_snapshot=sanitize_context(card) if card else None,
            response_snapshot=sanitize_context(response) if response else None,
            error_message=error,
            sent_at=datetime.now() if status != "PENDING" else None,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec
