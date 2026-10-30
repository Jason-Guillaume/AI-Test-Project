"""通知渠道服务层（CRUD + 连通性测试）。

安全红线（§十五/§三一）：
- webhook_url / secret 创建/更新时接收明文 → encrypt_secret 加密入 config_json；
- 对外响应**永不**返回明文，只回 webhook_configured（布尔）+ webhook_masked（脱敏 URL）；
- 解密仅在 FeishuNotificationService 发送瞬间发生，不入日志 / 不入 NotificationRecord。

权限：读 viewer+、写 member+、越权与不存在共用 404。service owns commit。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.platform.notifications.models.channel import NotificationChannel
from app.platform.notifications.schemas_channel import (
    ChannelCreateRequest,
    ChannelListResponse,
    ChannelResponse,
    ChannelUpdateRequest,
    NotificationRecordListResponse,
    NotificationRecordResponse,
    SendResultResponse,
)
from app.platform.notifications.services.feishu_service import FeishuNotificationService
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.platform.notifications.models.notification_record import NotificationRecord
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.core.http.errors import bad_request, not_found
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

_FEISHU = FeishuNotificationService()


class ChannelService:
    """通知渠道 CRUD 与连通性测试。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 创建 / 更新

    def create_channel(
        self, db: Session, project_id: int, body: ChannelCreateRequest, actor: User,
    ) -> ChannelResponse:
        """创建渠道。"""
        require_writable_project(db, project_id, actor)
        channel = NotificationChannel(
            project_id=project_id,
            name=body.name,
            channel_type=body.channel_type,
            enabled=body.enabled,
            config_json=self._build_config(body.webhook_url, body.secret, body.notify_condition, body.keyword),
            created_by=actor.id,
        )
        db.add(channel)
        db.commit()
        db.refresh(channel)
        return self._to_response(channel)

    def update_channel(
        self, db: Session, channel_id: int, body: ChannelUpdateRequest, actor: User,
    ) -> ChannelResponse:
        """更新渠道。"""
        channel = self.get_channel_orm(db, channel_id, actor)
        require_writable_project(db, channel.project_id, actor)
        if body.name is not None:
            channel.name = body.name
        if body.enabled is not None:
            channel.enabled = body.enabled
        config = dict(channel.config_json or {})
        # webhook_url / secret：不传（undefined）表示不变；显式提供则覆盖加密。
        if body.webhook_url is not None:
            # 空串或非法 URL 一律拒绝，而不是静默覆盖：否则会抹掉已存凭据、
            # 却仍返回 200 与 webhook_configured=true，之后每次通知都失败。
            if not body.webhook_url or not str(body.webhook_url).startswith("http"):
                raise bad_request("webhook URL 必须以 http 开头")
            config["webhook_url_encrypted"] = encrypt_secret(body.webhook_url)
        if body.secret is not None:
            # 空串表示清除签名；非空则加密覆盖。
            config["secret_encrypted"] = encrypt_secret(body.secret) if body.secret else ""
        if body.notify_condition is not None:
            config["notify_condition"] = body.notify_condition
        if body.keyword is not None:
            config["keyword"] = body.keyword
        channel.config_json = config
        db.commit()
        db.refresh(channel)
        return self._to_response(channel)

    # ---------------------------------------------------------------- 查询 / 删除

    def get_channel(self, db: Session, channel_id: int, user: User) -> ChannelResponse:
        """获取渠道。"""
        channel = self.get_channel_orm(db, channel_id, user)  # viewer+ 及以上角色
        return self._to_response(channel)

    def list_channels(
        self, db: Session, project_id: int, user: User, *,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ChannelListResponse:
        """列出`channels`。"""
        get_project_or_404(db, project_id, user)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        q = db.query(NotificationChannel).filter(NotificationChannel.project_id == project_id)
        total = int(q.count())
        rows = q.order_by(NotificationChannel.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return ChannelListResponse(
            items=[self._to_response(r) for r in rows], total=total, page=page, page_size=page_size,
        )

    def delete_channel(self, db: Session, channel_id: int, user: User) -> None:
        """删除渠道。"""
        channel = self.get_channel_orm(db, channel_id, user)
        require_writable_project(db, channel.project_id, user)
        db.delete(channel)
        db.commit()

    # ---------------------------------------------------------------- 连通性测试

    def test_channel(self, db: Session, channel_id: int, user: User) -> SendResultResponse:
        """发送测试卡片验证渠道；触发外发故要求 member+。"""
        channel = self.get_channel_orm(db, channel_id, user)
        require_writable_project(db, channel.project_id, user)
        record = _FEISHU.send_test_card(db, channel, actor_id=user.id)
        return SendResultResponse(
            record_id=record.id, status=record.status, error_message=record.error_message, skipped=False,
        )

    # ---------------------------------------------------------------- 发送记录审计

    def list_records_by_channel(
        self, db: Session, channel_id: int, user: User, *,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> NotificationRecordListResponse:
        """某渠道的发送记录（viewer+ 渠道可见即可读审计）。"""
        channel = self.get_channel_orm(db, channel_id, user)
        return self._list_records(
            db, channel.project_id, NotificationRecord.channel_id == channel_id, page, page_size,
        )

    def list_records_for_report(
        self, db: Session, project_id: int, report_id: int, *,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> NotificationRecordListResponse:
        """某报告的发送记录；project_id 由调用方（路由）在鉴权后传入。"""
        return self._list_records(
            db, project_id, NotificationRecord.report_id == report_id, page, page_size,
        )

    def _list_records(
        self, db: Session, project_id: int, extra_filter, page: int, page_size: int,
    ) -> NotificationRecordListResponse:
        """列出记录。"""
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        q = db.query(NotificationRecord).filter(
            NotificationRecord.project_id == project_id, extra_filter,
        )
        total = int(q.count())
        rows = q.order_by(NotificationRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return NotificationRecordListResponse(
            items=[NotificationRecordResponse.model_validate(r) for r in rows],
            total=total, page=page, page_size=page_size,
        )

    # ---------------------------------------------------------------- 内部

    def get_channel_orm(self, db: Session, channel_id: int, user: User) -> NotificationChannel:
        """取渠道 ORM（viewer+ 鉴权），供飞书发送等需读 config_json 的调用方使用。"""
        channel = db.get(NotificationChannel, channel_id)
        if channel is None:
            raise not_found("通知渠道不存在")
        get_project_or_404(db, channel.project_id, user)
        return channel

    def resolve_channel(
        self, db: Session, project_id: int, user: User, *, channel_id: int | None = None,
    ) -> NotificationChannel | None:
        """解析发送渠道：显式 channel_id 优先（须同项目），否则取项目首个 enabled 渠道。

        返回 None 表示项目内没有可用渠道——调用方应「跳过」而不是「失败」（§十七/§二十八）。
        统一放在本服务，REST 路由与 Agent 工具走同一套解析逻辑，行为一致。
        """
        if channel_id:
            channel = self.get_channel_orm(db, channel_id, user)  # viewer+ 及以上角色无权访问时返回 404
            if channel.project_id != project_id:
                raise not_found("通知渠道不存在")
            return channel
        return (
            db.query(NotificationChannel)
            .filter(NotificationChannel.project_id == project_id, NotificationChannel.enabled.is_(True))
            .order_by(NotificationChannel.id.asc())
            .first()
        )

    @staticmethod
    def _build_config(
        webhook_url: str, secret: str | None, notify_condition: str, keyword: str | None,
    ) -> dict[str, Any]:
        """构造 config_json：webhook/secret 加密，keyword/notify_condition 明文。"""
        if not webhook_url or not str(webhook_url).startswith("http"):
            raise bad_request("webhook URL 必须以 http 开头")
        return {
            "webhook_url_encrypted": encrypt_secret(webhook_url),
            "secret_encrypted": encrypt_secret(secret) if secret else "",
            "notify_condition": notify_condition or "ALWAYS",
            "keyword": keyword,
        }

    @classmethod
    def _to_response(cls, channel: NotificationChannel) -> ChannelResponse:
        """构造脱敏响应：webhook_url/secret 绝不回吐。"""
        config = channel.config_json or {}
        encrypted_url = config.get("webhook_url_encrypted")
        plain_url = decrypt_secret(encrypted_url) if encrypted_url else ""
        return ChannelResponse(
            id=channel.id,
            project_id=channel.project_id,
            name=channel.name,
            channel_type=channel.channel_type,
            enabled=channel.enabled,
            notify_condition=config.get("notify_condition", "ALWAYS"),
            webhook_configured=bool(encrypted_url),
            webhook_masked=cls._mask_url(plain_url) if plain_url else "(未配置或解密失败)",
            keyword=config.get("keyword"),
            created_by=channel.created_by,
            created_at=channel.created_at,
            updated_at=channel.updated_at,
        )

    @staticmethod
    def _mask_url(url: str) -> str:
        """脱敏 webhook URL：只保留 scheme+host，路径部分以 ...**** 替代（§十五）。

        用 parsed.hostname 而不是 parsed.netloc：urlparse 会把 userinfo 留在 netloc 里
        （https://user:pass@host/...），照抄就会把 URL 里的账号密码回显给前端。
        """
        if not url:
            return ""
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.hostname:
            return "...****"
        return f"{parsed.scheme}://{parsed.hostname}/...****"
