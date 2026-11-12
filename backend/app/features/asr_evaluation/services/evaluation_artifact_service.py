"""冻结运行快照并登记受控目录中的评测产物。

公开创建、列举和读取入口供 ASR 路由使用；文件与登记分两阶段完成，失败保留失败状态。
当前仅从已有规范化结果重建快照，不冒称历史 Provider 原始响应。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.http.errors import bad_request, conflict, not_found
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret
from app.features.asr_evaluation.models import AsrEvaluationArtifact, AsrModelRun
from app.features.asr_evaluation.providers.response_redaction import REDACTION_VERSION, execution_secrets, redact_response
from app.features.asr_evaluation.services.evaluation_markdown_service import CONVERTER_VERSION, render_markdown
from app.features.asr_evaluation.services.segments_service import list_transcript_segments
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project


def _dump(row: AsrEvaluationArtifact) -> dict:
    """返回非敏感元信息，不暴露文件路径或正文。"""
    return {"id": row.id, "run_id": row.run_id, "kind": row.kind, "schema_version": row.schema_version,
            "sha256": row.sha256, "byte_size": row.byte_size, "status": row.status,
            "source": row.source, "redaction_version": row.redaction_version, "redacted": row.redacted,
            "created_at": row.created_at}


def _run(db: Session, run_id: int, actor: User, *, write: bool = False) -> AsrModelRun:
    """校验运行所属项目，越权与不存在保持相同错误。"""
    run = db.get(AsrModelRun, run_id)
    if run is None:
        raise not_found("模型运行不存在")
    if write:
        require_writable_project(db, run.project_id, actor)
    else:
        get_project_or_404(db, run.project_id, actor)
    return run


def _mark_ready(db: Session, artifact_ids: list[int]) -> None:
    """带行锁完成文件登记；恢复流程已判失败时不得覆盖其结论。"""
    rows = db.query(AsrEvaluationArtifact).filter(AsrEvaluationArtifact.id.in_(artifact_ids)).populate_existing().with_for_update().all()
    if len(rows) != len(artifact_ids) or any(row.status not in {"PENDING", "READY"} for row in rows):
        db.rollback()
        raise ValueError("产物登记状态已变化")
    for row in rows:
        row.status = "READY"
    db.commit()


def _mark_failed(db: Session, artifact_ids: list[int]) -> None:
    """只将仍待写入的登记标记失败，避免覆盖恢复流程已验证的文件。"""
    db.query(AsrEvaluationArtifact).filter(AsrEvaluationArtifact.id.in_(artifact_ids),
        AsrEvaluationArtifact.status == "PENDING").update({"status": "FAILED"}, synchronize_session="fetch")
    db.commit()


def recover_pending_artifacts(db: Session, *, now: datetime | None = None, grace_seconds: int | None = None) -> int:
    """恢复过期的待写入登记：完整文件置 READY，缺失或损坏置 FAILED。"""
    now = now or datetime.now(timezone.utc)
    grace = max(1, grace_seconds if grace_seconds is not None else settings.ASR_ARTIFACT_RECOVERY_GRACE_SECONDS)
    rows = db.query(AsrEvaluationArtifact).filter(AsrEvaluationArtifact.status == "PENDING",
        AsrEvaluationArtifact.created_at < now - timedelta(seconds=grace)).order_by(
        AsrEvaluationArtifact.id).limit(50).with_for_update(skip_locked=True).all()
    for row in rows:
        valid = False
        if re.fullmatch(r"[0-9a-f]{32}", row.storage_key) and 0 <= row.byte_size <= settings.ASR_ARTIFACT_MAX_BYTES:
            path = Path(settings.ASR_ARTIFACT_DIR) / row.storage_key
            try:
                if path.stat().st_size == row.byte_size:
                    digest = hashlib.sha256()
                    # 按块校验避免把过大文件读入内存，也不将文件内容写入日志。
                    with path.open("rb") as stream:
                        while block := stream.read(1024 * 1024):
                            digest.update(block)
                    valid = digest.hexdigest() == row.sha256
            except OSError:
                valid = False
        row.status = "READY" if valid else "FAILED"
    if rows:
        db.commit()
    return len(rows)


def sanitize_snapshot(run: AsrModelRun, snapshot: dict) -> dict:
    """脱敏签名地址和已知凭据；文本发生替换后撤销可能失真的原文偏移。"""
    try:
        execution = json.loads(decrypt_secret(run.execution_ciphertext))
        secrets = execution_secrets(execution)
        knowledge = "执行快照已核验"
    except (ValueError, TypeError, AttributeError):
        # 旧运行可能没有可读执行快照，明确记录限制，不声称已识别所有历史密钥。
        secrets = []
        knowledge = "历史执行快照不可读，无法核验历史凭据值"
    safe, changed = redact_response(snapshot, secrets)
    text_changed = safe.get("transcript") != snapshot.get("transcript") or any(
        safe_item.get("text") != original.get("text")
        for safe_item, original in zip(safe.get("segments", []), snapshot.get("segments", []))
    )
    if text_changed:
        for segment in safe.get("segments", []):
            segment["start_offset"] = None
            segment["end_offset"] = None
        safe.setdefault("warnings", []).append("资料包含脱敏替换；原文偏移不可可靠复用。")
    if not secrets and knowledge.startswith("历史"):
        safe.setdefault("warnings", []).append(knowledge)
    safe["redaction"] = {"version": REDACTION_VERSION, "changed": changed, "text_changed": text_changed,
                         "credential_knowledge": knowledge}
    return safe


def save_provider_response(db: Session, run: AsrModelRun, kind: str, capture: dict) -> None:
    """登记并保存脱敏的 Provider JSON；调用方在提交结果前需重新核验租约。"""
    if kind not in {"RESPONSE_SUBMISSION", "RESPONSE_SYNC", "RESPONSE_POLL_FINAL"}:
        raise ValueError("不支持的响应产物类型")
    data = json.dumps(capture["body"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(data) > settings.ASR_ARTIFACT_MAX_BYTES:
        raise ValueError("ASR 响应产物超过配置上限，未保存截断内容")
    row = AsrEvaluationArtifact(project_id=run.project_id, job_id=run.job_id, run_id=run.id,
        kind=kind, schema_version="provider-json-1", sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data), storage_key=uuid.uuid4().hex, status="PENDING", source="PROVIDER_RESPONSE_REDACTED",
        redaction_version=capture["redaction_version"], redacted=capture["redacted"])
    db.add(row)
    # 记录先提交：磁盘写入或进程中断不会把不完整文件登记为 READY。
    db.commit()
    try:
        directory = Path(settings.ASR_ARTIFACT_DIR)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(directory / row.storage_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _mark_ready(db, [row.id])
    except (OSError, ValueError):
        db.rollback()
        _mark_failed(db, [row.id])
        raise ValueError("ASR 响应产物写入失败") from None


def save_review_text(db: Session, run: AsrModelRun, kind: str, content: str, *, redacted: bool = False,
                     redaction_version: str | None = None) -> int:
    """保存实际评审输入或模型原文；调用方在每次提交后重新校验租约。"""
    if kind not in {"REVIEW_INPUT_MD", "REVIEW_REPLY_JSON", "REVIEW_SOURCE_MD", "REVIEW_SOURCE_JSON", "REVIEW_REPORT_JSON"}:
        raise ValueError("不支持的评审产物类型")
    data = content.encode("utf-8")
    if len(data) > settings.ASR_ARTIFACT_MAX_BYTES:
        raise ValueError("评审产物超过配置上限")
    row = AsrEvaluationArtifact(project_id=run.project_id, job_id=run.job_id, run_id=run.id, kind=kind,
        schema_version="content-review-1", sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data),
        storage_key=uuid.uuid4().hex, status="PENDING", source="LLM_REVIEW",
        redacted=redacted, redaction_version=redaction_version)
    db.add(row)
    db.commit()
    try:
        directory = Path(settings.ASR_ARTIFACT_DIR)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(directory / row.storage_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _mark_ready(db, [row.id])
        return row.id
    except (OSError, ValueError):
        db.rollback()
        _mark_failed(db, [row.id])
        raise ValueError("评审产物写入失败") from None


def create_evaluation_artifacts(db: Session, run_id: int, actor: User) -> dict:
    """冻结成功运行的完整转写快照和 Markdown；文件失败不会报告成功。"""
    run = _run(db, run_id, actor, write=True)
    if run.status != "SUCCEEDED" or run.transcript is None:
        raise conflict("只有已完成且包含全文的运行可以生成评测资料")
    segments = []
    page = 1
    while True:
        result = list_transcript_segments(db, run.id, actor, page=page, page_size=200)
        for item in result["items"]:
            evidence_id = (f"run:{run.id}:source-index:{item['segment_index']}" if item["id"].startswith("legacy:")
                           else f"run:{run.id}:segment:{item['id']}")
            segments.append({key: item[key] for key in ("segment_index", "text", "start_ms", "end_ms", "start_offset", "end_offset", "native_speaker_id")}
                            | {"evidence_id": evidence_id})
        if len(segments) >= result["total"]:
            break
        if not result["items"]:
            raise conflict("片段读取不完整，未生成评测资料")
        page += 1
    warnings = []
    if "".join(item["text"] for item in segments) != run.transcript:
        warnings.append("全文与片段拼接不一致，二者均按原样保存。")
    if not run.audio_version_id:
        warnings.append("历史运行缺少固定音频版本。")
    snapshot = {"schema_version": "asr-evaluation-1", "run_id": run.id, "audio_version_id": run.audio_version_id,
                "configuration": {"connection_id": run.connection_id, "parameter_set_id": run.parameter_set_id,
                                  "request_snapshot": run.request_snapshot},
                "transcript": run.transcript, "segments": segments, "warnings": warnings}
    snapshot = sanitize_snapshot(run, snapshot)
    json_bytes = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payloads = [("SNAPSHOT_JSON", "asr-evaluation-1", json_bytes),
                ("MARKDOWN", CONVERTER_VERSION, render_markdown(snapshot))]
    if any(len(data) > settings.ASR_ARTIFACT_MAX_BYTES for _, _, data in payloads):
        raise bad_request("评测产物超过配置上限，未保存截断内容")
    rows = [AsrEvaluationArtifact(project_id=run.project_id, job_id=run.job_id, run_id=run.id,
             kind=kind, schema_version=version, sha256=hashlib.sha256(data).hexdigest(),
             byte_size=len(data), storage_key=uuid.uuid4().hex, status="PENDING", source="REGENERATED_NORMALIZED",
             redacted=snapshot["redaction"]["changed"], redaction_version=snapshot["redaction"]["version"])
            for kind, version, data in payloads]
    db.add_all(rows)
    # 先提交待写入记录，进程中断时可区分未完成与可下载的产物。
    db.commit()
    try:
        directory = Path(settings.ASR_ARTIFACT_DIR)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        for row, (_, _, data) in zip(rows, payloads):
            path = directory / row.storage_key
            # 随机键与独占创建防止覆盖已有文件，权限不依赖进程 umask。
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        _mark_ready(db, [row.id for row in rows])
    except (OSError, ValueError):
        db.rollback()
        _mark_failed(db, [row.id for row in rows])
        raise conflict("评测产物写入失败，请检查持久存储配置") from None
    return {"items": [_dump(row) for row in rows]}


def list_evaluation_artifacts(db: Session, run_id: int, actor: User) -> dict:
    """列出已登记产物与状态，不将历史结果伪装成原始响应。"""
    run = _run(db, run_id, actor)
    rows = db.query(AsrEvaluationArtifact).filter_by(run_id=run.id).order_by(AsrEvaluationArtifact.id.desc()).all()
    return {"items": [_dump(row) for row in rows], "raw_response_available": any(
        row.kind in {"RESPONSE_SYNC", "RESPONSE_POLL_FINAL"} and row.status == "READY" for row in rows)}


def read_evaluation_artifact(db: Session, artifact_id: int, actor: User) -> tuple[AsrEvaluationArtifact, bytes]:
    """按产物 ID 鉴权读取并核验 hash，缺失或损坏绝不返回伪成功。"""
    row = db.get(AsrEvaluationArtifact, artifact_id)
    if row is None:
        raise not_found("评测产物不存在")
    get_project_or_404(db, row.project_id, actor)
    if (row.status != "READY" or not re.fullmatch(r"[0-9a-f]{32}", row.storage_key)
            or not 0 <= row.byte_size <= settings.ASR_ARTIFACT_MAX_BYTES):
        raise conflict("评测产物尚不可用")
    try:
        # 即使磁盘文件被替换为超大文件，也只读取登记大小加一个字节。
        with (Path(settings.ASR_ARTIFACT_DIR) / row.storage_key).open("rb") as stream:
            data = stream.read(row.byte_size + 1)
    except OSError:
        raise conflict("评测产物无法读取") from None
    if len(data) != row.byte_size or hashlib.sha256(data).hexdigest() != row.sha256:
        raise conflict("评测产物完整性校验失败")
    return row, data
