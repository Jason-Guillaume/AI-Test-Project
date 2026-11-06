"""转写分段与单模型工作台读取服务。

本模块负责稳定保存 Provider 分段、精确文本偏移和工作台只读合同；缺少可靠时间时保留全文并显示未定位，
不从字数、标点或云端一致性推断时间和正确性。
"""

from __future__ import annotations

from typing import Any
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import threading
import time

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.platform.projects.services.access_service import get_project_or_404
from app.features.asr_evaluation.models import (
    AsrAudio, AsrAudioVersion, AsrConnection, AsrDiarizationResult, AsrFusionVersion,
    AsrJob, AsrModelRun, AsrProcessingRun, AsrSpeakerAssignment,
    AsrSpeakerTurn, AsrTranscriptSegment,
)

_statistics_cache: OrderedDict[tuple, tuple[float, dict[str, Any]]] = OrderedDict()
_statistics_lock = threading.Lock()


def persist_transcript_segments(db: Session, run: AsrModelRun, segments: list[dict[str, Any]]) -> None:
    """幂等保存转写片段及其原生 speaker_id、时间、声道、置信度和 Unicode 偏移。"""
    if len(segments) > 100_000:
        raise ValueError("转写片段超过上限，未保存截断结果")
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
    search: str | None = None, native_speaker_id: str | None = None, at_ms: int | None = None,
    start_ms: int | None = None, end_ms: int | None = None, locate_segment_id: str | None = None,
) -> dict[str, Any]:
    """分页读取稳定转写片段和本次关联归属，统计不受当前页或过滤器影响。"""
    run = db.get(AsrModelRun, run_id)
    if run is None:
        raise not_found("模型运行不存在")
    get_project_or_404(db, run.project_id, actor)
    if (start_ms is None) != (end_ms is None) or (start_ms is not None and end_ms is not None and end_ms <= start_ms):
        raise bad_request("播放定位范围无效")
    if at_ms is not None and start_ms is not None:
        raise bad_request("播放定位只能指定时间点或时间范围")
    persisted_count = db.query(func.count(AsrTranscriptSegment.id)).filter(
        AsrTranscriptSegment.model_run_id == run.id,
    ).scalar() or 0
    query = db.query(AsrTranscriptSegment).filter(AsrTranscriptSegment.model_run_id == run.id)
    timed_segment_count = db.query(func.count(AsrTranscriptSegment.id)).filter(
        AsrTranscriptSegment.model_run_id == run.id,
        AsrTranscriptSegment.start_ms.is_not(None), AsrTranscriptSegment.end_ms.is_not(None),
    ).scalar() or 0
    if locate_segment_id is not None:
        located_page = None
        if persisted_count:
            try:
                segment_id = int(locate_segment_id)
            except (TypeError, ValueError):
                segment_id = -1
            target = db.query(AsrTranscriptSegment).filter_by(id=segment_id, model_run_id=run.id).first()
            if target is not None:
                same_time = AsrTranscriptSegment.start_ms == target.start_ms
                same_index = AsrTranscriptSegment.segment_index == target.segment_index
                if target.start_ms is None:
                    before_target = or_(
                        AsrTranscriptSegment.start_ms.is_not(None),
                        and_(AsrTranscriptSegment.start_ms.is_(None), AsrTranscriptSegment.segment_index < target.segment_index),
                        and_(AsrTranscriptSegment.start_ms.is_(None), same_index, AsrTranscriptSegment.id < target.id),
                    )
                else:
                    before_target = or_(
                        and_(AsrTranscriptSegment.start_ms.is_not(None), AsrTranscriptSegment.start_ms < target.start_ms),
                        and_(same_time, AsrTranscriptSegment.segment_index < target.segment_index),
                        and_(same_time, same_index, AsrTranscriptSegment.id < target.id),
                    )
                preceding = db.query(func.count(AsrTranscriptSegment.id)).filter(
                    AsrTranscriptSegment.model_run_id == run.id, before_target,
                ).scalar() or 0
                located_page = preceding // page_size + 1
        elif run.segments:
            parts = locate_segment_id.split(":")
            if len(parts) == 3 and parts[0] == "legacy" and parts[1] == str(run.id):
                try:
                    target_index = int(parts[2])
                    values = [_legacy_segment(run, index, value) for index, value in enumerate(run.segments)]
                    values.sort(key=lambda item: (
                        item["start_ms"] is None, item["start_ms"] if item["start_ms"] is not None else 0,
                        item["segment_index"], item["id"],
                    ))
                    rank = next((index for index, item in enumerate(values) if item["segment_index"] == target_index), None)
                    located_page = rank // page_size + 1 if rank is not None else None
                except (TypeError, ValueError):
                    located_page = None
        return {"items": [], "total": persisted_count or len(run.segments or []), "page": 1,
                "page_size": page_size, "timed_segment_count": timed_segment_count,
                "located_page": located_page}
    if search:
        query = query.filter(AsrTranscriptSegment.text.contains(search[:200]))
    if native_speaker_id is not None:
        query = query.filter(AsrTranscriptSegment.native_speaker_id == native_speaker_id)
    if at_ms is not None:
        query = query.filter(
            AsrTranscriptSegment.start_ms.is_not(None), AsrTranscriptSegment.end_ms.is_not(None),
            AsrTranscriptSegment.start_ms <= at_ms, AsrTranscriptSegment.end_ms > at_ms,
        )
    if start_ms is not None and end_ms is not None:
        query = query.filter(
            AsrTranscriptSegment.start_ms.is_not(None), AsrTranscriptSegment.end_ms.is_not(None),
            AsrTranscriptSegment.start_ms < end_ms, AsrTranscriptSegment.end_ms > start_ms,
        )
    bounded_lookup = at_ms is not None or start_ms is not None
    page_assignment_lookup = bounded_lookup and speaker_id is None and not unknown_only and not mixed_only
    page_segment_ids = None
    if page_assignment_lookup and persisted_count:
        page_segment_ids = [row[0] for row in query.with_entities(AsrTranscriptSegment.id)
            .order_by(AsrTranscriptSegment.start_ms.asc().nulls_last(), AsrTranscriptSegment.segment_index, AsrTranscriptSegment.id)
            .offset((page - 1) * page_size).limit(page_size).all()]
    fusion = db.query(AsrFusionVersion).filter(
        AsrFusionVersion.model_run_id == run.id,
    ).order_by(AsrFusionVersion.version.desc()).first()
    assignment_map: dict[int, list[AsrSpeakerAssignment]] = {}
    if fusion is not None:
        assignment_query = db.query(AsrSpeakerAssignment).filter(AsrSpeakerAssignment.fusion_version_id == fusion.id)
        if page_segment_ids is not None:
            assignment_query = assignment_query.filter(AsrSpeakerAssignment.segment_id.in_(page_segment_ids or [-1]))
        assignments = assignment_query.order_by(AsrSpeakerAssignment.id).all()
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
    elif unknown_only:
        query = query.filter(or_(AsrTranscriptSegment.native_speaker_id.is_(None), AsrTranscriptSegment.native_speaker_id == ""))
    elif speaker_id is not None or mixed_only:
        # 没有关联结果时不能把独立说话人编号或混合归属解释成原生标签。
        query = query.filter(AsrTranscriptSegment.id == -1)
    total = query.order_by(None).count()
    rows = query.order_by(AsrTranscriptSegment.start_ms.asc().nulls_last(), AsrTranscriptSegment.segment_index,
        AsrTranscriptSegment.id).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    if not persisted_count and run.segments:
        # 0032 之前的历史 JSON 段按稳定的运行 ID 与原序号兼容呈现，不制造数据库时间。
        values = [_legacy_segment(run, index, value) for index, value in enumerate(run.segments)]
        timed_segment_count = sum(item["start_ms"] is not None and item["end_ms"] is not None for item in values)
        if speaker_id is not None:
            values = []
        if native_speaker_id is not None:
            values = [item for item in values if str(item["native_speaker_id"]) == native_speaker_id and item["native_speaker_id"] is not None]
        if mixed_only:
            values = []
        if search:
            values = [item for item in values if search[:200] in item["text"]]
        if at_ms is not None:
            values = [item for item in values if item["start_ms"] is not None and item["end_ms"] is not None
                      and item["start_ms"] <= at_ms < item["end_ms"]]
        if start_ms is not None and end_ms is not None:
            values = [item for item in values if item["start_ms"] is not None and item["end_ms"] is not None
                      and item["start_ms"] < end_ms and item["end_ms"] > start_ms]
        if unknown_only:
            values = [item for item in values if item["native_speaker_id"] is None or item["native_speaker_id"] == ""]
        total = len(values)
        values = values[(page - 1) * page_size:page * page_size]
    else:
        values = [_dump_segment(row, assignment_map.get(row.id, [])) for row in rows]
    return {"items": values, "total": total, "page": page, "page_size": page_size,
            "timed_segment_count": timed_segment_count}


def get_native_statistics(db: Session, run_id: int, actor: User) -> dict[str, Any]:
    """统计全量原生标签与合法时间并集；项目不可见时按不存在处理。"""
    run = db.get(AsrModelRun, run_id)
    if run is None:
        raise not_found("模型运行不存在")
    get_project_or_404(db, run.project_id, actor)
    # 始终先鉴权，再按运行结果、关联和人工复核版本命中受限进程缓存。
    segment_version = db.query(func.count(AsrTranscriptSegment.id), func.max(AsrTranscriptSegment.id)).filter_by(model_run_id=run.id).one()
    fusion = db.query(AsrFusionVersion).filter_by(model_run_id=run.id).order_by(AsrFusionVersion.version.desc()).first()
    review_version = db.query(func.count(AsrSpeakerAssignment.id), func.sum(AsrSpeakerAssignment.review_version),
        func.max(AsrSpeakerAssignment.updated_at)).filter_by(fusion_version_id=fusion.id).one() if fusion else None
    text_hash = hashlib.sha256((run.transcript or "").encode("utf-8")).hexdigest()
    legacy_hash = hashlib.sha256(json.dumps(run.segments or [], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest() if not segment_version[0] else None
    cache_key = (db.get_bind(), run.project_id, run.id, run.finished_at, text_hash, legacy_hash,
                 tuple(segment_version), fusion.id if fusion else None, tuple(review_version) if review_version else None)
    with _statistics_lock:
        cached = _statistics_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 30:
            _statistics_cache.move_to_end(cache_key)
            return deepcopy(cached[1])
    rows = db.query(AsrTranscriptSegment).filter(
        AsrTranscriptSegment.model_run_id == run.id,
    ).order_by(AsrTranscriptSegment.segment_index).all()
    segments = [_dump_segment(row, []) for row in rows] if rows else [
        _legacy_segment(run, index, value) for index, value in enumerate(run.segments or [])
    ]
    grouped: dict[str, list[tuple[int, int]]] = {}
    unknown = 0
    for segment in segments:
        label = segment["native_speaker_id"]
        if label is None or label == "":
            unknown += 1
            continue
        intervals = grouped.setdefault(str(label), [])
        start, end = segment["start_ms"], segment["end_ms"]
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end:
            intervals.append((start, end))
    speakers = []
    for label, intervals in sorted(grouped.items()):
        duration = 0
        last_start = last_end = None
        for start, end in sorted(intervals):
            if last_end is None:
                last_start, last_end = start, end
            elif start <= last_end:
                last_end = max(last_end, end)
            else:
                duration += last_end - last_start
                last_start, last_end = start, end
        if last_end is not None:
            duration += last_end - last_start
        speakers.append({"native_speaker_id": label, "speech_duration_ms": duration, "timed_intervals": len(intervals)})
    total_duration = sum(item["speech_duration_ms"] for item in speakers)
    for item in speakers:
        item["share"] = item["speech_duration_ms"] / total_duration if total_duration else None
    fusion_summary = None
    if fusion:
        assignments = db.query(AsrSpeakerAssignment).filter_by(fusion_version_id=fusion.id).all()
        # 人工确认只覆盖对应关联，不以全文或字符长度推断人工发言时长。
        fusion_summary = {"fusion_version": fusion.version, "assignment_count": len(assignments),
            "manual_confirmed": sum(item.review_status == "CONFIRMED" for item in assignments),
            "automatic": sum(item.review_status != "CONFIRMED" for item in assignments),
            "unknown": sum(item.assignment_status in {"UNKNOWN", "UNALIGNED"} for item in assignments),
            "mixed": sum(item.assignment_status == "MIXED" for item in assignments),
            "overlap": sum(item.assignment_status == "OVERLAPPED" for item in assignments),
            "review_version_sum": sum(item.review_version for item in assignments)}
    result = {
        "source": "NATIVE", "segment_count": len(segments), "unknown_segment_count": unknown,
        "character_count": sum(not char.isspace() for char in (run.transcript or "")),
        "speaker_count": len(speakers), "speakers": speakers, "fusion_summary": fusion_summary,
    }
    with _statistics_lock:
        _statistics_cache[cache_key] = (time.monotonic(), deepcopy(result))
        _statistics_cache.move_to_end(cache_key)
        while len(_statistics_cache) > 128:
            _statistics_cache.popitem(last=False)
    return result


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
