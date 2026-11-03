"""转写分段与单模型工作台读取服务。

本模块负责稳定保存 Provider 分段、精确文本偏移和工作台只读合同；缺少可靠时间时保留全文并显示未定位，
不从字数、标点或云端一致性推断时间和正确性。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.http.errors import not_found
from app.core.models.identity import User
from app.platform.projects.services.access_service import get_project_or_404
from app.features.asr_evaluation.models import (
    AsrAudio, AsrAudioVersion, AsrConnection, AsrDiarizationResult, AsrFusionVersion,
    AsrJob, AsrModelRun, AsrProcessingRun, AsrSpeakerAssignment,
    AsrSpeakerTurn, AsrTranscriptSegment,
)


def persist_transcript_segments(db: Session, run: AsrModelRun, segments: list[dict[str, Any]]) -> None:
    """幂等保存转写片段及其原生 speaker_id、时间、声道、置信度和 Unicode 偏移。"""
    existing = {
        row.segment_index: row for row in db.query(AsrTranscriptSegment).filter(
            AsrTranscriptSegment.model_run_id == run.id,
        ).all()
    }
    retained_indexes = set()
    cursor = 0
    for index, source in enumerate(segments[:100_000]):
        if not isinstance(source, dict) or not isinstance(source.get("text"), str):
            continue
        segment_index = int(source.get("segment_index", index))
        retained_indexes.add(segment_index)
        text_value = source["text"]
        start_offset = source.get("start_offset")
        end_offset = source.get("end_offset")
        if not isinstance(start_offset, int) or not isinstance(end_offset, int):
            # 旧 Provider 没有保存偏移时仅按原文后续精确出现位置补全，不用模糊匹配。
            found = (run.transcript or "").find(text_value, cursor) if text_value else -1
            start_offset = found if found >= 0 else None
            end_offset = found + len(text_value) if found >= 0 else None
        if end_offset is not None:
            cursor = max(cursor, end_offset)
        start_ms = source.get("start_ms")
        end_ms = source.get("end_ms")
        if start_ms is None and source.get("start_seconds") is not None:
            start_ms = round(float(source["start_seconds"]) * 1000)
        if end_ms is None and source.get("end_seconds") is not None:
            end_ms = round(float(source["end_seconds"]) * 1000)
        raw_speaker = source.get("native_speaker_id", source.get("speaker_id"))
        row = existing.get(segment_index)
        if row is None:
            row = AsrTranscriptSegment(model_run_id=run.id, segment_index=segment_index, text=text_value)
            db.add(row)
        row.source_segment_id = (
            str(source.get("source_segment_id")) if source.get("source_segment_id") is not None else None
        )
        row.text = text_value
        row.start_ms = int(start_ms) if isinstance(start_ms, (int, float)) else None
        row.end_ms = int(end_ms) if isinstance(end_ms, (int, float)) else None
        row.start_offset = start_offset
        row.end_offset = end_offset
        row.native_speaker_id = str(raw_speaker) if raw_speaker is not None else None
        confidence = source.get("confidence")
        row.confidence = float(confidence) if isinstance(confidence, (int, float)) else None
        row.channel = str(source.get("channel")) if source.get("channel") is not None else None
        row.word_times = source.get("word_times") if isinstance(source.get("word_times"), list) else []
        row.raw_payload = {}
    # 结果重放如果片段数减少，删掉超出范围的旧规范化片段。
    for old_index, old_row in existing.items():
        if old_index not in retained_indexes:
            db.delete(old_row)


def get_run_workbench(db: Session, run_id: int, actor: User) -> dict[str, Any]:
    """读取固定音频版本的单模型工作台摘要、状态与最新同版本关联结果。"""
    run = db.get(AsrModelRun, run_id)
    if run is None:
        raise not_found("模型运行不存在")
    get_project_or_404(db, run.project_id, actor)
    job = db.get(AsrJob, run.job_id)
    audio = db.get(AsrAudio, run.audio_id)
    version = db.get(AsrAudioVersion, run.audio_version_id) if run.audio_version_id else None
    connection = db.get(AsrConnection, run.connection_id)
    processing = None
    diarization = None
    fusion = None
    if version is not None:
        processing = db.query(AsrProcessingRun).filter(
            AsrProcessingRun.audio_version_id == version.id,
            AsrProcessingRun.task_type == "DIARIZATION",
        ).order_by(AsrProcessingRun.id.desc()).first()
        diarization = db.query(AsrDiarizationResult).filter(
            AsrDiarizationResult.audio_version_id == version.id,
        ).order_by(AsrDiarizationResult.id.desc()).first()
        if diarization is not None:
            fusion = db.query(AsrFusionVersion).filter(
                AsrFusionVersion.model_run_id == run.id,
                AsrFusionVersion.diarization_result_id == diarization.id,
            ).order_by(AsrFusionVersion.version.desc()).first()
    segment_count = db.query(func.count(AsrTranscriptSegment.id)).filter(
        AsrTranscriptSegment.model_run_id == run.id,
    ).scalar() or 0
    return {
        "run": {
            "id": run.id, "project_id": run.project_id, "job_id": run.job_id, "audio_id": run.audio_id,
            "audio_version_id": run.audio_version_id, "connection_id": run.connection_id,
            "role": run.role, "status": run.status, "transcript": run.transcript,
            "parameter_set_id": run.parameter_set_id, "request_snapshot": run.request_snapshot,
            "error_message": run.error_message, "duration_ms": run.duration_ms,
            "created_at": run.created_at, "finished_at": run.finished_at,
            "segment_count": segment_count or len(run.segments or []),
        },
        "job": {"id": job.id, "status": job.status} if job else None,
        "audio": ({
            "id": audio.id, "project_id": audio.project_id, "name": version.name,
            "audio_version_id": version.id, "content_version": version.version,
            "duration_seconds": version.duration_seconds, "url_display": version.url_display,
            "media_url": f"/api/v1/asr/audio/{audio.id}/versions/{version.id}/media",
            "version_available": True,
        } if audio and version else ({
            "id": audio.id, "project_id": audio.project_id, "name": audio.name,
            "audio_version_id": None, "content_version": None, "duration_seconds": None,
            "url_display": None, "media_url": None, "version_available": False,
        } if audio else None)),
        "model": ({
            "name": connection.name, "model_id": connection.model_id, "connection_version": connection.version,
        } if connection else None),
        "diarization": {
            "processing_run": dump_processing_run(processing) if processing else None,
            "result_id": diarization.id if diarization else None,
            "schema_version": diarization.schema_version if diarization else None,
            "timeline": diarization.timeline if diarization else None,
            "fusion_version_id": fusion.id if fusion else None,
            "fusion_version": fusion.version if fusion else None,
            "fusion_status": fusion.status if fusion else "UNALIGNED",
        },
    }


def list_transcript_segments(
    db: Session, run_id: int, actor: User, *, page: int = 1, page_size: int = 100,
    speaker_id: int | None = None, unknown_only: bool = False, mixed_only: bool = False,
    search: str | None = None,
) -> dict[str, Any]:
    """分页读取稳定转写片段和本次关联归属，统计不受当前页或过滤器影响。"""
    run = db.get(AsrModelRun, run_id)
    if run is None:
        raise not_found("模型运行不存在")
    get_project_or_404(db, run.project_id, actor)
    total = db.query(func.count(AsrTranscriptSegment.id)).filter(
        AsrTranscriptSegment.model_run_id == run.id,
    ).scalar() or 0
    query = db.query(AsrTranscriptSegment).filter(AsrTranscriptSegment.model_run_id == run.id)
    if search:
        query = query.filter(AsrTranscriptSegment.text.contains(search[:200]))
    fusion = db.query(AsrFusionVersion).filter(
        AsrFusionVersion.model_run_id == run.id,
    ).order_by(AsrFusionVersion.version.desc()).first()
    assignment_map: dict[int, list[AsrSpeakerAssignment]] = {}
    if fusion is not None:
        assignments = db.query(AsrSpeakerAssignment).filter(
            AsrSpeakerAssignment.fusion_version_id == fusion.id,
        ).order_by(AsrSpeakerAssignment.id).all()
        for assignment in assignments:
            if assignment.segment_id is not None:
                assignment_map.setdefault(assignment.segment_id, []).append(assignment)
        if speaker_id is not None:
            matched = {
                item.segment_id for item in assignments
                if (item.confirmed_speaker_id if item.review_status == "CONFIRMED" else item.speaker_id) == speaker_id
            }
            query = query.filter(AsrTranscriptSegment.id.in_(matched or [-1]))
        elif unknown_only:
            matched = {
                item.segment_id for item in assignments
                if (
                    item.assignment_status in {"UNKNOWN", "UNALIGNED"}
                    or (item.confirmed_speaker_id if item.review_status == "CONFIRMED" else item.speaker_id) is None
                )
            }
            if not assignments:
                matched = {
                    value[0] for value in db.query(AsrTranscriptSegment.id).filter(
                        AsrTranscriptSegment.model_run_id == run.id,
                    ).all()
                }
            query = query.filter(AsrTranscriptSegment.id.in_(matched or [-1]))
        elif mixed_only:
            matched = {item.segment_id for item in assignments if item.assignment_status in {"MIXED", "OVERLAPPED"}}
            query = query.filter(AsrTranscriptSegment.id.in_(matched or [-1]))
    total = query.order_by(None).count()
    rows = query.order_by(AsrTranscriptSegment.start_ms, AsrTranscriptSegment.segment_index).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    if not total and run.segments:
        # 0032 之前的历史 JSON 段按稳定的运行 ID 与原序号兼容呈现，不制造数据库时间。
        values = [_legacy_segment(run, index, value) for index, value in enumerate(run.segments)]
        if speaker_id is not None:
            values = [item for item in values if item["native_speaker_id"] == str(speaker_id)]
        if search:
            values = [item for item in values if search[:200] in item["text"]]
        if unknown_only:
            values = [item for item in values if item["native_speaker_id"] is None]
        total = len(values)
        values = values[(page - 1) * page_size:page * page_size]
    else:
        values = [_dump_segment(row, assignment_map.get(row.id, [])) for row in rows]
    return {"items": values, "total": total, "page": page, "page_size": page_size}


def dump_processing_run(row: AsrProcessingRun) -> dict[str, Any]:
    """序列化处理阶段状态，不回传加密请求快照或远端签名字段。"""
    return {
        "id": row.id, "task_type": row.task_type, "audio_version_id": row.audio_version_id,
        "connection_id": row.connection_id, "status": row.status, "attempts": row.attempts,
        "result_id": row.result_id, "error_message": row.error_message,
        "duration_ms": row.duration_ms, "created_at": row.created_at, "finished_at": row.finished_at,
    }


def _dump_segment(row: AsrTranscriptSegment, assignments: list[AsrSpeakerAssignment]) -> dict[str, Any]:
    """生成分段合同并区分原生 speaker 字段与独立模型关联。"""
    return {
        "id": str(row.id), "segment_index": row.segment_index, "source_segment_id": row.source_segment_id,
        "text": row.text, "start_ms": row.start_ms, "end_ms": row.end_ms,
        "start_offset": row.start_offset, "end_offset": row.end_offset,
        "native_speaker_id": row.native_speaker_id, "confidence": row.confidence, "channel": row.channel,
        "word_times": row.word_times or [],
        "assignments": [{
            "id": item.id,
            "speaker_id": item.confirmed_speaker_id if item.review_status == "CONFIRMED" else item.speaker_id,
            "turn_id": item.speaker_turn_id, "status": item.assignment_status,
            "source": "MANUAL" if item.review_status == "CONFIRMED" else item.source,
            "review_status": item.review_status, "review_version": item.review_version,
        } for item in assignments],
    }


def _legacy_segment(run: AsrModelRun, index: int, value: Any) -> dict[str, Any]:
    """把旧 JSON 分段映射为稳定兼容键，缺失时间保持未知。"""
    value = value if isinstance(value, dict) else {}
    start_ms = value.get("start_ms")
    end_ms = value.get("end_ms")
    if start_ms is None and value.get("start_seconds") is not None:
        start_ms = round(float(value["start_seconds"]) * 1000)
    if end_ms is None and value.get("end_seconds") is not None:
        end_ms = round(float(value["end_seconds"]) * 1000)
    return {
        "id": f"legacy:{run.id}:{index}", "segment_index": index,
        "source_segment_id": value.get("source_segment_id"), "text": value.get("text", ""),
        "start_ms": start_ms, "end_ms": end_ms, "start_offset": value.get("start_offset"),
        "end_offset": value.get("end_offset"), "native_speaker_id": value.get("native_speaker_id"),
        "confidence": value.get("confidence"), "channel": value.get("channel"),
        "word_times": value.get("word_times") or [], "assignments": [],
    }


__all__ = [
    "dump_processing_run", "get_run_workbench", "list_transcript_segments", "persist_transcript_segments",
]
