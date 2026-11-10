"""API-bound FunASR evaluation, immutable samples, and tuning-session lifecycle."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.http.errors import bad_request, conflict, not_found
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.core.security.roles import PROJECT_ROLE_EDITOR, has_project_role, project_role_for
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_request_body import ApiRequestBody
from app.features.api_catalog.models.api_parameter import ApiParameter
from app.features.asr_evaluation.funasr_schemas import (
    FunAsrBindingCreate, FunAsrBindingUpdate, FunAsrGroundTruthCreate, FunAsrTuningCreate,
)
from app.features.asr_evaluation.models import (
    AsrApiBinding, AsrAudio, AsrAudioVersion, AsrGroundTruthVersion, AsrTuningItem,
    AsrTuningRound, AsrTuningSession,
)
from app.features.asr_evaluation.services.assets_service import ensure_audio_version
from app.features.asr_evaluation.services.funasr_analysis import (
    FUNASR_DEFINITIONS, FUNASR_FIELDS, aggregate_cer, build_request, character_error_counts,
    effective_parameter_hash, is_in_night_window, normalize_document, normalize_text,
    select_best_round, validate_candidate,
)
from app.features.asr_evaluation.services.evaluation_markdown_service import render_markdown
from app.features.asr_evaluation.services.comparison_service import _model_access
from app.platform.environment_configuration.services.environment_service import (
    list_project_environment_options, resolve_project_environment_by_name,
)
from app.platform.model_configuration.services.model_config_service import model_configuration_revision
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.execution.http.request_builder import build_environment_url, get_environment_headers, merge_request_fields


def _require_editor(db: Session, project_id: int, actor: User) -> None:
    project = get_project_or_404(db, project_id, actor)
    if not has_project_role(project_role_for(db, project, actor), PROJECT_ROLE_EDITOR):
        from app.core.http.errors import forbidden
        raise forbidden("需要项目编辑者权限")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _safe_endpoint_display(value: str) -> str:
    """Keep a useful host/path label without exposing userinfo, query tokens, or fragments."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port:
            host += f":{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return "已配置接口地址"


def _dump_binding(db: Session, row: AsrApiBinding) -> dict[str, Any]:
    iface = db.get(ApiInterface, row.api_interface_id) if row.api_interface_id else None
    return {
        "id": row.id, "project_id": row.project_id, "api_interface_id": row.api_interface_id,
        "interface_name": (row.config_snapshot or {}).get("interface_name"),
        "method": (row.config_snapshot or {}).get("method"), "path": (row.config_snapshot or {}).get("path"),
        "interface_version": row.interface_version, "source_hash": row.source_hash,
        "interface_updated": bool(iface and (iface.version != row.interface_version or iface.source_hash != row.source_hash)),
        "interface_removed": iface is None, "environment_name": row.environment_name,
        "response_mapping": row.response_mapping or {},
        "response_mapping_verified": (row.config_snapshot or {}).get("mapping_verified_hash")
            == hashlib.sha256(_canonical(row.response_mapping or {})).hexdigest(),
        "timeout_seconds": row.timeout_seconds,
        "max_response_bytes": row.max_response_bytes, "has_credential": bool((row.config_snapshot or {}).get("has_credential")),
        "parameter_seed": (row.config_snapshot or {}).get("parameter_seed", {}),
        "parameter_seed_warnings": (row.config_snapshot or {}).get("parameter_seed_warnings", []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _read_parameter_seed(db: Session, interface_id: int) -> tuple[dict[str, Any], list[str]]:
    body = db.query(ApiRequestBody).filter_by(interface_id=interface_id).one_or_none()
    value: Any = None
    if body and body.body_type == "json":
        if isinstance(body.schema_json, dict) and "example" in body.schema_json:
            value = body.schema_json["example"]
        if value is None and body.raw_text:
            try:
                parsed = json.loads(body.raw_text)
                value = parsed if isinstance(parsed, dict) else None
            except (ValueError, TypeError):
                value = None
    if not isinstance(value, dict):
        return {}, []
    seed = {key: val for key, val in value.items() if key in FUNASR_FIELDS and key != "audio"}
    extras = sorted(set(value) - FUNASR_FIELDS)
    return seed, (["接口请求示例含非 FunASR 字段，未纳入可发送参数：" + ", ".join(extras)] if extras else [])


def list_fun_asr_interfaces(db: Session, project_id: int, actor: User) -> dict[str, Any]:
    get_project_or_404(db, project_id, actor)
    rows = db.query(ApiInterface).filter_by(project_id=project_id).order_by(ApiInterface.name, ApiInterface.id).all()
    return {"items": [{"id": row.id, "name": row.name, "method": row.method, "path": row.path,
                       "version": row.version, "source_hash": row.source_hash, "status": row.status,
                       "source_type": row.source_type} for row in rows], "total": len(rows)}


def list_fun_asr_environments(db: Session, project_id: int, actor: User) -> dict[str, Any]:
    get_project_or_404(db, project_id, actor)
    rows = list_project_environment_options(db, project_id)
    return {"items": [{"id": row["id"], "name": row["name"], "display_name": row["display_name"],
                       "is_default": row["is_default"]} for row in rows]}


def create_fun_asr_binding(db: Session, body: FunAsrBindingCreate, actor: User) -> dict[str, Any]:
    _require_editor(db, body.project_id, actor)
    iface = db.get(ApiInterface, body.api_interface_id)
    if iface is None or iface.project_id != body.project_id:
        raise not_found("项目接口不存在")
    path = (iface.path or "").rstrip("/")
    if iface.method.upper() != "POST" or not path.endswith("/api/v1/transcribe/paraformer/v2"):
        raise bad_request("请选择 POST /api/v1/transcribe/paraformer/v2 接口")
    if (iface.content_type or "").split(";")[0].strip().lower() not in {"application/json", ""}:
        raise bad_request("FunASR 绑定只支持 JSON 请求体")
    env = resolve_project_environment_by_name(db, body.project_id, body.environment_name)
    endpoint = build_environment_url(env, iface.path or "")
    if not endpoint.startswith(("http://", "https://")):
        raise bad_request("所选项目环境尚未配置服务地址")
    if body.credential and not body.credential_header:
        raise bad_request("填写凭据时请同时指定凭据请求头")
    if body.credential_header and not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", body.credential_header):
        raise bad_request("鉴权请求头名称格式无效")
    if body.credential_header and not any(word in body.credential_header.lower() for word in ("authorization", "token", "key")):
        raise bad_request("凭据请求头名称必须明确为鉴权字段")
    seed, seed_warnings = _read_parameter_seed(db, iface.id)
    headers = merge_request_fields(get_environment_headers(env), {"Content-Type": "application/json"})
    execution = {"endpoint": endpoint, "method": "POST", "headers": headers,
                 "credential": body.credential or "", "credential_header": body.credential_header or ""}
    snapshot = {"interface_id": iface.id, "interface_name": iface.name, "method": iface.method.upper(),
                "path": iface.path, "interface_version": iface.version, "source_hash": iface.source_hash,
                "environment_name": body.environment_name, "endpoint_display": _safe_endpoint_display(endpoint),
                "parameter_seed": seed, "parameter_seed_warnings": seed_warnings,
                "has_credential": bool(body.credential),
                "content_type": "application/json", "created_by": actor.id}
    row = AsrApiBinding(project_id=body.project_id, api_interface_id=iface.id, interface_version=iface.version,
        source_hash=iface.source_hash, environment_name=body.environment_name, config_snapshot=snapshot,
        execution_ciphertext=encrypt_secret(json.dumps(execution, ensure_ascii=False, separators=(",", ":"))),
        response_mapping=body.response_mapping, timeout_seconds=body.timeout_seconds,
        max_response_bytes=body.max_response_bytes, created_by=actor.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _dump_binding(db, row)


def list_fun_asr_bindings(db: Session, project_id: int, actor: User) -> dict[str, Any]:
    get_project_or_404(db, project_id, actor)
    rows = db.query(AsrApiBinding).filter_by(project_id=project_id, is_active=True).order_by(AsrApiBinding.id.desc()).all()
    return {"items": [_dump_binding(db, row) for row in rows], "total": len(rows)}


def update_fun_asr_binding(db: Session, binding_id: int, body: FunAsrBindingUpdate, actor: User) -> dict[str, Any]:
    row = db.get(AsrApiBinding, binding_id)
    if row is None:
        raise not_found("FunASR 接口绑定不存在")
    _require_editor(db, row.project_id, actor)
    try:
        sample_bytes = _canonical(body.response_sample)
        if len(sample_bytes) > 5_000_000:
            raise ValueError("响应样本 JSON 超过 5 MB")
        _mapping_preview(body.response_sample, body.response_mapping, source="recognition", audio_version_id=1)
    except (ValueError, TypeError) as exc:
        raise bad_request(f"响应样本映射无效，不能启动 ASR 请求：{exc}") from exc
    row.response_mapping = body.response_mapping
    snapshot = dict(row.config_snapshot or {})
    snapshot["mapping_verified_hash"] = hashlib.sha256(_canonical(body.response_mapping)).hexdigest()
    snapshot["mapping_preview_sample_hash"] = hashlib.sha256(sample_bytes).hexdigest()
    row.config_snapshot = snapshot
    db.commit()
    return _dump_binding(db, row)


def _mapping_preview(document: Any, mapping: dict[str, Any], *, source: str, audio_version_id: int) -> dict[str, Any]:
    normalized = normalize_document(document, mapping, source=source, audio_version_id=audio_version_id)
    markdown = render_markdown(normalized).decode("utf-8")
    return {"normalized_json": normalized, "markdown": markdown, "warnings": normalized.get("warnings", [])}


def preview_fun_asr_mapping(document: Any, mapping: dict[str, Any], source: str, audio_version_id: int) -> dict[str, Any]:
    return _mapping_preview(document, mapping, source=source, audio_version_id=audio_version_id)


def create_ground_truth(db: Session, audio_id: int, body: FunAsrGroundTruthCreate, actor: User) -> dict[str, Any]:
    audio = db.get(AsrAudio, audio_id)
    if audio is None:
        raise not_found("音频资源不存在")
    _require_editor(db, audio.project_id, actor)
    raw = _canonical(body.document)
    if len(raw) > 5_000_000:
        raise bad_request("标准答案 JSON 超过 5 MB")
    audio_version = ensure_audio_version(db, audio)
    try:
        preview = _mapping_preview(body.document, body.mapping, source="ground_truth", audio_version_id=audio_version.id)
    except ValueError as exc:
        raise bad_request(f"标准答案映射无效：{exc}") from exc
    version = (db.query(AsrGroundTruthVersion.version).filter_by(audio_version_id=audio_version.id)
               .order_by(AsrGroundTruthVersion.version.desc()).first())
    next_version = (version[0] if version else 0) + 1
    db.query(AsrGroundTruthVersion).filter_by(audio_id=audio.id, is_current=True).update(
        {"is_current": False}, synchronize_session="fetch")
    row = AsrGroundTruthVersion(project_id=audio.project_id, audio_id=audio.id,
        audio_version_id=audio_version.id, version=next_version, raw_sha256=hashlib.sha256(raw).hexdigest(),
        raw_document=body.document, mapping_snapshot=body.mapping, normalized_json=preview["normalized_json"],
        markdown=preview["markdown"], is_current=True, created_by=actor.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "audio_id": audio.id, "audio_version_id": audio_version.id,
            "version": row.version, "raw_sha256": row.raw_sha256, "transcript": row.normalized_json["transcript"],
            "warnings": preview["warnings"], "is_current": row.is_current, "created_at": row.created_at.isoformat()}


def list_ground_truth(db: Session, project_id: int, actor: User) -> dict[str, Any]:
    get_project_or_404(db, project_id, actor)
    rows = db.query(AsrGroundTruthVersion, AsrAudio, AsrAudioVersion).join(
        AsrAudio, AsrAudio.id == AsrGroundTruthVersion.audio_id,
    ).join(AsrAudioVersion, AsrAudioVersion.id == AsrGroundTruthVersion.audio_version_id).filter(
        AsrGroundTruthVersion.project_id == project_id, AsrGroundTruthVersion.is_current.is_(True)).order_by(AsrAudio.name).all()
    return {"items": [{"id": gt.id, "audio_id": gt.audio_id, "audio_name": audio.name,
                        "audio_version_id": gt.audio_version_id, "version": gt.version,
                        "audio_content_version": audio_version.version,
                        "raw_sha256": gt.raw_sha256, "transcript": gt.normalized_json.get("transcript", ""),
                        "created_at": gt.created_at.isoformat()} for gt, audio, audio_version in rows]}


def _validate_search_policies(parameters: dict[str, Any], allowed: dict[str, dict[str, Any]]) -> None:
    definitions = {item["path"]: item for item in FUNASR_DEFINITIONS}
    for path, policy in allowed.items():
        if path not in definitions or not definitions[path]["tunable"]:
            raise bad_request(f"参数不允许自动调优：{path}")
        if not isinstance(policy, dict) or set(policy) - {"minimum", "maximum", "choices"}:
            raise bad_request(f"参数搜索范围无效：{path}")
        definition = definitions[path]
        for key in ("minimum", "maximum"):
            if key in policy and policy[key] is not None:
                value = policy[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise bad_request(f"参数搜索边界必须是有限数值：{path}")
                lower = definition.get("exclusive_minimum")
                if lower is None:
                    lower = definition.get("minimum")
                if lower is not None and (value <= lower if definition.get("exclusive_minimum") is not None else value < lower):
                    raise bad_request(f"参数搜索范围低于接口范围：{path}")
                if definition.get("maximum") is not None and value > definition["maximum"]:
                    raise bad_request(f"参数搜索范围高于接口范围：{path}")
        if policy.get("minimum") is not None and policy.get("maximum") is not None and policy["minimum"] > policy["maximum"]:
            raise bad_request(f"参数搜索上下界倒置：{path}")
        if "choices" in policy:
            if (not isinstance(policy["choices"], list) or not policy["choices"]
                    or any(type(value) != type(parameters.get(path[1:])) for value in policy["choices"])):
                raise bad_request(f"参数候选类型无效：{path}")


def _new_round(db: Session, session: AsrTuningSession, ordinal: int, parameters: dict[str, Any]) -> AsrTuningRound:
    row = AsrTuningRound(session_id=session.id, ordinal=ordinal, status="QUEUED", parameters=copy.deepcopy(parameters),
                         parameter_hash=effective_parameter_hash(parameters), metrics={})
    db.add(row)
    db.flush()
    dataset = (session.config_snapshot or {}).get("dataset", [])
    for index, item in enumerate(dataset):
        db.add(AsrTuningItem(session_id=session.id, round_id=row.id, project_id=session.project_id,
            audio_id=item["audio_id"], audio_version_id=item["audio_version_id"],
            ground_truth_version_id=item["ground_truth_version_id"], ordinal=index,
            idempotency_key=hashlib.sha256(f"{session.id}:{ordinal}:{item['audio_id']}".encode()).hexdigest()[:80]))
    return row


def create_tuning_session(db: Session, body: FunAsrTuningCreate, actor: User) -> dict[str, Any]:
    _require_editor(db, body.project_id, actor)
    existing = db.query(AsrTuningSession).filter_by(idempotency_key=body.idempotency_key).one_or_none()
    if existing:
        if existing.project_id != body.project_id:
            raise conflict("幂等键已被其他项目使用")
        return get_tuning_session(db, existing.id, actor)
    binding = db.get(AsrApiBinding, body.binding_id)
    if binding is None or binding.project_id != body.project_id or not binding.is_active:
        raise not_found("FunASR 接口绑定不存在")
    iface = db.get(ApiInterface, binding.api_interface_id) if binding.api_interface_id else None
    if iface is None or iface.version != binding.interface_version or iface.source_hash != binding.source_hash:
        raise conflict("来源接口已更新或已删除，请更新绑定后再建任务")
    mapping = binding.response_mapping or {}
    if mapping.get("text_source") not in {"full", "segments"}:
        raise conflict("请先配置并预览响应映射")
    verified_hash = (binding.config_snapshot or {}).get("mapping_verified_hash")
    if verified_hash != hashlib.sha256(_canonical(mapping)).hexdigest():
        raise conflict("请提供真实响应 JSON，完成映射预览并保存后再创建任务")
    try:
        build_request(body.parameters, "https://fixture.invalid/audio")
    except (ValueError, HTTPException) as exc:
        detail = getattr(exc, "detail", str(exc))
        raise bad_request(f"FunASR 基线参数无效：{detail}") from exc
    if "audio" in body.parameters:
        raise bad_request("audio 由任务逐条注入，不能写入基线参数")
    if body.mode == "AUTO_TUNE" and len(body.audio_ids) + 1 > body.max_ai_calls:
        raise bad_request("每轮至少需要为每条音频分析一次并汇总一次，请增加 AI 调用预算")
    if body.max_asr_requests < len(body.audio_ids):
        raise bad_request("ASR 请求预算不足以覆盖第一轮的全部音频")
    if body.mode == "AUTO_TUNE" and not body.allowed_parameters:
        raise bad_request("自动调优至少要启用一个允许搜索的参数；否则请选择单轮分析")
    _validate_search_policies(body.parameters, body.allowed_parameters)
    _model_access(db, body.project_id, actor, body.model_config_id)
    model = db.get(ModelConfiguration, body.model_config_id)
    if model is None:
        raise not_found("文本分析模型不存在")
    dataset = []
    seen = set()
    for audio_id in body.audio_ids:
        if audio_id in seen:
            raise bad_request("音频列表不能重复")
        seen.add(audio_id)
        audio = db.get(AsrAudio, audio_id)
        if audio is None or audio.project_id != body.project_id:
            raise not_found("音频资源不存在")
        audio_version = ensure_audio_version(db, audio)
        truth = db.query(AsrGroundTruthVersion).filter_by(
            audio_id=audio_id, audio_version_id=audio_version.id, is_current=True).one_or_none()
        if truth is None:
            raise conflict(f"录音“{audio.name}”还没有对应当前音频版本的标准答案")
        dataset.append({"audio_id": audio.id, "audio_name": audio.name,
                        "audio_version_id": audio_version.id, "ground_truth_version_id": truth.id,
                        "content_fingerprint": audio_version.content_fingerprint})
    try:
        execution = json.loads(decrypt_secret(binding.execution_ciphertext))
    except (ValueError, TypeError):
        raise conflict("接口凭据快照无法读取") from None
    if not isinstance(execution, dict) or not execution.get("endpoint"):
        raise conflict("接口执行快照不完整")
    snapshot = {"schema_version": "funasr-tuning-1", "binding": {"id": binding.id,
        "api_interface_id": binding.api_interface_id, "interface_version": binding.interface_version,
        "source_hash": binding.source_hash, "environment_name": binding.environment_name,
        "response_mapping": copy.deepcopy(mapping), "timeout_seconds": binding.timeout_seconds,
        "max_response_bytes": binding.max_response_bytes, "config": copy.deepcopy(binding.config_snapshot)},
        "dataset": dataset, "parameters": copy.deepcopy(body.parameters),
        "allowed_parameters": copy.deepcopy(body.allowed_parameters),
        "scoring": {"version": "cer-normalize-1", "ignore_whitespace": False,
                    "ignore_punctuation": False, "casefold": False},
        "model_config_id": body.model_config_id, "model_revision": model_configuration_revision(model),
        "mode": body.mode, "created_at": datetime.now(timezone.utc).isoformat()}
    row = AsrTuningSession(project_id=body.project_id, binding_id=binding.id, model_config_id=body.model_config_id,
        status="QUEUED", mode=body.mode, config_snapshot=snapshot,
        execution_ciphertext=encrypt_secret(json.dumps(execution, ensure_ascii=False, separators=(",", ":"))),
        idempotency_key=body.idempotency_key, current_round=1, max_rounds=body.max_rounds,
        max_asr_requests=body.max_asr_requests, max_ai_calls=body.max_ai_calls,
        no_improvement_limit=body.no_improvement_limit, failed_items_limit=body.failed_items_limit,
        target_micro_cer=body.target_micro_cer, min_improvement=body.min_improvement,
        max_sample_degradation=body.max_sample_degradation, night_start=body.night_start,
        night_end=body.night_end, window_enabled=body.window_enabled, created_by=actor.id)
    db.add(row)
    try:
        db.flush()
        _new_round(db, row, 1, body.parameters)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(AsrTuningSession).filter_by(idempotency_key=body.idempotency_key).one_or_none()
        if existing and existing.project_id == body.project_id:
            return get_tuning_session(db, existing.id, actor)
        raise conflict("调优任务创建冲突") from None
    db.refresh(row)
    return get_tuning_session(db, row.id, actor)


def _dump_round(db: Session, row: AsrTuningRound, *, include_items: bool) -> dict[str, Any]:
    result = {"id": row.id, "ordinal": row.ordinal, "status": row.status, "parameters": row.parameters,
              "parameter_hash": row.parameter_hash, "metrics": row.metrics, "report_json": row.report_json,
              "report_markdown": row.report_markdown, "candidate_json": row.candidate_json,
              "accepted": row.accepted, "stop_reason": row.stop_reason,
              "started_at": row.started_at.isoformat() if row.started_at else None,
              "finished_at": row.finished_at.isoformat() if row.finished_at else None}
    if include_items:
        items = db.query(AsrTuningItem).filter_by(round_id=row.id).order_by(AsrTuningItem.ordinal).all()
        result["items"] = [{"id": item.id, "audio_id": item.audio_id, "audio_version_id": item.audio_version_id,
            "ground_truth_version_id": item.ground_truth_version_id, "status": item.status,
            "review_status": item.review_status, "response_received": item.response_received,
            "response_json": item.response_json,
            "normalized_json": item.normalized_json, "ground_truth_json": item.ground_truth_json,
            "answer_markdown": item.answer_markdown,
            "response_markdown": item.response_markdown, "metrics": item.metrics,
            "review_json": item.review_json, "duration_ms": item.duration_ms,
            "error_message": item.error_message} for item in items]
    return result


def _dump_session(db: Session, row: AsrTuningSession, *, detail: bool) -> dict[str, Any]:
    rounds = db.query(AsrTuningRound).filter_by(session_id=row.id).order_by(AsrTuningRound.ordinal).all()
    items_total = sum(db.query(AsrTuningItem.id).filter_by(round_id=round_row.id).count() for round_row in rounds)
    items_done = sum(db.query(AsrTuningItem.id).filter(AsrTuningItem.round_id == round_row.id,
        AsrTuningItem.status.in_(["SUCCEEDED", "FAILED", "RECONCILIATION_REQUIRED"])).count() for round_row in rounds)
    best = db.get(AsrTuningRound, row.best_round_id) if row.best_round_id else None
    data = {"id": row.id, "project_id": row.project_id, "binding_id": row.binding_id,
        "model_config_id": row.model_config_id, "status": row.status, "mode": row.mode,
        "current_round": row.current_round, "best_round_id": row.best_round_id,
        "best_micro_cer": (best.metrics or {}).get("micro_cer") if best else None,
        "total_rounds": len(rounds), "completed_items": items_done, "total_items": items_total,
        "asr_requests_used": row.asr_requests_used, "max_asr_requests": row.max_asr_requests,
        "ai_calls_used": row.ai_calls_used, "max_ai_calls": row.max_ai_calls,
        "stop_reason": row.stop_reason, "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "window_enabled": row.window_enabled, "night_start": row.night_start, "night_end": row.night_end,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None}
    if detail:
        data["config_snapshot"] = row.config_snapshot
        data["rounds"] = [_dump_round(db, r, include_items=True) for r in rounds]
    return data


def get_tuning_session(db: Session, session_id: int, actor: User) -> dict[str, Any]:
    row = db.get(AsrTuningSession, session_id)
    if row is None:
        raise not_found("FunASR 调优任务不存在")
    get_project_or_404(db, row.project_id, actor)
    return _dump_session(db, row, detail=True)


def list_tuning_sessions(db: Session, project_id: int, actor: User) -> dict[str, Any]:
    get_project_or_404(db, project_id, actor)
    rows = db.query(AsrTuningSession).filter_by(project_id=project_id).order_by(AsrTuningSession.id.desc()).limit(100).all()
    return {"items": [_dump_session(db, row, detail=False) for row in rows], "total": len(rows)}


def _session_for_write(db: Session, session_id: int, actor: User) -> AsrTuningSession:
    row = db.get(AsrTuningSession, session_id)
    if row is None:
        raise not_found("FunASR 调优任务不存在")
    require_writable_project(db, row.project_id, actor)
    return row


def pause_tuning_session(db: Session, session_id: int, actor: User) -> dict[str, Any]:
    row = _session_for_write(db, session_id, actor)
    if row.status in {"QUEUED", "WAITING_WINDOW"}:
        row.status = "PAUSED"
    elif row.status == "RUNNING":
        row.status = "PAUSE_REQUESTED"
    elif row.status not in {"PAUSED", "PAUSE_REQUESTED"}:
        raise conflict("当前任务状态不能暂停")
    db.commit()
    return get_tuning_session(db, row.id, actor)


def resume_tuning_session(db: Session, session_id: int, actor: User) -> dict[str, Any]:
    row = _session_for_write(db, session_id, actor)
    if row.status not in {"PAUSED", "WAITING_WINDOW"}:
        raise conflict("只有暂停或等待夜间窗口的任务可以继续")
    row.status, row.next_run_at = "QUEUED", None
    db.commit()
    return get_tuning_session(db, row.id, actor)


def stop_tuning_session(db: Session, session_id: int, actor: User) -> dict[str, Any]:
    row = _session_for_write(db, session_id, actor)
    if row.status in {"COMPLETED", "STOPPED", "FAILED"}:
        return get_tuning_session(db, row.id, actor)
    if row.status == "RUNNING":
        row.cancel_requested = True
        row.status = "STOP_REQUESTED"
    else:
        row.status, row.stop_reason, row.finished_at = "STOPPED", "用户停止任务。", datetime.now(timezone.utc)
    db.commit()
    return get_tuning_session(db, row.id, actor)


def retry_failed_tuning_items(db: Session, session_id: int, actor: User) -> dict[str, Any]:
    row = _session_for_write(db, session_id, actor)
    if row.status not in {"FAILED", "PAUSED"}:
        raise conflict("只有失败或暂停的任务可以补跑失败音频")
    round_row = db.query(AsrTuningRound).filter_by(session_id=row.id, ordinal=row.current_round).one_or_none()
    if round_row is None:
        raise conflict("当前轮次不存在")
    failed = db.query(AsrTuningItem).filter_by(round_id=round_row.id, status="FAILED").all()
    if not failed:
        raise conflict("当前轮次没有可安全重试的明确失败项；待核实状态不会自动重发")
    received = db.query(AsrTuningItem).filter_by(round_id=round_row.id, response_received=True).all()
    snapshot = dict(row.config_snapshot or {})
    binding_snapshot = dict(snapshot.get("binding") or {})
    current_binding = db.get(AsrApiBinding, row.binding_id)
    current_mapping = (current_binding.response_mapping or {}) if current_binding else {}
    mapping_hash = hashlib.sha256(_canonical(current_mapping)).hexdigest()
    verified_hash = (current_binding.config_snapshot or {}).get("mapping_verified_hash") if current_binding else None
    if received and verified_hash != mapping_hash:
        raise conflict("请先用实际响应样本验证并保存当前响应映射")
    old_mapping = binding_snapshot.get("response_mapping") or {}
    mapping_changed = bool(received and old_mapping != current_mapping)
    if mapping_changed:
        if row.current_round != 1:
            raise conflict("映射已用于历史轮次；为保持轮次可比，请修正配置后创建新任务")
        revisions = list(binding_snapshot.get("mapping_revisions") or [])
        revisions.append({"from_hash": hashlib.sha256(_canonical(old_mapping)).hexdigest(),
            "to_hash": mapping_hash, "changed_at": datetime.now(timezone.utc).isoformat(), "changed_by": actor.id,
            "reason": "用户对已收到的响应执行映射修复；不重发 ASR 请求。"})
        binding_snapshot["response_mapping"] = copy.deepcopy(current_mapping)
        binding_snapshot["mapping_revisions"] = revisions
        snapshot["binding"] = binding_snapshot
        row.config_snapshot = snapshot
    received_to_reprocess = received if mapping_changed else [item for item in received if item.status == "FAILED"]
    for item in received_to_reprocess:
        truth = db.get(AsrGroundTruthVersion, item.ground_truth_version_id)
        try:
            if truth is None:
                raise ValueError("固定标准答案版本不存在")
            normalized = normalize_document(item.response_json, current_mapping, source="recognition",
                audio_version_id=item.audio_version_id)
            score_config = snapshot.get("scoring", {})
            reference = normalize_text(truth.normalized_json.get("transcript", ""),
                ignore_whitespace=bool(score_config.get("ignore_whitespace")),
                ignore_punctuation=bool(score_config.get("ignore_punctuation")),
                casefold=bool(score_config.get("casefold")))
            hypothesis = normalize_text(normalized.get("transcript", ""),
                ignore_whitespace=bool(score_config.get("ignore_whitespace")),
                ignore_punctuation=bool(score_config.get("ignore_punctuation")),
                casefold=bool(score_config.get("casefold")))
            normalized["scoring_version"] = score_config.get("version", "cer-normalize-1")
            normalized["score_transcript"] = hypothesis
            item.normalized_json = normalized
            item.ground_truth_json = truth.normalized_json
            item.answer_markdown = truth.markdown
            item.response_markdown = render_markdown(normalized).decode("utf-8")
            item.metrics = character_error_counts(reference, hypothesis)
            item.status, item.error_message, item.finished_at = "SUCCEEDED", None, datetime.now(timezone.utc)
            if mapping_changed:
                item.review_json, item.review_status = None, "PENDING"
        except (ValueError, TypeError) as exc:
            item.status, item.error_message, item.finished_at = "FAILED", f"响应映射修复失败：{exc}", datetime.now(timezone.utc)
    asr_failures = [item for item in failed if not item.response_received]
    for item in asr_failures:
        item.status, item.error_message, item.started_at, item.finished_at = "PENDING", None, None, None
    round_row.metrics = _metrics_for_round(db, round_row)
    round_row.status = "QUEUED" if asr_failures else "RUNNING"
    round_row.report_json = None
    round_row.report_markdown = None
    round_row.candidate_json = None
    round_row.accepted = None
    round_row.finished_at = None
    row.status, row.cancel_requested, row.stop_reason, row.finished_at = "QUEUED", False, None, None
    db.commit()
    return get_tuning_session(db, row.id, actor)


def retry_tuning_analysis(db: Session, session_id: int, actor: User) -> dict[str, Any]:
    """Retry only known failed AI stages; unknown external states remain blocked."""
    row = _session_for_write(db, session_id, actor)
    if row.status != "FAILED":
        raise conflict("只有明确失败的任务可以补跑 AI 分析")
    round_row = db.query(AsrTuningRound).filter_by(session_id=row.id, ordinal=row.current_round).one_or_none()
    if round_row is None or round_row.status == "RECONCILIATION_REQUIRED":
        raise conflict("待核实状态不能自动重试")
    unknown = db.query(AsrTuningItem.id).filter_by(round_id=round_row.id, review_status="RECONCILIATION_REQUIRED").first()
    if unknown:
        raise conflict("存在 AI 调用状态待核实项，不能盲目重试")
    has_known_failure = round_row.status == "FAILED" or db.query(AsrTuningItem.id).filter_by(
        round_id=round_row.id, review_status="FAILED").first() is not None
    if not has_known_failure:
        raise conflict("当前轮次没有可安全重试的 AI 阶段")
    for item in db.query(AsrTuningItem).filter_by(round_id=round_row.id, review_status="FAILED").all():
        item.review_status, item.error_message = "PENDING", None
    round_row.status, round_row.analysis_stage, round_row.stop_reason = "RUNNING", None, None
    row.status, row.stop_reason, row.finished_at = "QUEUED", None, None
    row.cancel_requested = False
    db.commit()
    return get_tuning_session(db, row.id, actor)


def get_models_for_project(db: Session, project_id: int, actor: User) -> dict[str, Any]:
    from app.features.asr_evaluation.services.content_review_service import list_review_models
    return list_review_models(db, project_id, actor)


def _next_window_start(now: datetime, start: str) -> datetime:
    from datetime import time as clock_time
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Asia/Shanghai")
    local = now.astimezone(zone)
    hour, minute = (int(part) for part in start.split(":"))
    at = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if at <= local:
        at += timedelta(days=1)
    return at.astimezone(timezone.utc)


def _metrics_for_round(db: Session, round_row: AsrTuningRound) -> dict[str, Any]:
    items = db.query(AsrTuningItem).filter_by(round_id=round_row.id).order_by(AsrTuningItem.ordinal).all()
    samples = {}
    durations, successful = [], 0
    for item in items:
        metric = item.metrics or {"reference_characters": 0, "errors": 0, "cer": None,
                                  "substitutions": 0, "deletions": 0, "insertions": 0,
                                  "empty_reference_insertions": 0}
        samples[str(item.audio_id)] = {"status": item.status, "review_status": item.review_status,
                                       "metrics": metric, "duration_ms": item.duration_ms}
        if item.status == "SUCCEEDED":
            successful += 1
            if item.duration_ms is not None:
                durations.append(item.duration_ms)
    aggregated = aggregate_cer([value["metrics"] for value in samples.values()])
    return {**aggregated, "samples": samples, "successful_samples": successful,
            "planned_samples": len(items), "success_rate": successful / len(items) if items else 0,
            "coverage": successful / len(items) if items else 0,
            "duration_ms_total": sum(durations), "duration_ms_mean": sum(durations) / len(durations) if durations else None,
            "request_count": len(items)}


def _validate_finding_report(report: Any, item: AsrTuningItem, expected_ids: set[str], allowed_text: list[str]) -> dict[str, Any]:
    if not isinstance(report, dict) or set(report) - {"findings", "uncertainty", "summary"}:
        raise ValueError("逐条分析结构无效")
    findings = report.get("findings", [])
    if not isinstance(findings, list) or len(findings) > 20:
        raise ValueError("逐条分析发现数量无效")
    clean = []
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) - {"dimension", "explanation", "evidence"}:
            raise ValueError("逐条分析字段无效")
        evidence = finding.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("每项发现都必须引用证据")
        verified = []
        for quote in evidence:
            if not isinstance(quote, dict) or set(quote) != {"id", "quote"} or quote["id"] not in expected_ids:
                raise ValueError("分析引用了不存在的证据 ID")
            text = quote["quote"]
            if not isinstance(text, str) or not text or not any(text in content for content in allowed_text):
                raise ValueError("分析引文未逐字出现在输入文本中")
            verified.append({"id": quote["id"], "quote": text})
        clean.append({"dimension": str(finding.get("dimension", "text_difference"))[:80],
                      "explanation": str(finding.get("explanation", ""))[:1200], "evidence": verified})
    return {"summary": str(report.get("summary", ""))[:1500], "findings": clean,
            "uncertainty": str(report.get("uncertainty", ""))[:800]}


def _validate_decision(report: Any, current: dict[str, Any], best: dict[str, Any], session: AsrTuningSession,
                       evidence_by_audio: dict[str, set[str]]) -> dict[str, Any]:
    if not isinstance(report, dict) or set(report) - {"action", "summary", "common_findings", "changes", "stop_reason"}:
        raise ValueError("整轮分析结构无效")
    action = report.get("action")
    if action not in {"propose", "stop"}:
        raise ValueError("Agent action 必须是 propose 或 stop")
    common = report.get("common_findings", [])
    if not isinstance(common, list) or len(common) > 20 or any(not isinstance(value, str) for value in common):
        raise ValueError("整轮共性发现格式无效")
    common = [value[:1200] for value in common]
    changes = report.get("changes", [])
    if action == "stop" and changes:
        raise ValueError("停止操作不能同时包含候选参数")
    if action == "propose" and (not isinstance(changes, list) or not changes):
        raise ValueError("提出候选时必须包含参数变更")
    validated_changes = []
    if action == "propose":
        core_changes = []
        for change in changes:
            if not isinstance(change, dict) or set(change) != {"path", "old_value", "new_value", "audio_ids", "evidence_ids", "rationale", "expected_effect", "watch_metric"}:
                raise ValueError("候选变更字段不完整")
            path = change["path"]
            raw_audio_ids = change["audio_ids"]
            audio_ids = ([str(value) for value in raw_audio_ids]
                         if isinstance(raw_audio_ids, list) and all(
                             isinstance(value, (str, int)) and not isinstance(value, bool)
                             for value in raw_audio_ids
                         ) else [])
            evidence_ids = change["evidence_ids"] if isinstance(change["evidence_ids"], list) else []
            string_fields = (change["rationale"], change["expected_effect"], change["watch_metric"])
            if (not isinstance(path, str) or any(not isinstance(value, str) for value in string_fields)
                    or not audio_ids or len(audio_ids) > 200 or len(set(audio_ids)) != len(audio_ids)
                    or any(audio_id not in evidence_by_audio for audio_id in audio_ids)
                    or any(not isinstance(value, str) or not value for value in evidence_ids)):
                raise ValueError("候选缺少有效录音证据")
            if not evidence_ids or any(not any(evidence_id in evidence_by_audio[audio_id] for audio_id in audio_ids)
                                       for evidence_id in evidence_ids):
                raise ValueError("候选引用了未提供的证据")
            core_changes.append({key: change[key] for key in ("path", "old_value", "new_value")})
            validated_changes.append({**change, "audio_ids": audio_ids, "evidence_ids": evidence_ids,
                                      "rationale": str(change["rationale"])[:1200],
                                      "expected_effect": str(change["expected_effect"])[:600],
                                      "watch_metric": str(change["watch_metric"])[:120]})
        best_parameters = best.get("parameters") or current
        allowed = (session.config_snapshot or {}).get("allowed_parameters", {})
        validate_candidate(best_parameters, core_changes, allowed=allowed,
            previous_hashes=set(), speaker_metrics_available=False)
    return {"action": action, "summary": str(report.get("summary", ""))[:3000],
            "common_findings": common, "changes": validated_changes,
            "stop_reason": str(report.get("stop_reason", ""))[:1200]}


__all__ = [
    "FUNASR_DEFINITIONS", "FUNASR_FIELDS", "aggregate_cer", "build_request", "character_error_counts",
    "create_fun_asr_binding", "create_ground_truth", "create_tuning_session", "get_models_for_project",
    "get_tuning_session", "list_fun_asr_bindings", "list_fun_asr_environments", "list_fun_asr_interfaces",
    "list_ground_truth", "list_tuning_sessions", "pause_tuning_session", "preview_fun_asr_mapping",
    "retry_failed_tuning_items", "retry_tuning_analysis", "resume_tuning_session", "stop_tuning_session", "update_fun_asr_binding",
]
