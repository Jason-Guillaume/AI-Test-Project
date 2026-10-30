"""security_scan_profile：扫描策略。"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class SecurityScanProfile(Base):
    """一个扫描策略（§十六）。

    内置策略：code 非空、is_builtin=True、created_by 为空，可编辑但禁止删除与改 code。
    自定义策略：code 为空、is_builtin=False，只能在本项目内使用。
    Agent 只能引用已批准的 Profile ID，不能自己拼扫描参数（§十六）。

    限额字段在 Worker 侧还要再过一次硬上限（connector 的 ACTIVE_*_HARD_CAP）——
    库里的值不是可信输入，任何人（包括 Owner）改 Profile 都不能突破硬上限。
    """

    __tablename__ = "security_scan_profile"
    __table_args__ = (
        Index("ix_security_scan_profile_project_enabled", "project_id", "enabled"),
        {"comment": "OWASP ZAP 扫描策略：内置 6 个 + 项目自定义"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=True, index=True, comment="所属平台项目ID；NULL 表示平台内置",
    )
    code = Column(
        String(60), nullable=True, unique=True, index=True,
        comment="内置策略代号（如 API_PASSIVE_BASIC）；自定义策略为空",
    )
    is_builtin = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否平台内置（内置策略禁止删除）",
    )
    name = Column(String(100), nullable=False, comment="策略名称")
    scan_mode = Column(
        String(30), nullable=False, comment="扫描模式：API_PASSIVE / WEB_PASSIVE / HYBRID_PASSIVE / "
        "API_ACTIVE / WEB_ACTIVE / FULL_AUTHORIZED",
    )
    spider_enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用传统 Spider（覆盖静态链接）",
    )
    client_spider_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否启用 Client Spider（真实浏览器渲染 SPA / 登录页）",
    )
    passive_enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用被动扫描",
    )
    active_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否启用主动扫描",
    )
    authentication_profile_id = Column(
        Integer, ForeignKey("security_scan_auth_profile.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联的认证配置ID（可空表示未认证扫描）",
    )
    max_duration = Column(
        Integer, nullable=False, default=30, server_default=text("30"),
        comment="最大扫描时长（分钟）",
    )
    max_depth = Column(
        Integer, nullable=False, default=5, server_default=text("5"),
        comment="最大爬取深度",
    )
    max_concurrency = Column(
        Integer, nullable=False, default=4, server_default=text("4"),
        comment="最大并发线程数",
    )
    request_delay = Column(
        Integer, nullable=False, default=300, server_default=text("300"),
        comment="请求间隔（毫秒）",
    )
    max_alerts_per_rule = Column(
        Integer, nullable=True, comment="单规则最大告警数（空表示不额外限制）",
    )
    max_request_budget = Column(
        Integer, nullable=True, comment="最大请求预算（主动扫描用）",
    )
    include_paths = Column(JSON, nullable=True, comment="包含路径清单")
    exclude_paths = Column(JSON, nullable=True, comment="排除路径清单")
    selected_rule_ids = Column(
        JSON, nullable=True, comment="选中的 ZAP 规则 ID 列表（空表示沿用策略默认规则集）",
    )
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用",
    )
    description = Column(String(500), nullable=True, comment="策略说明")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
