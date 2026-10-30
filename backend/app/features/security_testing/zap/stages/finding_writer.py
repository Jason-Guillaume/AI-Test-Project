"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.features.security_testing.models.finding import SecurityFinding
from app.features.security_testing.zap.models.finding_link import SecurityScanFinding
from app.features.security_testing.zap.normalizer import NormalizedZAPAlert
from app.features.security_testing.zap.stages.contracts import _now


def _upsert_zap_finding(
    db: Session,
    *,
    project_id: int,
    test_run_id: int | None,
    scan_job_id: int,
    item: NormalizedZAPAlert,
    proposal: Any,
) -> tuple[Any | None, bool]:
    """按 fingerprint 命中 Phase 1 的 Finding 表；只新增关系，不动人工确认状态。

    Returns:
        (finding, is_new)；fingerprint 或 project_id 缺失时返回 (None, False)。
    """
    from sqlalchemy.exc import IntegrityError

    fingerprint = item.fingerprint
    if not fingerprint or not project_id:
        return None, False

    open_row = (
        db.query(SecurityFinding)
        .filter(
            SecurityFinding.project_id == project_id,
            SecurityFinding.fingerprint == fingerprint,
            SecurityFinding.status.in_(("OPEN", "CONFIRMED")),
        )
        .order_by(SecurityFinding.id.desc())
        .first()
    )
    if open_row is not None:
        evidence = dict(open_row.evidence or {})
        evidence["repeat_count"] = int(evidence.get("repeat_count") or 0) + 1
        evidence["last_scan_job_id"] = scan_job_id
        open_row.evidence = evidence
        if test_run_id:
            open_row.test_run_id = test_run_id
        open_row.updated_at = _now()
        db.add(open_row)
        db.flush()
        return open_row, False

    prior = (
        db.query(SecurityFinding)
        .filter(SecurityFinding.project_id == project_id, SecurityFinding.fingerprint == fingerprint)
        .order_by(SecurityFinding.id.desc())
        .first()
    )
    prior_status = str(getattr(prior, "status", None) or "") if prior is not None else None
    evidence = dict(proposal.evidence or {})
    evidence["repeat_count"] = 1
    evidence["scan_job_id"] = scan_job_id
    if prior is not None:
        # 旧记录已是误报 / 忽略 / 已解决：新记录上写明旧状态，不改动旧记录本身（§十九）。
        evidence["prior_status"] = prior_status
    row = SecurityFinding(
        project_id=project_id,
        test_run_id=test_run_id,
        api_id=None,
        mutation_type=proposal.mutation_type,
        severity=item.severity,
        status="OPEN",
        title=str(proposal.title)[:200],
        description=str(proposal.description)[:8000],
        evidence=evidence,
        recommendation=str(proposal.recommendation)[:8000],
        fingerprint=fingerprint,
        created_by=None,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # 并发插入撞了部分唯一索引：改走更新分支，保证重复命中只累加计数。
        db.rollback()
        open_row = (
            db.query(SecurityFinding)
            .filter(
                SecurityFinding.project_id == project_id,
                SecurityFinding.fingerprint == fingerprint,
                SecurityFinding.status.in_(("OPEN", "CONFIRMED")),
            )
            .order_by(SecurityFinding.id.desc())
            .first()
        )
        if open_row is None:
            return None, False
        evidence = dict(open_row.evidence or {})
        evidence["repeat_count"] = int(evidence.get("repeat_count") or 0) + 1
        evidence["last_scan_job_id"] = scan_job_id
        open_row.evidence = evidence
        if test_run_id:
            open_row.test_run_id = test_run_id
        open_row.updated_at = _now()
        db.add(open_row)
        db.flush()
        return open_row, False
    return row, True


def _link_scan_finding(
    db: Session,
    *,
    project_id: int,
    job_id: int,
    finding: Any,
    item: NormalizedZAPAlert,
) -> tuple[Any | None, bool]:
    """写扫描任务与 Finding 的关系行；同一任务命中同一 Finding 只累加 repeat_count。"""
    existing = (
        db.query(SecurityScanFinding)
        .filter(
            SecurityScanFinding.job_id == job_id,
            SecurityScanFinding.finding_id == finding.id,
        )
        .first()
    )
    if existing is not None:
        existing.repeat_count = int(existing.repeat_count or 1) + 1
        db.add(existing)
        db.flush()
        return existing, False
    row = SecurityScanFinding(
        project_id=project_id,
        job_id=job_id,
        finding_id=finding.id,
        source=item.source,
        source_rule_id=item.rule_id,
        source_alert_name=item.name[:200],
        risk=item.risk,
        confidence=int(item.confidence),
        url=(item.url or "")[:800],
        method=(item.method or "")[:10],
        parameter=(item.parameter or "")[:200],
        fingerprint=item.fingerprint,
        evidence_json=item.as_dict(),
        first_seen_in_job=True,
        repeat_count=1,
    )
    db.add(row)
    db.flush()
    return row, True
