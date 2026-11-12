"""固定音频版本的后台媒体分析任务与信息查询。

页面按需读取当前播放快照和服务端已生成的元数据/峰值；分析任务在明确触发后排队，
元数据缺失时返回空字段与状态，不由浏览器整段下载并解码音频。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.http.errors import not_found
from app.core.models.identity import User
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.features.asr_evaluation.models import (
    AsrAudio, AsrAudioVersion, AsrMediaAnalysis, AsrProcessingRun, AsrProcessingWorkItem,
)
from app.features.asr_evaluation.services.segments_service import dump_processing_run

_ANALYZER = "server-media-v1"


def create_media_analysis_run(
    db: Session, audio_id: int, audio_version_id: int, actor: User,
) -> dict[str, Any]:
    """为授权的不可变音频版本排队后台解析；成功缓存仍有效时复用原任务。"""
    audio = db.get(AsrAudio, audio_id)
    version = db.get(AsrAudioVersion, audio_version_id)
    if audio is None or version is None or version.audio_id != audio.id:
        raise not_found("音频或音频版本不存在")
    require_writable_project(db, audio.project_id, actor)
    parameter_hash = hashlib.sha256(_ANALYZER.encode()).hexdigest()
    existing = db.query(AsrProcessingRun).filter(
        AsrProcessingRun.audio_version_id == version.id,
        AsrProcessingRun.task_type == "MEDIA_ANALYSIS",
        AsrProcessingRun.parameter_hash == parameter_hash,
        AsrProcessingRun.retry_of_id.is_(None),
    ).order_by(AsrProcessingRun.id.desc()).first()
    if existing is not None:
        return dump_processing_run(existing)
    row = AsrProcessingRun(
        project_id=audio.project_id, audio_id=audio.id, audio_version_id=version.id,
        task_type="MEDIA_ANALYSIS", connection_id=None, parameters={"analyzer": _ANALYZER},
        parameter_hash=parameter_hash, execution_ciphertext=None,
        request_snapshot={"audio_version": version.version, "analyzer": _ANALYZER},
        status="PENDING", deadline_at=datetime.now(timezone.utc) + timedelta(hours=24),
        created_by=actor.id,
    )
    db.add(row)
    db.flush()
    db.add(AsrProcessingWorkItem(processing_run_id=row.id, available_at=datetime.now(timezone.utc)))
    db.commit()
    db.refresh(row)
    return dump_processing_run(row)


def record_media_analysis(
    db: Session, processing_run_id: int, data: dict[str, Any], *, commit: bool = True,
) -> AsrMediaAnalysis:
    """持久化后台分析结果、峰值和来源，失败或工具缺失也保留明确状态。"""
    run = db.get(AsrProcessingRun, processing_run_id)
    if run is None or run.task_type != "MEDIA_ANALYSIS":
        raise not_found("音频分析任务不存在")
    row = db.query(AsrMediaAnalysis).filter(
        AsrMediaAnalysis.processing_run_id == run.id,
    ).one_or_none()
    if row is None:
        row = AsrMediaAnalysis(
            project_id=run.project_id, audio_version_id=run.audio_version_id,
            processing_run_id=run.id, status=str(data.get("status", "UNAVAILABLE")),
            source=data.get("source"), analyzer_version=data.get("analyzer_version"),
            source_info=data.get("source_info") or {},
            original_format=data.get("original_format") or {}, analysis_pcm=data.get("analysis_pcm") or {},
            signal_statistics=data.get("signal_statistics") or {}, peaks=data.get("peaks") or {},
            processed_range=data.get("processed_range") or {}, warnings=data.get("warnings") or [],
            analyzed_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.flush()
    run.result_id = row.id
    run.status = "SUCCEEDED" if row.status in {"AVAILABLE", "PARTIAL"} else "FAILED"
    run.error_message = None if run.status == "SUCCEEDED" else (
        (row.warnings or ["服务端媒体分析不可用"])[0]
    )
    run.finished_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
    return row


def get_audio_metadata(
    db: Session, audio_id: int, audio_version_id: int, actor: User,
) -> dict[str, Any]:
    """读取来源、原文件、分析 PCM、信号统计和任务状态，未知字段保持显式为空。"""
    audio = db.get(AsrAudio, audio_id)
    version = db.get(AsrAudioVersion, audio_version_id)
    if audio is None or version is None or version.audio_id != audio.id:
        raise not_found("音频或音频版本不存在")
    get_project_or_404(db, audio.project_id, actor)
    analysis = db.query(AsrMediaAnalysis).filter(
        AsrMediaAnalysis.audio_version_id == version.id,
    ).order_by(AsrMediaAnalysis.id.desc()).first()
    processing = db.query(AsrProcessingRun).filter(
        AsrProcessingRun.audio_version_id == version.id,
        AsrProcessingRun.task_type == "MEDIA_ANALYSIS",
    ).order_by(AsrProcessingRun.id.desc()).first()
    source_info = {
        "name": version.name, "audio_version": version.version, "url_display": version.url_display,
        "playback_url": f"/api/v1/asr/audio/{audio.id}/versions/{version.id}/media",
        "source_size_bytes": None, "last_modified": None, "etag": None,
        "source_label": "已登记音频源；源文件响应头待后台分析读取",
    }
    if analysis and analysis.source_info:
        source_info.update(analysis.source_info)
    return {
        "audio_id": audio.id, "audio_version_id": version.id, "content_version": version.version,
        "source_info": source_info,
        "original_format": analysis.original_format if analysis else {},
        "analysis_pcm": analysis.analysis_pcm if analysis else {},
        "signal_statistics": analysis.signal_statistics if analysis else {},
        "processed_range": analysis.processed_range if analysis else {},
        "warnings": analysis.warnings if analysis else [],
        "analysis_status": analysis.status if analysis else (
            {
                "PENDING": "QUEUED", "SUBMITTING": "SUBMITTING", "REMOTE_RUNNING": "REMOTE_RUNNING",
                "FAILED": "FAILED", "RECONCILIATION_REQUIRED": "FAILED", "CANCELLED": "FAILED",
            }.get(processing.status, "NOT_STARTED") if processing else "NOT_STARTED"
        ),
        "analysis_id": analysis.id if analysis else None,
        "processing_run": dump_processing_run(processing) if processing else None,
    }


def get_audio_peaks(
    db: Session, audio_id: int, audio_version_id: int, resolution: int, actor: User,
) -> dict[str, Any]:
    """按需读取真实的服务端峰值数组；未分析时明确返回空集合和任务状态。"""
    metadata = get_audio_metadata(db, audio_id, audio_version_id, actor)
    if resolution not in {2048, 8192}:
        from app.core.http.errors import bad_request
        raise bad_request("峰值分辨率仅支持 2048 或 8192")
    analysis = db.query(AsrMediaAnalysis).filter(
        AsrMediaAnalysis.audio_version_id == audio_version_id,
    ).order_by(AsrMediaAnalysis.id.desc()).first()
    values = (analysis.peaks or {}).get(str(resolution), []) if analysis else []
    return {
        "audio_version_id": audio_version_id, "resolution": resolution,
        "channels": values, "status": metadata["analysis_status"],
    }


__all__ = [
    "create_media_analysis_run", "get_audio_metadata", "get_audio_peaks", "record_media_analysis",
]
