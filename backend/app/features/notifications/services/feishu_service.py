"""飞书通知发送服务（§十六/§十九/§二十）。

职责：解密 webhook → 构造交互卡片 → 签名 → httpx POST → 记录 NotificationRecord。
- 消息进本服务前必须经 SensitiveDataMasker（§二十）；webhook URL / secret 绝不入
  NotificationRecord.request_snapshot、日志、报告、Agent Prompt（§十五/§三一）。
- 发送失败只记 NotificationRecord.status=FAILED，**不改 TestRun / Report 状态**（§二十八 三者独立）。
- 通知条件（§十七）：ALWAYS / ONLY_FAILED / ONLY_HIGH_RISK；不满足时跳过、不记 FAILED。
- 不在 Agent Node 内写飞书 HTTP 逻辑（§三二）：Agent 只调用本服务的工具包装。

本服务接收**已加载并经权限校验**的 ORM 对象（channel / report），不跨 feature import service，
加载与鉴权由调用方（router / agent 工具）负责。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy.orm import Session

from app.features.agent.providers.sanitizer import sanitize_context, sanitize_text
from app.features.notifications.models.channel import NotificationChannel
from app.features.notifications.models.notification_record import NotificationRecord
from app.shared.crypto import decrypt_secret

if TYPE_CHECKING:
    from app.features.reports.models.report import TestReport

logger = logging.getLogger(__name__)

# 风险等级 → 飞书卡片头部颜色模板（Feishu 模板色）。
_RISK_COLOR = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "orange", "CRITICAL": "red"}


class FeishuNotificationService:
    """飞书 Webhook 通知发送服务。无状态，路由 / Agent 工具复用单例。"""

    def send_report_notification(
        self, db: Session, channel: NotificationChannel, report: "TestReport", *,
        actor_id: int | None = None,
    ) -> NotificationRecord | None:
        """按渠道通知条件发送报告卡片；渠道禁用或条件不满足时返回 None（跳过）。

        任何失败都只落 NotificationRecord(status=FAILED)，不外抛（§二十八）。
        """
        if not channel.enabled:
            return None
        condition = self._config(channel).get("notify_condition", "ALWAYS")
        if not self._should_send(condition, report):
            return None

        card = self._build_card(report)
        config = self._config(channel)
        webhook_url = decrypt_secret(config.get("webhook_url_encrypted"))
        secret = decrypt_secret(config.get("secret_encrypted"))

        if not webhook_url:
            # webhook 解密失败或为空：记 FAILED，不外抛（§二十八 独立记录）。
            return self._record(
                db, channel, report, "FAILED", card, None,
                "webhook 配置无效或解密失败", actor_id,
            )

        timestamp = int(time.time())
        body: dict[str, Any] = {
            "timestamp": str(timestamp),
            "msg_type": "interactive",
            "card": card,
        }
        if secret:
            body["sign"] = self._sign(secret, timestamp)

        try:
            # trust_env=False：直连 webhook，不继承环境代理（§二十八）。
            # httpx.post 每次新建 transport，若继承 socks5 代理而 socksio 缺失，会抛
            # ModuleNotFoundError（非 HTTPError）直接 500，而不是落一条 FAILED 记录。
            resp = httpx.post(
                webhook_url, json=body,
                headers={"Content-Type": "application/json"}, timeout=10, trust_env=False,
            )
        except Exception as exc:  # noqa: BLE001 — 任何失败（含代理导入失败）都只记 FAILED，不外抛。
            logger.warning("飞书通知发送网络异常 channel=%s: %s", channel.id, exc)
            return self._record(db, channel, report, "FAILED", card, None, f"网络异常：{exc}", actor_id)

        try:
            resp_data = resp.json()
        except ValueError:
            resp_data = {"status_code": resp.status_code, "text": resp.text[:300]}

        # 飞书成功响应：{"code":0,"msg":"success",...}；code 缺省视为兼容旧版成功。
        if resp.status_code < 400 and resp_data.get("code") in (0, None):
            return self._record(db, channel, report, "SUCCESS", card, resp_data, None, actor_id)
        err = resp_data.get("msg") or resp_data.get("text") or f"HTTP {resp.status_code}"
        return self._record(db, channel, report, "FAILED", card, resp_data, f"飞书返回失败：{err}", actor_id)

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
        except Exception as exc:  # noqa: BLE001 — 同 send_report_notification，失败落库不外抛。
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
    def _should_send(condition: str, report: "TestReport") -> bool:
        """通知条件判定（§十七）。未知条件按 ALWAYS 宽松处理，避免漏报。"""
        if condition == "ALWAYS":
            return True
        if condition == "ONLY_FAILED":
            return (report.failed_cases or 0) > 0 or (report.error_cases or 0) > 0
        if condition == "ONLY_HIGH_RISK":
            return (report.risk_level or "LOW") in ("HIGH", "CRITICAL")
        return True

    @staticmethod
    def _build_card(report: "TestReport") -> dict[str, Any]:
        """构造飞书交互卡片（§二十二），内容整体经 SensitiveDataMasker。"""
        risk = report.risk_level or "LOW"
        ai = report.ai_summary if isinstance(report.ai_summary, dict) else {}
        overview = sanitize_text(str(ai.get("overview", ""))) if ai else ""
        findings = ai.get("key_findings") if ai else None
        recommendations = ai.get("recommendations") if ai else None

        elements: list[dict[str, Any]] = [
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**总数**\n{report.total_cases}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**通过**\n{report.passed_cases}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**失败**\n{report.failed_cases}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**错误**\n{report.error_cases}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**跳过**\n{report.skipped_cases}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**通过率**\n{report.pass_rate}%"}},
                ],
            },
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**执行耗时**：{report.duration_ms or 0} ms"}},
        ]
        # 安全摘要（§14）：只带计数与标题，不带 Token、不带响应体——evidence 留在
        # 平台 Finding 详情页按需拉取。沿用现有报告卡片，不新增安全专用 webhook。
        security = (report.summary or {}).get("security") if isinstance(report.summary, dict) else None
        if isinstance(security, dict) and security.get("cases"):
            top_titles = [
                sanitize_text(str(item.get("title") or ""))
                for item in (security.get("top_findings") or [])[:3]
                if item.get("title")
            ]
            content = (
                f"**安全**\n{security.get('cases', 0)} 条安全用例，"
                f"{security.get('potential_issues', 0)} 条疑似问题"
                + (f"\n- " + "\n- ".join(top_titles) if top_titles else "")
            )
            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})
        if overview:
            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**AI 总结**\n{overview}"}})
        if findings:
            text = "\n".join(f"- {sanitize_text(str(f))}" for f in list(findings)[:5])
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**主要发现**\n{text}"}})
        if recommendations:
            text = "\n".join(f"- {sanitize_text(str(r))}" for r in list(recommendations)[:5])
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**建议**\n{text}"}})
        elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "接口测试平台 · 自动发送"}]})

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": sanitize_text(f"测试报告 {report.report_no}")},
                "template": _RISK_COLOR.get(risk, "grey"),
            },
            "elements": elements,
        }
        # 卡片内容整体脱敏（§二十）：字段名掩码 + 值形态掩码（webhook / 签名密钥），
        # 防止快照里残留的敏感串被 LLM 回显后发进飞书群。
        return sanitize_context(card)

    @staticmethod
    def _sign(secret: str, timestamp: int) -> str:
        """飞书官方签名算法：HMAC-SHA256(key="timestamp\\nsecret", msg="") → base64。"""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    @staticmethod
    def _record(
        db: Session, channel: NotificationChannel, report: "TestReport | None",
        status: str, card: dict[str, Any] | None, response: dict[str, Any] | None,
        error: str | None, actor_id: int | None,
    ) -> NotificationRecord:
        """落库发送审计记录；webhook URL 绝不入 request_snapshot（§三十一）。"""
        rec = NotificationRecord(
            project_id=channel.project_id,
            channel_id=channel.id,
            report_id=report.id if report is not None else None,
            status=status,
            request_snapshot=sanitize_context(card) if card else None,
            response_snapshot=sanitize_context(response) if response else None,
            error_message=error,
            sent_at=datetime.now() if status != "PENDING" else None,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec
