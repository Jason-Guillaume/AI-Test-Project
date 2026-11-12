"""独立说话人处理、版本化关联与人工复核服务。

同一原始音频版本默认只创建一条处理运行；结果可与该版本的多家转写分别关联。
本模块不识别真实身份、不按字数造时间、不把说话人重试转换成 ASR 重跑。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import heapq
from typing import Any

from sqlalchemy.orm import Session

from app.core.http.errors import bad_request, conflict, not_found
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.features.asr_evaluation.models import (
    AsrAudio, AsrAudioVersion, AsrConnection, AsrDiarizationResult, AsrFusionVersion,
    AsrModelRun, AsrProcessingRun, AsrProcessingWorkItem, AsrSpeaker, AsrSpeakerAssignment,
    AsrSpeakerNameAudit, AsrSpeakerReviewAudit, AsrSpeakerTurn, AsrTranscriptSegment,
)
from app.features.asr_evaluation.schemas import DiarizationRunCreate, SpeakerNameUpdate, SpeakerReviewInput
from app.features.asr_evaluation.services.assets_service import _validate_parameters
from app.features.asr_evaluation.services.segments_service import dump_processing_run
from app.platform.model_configuration.models import ModelTaskSlot
from app.platform.model_configuration.services.model_center_service import resolve_task_slots


def _hash_json(value: dict[str, Any]) -> str:
    """对规范化参数快照计算摘要，用于同版本重复请求去重。"""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _redact_parameters(value: Any) -> Any:
    """Remove credentials from request snapshots while retaining adjustable model values."""
    if isinstance(value, dict):
        return {
            key: "[已脱敏]" if any(token in str(key).lower() for token in ("token", "secret", "password", "key", "cookie"))
            else _redact_parameters(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_parameters(item) for item in value]
    return value


def create_diarization_run(
    db: Session, audio_id: int, audio_version_id: int, body: DiarizationRunCreate, actor: User,
) -> dict[str, Any]:
    """按固定音频版本排队说话人分析；重复请求复用现存运行，不重复提交模型。"""
    audio = db.get(AsrAudio, audio_id)
    version = db.get(AsrAudioVersion, audio_version_id)
    if audio is None or version is None or version.audio_id != audio_id:
        raise not_found("音频或音频版本不存在")
    require_writable_project(db, audio.project_id, actor)
    model_selection = None
    if body.resource_id is not None:
        from app.features.asr_evaluation.schemas import ModelTaskSlotInput

        model_selection = resolve_task_slots(db, audio.project_id, [ModelTaskSlotInput(
            slot="DIARIZATION", resource_id=body.resource_id,
            revision_id=body.revision_id, profile_id=body.profile_id,
        )], actor)[0]
        connection = model_selection["connection"]
        parameters = dict(model_selection["profile"].parameter_values or {})
        definitions = model_selection["profile"].definitions or []
    else:
        connection = db.get(AsrConnection, body.connection_id)
        parameters = body.parameters or {}
        definitions = (connection.config_json or {}).get("parameter_definitions") or [] if connection else []
    if (
        connection is None or connection.project_id != audio.project_id
        or connection.task_type != "DIARIZATION" or not connection.enabled
    ):
        raise not_found("可用的说话人连接不存在")
    config = connection.config_json or {}
    _validate_parameters(parameters, definitions)
    parameter_hash = _hash_json(parameters)
    # 音频版本行锁串行化首次创建，避免两个浏览器同时点击产生重复模型调用。
    db.query(AsrAudioVersion).filter(AsrAudioVersion.id == version.id).with_for_update().one()
    existing = db.query(AsrProcessingRun).filter(
        AsrProcessingRun.audio_version_id == version.id,
        AsrProcessingRun.task_type == "DIARIZATION",
        AsrProcessingRun.connection_id == connection.id,
        AsrProcessingRun.parameter_hash == parameter_hash,
        AsrProcessingRun.retry_of_id.is_(None),
    ).order_by(AsrProcessingRun.id.desc()).first()
    if existing is not None:
        return dump_processing_run(existing)
    execution = {
        "audio_url": decrypt_secret(version.url_ciphertext),
        "endpoint": decrypt_secret(connection.endpoint_ciphertext),
        "model_id": connection.model_id, "model_version": config.get("model_version"),
        "secret": decrypt_secret(connection.secret_ciphertext),
        "secret_header": connection.secret_header, "parameters": parameters, **config,
    }
    row = AsrProcessingRun(
        project_id=audio.project_id, audio_id=audio.id, audio_version_id=version.id,
        task_type="DIARIZATION", connection_id=connection.id, parameters=parameters,
        parameter_hash=parameter_hash, execution_ciphertext=encrypt_secret(json.dumps(execution, ensure_ascii=False)),
        request_snapshot={
            "connection_name": connection.name, "connection_version": connection.version,
            "model_id": connection.model_id, "parameters": _redact_parameters(parameters),
            "audio_version": version.version,
            "model_resource_id": model_selection["resource"].id if model_selection else None,
            "model_revision_id": model_selection["revision"].id if model_selection else None,
            "parameter_profile_id": model_selection["profile"].id if model_selection else None,
            "parameter_profile_name": model_selection["profile"].name if model_selection else None,
            "parameter_profile_version": model_selection["profile"].version if model_selection else None,
        },
        status="PENDING", deadline_at=datetime.now(timezone.utc) + timedelta(hours=24), created_by=actor.id,
    )
    db.add(row)
    db.flush()
    if model_selection is not None:
        db.add(ModelTaskSlot(
            task_kind="ASR_PROCESSING_RUN", task_id=row.id, slot="DIARIZATION",
            resource_id=model_selection["resource"].id, revision_id=model_selection["revision"].id,
            profile_id=model_selection["profile"].id, legacy_connection_id=connection.id,
        ))
    db.add(AsrProcessingWorkItem(processing_run_id=row.id, available_at=datetime.now(timezone.utc)))
    # 任务快照与独立工作项同事务提交，失败不会留下不可恢复的处理中状态。
    db.commit()
    db.refresh(row)
    return dump_processing_run(row)


def retry_processing_run(db: Session, processing_run_id: int, actor: User) -> dict[str, Any]:
    """创建失败处理阶段的新尝试，沿用相同快照且不创建任何 ASR 运行。"""
    source = db.get(AsrProcessingRun, processing_run_id)
    if source is None:
        raise not_found("后台处理任务不存在")
    project = get_project_or_404(db, source.project_id, actor)
    if source.status != "FAILED":
        raise bad_request("仅明确失败的处理阶段可安全重试；待核实提交需要先核对远端状态")
    require_writable_project(db, project.id, actor)
    if source.task_type != "MEDIA_ANALYSIS" and source.execution_ciphertext is None:
        raise bad_request("该处理任务没有可复用的执行快照")
    retry = AsrProcessingRun(
        project_id=source.project_id, audio_id=source.audio_id, audio_version_id=source.audio_version_id,
        task_type=source.task_type, connection_id=source.connection_id, retry_of_id=source.id,
        parameters=source.parameters or {}, parameter_hash=source.parameter_hash,
        execution_ciphertext=source.execution_ciphertext, request_snapshot=source.request_snapshot or {},
        status="PENDING", deadline_at=datetime.now(timezone.utc) + timedelta(hours=24), created_by=actor.id,
    )
    db.add(retry)
    db.flush()
    db.add(AsrProcessingWorkItem(processing_run_id=retry.id, available_at=datetime.now(timezone.utc)))
    db.commit()
    db.refresh(retry)
    return dump_processing_run(retry)


def get_processing_run(db: Session, processing_run_id: int, actor: User) -> dict[str, Any]:
    """读取一个独立处理阶段的持久状态、结果引用和安全错误。"""
    row = db.get(AsrProcessingRun, processing_run_id)
    if row is None:
        raise not_found("后台处理任务不存在")
    get_project_or_404(db, row.project_id, actor)
    return dump_processing_run(row)


def record_diarization_result(
    db: Session, processing_run_id: int, *, turns: list[dict[str, Any]], timeline: str,
    raw_response: Any, model_version: str | None, duration_ms: int | None, commit: bool = True,
) -> AsrDiarizationResult:
    """保存一份不可变标准结果，并自动与同音频版本的成功转写建立时间关联。"""
    run = db.get(AsrProcessingRun, processing_run_id)
    if run is None or run.task_type != "DIARIZATION":
        raise not_found("说话人处理任务不存在")
    connection = db.get(AsrConnection, run.connection_id) if run.connection_id else None
    if connection is None:
        raise not_found("说话人连接不存在")
    result = db.query(AsrDiarizationResult).filter(
        AsrDiarizationResult.processing_run_id == run.id,
    ).one_or_none()
    if result is None:
        result = AsrDiarizationResult(
            project_id=run.project_id, audio_id=run.audio_id, audio_version_id=run.audio_version_id,
            processing_run_id=run.id, schema_version="1.0", timeline=timeline,
            source_model_id=connection.model_id, source_model_version=model_version,
            raw_response=raw_response if isinstance(raw_response, (dict, list)) else {},
            warnings=[] if timeline == "original_audio" else ["模型时间轴不是原始音频，未执行自动转写关联。"],
        )
        db.add(result)
        db.flush()
        _save_speakers_and_turns(db, result, turns)
    run.result_id = result.id
    run.status = "SUCCEEDED"
    run.error_message = None
    run.duration_ms = duration_ms
    run.finished_at = datetime.now(timezone.utc)
    db.flush()
    if timeline == "original_audio":
        transcription_runs = db.query(AsrModelRun).filter(
            AsrModelRun.audio_version_id == run.audio_version_id,
            AsrModelRun.status == "SUCCEEDED",
        ).order_by(AsrModelRun.id).all()
        for transcription_run in transcription_runs:
            create_fusion_version(db, transcription_run, result)
    if commit:
        db.commit()
    return result


def _save_speakers_and_turns(
    db: Session, result: AsrDiarizationResult, turns: list[dict[str, Any]],
) -> None:
    """保存原生标签与区间顺序；未知标签保留 null，重叠区间不合并。"""
    speakers: dict[tuple[str, str | None], AsrSpeaker] = {}
    ordinal: dict[tuple[str, str | None], int] = {}
    for index, turn in enumerate(turns[:100_000]):
        source_label = turn.get("source_speaker_id")
        channel = str(turn["channel"]) if turn.get("channel") is not None else None
        key = (str(source_label), channel) if source_label is not None else None
        speaker = None
        if key is not None:
            speaker = speakers.get(key)
            if speaker is None:
                ordinal[key] = len(ordinal) + 1
                speaker = AsrSpeaker(
                    result_id=result.id, source_label=key[0], channel=channel,
                    display_name=f"说话人 {ordinal[key]}", first_seen_ms=turn.get("start_ms"),
                )
                db.add(speaker)
                db.flush()
                speakers[key] = speaker
        stable_id = str(turn.get("stable_id") or f"{result.id}:turn:{index}")
        db.add(AsrSpeakerTurn(
            result_id=result.id, turn_index=index, stable_id=stable_id,
            speaker_id=speaker.id if speaker else None,
            source_speaker_id=str(source_label) if source_label is not None else None,
            start_ms=int(turn["start_ms"]), end_ms=int(turn["end_ms"]),
            text=turn.get("text"), channel=channel, confidence=turn.get("confidence"),
            raw_payload=turn.get("raw_payload") if isinstance(turn.get("raw_payload"), dict) else {},
        ))


def create_fusion_version(
    db: Session, run: AsrModelRun, result: AsrDiarizationResult, *, actor: User | None = None,
) -> AsrFusionVersion:
    """按真实时间交集为同音频版本创建不可变关联，未对齐文本保留为未知。"""
    if run.audio_version_id != result.audio_version_id:
        raise conflict("转写与说话人结果不属于同一音频版本")
    existing = db.query(AsrFusionVersion).filter(
        AsrFusionVersion.model_run_id == run.id,
        AsrFusionVersion.diarization_result_id == result.id,
    ).order_by(AsrFusionVersion.version.desc()).first()
    if existing is not None:
        return existing
    segments = db.query(AsrTranscriptSegment).filter(
        AsrTranscriptSegment.model_run_id == run.id,
    ).order_by(AsrTranscriptSegment.segment_index).all()
    timed_segments = [
        item for item in segments
        if item.start_ms is not None and item.end_ms is not None and item.end_ms > item.start_ms
    ]
    fusion_status = (
        "UNALIGNED" if result.timeline != "original_audio" or not timed_segments
        else "PARTIAL" if len(timed_segments) < len(segments) else "COMPLETE"
    )
    fusion = AsrFusionVersion(
        project_id=run.project_id, model_run_id=run.id, audio_version_id=run.audio_version_id,
        diarization_result_id=result.id, version=1, status=fusion_status,
        created_by=actor.id if actor else None,
    )
    db.add(fusion)
    db.flush()
    if result.timeline != "original_audio":
        return fusion
    turns = db.query(AsrSpeakerTurn).filter(
        AsrSpeakerTurn.result_id == result.id,
    ).order_by(AsrSpeakerTurn.start_ms, AsrSpeakerTurn.turn_index).all()
    ordered_segments = sorted(
        segments, key=lambda segment: (segment.start_ms if segment.start_ms is not None else -1, segment.segment_index),
    )
    turn_index = 0
    active: list[AsrSpeakerTurn] = []
    for segment in ordered_segments:
        if segment.start_ms is None or segment.end_ms is None or segment.end_ms <= segment.start_ms:
            db.add(AsrSpeakerAssignment(
                fusion_version_id=fusion.id, segment_id=segment.id, assignment_status="UNALIGNED",
            ))
            continue
        while turn_index < len(turns) and turns[turn_index].start_ms < segment.end_ms:
            active.append(turns[turn_index])
            turn_index += 1
        active = [turn for turn in active if turn.end_ms > segment.start_ms]
        overlaps = [turn for turn in active if turn.start_ms < segment.end_ms]
        if not overlaps:
            db.add(AsrSpeakerAssignment(
                fusion_version_id=fusion.id, segment_id=segment.id,
                start_offset=segment.start_offset, end_offset=segment.end_offset,
                assignment_status="UNKNOWN",
            ))
            continue
        speaker_ids = {turn.speaker_id for turn in overlaps if turn.speaker_id is not None}
        concurrent = _has_cross_speaker_overlap(overlaps)
        duration = segment.end_ms - segment.start_ms
        status_name = (
            "OVERLAPPED" if concurrent else "MIXED" if len(speaker_ids) > 1
            else "UNKNOWN" if any(turn.speaker_id is None for turn in overlaps)
            else "ASSIGNED"
        )
        for turn in overlaps:
            coverage = max(0, min(segment.end_ms, turn.end_ms) - max(segment.start_ms, turn.start_ms)) / duration
            db.add(AsrSpeakerAssignment(
                fusion_version_id=fusion.id, segment_id=segment.id,
                speaker_turn_id=turn.id, speaker_id=turn.speaker_id,
                start_offset=segment.start_offset if status_name == "ASSIGNED" else None,
                end_offset=segment.end_offset if status_name == "ASSIGNED" else None,
                coverage_ratio=coverage, assignment_status=status_name,
            ))
    return fusion


def create_run_fusion(
    db: Session, run: AsrModelRun, *, result_id: int | None = None, actor: User | None = None,
) -> dict[str, Any]:
    """关联指定或最新同版本说话人结果，结果不兼容时保留明确未对齐状态。"""
    if run.audio_version_id is None:
        raise bad_request("该历史转写没有可靠音频版本引用，不能自动关联说话人结果")
    query = db.query(AsrDiarizationResult).filter(
        AsrDiarizationResult.audio_version_id == run.audio_version_id,
    )
    if result_id is not None:
        query = query.filter(AsrDiarizationResult.id == result_id)
    result = query.order_by(AsrDiarizationResult.id.desc()).first()
    if result is None:
        raise not_found("该音频版本没有可用的说话人结果")
    if result.timeline != "original_audio":
        raise bad_request("说话人时间轴不是原始音频，不能自动关联转写")
    fusion = create_fusion_version(db, run, result, actor=actor)
    db.commit()
    db.refresh(fusion)
    return _dump_fusion(fusion)


def create_run_fusion_by_id(
    db: Session, run_id: int, result_id: int, actor: User,
) -> dict[str, Any]:
    """校验转写运行的项目权限后按 ID 创建同版本说话人关联。"""
    run = db.get(AsrModelRun, run_id)
    if run is None:
        raise not_found("模型运行不存在")
    require_writable_project(db, run.project_id, actor)
    return create_run_fusion(db, run, result_id=result_id, actor=actor)


def list_speakers(db: Session, result_id: int, actor: User) -> dict[str, Any]:
    """返回全量说话人统计，发言时长按每人区间并集计算且注明可超过录音时长。"""
    result = db.get(AsrDiarizationResult, result_id)
    if result is None:
        raise not_found("说话人结果不存在")
    get_project_or_404(db, result.project_id, actor)
    speakers = db.query(AsrSpeaker).filter(AsrSpeaker.result_id == result.id).order_by(
        AsrSpeaker.first_seen_ms, AsrSpeaker.id,
    ).all()
    turns = db.query(AsrSpeakerTurn).filter(
        AsrSpeakerTurn.result_id == result.id,
    ).order_by(AsrSpeakerTurn.start_ms, AsrSpeakerTurn.turn_index).all()
    durations: dict[int, int] = {}
    grouped: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for turn in turns:
        if turn.speaker_id is not None:
            grouped[turn.speaker_id].append((turn.start_ms, turn.end_ms))
    for speaker_id, intervals in grouped.items():
        durations[speaker_id] = _union_duration(intervals)
    overlap_turn_ids = _overlap_turn_ids(turns)
    unknown = sum(turn.speaker_id is None for turn in turns)
    items = [{
        "id": row.id, "result_id": row.result_id, "source_label": row.source_label,
        "channel": row.channel, "display_name": row.display_name, "first_seen_ms": row.first_seen_ms,
        "revision": row.revision,
        "turn_count": sum(turn.speaker_id == row.id for turn in turns),
        "speech_duration_ms": durations.get(row.id, 0),
    } for row in speakers]
    return {
        "items": items,
        "summary": {
            "speaker_count": len(speakers), "turn_count": len(turns),
            "unknown_turn_count": unknown, "overlap_turn_count": len(overlap_turn_ids),
            "speech_duration_definition": "每个说话人区间并集；不同说话人重叠时总和可超过录音时长。",
        },
    }


def list_speaker_turns(
    db: Session, result_id: int, actor: User, *, page: int = 1, page_size: int = 100,
    speaker_id: int | None = None, unknown_only: bool = False, overlap_only: bool = False,
    start_ms: int | None = None, end_ms: int | None = None,
) -> dict[str, Any]:
    """按时间、说话人、未知和重叠条件分页读取真实时间区间。"""
    result = db.get(AsrDiarizationResult, result_id)
    if result is None:
        raise not_found("说话人结果不存在")
    get_project_or_404(db, result.project_id, actor)
    query = db.query(AsrSpeakerTurn).filter(AsrSpeakerTurn.result_id == result.id)
    if speaker_id is not None:
        query = query.filter(AsrSpeakerTurn.speaker_id == speaker_id)
    if unknown_only:
        query = query.filter(AsrSpeakerTurn.speaker_id.is_(None))
    if start_ms is not None:
        query = query.filter(AsrSpeakerTurn.end_ms > start_ms)
    if end_ms is not None:
        query = query.filter(AsrSpeakerTurn.start_ms < end_ms)
    total = query.order_by(None).count()
    rows = query.order_by(AsrSpeakerTurn.start_ms, AsrSpeakerTurn.turn_index).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    all_turns = None
    if overlap_only:
        all_turns = db.query(AsrSpeakerTurn).filter(
            AsrSpeakerTurn.result_id == result.id,
        ).order_by(AsrSpeakerTurn.start_ms, AsrSpeakerTurn.turn_index).all()
        overlap_ids = _overlap_turn_ids(all_turns)
        query = query.filter(AsrSpeakerTurn.id.in_(overlap_ids or [-1]))
        total = query.order_by(None).count()
        rows = query.order_by(AsrSpeakerTurn.start_ms, AsrSpeakerTurn.turn_index).offset(
            (page - 1) * page_size,
        ).limit(page_size).all()
    speaker_map = {
        row.id: row for row in db.query(AsrSpeaker).filter(AsrSpeaker.result_id == result.id).all()
    }
    overlap_ids = _overlap_turn_ids(all_turns or rows)
    return {
        "items": [{
            "id": row.id, "stable_id": row.stable_id, "turn_index": row.turn_index,
            "speaker_id": row.speaker_id, "source_speaker_id": row.source_speaker_id,
            "display_name": speaker_map[row.speaker_id].display_name if row.speaker_id in speaker_map else None,
            "start_ms": row.start_ms, "end_ms": row.end_ms, "text": row.text, "channel": row.channel,
            "confidence": row.confidence, "is_overlap": row.id in overlap_ids,
        } for row in rows],
        "total": total, "page": page, "page_size": page_size,
    }


def _overlap_turn_ids(turns: list[AsrSpeakerTurn]) -> set[int]:
    """用区间扫描找出与其他标签真实时间重叠的区间，避免全量两两比较。"""
    marked: set[int] = set()
    active: dict[int | None, dict[int, AsrSpeakerTurn]] = defaultdict(dict)
    endings: list[tuple[int, int, int | None]] = []
    for turn in sorted(turns, key=lambda item: (item.start_ms, item.turn_index)):
        while endings and endings[0][0] <= turn.start_ms:
            _, turn_id, speaker_id = heapq.heappop(endings)
            active[speaker_id].pop(turn_id, None)
        has_other = any(speaker_id != turn.speaker_id and values for speaker_id, values in active.items())
        if has_other:
            marked.add(turn.id)
            for values in active.values():
                marked.update(values)
        active[turn.speaker_id][turn.id] = turn
        heapq.heappush(endings, (turn.end_ms, turn.id, turn.speaker_id))
    return marked


def _has_cross_speaker_overlap(turns: list[AsrSpeakerTurn]) -> bool:
    """判断当前转写片段范围内是否存在说话人标签不同的同时发言。"""
    active: list[AsrSpeakerTurn] = []
    for turn in sorted(turns, key=lambda item: (item.start_ms, item.turn_index)):
        active = [item for item in active if item.end_ms > turn.start_ms]
        if any(item.speaker_id != turn.speaker_id for item in active):
            return True
        active.append(turn)
    return False


def _union_duration(intervals: list[tuple[int, int]]) -> int:
    """合并同一说话人的重叠区间，避免重复计算发言时长。"""
    if not intervals:
        return 0
    total = 0
    start, end = sorted(intervals)[0]
    for next_start, next_end in sorted(intervals)[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def review_speaker_assignment(
    db: Session, assignment_id: int, body: SpeakerReviewInput, actor: User,
) -> dict[str, Any]:
    """按 expected_version 确认归属或未知，并记录操作者审计版本。"""
    assignment = db.get(AsrSpeakerAssignment, assignment_id)
    if assignment is None:
        raise not_found("说话人关联片段不存在")
    fusion = db.get(AsrFusionVersion, assignment.fusion_version_id)
    if fusion is None:
        raise not_found("说话人关联版本不存在")
    require_writable_project(db, fusion.project_id, actor)
    locked = db.query(AsrSpeakerAssignment).filter(
        AsrSpeakerAssignment.id == assignment.id,
    ).with_for_update().one()
    if locked.review_version != body.expected_version:
        raise conflict("说话人归属已被其他人更新，请刷新后重试")
    if body.speaker_id is not None:
        speaker = db.get(AsrSpeaker, body.speaker_id)
        result = db.get(AsrDiarizationResult, fusion.diarization_result_id)
        if speaker is None or result is None or speaker.result_id != result.id:
            raise bad_request("确认的说话人必须属于当前说话人结果版本")
    locked.review_version += 1
    locked.review_status = body.review_status
    locked.confirmed_speaker_id = body.speaker_id if body.review_status == "CONFIRMED" else None
    db.add(AsrSpeakerReviewAudit(
        assignment_id=locked.id, version=locked.review_version, reviewer_id=actor.id,
        speaker_id=locked.confirmed_speaker_id, review_status=locked.review_status,
    ))
    db.commit()
    db.refresh(locked)
    return {
        "id": locked.id, "speaker_id": locked.confirmed_speaker_id,
        "review_status": locked.review_status, "review_version": locked.review_version,
    }


def rename_speaker(
    db: Session, speaker_id: int, body: SpeakerNameUpdate, actor: User,
) -> dict[str, Any]:
    """修改本次结果显示名并留存历史，不修改模型原标签或其他录音中的同名标签。"""
    speaker = db.get(AsrSpeaker, speaker_id)
    if speaker is None:
        raise not_found("说话人不存在")
    result = db.get(AsrDiarizationResult, speaker.result_id)
    if result is None:
        raise not_found("说话人结果不存在")
    require_writable_project(db, result.project_id, actor)
    locked = db.query(AsrSpeaker).filter(AsrSpeaker.id == speaker.id).with_for_update().one()
    previous_name = locked.display_name
    next_name = body.display_name.strip()
    if not next_name:
        raise bad_request("说话人显示名不能为空")
    if next_name != previous_name:
        locked.revision += 1
        locked.display_name = next_name
        db.add(AsrSpeakerNameAudit(
            speaker_id=locked.id, reviewer_id=actor.id, revision=locked.revision,
            previous_name=previous_name, next_name=next_name,
        ))
        db.commit()
    return {"id": locked.id, "display_name": locked.display_name, "revision": locked.revision}


def _dump_fusion(row: AsrFusionVersion) -> dict[str, Any]:
    """返回转写与说话人结果的版本关联状态。"""
    return {
        "id": row.id, "model_run_id": row.model_run_id, "audio_version_id": row.audio_version_id,
        "diarization_result_id": row.diarization_result_id, "version": row.version,
        "status": row.status, "algorithm_version": row.algorithm_version,
    }


def export_run_workbench(
    db: Session, run_id: int, actor: User, *, format_name: str = "json", include_assignments: bool = True,
) -> tuple[str, str]:
    """导出指定运行的原始转写、真实时间与独立归属来源，不把人工文本覆盖到模型原文。"""
    run = db.get(AsrModelRun, run_id)
    if run is None:
        raise not_found("模型运行不存在")
    get_project_or_404(db, run.project_id, actor)
    rows = db.query(AsrTranscriptSegment).filter(
        AsrTranscriptSegment.model_run_id == run.id,
    ).order_by(AsrTranscriptSegment.start_ms, AsrTranscriptSegment.segment_index).all()
    payload = {
        "run_id": run.id, "audio_version_id": run.audio_version_id,
        "transcript_source": "MODEL_ORIGINAL", "transcript": run.transcript,
        "segments": [{
            "segment_id": row.id, "segment_index": row.segment_index, "text": row.text,
            "start_ms": row.start_ms, "end_ms": row.end_ms,
            "start_offset": row.start_offset, "end_offset": row.end_offset,
            "native_speaker_id": row.native_speaker_id, "channel": row.channel,
        } for row in rows],
    }
    if include_assignments:
        fusion = db.query(AsrFusionVersion).filter(
            AsrFusionVersion.model_run_id == run.id,
        ).order_by(AsrFusionVersion.version.desc()).first()
        if fusion:
            payload["fusion_version"] = _dump_fusion(fusion)
            payload["assignments"] = [{
                "segment_id": row.segment_id, "speaker_id": row.speaker_id,
                "turn_id": row.speaker_turn_id, "status": row.assignment_status,
                "source": row.source, "review_status": row.review_status,
                "confirmed_speaker_id": row.confirmed_speaker_id,
            } for row in db.query(AsrSpeakerAssignment).filter(
                AsrSpeakerAssignment.fusion_version_id == fusion.id,
            ).order_by(AsrSpeakerAssignment.id).all()]
    if format_name == "txt":
        return run.transcript or "", "text/plain; charset=utf-8"
    if format_name != "json":
        raise bad_request("工作台导出格式仅支持 JSON 或 TXT")
    return json.dumps(payload, ensure_ascii=False, indent=2), "application/json; charset=utf-8"


__all__ = [
    "create_diarization_run", "create_fusion_version", "create_run_fusion", "create_run_fusion_by_id",
    "export_run_workbench",
    "get_processing_run", "list_speaker_turns", "list_speakers", "record_diarization_result",
    "rename_speaker", "retry_processing_run", "review_speaker_assignment",
]
