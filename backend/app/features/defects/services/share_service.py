"""缺陷分享、飞书推送和免登录修复。

创建分享时生成 256 bit 凭证，数据库只留 SHA-256。飞书发送复用
FeishuNotificationService，不新写 Webhook 客户端。状态变更复用 DefectService，
公开接口不能直接改缺陷 ORM。
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.http.errors import bad_request, conflict, forbidden, not_found
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.security.crypto import decrypt_secret
from app.core.security.roles import (
    PROJECT_ROLE_EDITOR,
    has_project_role,
    is_platform_admin,
    project_role_for,
)
from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.core.security.sensitive import is_sensitive_key
from app.features.defects.models.bug import Bug
from app.features.defects.models.share import DefectExternalAction, DefectShareLink
from app.features.defects.models.source_link import DefectSourceLink
from app.features.defects.schemas import SEVERITY_LABELS
from app.features.defects.schemas_share import (
    BatchShareRequest,
    BatchShareResponse,
    ExternalActionResponse,
    PublicDefectResponse,
    PublicResolutionResponse,
    PublicResolveRequest,
    PublicResolveResponse,
    RevokeBatchRequest,
    ShareDetailResponse,
    ShareListResponse,
    ShareNotificationResponse,
    ShareOptions,
    SharePreviewRequest,
    SharePreviewResponse,
    SharePushResponse,
    ShareRetryRequest,
    ShareSummaryResponse,
)
from app.features.defects.services.defect_service import DefectService
from app.orchestration.report_delivery.card_builder import build_defect_share_card
from app.platform.notifications.models.channel import NotificationChannel
from app.platform.notifications.models.notification_record import NotificationRecord
from app.platform.notifications.services.channel_service import ChannelService
from app.platform.notifications.services.feishu_service import FeishuNotificationService
from app.platform.projects.services.access_service import check_writable

DEFAULT_VISIBLE_FIELDS = (
    "bug_no", "title", "severity", "status", "project_name", "description",
    "steps_to_reproduce", "environment", "expected_result", "actual_result",
    "created_at", "source_summary", "reporter", "assignee",
)
OPTIONAL_VISIBLE_FIELDS = (
    "api_execution", "agent_execution", "security_record", "request_response",
    "error_stack", "screenshots", "allure",
)
ALL_VISIBLE_FIELDS = set(DEFAULT_VISIBLE_FIELDS) | set(OPTIONAL_VISIBLE_FIELDS)
_CARD_CHUNK = 8
_PATH_PATTERN = re.compile(
    r"(?i)(?:[a-z]:\\[^\s\"']+|/(?:users|home|var|etc|opt|tmp|usr|private|app)(?:/[^\s\"']*)?"
    r"|postgres(?:ql)?://\S+|mysql://\S+|mongodb(?:\+srv)?://\S+|redis://\S+)"
)
_TAG_PATTERN = re.compile(r"<[^>]*>")
_COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{7,64}")
_IDENTITY_NOTE = "开发人员姓名为自报信息，平台未认证其飞书或内部身份。"


def _clean_text(value: str | None, limit: int = 2000) -> str | None:
    """去掉标记、凭证和内部路径，并限制公开文本长度。"""
    if value is None:
        return None
    text = _TAG_PATTERN.sub("", value)
    text = sanitize_text(text) or ""
    text = _PATH_PATTERN.sub("[内部路径已隐藏]", text).strip()
    if not text:
        return None
    return text[:limit]


def _clean_json(value: Any, depth: int = 0) -> Any:
    """递归清理可公开的 JSON。敏感键和路径直接丢弃，不替换成掩码后继续展示。"""
    if depth > 6:
        return None
    masked = sanitize_context(value)
    return _walk_public_json(masked, depth)


def _walk_public_json(value: Any, depth: int) -> Any:
    """在已经按字段名脱敏的对象上继续删除路径和超长结构。"""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:40]:
            normalized = str(key)
            if is_sensitive_key(normalized) or normalized.lower() in {
                "traceback", "stack", "file", "filename", "filepath", "file_path",
                "path", "local_path", "dsn", "database_url", "connection_string",
            }:
                continue
            result[normalized[:80]] = _walk_public_json(item, depth + 1)
        return result
    if isinstance(value, list):
        return [_walk_public_json(item, depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return _clean_text(value, 1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _clean_text(str(value), 200)


def _screenshot_urls(value: Any) -> list[str]:
    """只保留字段名明确是截图、且本身是 https 链接的地址。"""
    found: list[str] = []

    def walk(item: Any, key: str = "") -> None:
        if len(found) >= 5:
            return
        if isinstance(item, dict):
            for child_key, child in item.items():
                walk(child, str(child_key))
        elif isinstance(item, list):
            for child in item:
                walk(child, key)
        elif isinstance(item, str) and any(word in key.lower() for word in ("screenshot", "image", "img")):
            lowered = item.lower()
            if item.startswith("https://") and "token" not in lowered and "hook" not in lowered and len(item) < 300:
                found.append(item)

    walk(value)
    return found


def _hash_token(token: str) -> str:
    """计算凭证哈希。比较时必须走常量时间函数。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    """生成至少 256 bit 的 URL 安全凭证。"""
    return secrets.token_urlsafe(32)


def _new_share_id() -> str:
    """生成公开标识。它不是访问凭证，可以出现在路径里。"""
    return secrets.token_urlsafe(12)


_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_LOCAL_SUFFIXES = (".local", ".localhost", ".internal")
_FEISHU_WEBHOOK_SUFFIXES = (
    "open.feishu.cn",
    ".feishu.cn",
    ".larksuite.com",
    ".feishu.net",
)


def _is_dev_or_local_host(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if not host or host in _LOCAL_HOSTNAMES or host.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local or ip_obj.is_unspecified


def _is_external_feishu_webhook(webhook_url: str | None) -> bool:
    if not webhook_url:
        return False
    host = (urlsplit(webhook_url).hostname or "").strip().lower().rstrip(".")
    return host in {"feishu.cn", "larksuite.com", "feishu.net"} or host.endswith(_FEISHU_WEBHOOK_SUFFIXES)


def validate_public_share_base_url(webhook_url: str | None = None) -> tuple[bool, str | None]:
    """校验 PUBLIC_APP_BASE_URL 是否允许用于生成飞书卡片中的免登录链接。"""
    base = (settings.PUBLIC_APP_BASE_URL or "").strip().rstrip("/")
    if not base:
        return False, "未配置 PUBLIC_APP_BASE_URL，无法生成可从飞书访问的绝对分享链接；不能推送相对路径。"

    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return False, "PUBLIC_APP_BASE_URL 配置格式无效，须为不含凭据或查询串的完整 URL。"

    is_prod = (settings.APP_ENV or "").strip().lower() in {"prod", "production"}
    is_local = _is_dev_or_local_host(parsed.hostname)

    if is_prod:
        if parsed.scheme != "https":
            return False, "生产环境必须为 PUBLIC_APP_BASE_URL 配置完整的 HTTPS 域名。"
        if is_local:
            return False, "生产环境不允许将 localhost 或私网开发地址作为 PUBLIC_APP_BASE_URL 推送到飞书群。"

    if _is_external_feishu_webhook(webhook_url) and (parsed.scheme != "https" or is_local):
        return False, "不允许把开发环境或非 HTTPS 地址推送到飞书群，请配置公网可访问的 HTTPS 域名。"

    return True, None


def _channel_webhook_url(channel: NotificationChannel) -> str:
    return decrypt_secret((channel.config_json or {}).get("webhook_url_encrypted")) or ""


def archive_expired_shares(db: Session, *, batch_size: int = 500) -> int:
    """幂等批量归档已过期的缺陷分享链接。归档仅标记 archived_at，保留全部审计与通知记录。"""
    now = datetime.now()
    rows = (
        db.query(DefectShareLink)
        .filter(
            DefectShareLink.archived_at.is_(None),
            DefectShareLink.expires_at.is_not(None),
            DefectShareLink.expires_at <= now,
        )
        .order_by(DefectShareLink.id.asc())
        .limit(batch_size)
        .all()
    )
    if not rows:
        return 0
    for row in rows:
        row.archived_at = now
    db.commit()
    return len(rows)


def build_share_url(share_id: str, token: str) -> str:
    """拼免登录地址。凭证放在 Fragment，避免进入访问日志和 Referer。"""
    base = (settings.PUBLIC_APP_BASE_URL or "").strip().rstrip("/")
    path = f"/public/defects/share/{share_id}#token={token}"
    return f"{base}{path}" if base else path


class DefectShareService:
    """缺陷分享用例。服务层提交事务，路由层只做认证和响应映射。"""

    def __init__(self) -> None:
        """复用缺陷权限、渠道读取和飞书传输，不复制这三套实现。"""
        self.defects = DefectService()
        self.channels = ChannelService()
        self.feishu = FeishuNotificationService()

    def preview(self, db: Session, body: SharePreviewRequest, actor: User) -> SharePreviewResponse:
        """生成确认框预览。不写分享、不调用飞书。"""
        bugs = self._bugs(db, body.bug_ids, actor)
        channel = self._channel(db, bugs[0], body.channel_id, actor)
        fields = self._fields(body.visible_fields)
        self._expiry(db, bugs[0].project_id, actor, body)
        url_ok, url_err = validate_public_share_base_url(_channel_webhook_url(channel))
        names = "、".join(bug.title for bug in bugs[:8])
        return SharePreviewResponse(
            defect_count=len(bugs),
            channel_name=channel.name,
            channel_enabled=bool(channel.enabled),
            webhook_configured=bool((channel.config_json or {}).get("webhook_url_encrypted")),
            expires_label=self._expires_label(body),
            allow_resolve=body.allow_resolve,
            visible_fields=fields,
            public_url_valid=url_ok,
            public_url_error=url_err,
            message_preview=(
                f"将向「{channel.name}」推送 {len(bugs)} 条缺陷。\n"
                f"有效期：{self._expires_label(body)}。\n"
                f"允许开发人员提交已解决：{'是' if body.allow_resolve else '否'}。\n"
                f"展示字段：{'、'.join(fields)}。\n"
                f"缺陷：{names}"
            ),
        )

    def create(self, db: Session, bug_id: int, body: ShareOptions, actor: User) -> SharePushResponse:
        """为一条缺陷创建独立分享并推送到已有飞书渠道。"""
        result = self.create_batch(db, BatchShareRequest(bug_ids=[bug_id], **body.model_dump()), actor)
        return result.items[0]

    def create_batch(self, db: Session, body: BatchShareRequest, actor: User) -> BatchShareResponse:
        """批量创建分享。每条缺陷一张独立凭证，飞书侧按数量合并卡片。"""
        bugs = self._bugs(db, body.bug_ids, actor)
        channel = self._channel(db, bugs[0], body.channel_id, actor)
        url_ok, url_err = validate_public_share_base_url(_channel_webhook_url(channel))
        if not url_ok:
            raise bad_request(url_err or "PUBLIC_APP_BASE_URL 配置无效")
        fields = self._fields(body.visible_fields)
        expires_at = self._expiry(db, bugs[0].project_id, actor, body)
        created: list[tuple[DefectShareLink, str, Bug]] = []
        for bug in bugs:
            token = _new_token()
            share = DefectShareLink(
                share_id=self._unique_share_id(db),
                bug_id=bug.id,
                project_id=bug.project_id,
                channel_id=channel.id,
                token_hash=_hash_token(token),
                allow_view=body.allow_view,
                allow_resolve=body.allow_resolve,
                visible_fields=fields,
                content_snapshot=self._snapshot(db, bug, fields),
                expires_at=expires_at,
                pushed_by=actor.id,
                pushed_at=datetime.now(),
            )
            db.add(share)
            created.append((share, token, bug))
        db.flush()
        responses: list[SharePushResponse] = []
        card_count = 0
        for offset in range(0, len(created), _CARD_CHUNK):
            chunk = created[offset:offset + _CARD_CHUNK]
            card_count += 1
            records = self._dispatch(
                db, channel, [item[0] for item in chunk], [item[1] for item in chunk], actor,
                part=card_count, parts=(len(created) + _CARD_CHUNK - 1) // _CARD_CHUNK,
            )
            for (share, token, _bug), record in zip(chunk, records):
                responses.append(self._push_response(share, token, channel, record))
        return BatchShareResponse(items=responses, card_count=card_count)

    def retry(
        self, db: Session, bug_id: int, share_id: str, body: ShareRetryRequest, actor: User,
    ) -> SharePushResponse:
        """重发同一条分享。没有原凭证时轮换哈希，不新增分享行。"""
        share = self._managed_share(db, bug_id, share_id, actor)
        if share.revoked_at is not None:
            raise conflict("分享链接已撤销，不能重新推送")
        if share.archived_at is not None:
            raise conflict("分享链接已归档，请重新创建分享")
        if share.expires_at is not None and share.expires_at <= datetime.now():
            raise conflict("分享链接已过期，请重新创建分享")
        if share.channel_id is None:
            raise bad_request("原飞书渠道已删除，请重新创建分享")
        channel = self._channel(db, self._bug_of(db, share), share.channel_id, actor)
        url_ok, url_err = validate_public_share_base_url(_channel_webhook_url(channel))
        if not url_ok:
            raise bad_request(url_err or "PUBLIC_APP_BASE_URL 配置无效")
        if body.access_token:
            # 客户端还持有创建时返回的凭证时，核对后原样重发，避免无意义轮换。
            if not hmac.compare_digest(_hash_token(body.access_token), share.token_hash):
                raise forbidden("访问凭证不正确，没有重新推送")
            token = body.access_token
        else:
            token = _new_token()
            share.token_hash = _hash_token(token)
        share.retry_count = int(share.retry_count or 0) + 1
        db.flush()
        record = self._dispatch(db, channel, [share], [token], actor, part=1, parts=1)[0]
        return self._push_response(share, token, channel, record)

    def list_shares(self, db: Session, bug_id: int, actor: User) -> ShareListResponse:
        """返回一个缺陷的分享历史。凭证明文不可再取回。"""
        self.defects.get_bug_or_404(db, bug_id, actor)
        rows = (
            db.query(DefectShareLink)
            .filter(DefectShareLink.bug_id == bug_id)
            .order_by(DefectShareLink.id.desc())
            .all()
        )
        return ShareListResponse(items=[self._summary(db, row) for row in rows])

    def get_share(self, db: Session, bug_id: int, share_id: str, actor: User) -> ShareDetailResponse:
        """返回分享快照、外部处理和飞书投递结果。"""
        share = self._visible_share(db, bug_id, share_id, actor)
        summary = self._summary(db, share)
        actions = (
            db.query(DefectExternalAction)
            .filter(DefectExternalAction.share_link_id == share.id)
            .order_by(DefectExternalAction.id.desc())
            .all()
        )
        records = (
            db.query(NotificationRecord)
            .filter(NotificationRecord.share_link_id == share.id)
            .order_by(NotificationRecord.id.desc())
            .all()
        )
        return ShareDetailResponse(
            **summary.model_dump(),
            visible_fields=list(share.visible_fields or []),
            content_snapshot=dict(share.content_snapshot or {}),
            external_actions=[self._action_response(item) for item in actions],
            notifications=[
                ShareNotificationResponse(
                    id=item.id, status=item.status, error_message=item.error_message,
                    retry_count=int(item.retry_count or 0), sent_at=item.sent_at, created_at=item.created_at,
                )
                for item in records
            ],
        )

    def revoke(self, db: Session, bug_id: int, share_id: str, actor: User) -> ShareSummaryResponse:
        """撤销一条分享。同一缺陷的其他分享不受影响。"""
        share = self._managed_share(db, bug_id, share_id, actor)
        if share.revoked_at is None:
            share.revoked_at = datetime.now()
            db.commit()
            db.refresh(share)
        return self._summary(db, share)

    def revoke_batch(self, db: Session, body: RevokeBatchRequest, actor: User) -> list[ShareSummaryResponse]:
        """批量撤销。任一分享不存在或无权时整批回滚。"""
        shares = [self._managed_share(db, item.bug_id, item.share_id, actor) for item in body.items]
        now = datetime.now()
        for share in shares:
            if share.revoked_at is None:
                share.revoked_at = now
        db.commit()
        return [self._summary(db, share) for share in shares]

    def archive_expired(self, db: Session, actor: User) -> int:
        """把已经过期的分享标记为归档。不删除审计，也不影响未过期链接。"""
        if not is_platform_admin(actor):
            raise forbidden("只有平台管理员可以归档过期分享")
        archived = 0
        while True:
            batch = archive_expired_shares(db, batch_size=500)
            archived += batch
            if batch < 500:
                break
        return archived

    def active_counts(self, db: Session, bug_ids: list[int]) -> dict[int, int]:
        """统计仍可访问的分享数量，供缺陷列表显示已推送。"""
        if not bug_ids:
            return {}
        now = datetime.now()
        rows = (
            db.query(DefectShareLink.bug_id, DefectShareLink.id)
            .join(Bug, Bug.id == DefectShareLink.bug_id)
            .filter(
                DefectShareLink.bug_id.in_(bug_ids),
                Bug.deleted_at.is_(None),
                DefectShareLink.revoked_at.is_(None),
                DefectShareLink.archived_at.is_(None),
                or_(DefectShareLink.expires_at.is_(None), DefectShareLink.expires_at > now),
            )
            .all()
        )
        counts: dict[int, int] = {}
        for bug_id, _share_row_id in rows:
            counts[bug_id] = counts.get(bug_id, 0) + 1
        return counts

    def view_public(self, db: Session, share_id: str, token: str) -> PublicDefectResponse:
        """校验凭证并返回授权字段。GET 不写访问次数，也不改变缺陷。"""
        share = self._authenticated_share(db, share_id, token)
        self._ensure_readable(share)
        bug = self._public_bug(db, share)
        return self._public_response(db, share, bug)

    def record_view(self, db: Session, share_id: str, token: str) -> None:
        """记录一次公开页访问。必须由 POST 调用，避免 GET 产生写入，且原子递增计数。"""
        share = self._authenticated_share(db, share_id, token)
        self._ensure_readable(share)
        self._public_bug(db, share)
        now = datetime.now()
        db.query(DefectShareLink).filter(DefectShareLink.id == share.id).update(
            {
                DefectShareLink.view_count: func.coalesce(DefectShareLink.view_count, 0) + 1,
                DefectShareLink.last_viewed_at: now,
            },
            synchronize_session=False,
        )
        db.commit()

    def resolve_public(
        self, db: Session, share_id: str, token: str, body: PublicResolveRequest,
    ) -> PublicResolveResponse:
        """提交已解决。重复请求返回已有记录，不新增状态变更。"""
        share = self._authenticated_share(db, share_id, token)
        self._ensure_readable(share)
        if not share.allow_resolve:
            raise forbidden("该分享链接不允许提交修复结果")
        bug = self._public_bug(db, share)
        # 已关闭或已拒绝后，旧链接不能再表现为一次新的修复提交。
        if bug.status in {"已关闭", "已拒绝"}:
            raise conflict("当前缺陷状态不允许通过分享链接修改")
        existing = self._resolve_action(db, share.id)
        if existing is not None:
            return self._resolve_result(existing, bug.status, True, "已提交过修复结果，未重复变更状态")
        description = _clean_text(body.repair_description, 2000)
        if not description:
            raise bad_request("请填写修复说明")
        version = _clean_text(body.fix_version, 80) if body.fix_version else None
        name = _clean_text(body.reporter_name, 40) if body.reporter_name else None
        commit_sha = body.commit_sha.strip() if body.commit_sha else None
        if commit_sha and _COMMIT_PATTERN.fullmatch(commit_sha) is None:
            raise bad_request("Commit SHA 格式不正确")
        old_status, new_status, changed = self.defects.apply_external_repair(db, bug, display_name=name)
        if not changed:
            db.commit()
            again = self._resolve_action(db, share.id)
            if again is not None:
                return self._resolve_result(again, new_status, True, "已提交过修复结果，未重复变更状态")
            return PublicResolveResponse(
                live_status=new_status, idempotent=True, message="缺陷已是已修复状态，未新增处理记录",
                repair_description=None, submitted_at=None, actor_display_name=None,
            )
        action = DefectExternalAction(
            bug_id=bug.id, share_link_id=share.id, action_type="RESOLVE",
            old_status=old_status, new_status=new_status, actor_type="EXTERNAL_SHARE",
            actor_display_name=name, repair_description=description, fix_version=version,
            commit_sha=commit_sha,
        )
        db.add(action)
        try:
            db.commit()
        except IntegrityError:
            # 并发提交只有一条 RESOLVE 能留下；后来的请求读回胜出的记录。
            db.rollback()
            winner = self._resolve_action(db, share.id)
            if winner is None:
                raise conflict("修复结果正在提交，请稍后刷新")
            return self._resolve_result(winner, "已修复", True, "已提交过修复结果，未重复变更状态")
        db.refresh(action)
        return self._resolve_result(action, "已修复", False, "已提交修复结果，缺陷状态更新为已修复")

    def _bugs(self, db: Session, bug_ids: list[int], actor: User) -> list[Bug]:
        """读取并校验同一项目内的可写缺陷。"""
        bugs = [self.defects.get_bug_or_404(db, bug_id, actor) for bug_id in dict.fromkeys(bug_ids)]
        projects = {bug.project_id for bug in bugs}
        if len(projects) != 1:
            raise bad_request("批量推送仅支持同一项目的缺陷")
        project = db.get(Project, bugs[0].project_id)
        if project is None:
            raise not_found("缺陷不存在")
        check_writable(db, project, actor)
        return bugs

    def _channel(self, db: Session, bug: Bug, channel_id: int, actor: User) -> NotificationChannel:
        """复用渠道服务的可见性检查，并限制为同一项目的启用飞书渠道。"""
        if not channel_id:
            raise bad_request("请选择飞书群聊")
        channel = self.channels.get_channel_orm(db, channel_id, actor)
        if channel.project_id != bug.project_id or channel.channel_type != "FEISHU_WEBHOOK":
            raise not_found("通知渠道不存在")
        if not channel.enabled:
            raise bad_request("所选飞书群聊已停用")
        return channel

    def _fields(self, fields: list[str] | None) -> list[str]:
        """校验展示字段白名单。未传时使用默认公开范围。"""
        if fields is None:
            return list(DEFAULT_VISIBLE_FIELDS)
        selected: list[str] = []
        for field in fields:
            if field not in ALL_VISIBLE_FIELDS:
                raise bad_request("包含不支持的展示字段")
            if field not in selected:
                selected.append(field)
        if not selected:
            raise bad_request("请至少选择一个展示字段")
        return selected

    def _expiry(self, db: Session, project_id: int, actor: User, body: ShareOptions) -> datetime | None:
        """计算有效期。永久链接只开放给项目管理员及以上。"""
        if body.permanent:
            project = db.get(Project, project_id)
            role = project_role_for(db, project, actor) if project is not None else None
            if not has_project_role(role, PROJECT_ROLE_EDITOR):
                raise forbidden("只有项目管理员可以选择永久有效")
            return None
        days = body.expires_in_days or 7
        if days not in {7, 30, 90}:
            raise bad_request("有效期仅支持 7、30 或 90 天")
        return datetime.now() + timedelta(days=days)

    def _expires_label(self, body: ShareOptions) -> str:
        """预览用的有效期文案。"""
        if body.permanent:
            return "永久有效"
        return f"{body.expires_in_days or 7} 天"

    def _snapshot(self, db: Session, bug: Bug, fields: list[str]) -> dict[str, Any]:
        """只把勾选字段放进快照。未勾选的数据即使库里有，也不进入公开内容。"""
        selected = set(fields)
        project = db.get(Project, bug.project_id)
        reporter = db.get(User, bug.reporter_id) if bug.reporter_id else None
        assignee = db.get(User, bug.assignee_id) if bug.assignee_id else None
        content: dict[str, Any] = {}
        if "bug_no" in selected:
            content["bug_no"] = f"BUG-{bug.id}"
        if "title" in selected:
            content["title"] = _clean_text(bug.title, 200)
        if "severity" in selected:
            content["severity"] = bug.severity
            content["severity_label"] = SEVERITY_LABELS.get(bug.severity, str(bug.severity))
        if "status" in selected:
            content["status"] = bug.status
        if "project_name" in selected:
            content["project_name"] = _clean_text(project.name, 200) if project else None
        if "description" in selected:
            content["description"] = _clean_text(bug.description)
        if "steps_to_reproduce" in selected:
            content["steps_to_reproduce"] = _clean_text(bug.steps_to_reproduce, 4000)
        if "environment" in selected:
            content["environment"] = _clean_text(bug.environment, 200)
        if "expected_result" in selected:
            # 当前缺陷模型没有独立的预期结果列，不能从描述里猜测。
            content["expected_result"] = None
        if "actual_result" in selected:
            content["actual_result"] = None
        if "created_at" in selected and bug.created_at is not None:
            content["created_at"] = bug.created_at.isoformat(sep=" ", timespec="seconds")
        if "reporter" in selected:
            content["reporter_name"] = reporter.username if reporter else None
        if "assignee" in selected:
            content["assignee_name"] = assignee.username if assignee else None
        if selected & {"source_summary", "api_execution", "security_record", "request_response", "error_stack", "screenshots", "allure"}:
            content["sources"] = self._sources(db, bug, selected)
        if "agent_execution" in selected:
            content["agent_executions"] = []
        if "allure" in selected:
            # 报告文件位于服务器目录，公开页面不提供路径。
            content["allure"] = None
        return content

    def _sources(self, db: Session, bug: Bug, selected: set[str]) -> list[dict[str, Any]]:
        """按授权字段摘取来源摘要。请求和响应只有勾选后才读取。"""
        from app.features.security_testing.models.finding import SecurityFinding
        from app.features.test_management.models.execution import CaseExecution
        from app.features.test_management.models.test_case import TestCase

        items: list[dict[str, Any]] = []
        links = db.query(DefectSourceLink).filter(DefectSourceLink.bug_id == bug.id).all()
        for link in links:
            if link.case_execution_id and selected & {"source_summary", "api_execution", "request_response", "error_stack", "screenshots"}:
                execution = db.get(CaseExecution, link.case_execution_id)
                item: dict[str, Any] = {"kind": "接口用例执行"}
                if execution is not None and {"source_summary", "api_execution"} & selected:
                    case = db.get(TestCase, execution.test_case_id) if execution.test_case_id else None
                    item["summary"] = {
                        "status": execution.status,
                        "case_name": _clean_text(case.name, 200) if case is not None else None,
                        "executor_type": execution.executor_type,
                    }
                if execution is not None and "error_stack" in selected:
                    item["error_message"] = _clean_text(execution.error_message, 2000)
                if execution is not None and "request_response" in selected:
                    item["request"] = _clean_json(execution.request_snapshot)
                    item["response"] = _clean_json(execution.response_snapshot)
                if execution is not None and "screenshots" in selected:
                    item["screenshots"] = _screenshot_urls(execution.response_snapshot)
                items.append(item)
            if link.security_finding_id and selected & {"source_summary", "security_record", "request_response"}:
                finding = db.get(SecurityFinding, link.security_finding_id)
                item = {"kind": "安全测试"}
                if finding is not None and {"source_summary", "security_record"} & selected:
                    item["summary"] = {
                        "title": _clean_text(finding.title, 200),
                        "severity": finding.severity,
                        "status": finding.status,
                    }
                if finding is not None and "request_response" in selected:
                    item["evidence"] = _clean_json(finding.evidence)
                items.append(item)
        return items

    def _dispatch(
        self, db: Session, channel: NotificationChannel, shares: list[DefectShareLink],
        tokens: list[str], actor: User, *, part: int, parts: int,
    ) -> list[NotificationRecord]:
        """发送一张汇总卡片，并为卡片中的每条分享各写一条投递记录。"""
        items = [self._card_item(share, token) for share, token in zip(shares, tokens)]
        keyword = (channel.config_json or {}).get("keyword")
        card = build_defect_share_card(
            items, channel_name=channel.name, pusher_name=actor.username,
            expires_label=self._share_expiry_label(shares[0]),
            allow_resolve=bool(shares[0].allow_resolve), keyword=str(keyword) if keyword else None,
            part=part, parts=parts,
        )
        status, response, error = self.feishu._deliver(channel, card)
        records: list[NotificationRecord] = []
        for share in shares:
            records.append(self.feishu._record(
                db, channel, None, status, card, response, error, actor.id,
                bug_id=share.bug_id, share_link_id=share.id, event_type="defect.share",
                idempotency_key=f"defect-share:{share.share_id}:{int(share.retry_count or 0)}",
                retry_count=int(share.retry_count or 0),
            ))
        return records

    def _card_item(self, share: DefectShareLink, token: str) -> dict[str, str | None]:
        """从已授权快照提取卡片摘要，不回读未授权字段。"""
        fields = set(share.visible_fields or [])
        snapshot = share.content_snapshot or {}
        description = snapshot.get("description") if "description" in fields else None
        steps = snapshot.get("steps_to_reproduce") if "steps_to_reproduce" in fields else None
        return {
            "bug_no": snapshot.get("bug_no") if "bug_no" in fields else "缺陷",
            "title": snapshot.get("title") if "title" in fields else "标题未在本次公开范围",
            "severity_label": snapshot.get("severity_label") if "severity" in fields else "未公开",
            "status": snapshot.get("status") if "status" in fields else "未公开",
            "project_name": snapshot.get("project_name") if "project_name" in fields else "未公开",
            "summary": (description or "无描述") if "description" in fields else "未选择缺陷描述",
            "steps_summary": (steps or "无")[:120] if "steps_to_reproduce" in fields else "未选择",
            "created_at": snapshot.get("created_at") if "created_at" in fields else "未公开",
            "share_url": build_share_url(share.share_id, token),
        }

    def _push_response(
        self, share: DefectShareLink, token: str, channel: NotificationChannel, record: NotificationRecord,
    ) -> SharePushResponse:
        """组装只返回一次的分享地址和本次投递状态。"""
        url = build_share_url(share.share_id, token)
        return SharePushResponse(
            share_id=share.share_id, share_url=url, url_is_absolute=url.startswith("http"),
            bug_id=share.bug_id, bug_no=f"BUG-{share.bug_id}", channel_id=channel.id,
            channel_name=channel.name, allow_view=bool(share.allow_view),
            allow_resolve=bool(share.allow_resolve), expires_at=share.expires_at,
            visible_fields=list(share.visible_fields or []), notification_status=record.status,
            error_message=record.error_message, retry_count=int(share.retry_count or 0),
        )

    def _summary(self, db: Session, share: DefectShareLink) -> ShareSummaryResponse:
        """内部历史项。不包含 share_url。"""
        channel = db.get(NotificationChannel, share.channel_id) if share.channel_id else None
        actor = db.get(User, share.pushed_by) if share.pushed_by else None
        record = (
            db.query(NotificationRecord)
            .filter(NotificationRecord.share_link_id == share.id)
            .order_by(NotificationRecord.id.desc())
            .first()
        )
        resolved = self._resolve_action(db, share.id)
        return ShareSummaryResponse(
            share_id=share.share_id, bug_id=share.bug_id, channel_id=share.channel_id,
            channel_name=channel.name if channel is not None else "渠道已删除",
            pushed_by_username=actor.username if actor is not None else None,
            pushed_at=share.pushed_at, expires_at=share.expires_at,
            expires_label=self._share_expiry_label(share), share_status=self._share_status(share),
            allow_view=bool(share.allow_view), allow_resolve=bool(share.allow_resolve),
            view_count=int(share.view_count or 0), last_viewed_at=share.last_viewed_at,
            resolution_status="已解决" if resolved else "未处理",
            latest_resolution=self._action_response(resolved) if resolved else None,
            notification_status=record.status if record is not None else None,
            error_message=record.error_message if record is not None else None,
            retry_count=int(share.retry_count or 0),
        )

    def _share_status(self, share: DefectShareLink) -> str:
        """计算分享展示状态。撤销优先于过期。"""
        if share.revoked_at is not None:
            return "已撤销"
        if share.archived_at is not None or (share.expires_at is not None and share.expires_at <= datetime.now()):
            return "已过期"
        return "有效"

    def _share_expiry_label(self, share: DefectShareLink) -> str:
        """把空的到期时间显示为永久有效。"""
        if share.expires_at is None:
            return "永久有效"
        return share.expires_at.isoformat(sep=" ", timespec="minutes")

    def _action_response(self, action: DefectExternalAction) -> ExternalActionResponse:
        """内部详情里的外部处理记录。"""
        return ExternalActionResponse(
            action_type=action.action_type, old_status=action.old_status, new_status=action.new_status,
            actor_type=action.actor_type, actor_display_name=action.actor_display_name,
            repair_description=action.repair_description, fix_version=action.fix_version,
            commit_sha=action.commit_sha, created_at=action.created_at, identity_note=_IDENTITY_NOTE,
        )

    def _public_response(self, db: Session, share: DefectShareLink, bug: Bug) -> PublicDefectResponse:
        """公开响应以快照为内容边界，状态单独取实时值。"""
        allowed = set(share.visible_fields or [])
        content = {key: value for key, value in dict(share.content_snapshot or {}).items() if key in allowed}
        action = self._resolve_action(db, share.id)
        resolution = None
        if action is not None:
            resolution = PublicResolutionResponse(
                repair_description=action.repair_description, fix_version=action.fix_version,
                commit_sha=action.commit_sha, actor_display_name=action.actor_display_name,
                actor_type=action.actor_type, old_status=action.old_status, new_status=action.new_status,
                submitted_at=action.created_at, identity_note=_IDENTITY_NOTE,
            )
        blocked = bug.status in {"已关闭", "已拒绝", "已修复"} or action is not None
        return PublicDefectResponse(
            live_status=bug.status, allow_resolve=bool(share.allow_resolve),
            can_submit=bool(share.allow_resolve) and not blocked, expires_at=share.expires_at,
            content=content, resolution=resolution, identity_note=_IDENTITY_NOTE,
        )

    def _resolve_result(
        self, action: DefectExternalAction, status: str, idempotent: bool, message: str,
    ) -> PublicResolveResponse:
        """统一成功和幂等响应，避免重复拼装。"""
        return PublicResolveResponse(
            live_status=status, idempotent=idempotent, message=message,
            repair_description=action.repair_description, submitted_at=action.created_at,
            actor_display_name=action.actor_display_name,
        )

    def _resolve_action(self, db: Session, share_link_id: int) -> DefectExternalAction | None:
        """读取这个分享已经留下的修复记录。"""
        return (
            db.query(DefectExternalAction)
            .filter(
                DefectExternalAction.share_link_id == share_link_id,
                DefectExternalAction.action_type == "RESOLVE",
            )
            .order_by(DefectExternalAction.id.asc())
            .first()
        )

    def _authenticated_share(self, db: Session, share_id: str, token: str) -> DefectShareLink:
        """先按公开标识定位，再用哈希核对凭证。错误凭证与不存在使用同一文案。"""
        share = db.query(DefectShareLink).filter(DefectShareLink.share_id == share_id).one_or_none()
        if share is None or not token:
            raise not_found("分享链接无效或无权访问")
        if not hmac.compare_digest(_hash_token(token), share.token_hash):
            raise not_found("分享链接无效或无权访问")
        return share

    def _ensure_readable(self, share: DefectShareLink) -> None:
        """凭证正确之后才区分过期、撤销和只读。"""
        if share.revoked_at is not None:
            raise forbidden("分享链接已撤销")
        if share.archived_at is not None or (share.expires_at is not None and share.expires_at <= datetime.now()):
            raise forbidden("分享链接已过期")
        if not share.allow_view:
            raise forbidden("分享链接不允许查看")

    def _public_bug(self, db: Session, share: DefectShareLink) -> Bug:
        """软删除后的缺陷对公开页显示为已删除，不返回快照。"""
        bug = db.get(Bug, share.bug_id)
        if bug is None or getattr(bug, "deleted_at", None) is not None:
            raise not_found("缺陷已删除")
        return bug

    def _visible_share(self, db: Session, bug_id: int, share_id: str, actor: User) -> DefectShareLink:
        """内部读取一条分享。越权与不存在都是 404。"""
        self.defects.get_bug_or_404(db, bug_id, actor)
        share = (
            db.query(DefectShareLink)
            .filter(DefectShareLink.bug_id == bug_id, DefectShareLink.share_id == share_id)
            .one_or_none()
        )
        if share is None:
            raise not_found("分享记录不存在")
        return share

    def _managed_share(self, db: Session, bug_id: int, share_id: str, actor: User) -> DefectShareLink:
        """撤销和重试需要项目成员权限。"""
        share = self._visible_share(db, bug_id, share_id, actor)
        project = db.get(Project, share.project_id)
        if project is None:
            raise not_found("分享记录不存在")
        check_writable(db, project, actor)
        return share

    def _bug_of(self, db: Session, share: DefectShareLink) -> Bug:
        """重试时取回缺陷，确认它仍然可见。"""
        bug = db.get(Bug, share.bug_id)
        if bug is None or getattr(bug, "deleted_at", None) is not None:
            raise not_found("缺陷已删除")
        return bug

    def _unique_share_id(self, db: Session) -> str:
        """避免公开标识撞车。凭证哈希另有唯一约束。"""
        for _ in range(5):
            candidate = _new_share_id()
            exists = db.query(DefectShareLink.id).filter(DefectShareLink.share_id == candidate).first()
            if exists is None:
                return candidate
        raise bad_request("分享标识生成失败，请重试")
