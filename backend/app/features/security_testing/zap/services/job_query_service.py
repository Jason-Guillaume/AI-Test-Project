"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.platform.projects.services.access_service import get_project_or_404

from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.features.security_testing.zap.contracts import (
    COVERAGE_NOT_COVERED,
    COVERAGE_STAGES,
    DEFAULT_ZAP_ALERT_SEVERITY,
    ZAP_RISK_TO_SEVERITY,
    map_zap_risk,
)
from app.features.security_testing.zap.models.finding_link import SecurityScanFinding
from app.features.security_testing.zap.models.job import SecurityScanEvent, SecurityScanJob
from app.features.security_testing.zap.models.profile import SecurityScanProfile
from app.features.security_testing.zap.models.target import SecurityScanTarget
from app.features.security_testing.zap.schemas import (
    CoverageRead,
    CoverageRowRead,
    ScanAlertCountsRead,
    ScanAlertListResponse,
    ScanAlertRead,
    ScanAuthProfileRead,
    ScanEventListResponse,
    ScanEventRead,
    ScanFindingListResponse,
    ScanFindingLinkRead,
    ScanJobListResponse,
    ScanJobProgressRead,
    ScanJobRead,
    ScanReportRead,
)
from app.features.security_testing.zap.services import (
    _access,
    auth_profile_service,
    profile_service,
    target_service,
)
from app.core.models.configuration import Environment
from app.core.models.identity import User
from app.core.http.pagination import paginate
from app.features.security_testing.zap.services.job_access import _AUTH_PROFILE_NOT_FOUND
from app.features.security_testing.zap.services.job_access import load_job
from app.features.security_testing.zap.services.job_access import utcnow


def to_read(db: Session, row: SecurityScanJob) -> ScanJobRead:
    """ORM → 响应；补目标 / 环境 / 策略名称，并把 NULL 的 JSON 列收敛成空对象。

    coverage_summary 在任务结束前一直是 NULL。schema 里的 default_factory 只在字段
    **缺失**时生效，遇到显式 NULL 会直接 ValidationError → 整个任务列表 500，
    所以必须在校验之前收敛。
    """
    data = dict(row.__dict__)
    data.pop("_sa_instance_state", None)
    data["coverage_summary"] = dict(row.coverage_summary or {})
    base = ScanJobRead.model_validate(data)
    target = db.get(SecurityScanTarget, row.target_id) if row.target_id else None
    base.target_name = target.name if target is not None else None
    if row.scan_profile_id:
        profile = db.get(SecurityScanProfile, row.scan_profile_id)
        base.scan_profile_name = profile.name if profile is not None else None
    env = db.get(Environment, row.environment_id) if row.environment_id else None
    base.environment_name = env.name if env is not None else None
    return base


def list_jobs(
    db: Session,
    project_id: int,
    user: User,
    page: int,
    page_size: int,
    *,
    status: str | None = None,
    target_id: int | None = None,
) -> ScanJobListResponse:
    """列出扫描任务（viewer+）。"""
    get_project_or_404(db, project_id, user)
    query = db.query(SecurityScanJob).filter(SecurityScanJob.project_id == project_id)
    if status:
        query = query.filter(SecurityScanJob.status == status)
    if target_id:
        query = query.filter(SecurityScanJob.target_id == target_id)
    query = query.order_by(SecurityScanJob.id.desc())
    result = paginate(query, page, page_size)
    return ScanJobListResponse(
        items=[to_read(db, row) for row in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
    )


def get_job(db: Session, project_id: int, user: User, job_id: int) -> ScanJobRead:
    """查看单个任务（viewer+）。"""
    get_project_or_404(db, project_id, user)
    return to_read(db, load_job(db, project_id, job_id))


def progress(db: Session, project_id: int, user: User, job_id: int) -> ScanJobProgressRead:
    """进度查询（viewer+）。ZAP 没给百分比时前端只显示阶段与计数。"""
    get_project_or_404(db, project_id, user)
    return ScanJobProgressRead.model_validate(load_job(db, project_id, job_id))


def events(
    db: Session,
    project_id: int,
    user: User,
    job_id: int,
    page: int,
    page_size: int,
    *,
    event_type: str | None = None,
) -> ScanEventListResponse:
    """过程事件（viewer+）。payload 已脱敏，可直接展示。"""
    get_project_or_404(db, project_id, user)
    job = load_job(db, project_id, job_id)
    query = db.query(SecurityScanEvent).filter(SecurityScanEvent.job_id == job.id)
    if event_type:
        query = query.filter(SecurityScanEvent.event_type == event_type)
    # seq 相同（历史数据）时按 id 兜底，保证同一任务的时间线排序稳定。
    query = query.order_by(SecurityScanEvent.seq.asc(), SecurityScanEvent.id.asc())
    result = paginate(query, page, page_size)
    return ScanEventListResponse(
        items=[ScanEventRead.model_validate(row) for row in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
    )


def alert_read_from_link(link: SecurityScanFinding) -> ScanAlertRead:
    """把一条关系记录转成告警视图：结构化字段优先，evidence_json 兜底。"""
    payload = dict(link.evidence_json or {})
    return ScanAlertRead(
        rule_id=str(link.source_rule_id or payload.get("rule_id", "")),
        name=str(link.source_alert_name or payload.get("name", "")),
        risk=str(link.risk or payload.get("risk", "")),
        confidence=int(link.confidence if link.confidence is not None else payload.get("confidence", 1)),
        severity=str(payload.get("severity") or map_zap_risk(str(link.risk or ""))),
        url=str(link.url or ""),
        method=str(link.method or ""),
        parameter=str(link.parameter or ""),
        description=str(payload.get("description", "")),
        remediation=str(payload.get("remediation", "")),
        evidence=str(payload.get("evidence", "")),
        cwe_id=payload.get("cwe_id"),
        wasc_id=payload.get("wasc_id"),
        reference=str(payload.get("reference", "")),
    )


def alerts(
    db: Session,
    project_id: int,
    user: User,
    job_id: int,
    page: int,
    page_size: int,
    *,
    rule_id: str | None = None,
    severity: str | None = None,
) -> ScanAlertListResponse:
    """本次扫描的告警（viewer+）。

    数据来自 security_scan_finding：一行代表该任务里一次「去重后的告警签名」，
    evidence_json 里是归一化并脱敏后的告警明细。
    """
    get_project_or_404(db, project_id, user)
    job = load_job(db, project_id, job_id)
    query = db.query(SecurityScanFinding).filter(SecurityScanFinding.job_id == job.id)
    if rule_id:
        query = query.filter(SecurityScanFinding.source_rule_id == rule_id)
    if severity:
        # risk 列存的是 ZAP 原文（"High"），severity 是映射后的平台级别（"HIGH"）。
        # 过滤必须按映射表反查，不能拿 "HIGH" 直接去比 risk——那样永远查不到任何结果。
        wanted = str(severity).strip().upper()
        known_labels = set(ZAP_RISK_TO_SEVERITY)
        labels = {label for label, mapped in ZAP_RISK_TO_SEVERITY.items() if mapped == wanted}
        if not labels:
            # CRITICAL 等平台级别不会由 ZAP 产生：如实返回空结果，不放宽条件凑数。
            labels = {"__ZAP 不产生该级别__"}
        conditions = [SecurityScanFinding.risk.in_(list(labels))]
        if wanted == DEFAULT_ZAP_ALERT_SEVERITY:
            # risk 原文未识别时也按默认级别展示，过滤时要一并算上。
            conditions.append(~SecurityScanFinding.risk.in_(list(known_labels)))
        query = query.filter(or_(*conditions))
    query = query.order_by(SecurityScanFinding.confidence.desc(), SecurityScanFinding.id.desc())
    result = paginate(query, page, page_size)
    return ScanAlertListResponse(
        items=[alert_read_from_link(link) for link in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
        counts=ScanAlertCountsRead(
            total=int(job.total_alerts or 0),
            high=int(job.high_count or 0),
            medium=int(job.medium_count or 0),
            low=int(job.low_count or 0),
            info=int(job.info_count or 0),
        ),
    )


def findings(
    db: Session,
    project_id: int,
    user: User,
    job_id: int,
    page: int,
    page_size: int,
    *,
    source_rule_id: str | None = None,
) -> ScanFindingListResponse:
    """扫描任务与 Finding 的关联（viewer+）。

    Finding 的生命周期（OPEN / CONFIRMED / FALSE_POSITIVE ...）仍然走 Phase 1 的
    security_finding 接口，这里只给「本次扫描命中了哪些 Finding」的视角。
    """
    get_project_or_404(db, project_id, user)
    job = load_job(db, project_id, job_id)
    query = db.query(SecurityScanFinding).filter(SecurityScanFinding.job_id == job.id)
    if source_rule_id:
        query = query.filter(SecurityScanFinding.source_rule_id == source_rule_id)
    query = query.order_by(SecurityScanFinding.confidence.desc(), SecurityScanFinding.id.desc())
    result = paginate(query, page, page_size)
    return ScanFindingListResponse(
        items=[ScanFindingLinkRead.model_validate(link) for link in result["items"]],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
    )


def coverage(db: Session, project_id: int, user: User, job_id: int, page: int, page_size: int) -> CoverageRead:
    """覆盖率明细（§三十一）。行数据来自任务上冻结的 coverage_summary 快照。"""
    get_project_or_404(db, project_id, user)
    job = load_job(db, project_id, job_id)
    snapshot = dict(job.coverage_summary or {})
    summary = {str(k): int(v) for k, v in (snapshot.get("summary") or {}).items()}
    rows: list[CoverageRowRead] = []
    for item in snapshot.get("rows") or []:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or COVERAGE_NOT_COVERED)
        if stage not in COVERAGE_STAGES:
            # 快照里可能出现未知阶段值：按未覆盖处理，不要让一个坏值打断整页。
            stage = COVERAGE_NOT_COVERED
        rows.append(CoverageRowRead(
            identifier=str(item.get("identifier", "")),
            stage=stage,  # type: ignore[arg-type]
            method=str(item.get("method", "")),
            status_code=item.get("status_code"),
            passive_analyzed=bool(item.get("passive_analyzed", False)),
            active_scanned=bool(item.get("active_scanned", False)),
        ))
    offset = (page - 1) * page_size
    return CoverageRead(
        items=rows[offset:offset + page_size],
        total=len(rows),
        page=page,
        page_size=page_size,
        summary=summary,
    )


def report(db: Session, project_id: int, user: User, job_id: int) -> ScanReportRead:
    """独立安全扫描报告（§二十五）。所有数字都来自任务记录本身。"""
    get_project_or_404(db, project_id, user)
    job = load_job(db, project_id, job_id)

    links = (
        db.query(SecurityScanFinding)
        .filter(SecurityScanFinding.job_id == job.id)
        .order_by(SecurityScanFinding.confidence.desc(), SecurityScanFinding.id.asc())
        .all()
    )
    high_risk: list[ScanAlertRead] = []
    findings_rows: list[ScanFindingLinkRead] = []
    for link in links:
        findings_rows.append(ScanFindingLinkRead.model_validate(link))
        if link.risk in ("High", "Medium"):
            high_risk.append(alert_read_from_link(link))

    snapshot = dict(job.coverage_summary or {})
    coverage_summary = {str(k): int(v) for k, v in (snapshot.get("summary") or {}).items()}

    target_row = db.get(SecurityScanTarget, job.target_id) if job.target_id else None
    profile_row = db.get(SecurityScanProfile, job.scan_profile_id) if job.scan_profile_id else None
    return ScanReportRead(
        job=to_read(db, job),
        target=target_service.to_read(db, target_row) if target_row is not None else None,
        profile=profile_service.to_read(profile_row) if profile_row is not None else None,
        alert_counts=ScanAlertCountsRead(
            total=int(job.total_alerts or 0),
            high=int(job.high_count or 0),
            medium=int(job.medium_count or 0),
            low=int(job.low_count or 0),
            info=int(job.info_count or 0),
        ),
        high_risk_alerts=high_risk[:50],
        coverage_summary=coverage_summary,
        findings=findings_rows,
        generated_at=utcnow(),
    )


def get_auth_profile(db: Session, project_id: int, user: User, profile_id: int) -> ScanAuthProfileRead:
    """按 ID 读认证配置（viewer+），只返回脱敏字段。"""
    get_project_or_404(db, project_id, user)
    row = auth_profile_service.get_or_none(db, project_id, profile_id)
    if row is None:
        raise _AUTH_PROFILE_NOT_FOUND
    return ScanAuthProfileRead.model_validate(row)
