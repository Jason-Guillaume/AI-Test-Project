"""持久化 ASR 评测批次服务。

批次创建在一个短事务中保存音频、连接、参数版本快照和三方工作项；具体 HTTP 请求由独立 Worker 执行。
对不确定提交不提供盲重试，已提交的远端任务只能继续查询或标记本地停止跟踪。
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only

from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.core.security.roles import PROJECT_ROLE_EDITOR, PROJECT_ROLE_MEMBER, has_project_role, project_role_for
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.features.asr_evaluation.models import (
    AsrAudio, AsrAudioVersion, AsrComparison, AsrConnection, AsrContentReviewJob, AsrJob, AsrModelRun,
    AsrParameterSet, AsrProcessingRun, AsrSchedule, AsrTranscriptSegment, AsrWorkItem, AsrWorkerHeartbeat,
)
from app.features.asr_evaluation.schemas import ConnectionCheck, JobCreate
from app.features.asr_evaluation.services.assets_service import _validate_schedule_assets, ensure_audio_version
from app.platform.model_configuration.models import ModelTaskSlot
from app.platform.model_configuration.services.model_center_service import resolve_task_slots

_SENSITIVE_NAME = re.compile(r"(authorization|token|secret|password|api[-_]?key|cookie|url)", re.I)


def _redact(value: Any) -> Any:
    """递归移除参数快照中按字段名识别的凭据与 URL。"""
    if isinstance(value, dict):
        return {key: ("[已脱敏]" if _SENSITIVE_NAME.search(str(key)) else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _can_full_rerun(db: Session, job: AsrJob) -> bool:
    """摘要模式也能判断完整重跑资格，但不读取或返回转写正文和密文。"""
    if job.status not in {"FAILED", "PARTIAL_FAILED", "COMPLETED"}:
        return False
    rows = db.query(
        AsrModelRun.status, AsrModelRun.audio_version_id, func.length(AsrModelRun.execution_ciphertext),
    ).filter(AsrModelRun.job_id == job.id).all()
    if not rows or any(status not in {"SUCCEEDED", "FAILED"} or version_id is None or not ciphertext_length
                     for status, version_id, ciphertext_length in rows):
        return False
    version_ids = {version_id for _, version_id, _ in rows}
    available_versions = {row[0] for row in db.query(AsrAudioVersion.id)
                          .filter(AsrAudioVersion.id.in_(version_ids)).all()}
    return version_ids == available_versions


def _dump_job(
    db: Session, job: AsrJob, *, include_runs: bool = False, include_text: bool = True,
    include_rerun_eligibility: bool = False,
) -> dict:
    """返回批次事实与可选运行摘要，不暴露执行密文。"""
    result = {
        "id": job.id, "project_id": job.project_id, "schedule_id": job.schedule_id,
        "status": job.status, "config_snapshot": job.config_snapshot, "cancel_requested": job.cancel_requested,
        "created_at": job.created_at, "started_at": job.started_at, "finished_at": job.finished_at,
    }
    if include_rerun_eligibility:
        result["can_full_rerun"] = _can_full_rerun(db, job)
    if include_runs:
        query = db.query(AsrModelRun).filter(AsrModelRun.job_id == job.id)
        if not include_text:
            # 列表和模型切换只需摘要，避免把整批转写全文加载进内存或传到浏览器。
            query = query.options(load_only(AsrModelRun.id, AsrModelRun.audio_id, AsrModelRun.connection_id,
                AsrModelRun.audio_version_id, AsrModelRun.role, AsrModelRun.status, AsrModelRun.remote_task_id,
                AsrModelRun.request_snapshot, AsrModelRun.error_message, AsrModelRun.duration_ms, AsrModelRun.parameter_set_id))
        runs = query.order_by(AsrModelRun.id).all()
        # 名称和时长取固定版本，避免后续编辑音频资源污染历史批次展示。
        version_ids = {row.audio_version_id for row in runs if row.audio_version_id is not None}
        versions = {row.id: row for row in db.query(AsrAudioVersion).filter(AsrAudioVersion.id.in_(version_ids or [-1])).all()}
        result["runs"] = [{
            "id": row.id, "audio_id": row.audio_id, "connection_id": row.connection_id,
            "audio_version_id": row.audio_version_id,
            "audio_name": versions[row.audio_version_id].name if row.audio_version_id in versions else None,
            "audio_duration_seconds": versions[row.audio_version_id].duration_seconds if row.audio_version_id in versions else None,
            "audio_content_version": versions[row.audio_version_id].version if row.audio_version_id in versions else None,
            "role": row.role, "status": row.status, "remote_task_id": row.remote_task_id,
            "request_snapshot": row.request_snapshot, "transcript": row.transcript if include_text else None,
            "segments": (row.segments or []) if include_text else [],
            "error_message": row.error_message, "duration_ms": row.duration_ms,
            "parameter_set_id": row.parameter_set_id,
        } for row in runs]
        result["comparisons"] = [{"id": row.id, "audio_id": row.audio_id, "status": row.status}
                                  for row in db.query(AsrComparison).filter(AsrComparison.job_id == job.id).all()]
    return result


def create_job(
    db: Session, body: JobCreate, actor: User, *, schedule_id: int | None = None,
    scheduled_for: datetime | None = None,
    reused_reference_runs: dict[int, AsrModelRun] | None = None,
    reference_reuse_source_comparison_id: int | None = None,
    commit: bool = True,
) -> dict:
    """保存一批三方识别运行和工作项，之后立即返回批次 ID。"""
    require_writable_project(db, body.project_id, actor)
    audio_ids = sorted(set(body.audio_ids))
    if len(audio_ids) != len(body.audio_ids):
        raise bad_request("音频列表存在重复项")
    resolved_slots = resolve_task_slots(db, body.project_id, body.model_slots, actor) if body.model_slots else None
    if resolved_slots is not None:
        asr_slots = [item for item in resolved_slots if item["slot"] != "DIARIZATION"]
        if {item["slot"] for item in asr_slots} != {"TEST", "REFERENCE_A", "REFERENCE_B"}:
            raise bad_request("夜间对照任务必须分别配置待测与两个参考槽位")
        if len({item["resource"].id for item in asr_slots}) != 3:
            raise bad_request("待测模型与两个参考模型必须是三个不同的授权模型资源")
        connection_ids = [item["connection"].id for item in asr_slots]
        if len(set(connection_ids)) != 3:
            raise bad_request("同一批次的待测、参考 A、参考 B 必须选择三个不同的模型资源")
        connections = [item["connection"] for item in asr_slots]
        slot_by_connection = {item["connection"].id: item["slot"] for item in asr_slots}
        parameter_by_connection = {item["connection"].id: item["parameter_set"] for item in asr_slots}
        test_connection = next(item["connection"] for item in asr_slots if item["slot"] == "TEST")
        parameter_set = parameter_by_connection[test_connection.id]
        slot_snapshot = [{
            "slot": item["slot"], "resource_id": item["resource"].id,
            "revision_id": item["revision"].id, "profile_id": item["profile"].id,
            "legacy_connection_id": item["connection"].id,
            "legacy_parameter_set_id": item["parameter_set"].id,
        } for item in resolved_slots]
    else:
        if body.connection_ids is None or body.parameter_set_id is None:
            raise bad_request("任务模型槽位配置缺失")
        _validate_schedule_assets(db, body.project_id, body.audio_ids, body.connection_ids, body.parameter_set_id)
        selected_connections = db.query(AsrConnection).filter(
            AsrConnection.project_id == body.project_id, AsrConnection.id.in_(body.connection_ids),
            AsrConnection.enabled.is_(True),
        ).all()
        by_id = {row.id: row for row in selected_connections}
        connections = [by_id[item] for item in body.connection_ids if item in by_id]
        slot_by_connection = {row.id: row.role for row in connections}
        parameter_set = db.get(AsrParameterSet, body.parameter_set_id)
        parameter_by_connection = {row.id: parameter_set if row.role == "TEST" else None for row in connections}
        test_connection = next((row for row in connections if row.role == "TEST"), None)
        slot_snapshot = []
    audios = db.query(AsrAudio).filter(AsrAudio.project_id == body.project_id, AsrAudio.id.in_(audio_ids)).all()
    if test_connection is None or parameter_set is None:
        raise not_found("待测连接或参数方案不存在")
    job = AsrJob(
        project_id=body.project_id, status="QUEUED", created_by=actor.id,
        schedule_id=schedule_id, scheduled_for=scheduled_for,
        config_snapshot={
            "audio_ids": audio_ids,
            "audio_versions": {str(row.id): row.content_version for row in audios},
            "connections": [{"id": row.id, "name": row.name, "role": row.role, "model_id": row.model_id, "version": row.version}
                            for row in sorted(connections, key=lambda item: item.id)],
            "parameter_set": {"id": parameter_set.id, "name": parameter_set.name, "version": parameter_set.version},
            "model_slots": slot_snapshot,
            "slot_parameters": [{
                "slot": slot_by_connection[connection.id], "parameter_set_id": parameter_by_connection[connection.id].id,
                "name": parameter_by_connection[connection.id].name,
                "version": parameter_by_connection[connection.id].version,
            } for connection in connections if parameter_by_connection.get(connection.id) is not None],
            "expected_runs": len(audio_ids) * 3,
            "reference_reuse": ({
                "source_comparison_id": reference_reuse_source_comparison_id,
                "reused_run_ids": [row.id for row in reused_reference_runs.values()],
            } if reused_reference_runs else None),
        },
    )
    db.add(job)
    db.flush()
    for item in resolved_slots or []:
        db.add(ModelTaskSlot(
            task_kind="ASR_JOB", task_id=job.id, slot=item["slot"],
            resource_id=item["resource"].id, revision_id=item["revision"].id,
            profile_id=item["profile"].id, legacy_connection_id=item["connection"].id,
        ))
    for audio in audios:
        audio_version = ensure_audio_version(db, audio)
        audio_url = decrypt_secret(audio.url_ciphertext)
        for connection in connections:
            config = connection.config_json or {}
            parameter_for_connection = parameter_by_connection.get(connection.id)
            parameters = parameter_for_connection.parameters if parameter_for_connection is not None else {}
            task_slot = slot_by_connection[connection.id]
            run_role = "TEST" if task_slot == "TEST" else "REFERENCE"
            execution = {
                "audio_url": audio_url, "endpoint": decrypt_secret(connection.endpoint_ciphertext),
                "model_id": connection.model_id, "secret": decrypt_secret(connection.secret_ciphertext),
                "secret_header": connection.secret_header, "parameters": parameters,
                **config,
            }
            safe_request = {
                "endpoint": connection.endpoint_display, "model_id": connection.model_id,
                "role": run_role, "task_slot": task_slot,
                "parameters": _redact(parameters),
            }
            if parameter_for_connection is not None:
                safe_request["parameter_set"] = {
                    "id": parameter_for_connection.id, "name": parameter_for_connection.name,
                    "version": parameter_for_connection.version,
                }
            source_run = (reused_reference_runs or {}).get(connection.id) if run_role == "REFERENCE" else None
            if source_run is not None:
                safe_request["reference_reuse"] = {
                    "source_run_id": source_run.id,
                    "source_comparison_id": reference_reuse_source_comparison_id,
                    "source_finished_at": source_run.finished_at.isoformat() if source_run.finished_at else None,
                    "audio_content_version": audio.content_version,
                    "manual_reuse": True,
                }
            run = AsrModelRun(
                project_id=body.project_id, job_id=job.id, audio_id=audio.id,
                audio_version_id=audio_version.id,
                connection_id=connection.id,
                parameter_set_id=parameter_for_connection.id if parameter_for_connection is not None else None,
                role=run_role, status="SUCCEEDED" if source_run is not None else "PENDING",
                idempotency_key=str(uuid.uuid4()),
                execution_ciphertext=encrypt_secret(json.dumps(execution, ensure_ascii=False)),
                request_snapshot=safe_request,
                transcript=source_run.transcript if source_run is not None else None,
                segments=source_run.segments if source_run is not None else [],
                duration_ms=source_run.duration_ms if source_run is not None else None,
                started_at=source_run.started_at if source_run is not None else None,
                finished_at=source_run.finished_at if source_run is not None else None,
            )
            db.add(run)
            db.flush()
            if source_run is None:
                db.add(AsrWorkItem(run_id=run.id, available_at=datetime.now(timezone.utc)))
    # 批次、三方运行和工作项同事务提交，避免返回已创建却没有队列项的任务 ID。
    db.commit() if commit else db.flush()
    db.refresh(job)
    return _dump_job(db, job)


def list_jobs(db: Session, project_id: int, actor: User, *, page: int = 1, page_size: int = 20) -> dict:
    """以平台分页合同读取项目任务摘要。"""
    get_project_or_404(db, project_id, actor)
    query = db.query(AsrJob).filter(AsrJob.project_id == project_id)
    total = query.order_by(None).count()
    rows = query.order_by(AsrJob.created_at.desc(), AsrJob.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_dump_job(db, row) for row in rows], "total": total, "page": page, "page_size": page_size}


def create_connection_check(db: Session, connection_id: int, body: ConnectionCheck, actor: User) -> dict:
    """为单个连接创建短后台诊断运行，页面立即获得任务 ID。"""
    connection = db.get(AsrConnection, connection_id)
    audio = db.get(AsrAudio, body.audio_id)
    if connection is None or audio is None or connection.project_id != audio.project_id:
        raise not_found("接口连接或音频资源不存在")
    require_writable_project(db, connection.project_id, actor)
    parameter_set = db.get(AsrParameterSet, body.parameter_set_id) if body.parameter_set_id else None
    if connection.role == "TEST":
        if parameter_set is None or parameter_set.project_id != connection.project_id or parameter_set.connection_id != connection.id:
            raise bad_request("待测连接调试需要其参数方案")
    elif parameter_set is not None:
        raise bad_request("参考连接调试不使用待测参数方案")
    # 模型中心的连接不固定实验角色；单模型任务在本次运行中作为待测，不改模型本身。
    run_role = connection.role or "TEST"
    execution = {
        "audio_url": decrypt_secret(audio.url_ciphertext),
        "endpoint": decrypt_secret(connection.endpoint_ciphertext), "model_id": connection.model_id,
        "secret": decrypt_secret(connection.secret_ciphertext), "secret_header": connection.secret_header,
        "parameters": parameter_set.parameters if parameter_set else {}, **(connection.config_json or {}),
    }
    job = AsrJob(
        project_id=connection.project_id, status="QUEUED", created_by=actor.id,
        config_snapshot={
            "debug_connection_id": connection.id, "audio_ids": [audio.id],
            "audio_versions": {str(audio.id): audio.content_version}, "expected_runs": 1,
        },
    )
    db.add(job)
    db.flush()
    audio_version = ensure_audio_version(db, audio)
    run = AsrModelRun(
        project_id=connection.project_id, job_id=job.id, audio_id=audio.id,
        audio_version_id=audio_version.id,
        connection_id=connection.id, parameter_set_id=parameter_set.id if parameter_set else None,
        role=run_role, status="PENDING", idempotency_key=str(uuid.uuid4()),
        execution_ciphertext=encrypt_secret(json.dumps(execution, ensure_ascii=False)),
        request_snapshot={"endpoint": connection.endpoint_display, "model_id": connection.model_id,
                          "role": run_role, "parameters": _redact(parameter_set.parameters if parameter_set else {})},
    )
    db.add(run)
    db.flush()
    db.add(AsrWorkItem(run_id=run.id, available_at=datetime.now(timezone.utc)))
    db.commit()
    db.refresh(job)
    return _dump_job(db, job)


def get_job(db: Session, job_id: int, actor: User, *, summary_only: bool = False, include_text: bool = True) -> dict:
    """读取项目任务、脱敏请求快照、三方文本与结果对比。"""
    job = db.get(AsrJob, job_id)
    if job is None:
        raise not_found("评测任务不存在")
    get_project_or_404(db, job.project_id, actor)
    return _dump_job(db, job, include_runs=not summary_only, include_text=include_text,
                     include_rerun_eligibility=summary_only)


def list_job_audio_runs(db: Session, job_id: int, actor: User, *, page: int, page_size: int,
                        keyword: str | None = None, status: str | None = None) -> dict:
    """按固定音频版本分页读取运行摘要；筛选匹配某一槽位后仍返回该音频的全部槽位。"""
    job = db.get(AsrJob, job_id)
    if job is None:
        raise not_found("评测任务不存在")
    get_project_or_404(db, job.project_id, actor)
    query = db.query(AsrModelRun.audio_id, AsrModelRun.audio_version_id).outerjoin(
        AsrAudioVersion, AsrAudioVersion.id == AsrModelRun.audio_version_id,
    ).join(AsrAudio, AsrAudio.id == AsrModelRun.audio_id).filter(AsrModelRun.job_id == job.id)
    if keyword:
        query = query.filter(func.lower(func.coalesce(AsrAudioVersion.name, AsrAudio.name)).contains(keyword.lower(), autoescape=True))
    if status:
        query = query.filter(AsrModelRun.status == status)
    query = query.distinct()
    total = query.count()
    groups = query.order_by(AsrModelRun.audio_id, AsrModelRun.audio_version_id).offset((page - 1) * page_size).limit(page_size).all()
    result = []
    for audio_id, version_id in groups:
        # 每页仅加载当前音频的三个槽位，并排除全文和片段大字段。
        query_runs = db.query(AsrModelRun).filter_by(job_id=job.id, audio_id=audio_id, audio_version_id=version_id).options(
            load_only(AsrModelRun.id, AsrModelRun.audio_id, AsrModelRun.audio_version_id, AsrModelRun.connection_id,
                AsrModelRun.role, AsrModelRun.status, AsrModelRun.remote_task_id, AsrModelRun.request_snapshot,
                AsrModelRun.error_message, AsrModelRun.duration_ms, AsrModelRun.parameter_set_id)).order_by(AsrModelRun.id).all()
        version = db.get(AsrAudioVersion, version_id) if version_id else None
        audio = db.get(AsrAudio, audio_id)
        comparison = db.query(AsrComparison).filter_by(job_id=job.id, audio_id=audio_id).order_by(AsrComparison.version.desc()).first()
        processing = db.query(AsrProcessingRun).filter_by(audio_version_id=version_id, task_type="DIARIZATION").order_by(AsrProcessingRun.id.desc()).first() if version_id else None
        review = db.query(AsrContentReviewJob).filter_by(comparison_id=comparison.id, review_type="TRIPLET").order_by(AsrContentReviewJob.id.desc()).first() if comparison else None
        test_run = next((run for run in query_runs if run.role == "TEST"), None)
        segment_count = db.query(func.count(AsrTranscriptSegment.id)).filter_by(model_run_id=test_run.id).scalar() if test_run else None
        result.append({"key": f"{audio_id}:{version_id or 'unknown'}", "audio_id": audio_id,
            "audio_version_id": version_id, "audio_name": version.name if version else audio.name if audio else None,
            "audio_content_version": version.version if version else None,
            "audio_duration_seconds": version.duration_seconds if version else None,
            "comparison_id": comparison.id if comparison else None,
            "diarization_status": processing.status if processing else None,
            "content_review_status": review.status if review else None,
            "test_segment_count": segment_count,
            "runs": [{"id": row.id, "audio_id": row.audio_id, "audio_version_id": row.audio_version_id,
                "connection_id": row.connection_id, "role": row.role, "status": row.status,
                "remote_task_id": row.remote_task_id, "request_snapshot": row.request_snapshot,
                "error_message": row.error_message, "duration_ms": row.duration_ms,
                "parameter_set_id": row.parameter_set_id, "transcript": None} for row in query_runs]})
    return {"items": result, "total": total, "page": page, "page_size": page_size}


def list_audio_recent_runs(db: Session, project_id: int, audio_ids: list[int], actor: User) -> list[dict]:
    """为当前音频页返回每条音频最新运行摘要，用于直接回到任务和结果。"""
    get_project_or_404(db, project_id, actor)
    ids = sorted(set(audio_ids))
    if len(ids) != len(audio_ids) or any(item <= 0 for item in ids):
        raise bad_request("音频列表存在重复项")
    owned = {row.id for row in db.query(AsrAudio.id).filter(
        AsrAudio.project_id == project_id, AsrAudio.id.in_(ids or [-1]),
    ).all()}
    if owned != set(ids):
        raise not_found("部分音频不存在")
    rows = db.query(AsrModelRun).filter(
        AsrModelRun.project_id == project_id, AsrModelRun.audio_id.in_(ids or [-1]),
    ).order_by(AsrModelRun.audio_id, AsrModelRun.created_at.desc(), AsrModelRun.id.desc()).all()
    latest: dict[int, dict] = {}
    for row in rows:
        if row.audio_id not in latest:
            latest[row.audio_id] = {
                "audio_id": row.audio_id, "run_id": row.id, "job_id": row.job_id,
                "audio_version_id": row.audio_version_id, "status": row.status,
                "created_at": row.created_at,
            }
    return list(latest.values())


def cancel_job(db: Session, job_id: int, actor: User) -> dict:
    """停止未提交运行并停止本地跟踪已提交运行；不会伪称远端已取消。"""
    job = db.get(AsrJob, job_id)
    if job is None:
        raise not_found("评测任务不存在")
    project = get_project_or_404(db, job.project_id, actor)
    role = project_role_for(db, project, actor)
    if job.created_by != actor.id and not has_project_role(role, PROJECT_ROLE_MEMBER):
        from app.core.http.errors import forbidden
        raise forbidden("无权取消该评测任务")
    job.cancel_requested = True
    runs = db.query(AsrModelRun).filter(AsrModelRun.job_id == job.id).all()
    for run in runs:
        if run.status == "PENDING":
            run.status = "CANCELLED"
            run.error_message = "本地已停止新提交"
            run.finished_at = datetime.now(timezone.utc)
            db.query(AsrWorkItem).filter(AsrWorkItem.run_id == run.id).delete(synchronize_session=False)
        elif run.status == "SUBMITTING":
            # 提交请求可能已经到达远端；不能将取消解释为未收费，也不能盲目重试。
            run.status = "RECONCILIATION_REQUIRED"
            run.error_message = "提交状态待核实；请按幂等键检查服务端后再处理"
            run.finished_at = datetime.now(timezone.utc)
            db.query(AsrWorkItem).filter(AsrWorkItem.run_id == run.id).delete(synchronize_session=False)
        elif run.status == "REMOTE_RUNNING":
            run.status = "CANCELLED"
            run.error_message = "本地已停止跟踪；远端任务可能仍在运行"
            run.finished_at = datetime.now(timezone.utc)
            db.query(AsrWorkItem).filter(AsrWorkItem.run_id == run.id).delete(synchronize_session=False)
    job.status = "RECONCILIATION_REQUIRED" if any(
        row.status == "RECONCILIATION_REQUIRED" for row in runs
    ) else "CANCELLED"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    # 取消也可能结束一批只成功了两家的运行，保留可供人工复核的部分对比。
    from app.features.asr_evaluation.services.comparison_service import record_run_result
    for run in runs:
        if run.status in {"CANCELLED", "RECONCILIATION_REQUIRED"}:
            record_run_result(db, run.id, status=run.status, error_message=run.error_message)
    return _dump_job(db, job, include_runs=True)


def retry_job(db: Session, job_id: int, actor: User, *, request_key: str | None = None) -> dict:
    """原子地重试明确失败的运行，并在新批次中复用原版本成功结果。"""
    return _clone_job(db, job_id, actor, mode="FAILED_ONLY", request_key=request_key)


def rerun_job(db: Session, job_id: int, actor: User, *, request_key: str | None = None) -> dict:
    """以原固定音频和模型快照重新执行全部确定终态的运行。"""
    return _clone_job(db, job_id, actor, mode="FULL_RERUN", request_key=request_key)


def _clone_job(db: Session, job_id: int, actor: User, *, mode: str, request_key: str | None) -> dict:
    job = db.get(AsrJob, job_id)
    if job is None:
        raise not_found("评测任务不存在")
    project = get_project_or_404(db, job.project_id, actor)
    role = project_role_for(db, project, actor)
    if job.created_by != actor.id and not has_project_role(role, PROJECT_ROLE_EDITOR):
        from app.core.http.errors import forbidden
        raise forbidden("仅任务创建者或项目编辑者可以重新执行")
    request_key = request_key.strip() if request_key else None
    if request_key:
        if len(request_key) > 128:
            raise bad_request("幂等键长度不能超过 128 个字符")
        existing = db.query(AsrJob).filter_by(request_key=request_key).first()
        if existing is not None:
            snapshot = existing.config_snapshot or {}
            if snapshot.get("retry_source_job_id") != job.id or snapshot.get("retry_mode") != mode:
                raise bad_request("该幂等键已用于其他执行请求")
            return _dump_job(db, existing, include_runs=True)
    if job.status not in {"FAILED", "PARTIAL_FAILED", "COMPLETED"}:
        raise bad_request("仅可从已结束批次重新执行；提交状态待核实的运行不会自动重发")
    source_runs = db.query(AsrModelRun).filter(AsrModelRun.job_id == job.id).order_by(AsrModelRun.id).all()
    failed_runs = [row for row in source_runs if row.status == "FAILED"]
    if mode == "FAILED_ONLY":
        if job.status not in {"FAILED", "PARTIAL_FAILED"} or not failed_runs:
            raise bad_request("此批次没有可安全重试的明确失败项；远端状态待核实的运行不会重发")
        source_for_clone = failed_runs
    else:
        if any(row.status not in {"SUCCEEDED", "FAILED"} for row in source_runs):
            raise bad_request("批次仍有未确定终态的运行，不能完整重跑")
        source_for_clone = source_runs
    if any(row.audio_version_id is None or not row.execution_ciphertext for row in source_for_clone):
        raise bad_request("部分运行缺少固定音频版本或加密请求快照，无法安全重新执行")
    version_ids = {row.audio_version_id for row in source_for_clone}
    available_versions = {
        row.id for row in db.query(AsrAudioVersion.id).filter(AsrAudioVersion.id.in_(version_ids)).all()
    }
    if version_ids != available_versions:
        raise bad_request("部分运行的原音频版本已不可用，未创建新批次")

    snapshot = copy.deepcopy(job.config_snapshot or {})
    snapshot["retry_source_job_id"] = job.id
    snapshot["retry_mode"] = mode
    snapshot["retry_failed_run_ids"] = [row.id for row in failed_runs] if mode == "FAILED_ONLY" else []
    retried = AsrJob(
        project_id=job.project_id, status="QUEUED", created_by=actor.id,
        config_snapshot=snapshot, request_key=request_key,
    )
    try:
        db.add(retried)
        db.flush()
        for slot in db.query(ModelTaskSlot).filter_by(task_kind="ASR_JOB", task_id=job.id).all():
            db.add(ModelTaskSlot(
                task_kind="ASR_JOB", task_id=retried.id, slot=slot.slot,
                resource_id=slot.resource_id, revision_id=slot.revision_id,
                profile_id=slot.profile_id, legacy_connection_id=slot.legacy_connection_id,
            ))

        created_runs: list[AsrModelRun] = []
        retry_ids = {row.id for row in failed_runs}
        for source in source_runs:
            should_retry = mode == "FULL_RERUN" or source.id in retry_ids
            row = AsrModelRun(
                project_id=source.project_id, job_id=retried.id, audio_id=source.audio_id,
                audio_version_id=source.audio_version_id, connection_id=source.connection_id,
                parameter_set_id=source.parameter_set_id, role=source.role,
                status="PENDING" if should_retry else source.status,
                remote_task_id=None if should_retry else source.remote_task_id,
                idempotency_key=str(uuid.uuid4()),
                execution_ciphertext=source.execution_ciphertext,
                request_snapshot=copy.deepcopy(source.request_snapshot or {}),
                transcript=None if should_retry else source.transcript,
                segments=[] if should_retry else copy.deepcopy(source.segments or []),
                error_message=None if should_retry else source.error_message,
                duration_ms=None if should_retry else source.duration_ms,
                started_at=None if should_retry else source.started_at,
                finished_at=None if should_retry else source.finished_at,
            )
            db.add(row)
            db.flush()
            created_runs.append(row)
            if should_retry:
                db.add(AsrWorkItem(run_id=row.id, available_at=datetime.now(timezone.utc)))

        # 成功运行的规范化读模型也在同一事务里准备；失败时整个新批次和队列项回滚。
        if mode == "FAILED_ONLY":
            from app.features.asr_evaluation.services.comparison_service import record_run_result
            for row in created_runs:
                if row.status != "PENDING":
                    record_run_result(
                        db, row.id, status=row.status, transcript=row.transcript,
                        segments=row.segments or [], error_message=row.error_message,
                        duration_ms=row.duration_ms, finished_at=row.finished_at, commit=False,
                    )
        db.commit()
    except IntegrityError:
        db.rollback()
        if request_key:
            existing = db.query(AsrJob).filter_by(request_key=request_key).first()
            if existing is not None:
                snapshot = existing.config_snapshot or {}
                if snapshot.get("retry_source_job_id") == job.id and snapshot.get("retry_mode") == mode:
                    return _dump_job(db, existing, include_runs=True)
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(retried)
    return _dump_job(db, retried)


def runtime_status(db: Session, *, stale_seconds: int = 90) -> dict:
    """返回最近 Worker 心跳；过期心跳明确标记后台执行器离线。"""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
    rows = db.query(AsrWorkerHeartbeat).order_by(AsrWorkerHeartbeat.last_seen_at.desc()).limit(20).all()
    latest = rows[0] if rows else None
    last_seen = latest.last_seen_at if latest else None
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    online = bool(last_seen and last_seen >= cutoff)
    return {
        "online": online,
        "process_alive": online,
        "business_ready": bool(online and getattr(latest, "business_ready", False)),
        "status": "业务就绪" if online and getattr(latest, "business_ready", False) else "进程存活，业务暂未就绪" if online else "后台执行器离线",
        "last_seen_at": last_seen,
        "worker_id": latest.worker_id if latest else None,
        "active_count": latest.active_count if latest else 0,
    }


__all__ = ["cancel_job", "create_connection_check", "create_job", "get_job", "list_audio_recent_runs", "list_jobs", "retry_job", "runtime_status"]
