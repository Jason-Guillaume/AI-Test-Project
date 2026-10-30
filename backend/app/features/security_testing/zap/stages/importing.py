"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.security_testing.zap.contracts import (
    EVENT_TYPE_ALERT,
    EVENT_TYPE_PROGRESS,
    EVENT_TYPE_STAGE,
    EVENT_TYPE_WARNING,
    JOB_STATUS_IMPORTING_RESULTS,
)
from app.features.security_testing.zap.normalizer import ZAPAlertNormalizer
from app.features.security_testing.zap.stages.contracts import ScanSnapshot
from app.features.security_testing.zap.stages.contracts import ScanStageContext
from app.features.security_testing.zap.stages.contracts import _build_coverage
from app.features.security_testing.zap.stages.finding_writer import _link_scan_finding
from app.features.security_testing.zap.stages.finding_writer import _upsert_zap_finding
from app.features.security_testing.zap.stages.control import check_running
from app.features.security_testing.zap.stages.control import checkpoint
from app.features.security_testing.zap.stages.persistence import emit
from app.features.security_testing.zap.stages.persistence import emit_db
from app.features.security_testing.zap.stages.control import split_scope
from app.features.security_testing.zap.stages.persistence import update_job


def stage_import(context: ScanStageContext, snap: ScanSnapshot, started: float, normalizer: ZAPAlertNormalizer) -> None:
    """IMPORTING_RESULTS：拉取告警、归一化、去重落库、生成覆盖汇总。"""
    checkpoint(context, snap, JOB_STATUS_IMPORTING_RESULTS, "导入扫描结果", progress=100)
    emit(context, snap, EVENT_TYPE_STAGE, JOB_STATUS_IMPORTING_RESULTS, "开始导入扫描结果")

    alerts = context.connector.get_alerts()
    alert_counts = context.connector.get_alert_counts(alerts)
    pages, counts_from_stats = context.connector.get_scan_statistics()
    urls = context.connector.list_urls()

    new_count = 0
    duplicate_count = 0
    severity_counts: dict[str, int] = {}
    emitted = 0
    with context.db_factory() as db:
        for alert in alerts:
            # 导入是取消请求能生效的最后一站；不检查的话点取消会得到一个已完成的任务。
            check_running(context, snap, started, JOB_STATUS_IMPORTING_RESULTS)
            item = normalizer.normalize(alert, scan_job_id=snap.job_id)
            proposal = normalizer.finding_fields(item)
            finding, is_new = _upsert_zap_finding(
                db,
                project_id=snap.project_id,
                test_run_id=snap.test_run_id,
                scan_job_id=snap.job_id,
                item=item,
                proposal=proposal,
            )
            if finding is None:
                continue
            link, was_new = _link_scan_finding(
                db,
                project_id=snap.project_id,
                job_id=snap.job_id,
                finding=finding,
                item=item,
            )
            if is_new:
                new_count += 1
            else:
                duplicate_count += 1
            severity_counts[item.severity] = severity_counts.get(item.severity, 0) + 1
            if link is not None and was_new and emitted < 50:
                emit_db(
                    db, snap, EVENT_TYPE_ALERT, JOB_STATUS_IMPORTING_RESULTS,
                    f"发现潜在问题：{item.name}",
                    {"rule_id": item.rule_id, "url": item.url, "severity": item.severity,
                     "confidence": item.confidence, "finding_id": int(finding.id)},
                )
                emitted += 1
            db.commit()

    in_scope, dropped = split_scope(context, urls, snap)
    if dropped:
        # 范围外的地址进不了覆盖统计：报告不能声称扫了未授权的目标（§三十四）。
        emit(context,
            snap, EVENT_TYPE_WARNING, JOB_STATUS_IMPORTING_RESULTS,
            f"发现 {len(dropped)} 个范围外的地址，未计入覆盖统计",
            {"out_of_scope_sample": dropped[:5]},
        )
    coverage = _build_coverage(
        urls=in_scope, pages=pages, alerts=alerts, items=len(alerts),
    )
    update_job(context,
        snap,
        total_alerts=int(alert_counts.total or 0),
        high_count=int(alert_counts.high or 0),
        medium_count=int(alert_counts.medium or 0),
        low_count=int(alert_counts.low or 0),
        info_count=int(alert_counts.info or 0),
        urls_discovered=pages.urls or len(urls),
        requests_made=pages.requests,
        new_findings_count=new_count,
        duplicate_findings_count=duplicate_count,
        coverage_summary=coverage,
        stage=JOB_STATUS_IMPORTING_RESULTS,
    )
    emit(context,
        snap, EVENT_TYPE_PROGRESS, JOB_STATUS_IMPORTING_RESULTS,
        f"结果导入完成：新增 {new_count} 条，重复 {duplicate_count} 条",
        {"alerts": len(alerts), "new": new_count, "duplicates": duplicate_count,
         "severity_counts": severity_counts,
         "page_stats": {"pages": pages.pages, "requests": pages.requests, "urls": pages.urls},
         "counts_from_stats": counts_from_stats.as_dict()},
    )
