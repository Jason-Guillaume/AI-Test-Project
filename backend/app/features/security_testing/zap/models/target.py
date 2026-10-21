"""security_scan_target：扫描目标。"""

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

from app.shared.database import Base


class SecurityScanTarget(Base):
    """一个被授权的扫描目标（§四）。

    创建时必须通过 scope_guard 校验：协议 / 主机白名单 / 解析 IP / 端口 / 授权状态。
    active_scan_allowed 是环境级主动扫描开关的显式记录：Staging 默认关闭（§五），
    只有项目 Owner/Admin 能打开，Production 目标无论怎么配都禁止主动扫描。
    """

    __tablename__ = "security_scan_target"
    __table_args__ = (
        Index("ix_security_scan_target_project_enabled", "project_id", "enabled"),
        Index("ix_security_scan_target_env", "environment_id"),
        {"comment": "OWASP ZAP 扫描目标：范围与授权登记的唯一入口"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属平台项目ID",
    )
    environment_id = Column(
        Integer, ForeignKey("environment.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="被测环境ID",
    )
    name = Column(String(100), nullable=False, comment="目标名称")
    target_type = Column(
        String(20), nullable=False, server_default=text("'API'"),
        comment="目标类型：API / WEB / HYBRID",
    )
    base_url = Column(String(500), nullable=False, comment="扫描根地址（已规范化，过 scope_guard）")
    entry_url = Column(String(500), nullable=True, comment="Web 爬取入口地址（可空，缺省用 base_url）")
    enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用（停用后不可被选择）",
    )
    # 测试授权状态（§四）：只有 AUTHORIZED 允许发起扫描。
    authorization_status = Column(
        String(20), nullable=False, server_default=text("'PENDING'"),
        comment="授权状态：PENDING / AUTHORIZED / REVOKED",
    )
    authorization_note = Column(
        String(500), nullable=True, comment="授权说明：授权范围、时间窗口、授权人",
    )
    # 主动扫描开关：默认关闭，Production 目标在 service 层强制视为关闭。
    active_scan_allowed = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="是否允许在该目标上发起受控主动扫描",
    )
    allowed_hosts = Column(
        JSON, nullable=True, comment="允许主机白名单（空表示仅允许 base_url 主机）",
    )
    include_paths = Column(JSON, nullable=True, comment="包含路径清单")
    exclude_paths = Column(JSON, nullable=True, comment="排除路径清单")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
