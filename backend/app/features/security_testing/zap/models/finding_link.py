"""security_scan_finding：扫描任务与 security_finding 的关系表。"""

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


class SecurityScanFinding(Base):
    """一条「本次扫描命中了这条 Finding」的关系记录（§二十一）。

    Finding 本体复用 Phase 1 的 security_finding 与部分唯一索引（§十九），
    这里只负责「哪次扫描 → 哪条 Finding」，以及该次扫描的告警快照。

    重要约定（§十九「不能因为重新扫描而无条件重置人工确认或误报状态」）：
    重复命中时只新增一行关系记录（保留出现记录），**不修改**
    security_finding.status / verified_by / verified_at / note，
    也不把 CONFIRMED 降回 OPEN。
    """

    __tablename__ = "security_scan_finding"
    __table_args__ = (
        Index("ix_security_scan_finding_job", "job_id"),
        Index("ix_security_scan_finding_finding", "finding_id"),
        Index("ix_security_scan_finding_project_finding", "project_id", "finding_id"),
        Index(
            "uq_security_scan_finding_job_finding", "job_id", "finding_id", unique=True,
        ),
        {"comment": "扫描任务与 security_finding 的多对多关系：同一任务对同一 Finding 只记录一行"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属平台项目ID",
    )
    job_id = Column(
        Integer, ForeignKey("security_scan_job.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="扫描任务ID",
    )
    finding_id = Column(
        Integer, ForeignKey("security_finding.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="关联的 security_finding ID",
    )
    # ZAP 告警快照（已脱敏）：保留 source / source_rule_id / 原始 risk / confidence /
    # CWE / WASC / reference，便于回溯「这条 Finding 是哪条 ZAP 规则报出来的」。
    source = Column(
        String(20), nullable=False, default="ZAP", server_default=text("'ZAP'"),
        comment="来源工具",
    )
    source_rule_id = Column(String(20), nullable=True, comment="ZAP 规则 ID")
    source_alert_name = Column(String(200), nullable=True, comment="ZAP 告警名称")
    risk = Column(String(20), nullable=True, comment="ZAP 原始 Risk 文本")
    confidence = Column(
        Integer, nullable=True, comment="ZAP 原始 Confidence（1-5，与 Severity 是独立维度）",
    )
    url = Column(String(800), nullable=True, comment="命中 URL（已脱敏）")
    method = Column(String(10), nullable=True, comment="HTTP 方法")
    parameter = Column(String(200), nullable=True, comment="命中参数")
    fingerprint = Column(
        String(200), nullable=True, comment="归一化指纹（zap| 命名空间）",
    )
    evidence_json = Column(
        JSON, nullable=True, comment="结构化脱敏证据（不含原始 Request/Response）",
    )
    # 本次命中的判定：NEW 表示 Finding 是本次新建的，EXISTING 表示命中已有 Finding。
    first_seen_in_job = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="该 Finding 是否由本次扫描首次创建",
    )
    repeat_count = Column(
        Integer, nullable=False, default=1, server_default=text("1"),
        comment="该 Finding 的历史累计命中次数（每次扫描重复命中加一）",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="关联创建时间")
