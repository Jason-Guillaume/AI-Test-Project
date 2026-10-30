"""security_scan_auth_profile：认证配置。

凭据（Bearer Token / Cookie / Session 值）只以 **Fernet 密文** 存在（§十一、§三「API Key 加密保存」）。
任何接口都不回显明文，只回显 ``has_token`` / ``token_fingerprint``；Agent Prompt、日志、
事件表同样不含凭据明文。
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class SecurityScanAuthProfile(Base):
    """一份认证配置（§十一 / §十二 / §十三）。

    三种模式：
    - BEARER_TOKEN / HEADER_BASED：API 鉴权。ZAP 用 Session Management 附加请求头，
      **只覆盖 API 请求**，浏览器渲染 SPA 时不会带上（§十二）。
    - BROWSER_AUTH：会话导入。以 cookieBased 方式导入会话值，浏览器里才有真实登录态。
    - MANUAL：飞书 SSO 等人工扫码。本部署无浏览器交互能力时由 connector 明确报错，
      不假装成功（§十三）。

    authentication_check_url 是登录态验证接口（§十一「扫描前必须调用用户配置的安全验证
    接口」）；判定不看 HTTP 200，而看 logged_in_indicator / logged_out_indicator。
    """

    __tablename__ = "security_scan_auth_profile"
    __table_args__ = (
        Index("ix_security_scan_auth_profile_project_enabled", "project_id", "enabled"),
        {"comment": "OWASP ZAP 认证配置：凭据只存密文，接口不回显明文"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属平台项目ID",
    )
    name = Column(String(100), nullable=False, comment="配置名称")
    auth_mode = Column(
        String(20), nullable=False, comment="认证模式：NONE / BEARER_TOKEN / HEADER_BASED / "
        "BROWSER_AUTH / MANUAL",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用",
    )
    # -------------------------------------------------------------- 请求级鉴权
    session_method = Column(
        String(30), nullable=True, comment="ZAP 会话管理方式：none / headerBased / "
        "cookieBased / queryBased",
    )
    session_header = Column(String(100), nullable=True, comment="自定义请求头名（如 Authorization）")
    session_name = Column(String(100), nullable=True, comment="Cookie / 参数名（如 session）")
    # 明文凭据只以 Fernet 密文存在；读取时按需解密，用完即弃。
    credential_encrypted = Column(
        Text, nullable=True, comment="加密后的 Token / Session 值（任何接口不回显明文）",
    )
    # 凭据指纹（sha256 前 12 位），用于判断「凭据是否被换过」而不暴露凭据本身。
    token_fingerprint = Column(String(64), nullable=True, comment="凭据指纹（sha256 前 12 位）")
    has_credential = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否已配置凭据（列表页展示用，替代明文）",
    )
    credential_updated_at = Column(DateTime, nullable=True, comment="凭据最近一次更新时间")
    # -------------------------------------------------------------- 登录态验证
    authentication_check_url = Column(
        String(500), nullable=True, comment="登录态验证接口地址（如 https://x/api/v1/users/me）",
    )
    logged_in_indicator = Column(
        String(200), nullable=True, comment="已登录判定正则（响应体片段）",
    )
    logged_out_indicator = Column(
        String(200), nullable=True, comment="未登录判定正则（响应体片段）",
    )
    expected_user_id = Column(
        String(100), nullable=True, comment="预期的登录用户标识（验证真实登录用户）",
    )
    # 凭据有效期策略：FIXED / UNKNOWN，FIXED 用于过期前提示重新配置。
    auth_expiry_policy = Column(
        String(20), nullable=False, server_default=text("'UNKNOWN'"),
        comment="凭据有效期策略：FIXED / UNKNOWN",
    )
    credential_expires_at = Column(DateTime, nullable=True, comment="凭据预期过期时间（可空）")
    description = Column(String(500), nullable=True, comment="说明（不含凭据）")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
