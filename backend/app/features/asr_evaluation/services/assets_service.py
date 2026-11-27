"""音频资产服务。

所有写操作在服务层校验项目权限并提交事务；音频 URL 用 core.security.crypto 加密，
返回值只含脱敏地址和是否已配置凭据。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.features.asr_evaluation.models import AsrAudio, AsrAudioVersion, AsrGroundTruthVersion
from app.features.asr_evaluation.schemas import AudioItemInput


def _safe_url_display(url: str) -> str:
    """移除用户信息、查询串和片段，避免签名 URL 在页面、错误或导出中泄漏。"""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))[:500]


def _dump_audio(row: AsrAudio) -> dict:
    """生成不含原始 URL 查询串的音频合同。"""
    return {
        "id": row.id, "project_id": row.project_id, "name": row.name,
        "url_display": row.url_display, "duration_seconds": row.duration_seconds,
        "content_version": row.content_version, "availability": row.availability,
        "tags": row.tags or [], "created_at": row.created_at,
    }


def ensure_audio_version(db: Session, row: AsrAudio) -> AsrAudioVersion:
    """确保当前音频链接有不可变版本行，供新运行固定引用而非读取未来的可变链接。"""
    version = db.query(AsrAudioVersion).filter(
        AsrAudioVersion.audio_id == row.id, AsrAudioVersion.version == row.content_version,
    ).one_or_none()
    if version is None:
        version = AsrAudioVersion(
            audio_id=row.id, version=row.content_version, name=row.name,
            url_ciphertext=row.url_ciphertext, url_display=row.url_display,
            duration_seconds=row.duration_seconds, content_fingerprint=row.content_fingerprint,
            source_info={},
        )
        db.add(version)
        db.flush()
    return version


def _validate_parameters(parameters: dict, definitions: list[dict]) -> None:
    """按已知参数定义检查 JSON Pointer、类型、数值范围和枚举。"""
    from app.features.asr_evaluation.providers.generic_json import read_json_pointer

    def validate_keys(value: Any) -> None:
        """禁止把凭据、URL 或 Cookie 放进普通模型参数 JSON。"""
        if isinstance(value, dict):
            for key, nested in value.items():
                if re.search(r"(authorization|access[-_]?token|auth[-_]?token|secret|password|api[-_]?key|cookie|url|credential|signature)", str(key), re.I):
                    raise bad_request("凭据、URL 和 Cookie 不能存入待测模型参数；请使用加密连接凭据")
                validate_keys(nested)
        elif isinstance(value, list):
            for nested in value:
                validate_keys(nested)
        elif isinstance(value, str) and re.search(
            r"https?://|\bBearer\s+|\b(?:token|secret|password|api[-_]?key|signature)\s*[:=]",
            value, re.I,
        ):
            raise bad_request("待测模型参数不能包含 URL 或疑似凭据文本")

    validate_keys(parameters)

    import math

    missing = object()
    for definition in definitions:
        path = definition["path"]
        value = read_json_pointer(parameters, path, missing=missing)
        if value is missing:
            if definition.get("required", True):
                raise bad_request(f"参数缺少已定义字段：{path}")
            continue
        if value is None:
            if not definition.get("nullable", False):
                raise bad_request(f"参数不允许为空：{path}")
            if definition.get("choices") is not None and value not in definition["choices"]:
                raise bad_request(f"参数不在允许选项中：{path}")
            continue
        expected = definition["value_type"]
        valid = {
            "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool), "object": isinstance(value, dict), "array": isinstance(value, list),
        }[expected]
        if not valid:
            raise bad_request(f"参数类型与定义不符：{path}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, float) and not math.isfinite(value):
                raise bad_request(f"参数必须为有限数值：{path}")
            if definition.get("exclusive_minimum") is not None and value <= definition["exclusive_minimum"]:
                raise bad_request(f"参数低于允许范围：{path}")
            if definition.get("minimum") is not None and value < definition["minimum"]:
                raise bad_request(f"参数低于允许范围：{path}")
            if definition.get("maximum") is not None and value > definition["maximum"]:
                raise bad_request(f"参数高于允许范围：{path}")
        if definition.get("choices") is not None and value not in definition["choices"]:
            raise bad_request(f"参数不在允许选项中：{path}")


def create_audio(db: Session, project_id: int, item: AudioItemInput, actor: User) -> dict:
    """加密保存一条音频 URL，并返回脱敏项目资源。"""
    require_writable_project(db, project_id, actor)
    raw_url = str(item.url)
    row = AsrAudio(
        project_id=project_id, name=item.name.strip(), url_ciphertext=encrypt_secret(raw_url),
        url_display=_safe_url_display(raw_url), duration_seconds=item.duration_seconds,
        tags=item.tags, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    ensure_audio_version(db, row)
    db.commit()
    db.refresh(row)
    return _dump_audio(row)


def import_audios(db: Session, project_id: int, items: list[AudioItemInput], actor: User) -> list[dict]:
    """在一个事务里导入一批已授权音频链接，逐条加密 URL。"""
    require_writable_project(db, project_id, actor)
    rows = []
    for item in items:
        raw_url = str(item.url)
        rows.append(AsrAudio(
            project_id=project_id, name=item.name.strip(), url_ciphertext=encrypt_secret(raw_url),
            url_display=_safe_url_display(raw_url), duration_seconds=item.duration_seconds,
            tags=item.tags, created_by=actor.id,
        ))
    db.add_all(rows)
    db.flush()
    for row in rows:
        ensure_audio_version(db, row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return [_dump_audio(row) for row in rows]


def update_audio(db: Session, audio_id: int, *, name: str | None, url: str | None, duration_seconds: int | None, actor: User) -> dict:
    """更新音频元数据；URL 改变时递增内容版本并清除旧指纹。"""
    row = db.get(AsrAudio, audio_id)
    if row is None:
        raise not_found("音频资源不存在")
    require_writable_project(db, row.project_id, actor)
    if name is not None:
        row.name = name.strip()
    if url is not None and decrypt_secret(row.url_ciphertext) != url:
        row.url_ciphertext = encrypt_secret(url)
        row.url_display = _safe_url_display(url)
        row.content_version += 1
        row.content_fingerprint = None
        row.availability = "UNKNOWN"
        ensure_audio_version(db, row)
    if duration_seconds is not None:
        row.duration_seconds = duration_seconds
    db.commit()
    db.refresh(row)
    return _dump_audio(row)


def list_audios(
    db: Session, project_id: int, actor: User, *, page: int = 1, page_size: int = 20,
    keyword: str | None = None, availability: str | None = None, ground_truth_status: str | None = None,
) -> dict:
    """分页列出项目可见音频，不暴露签名查询串。"""
    get_project_or_404(db, project_id, actor)
    query = db.query(AsrAudio).filter(AsrAudio.project_id == project_id)
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        query = query.filter(AsrAudio.name.ilike(f"%{normalized_keyword}%"))
    if availability:
        allowed_availability = {"AVAILABLE", "UNKNOWN", "UNREACHABLE", "PLATFORM_DENIED"}
        if availability not in allowed_availability:
            raise bad_request("音频可用性筛选值无效")
        query = query.filter(AsrAudio.availability == availability)
    if ground_truth_status:
        if ground_truth_status not in {"BOUND", "UNBOUND"}:
            raise bad_request("标准答案筛选值无效")
        current_ground_truth = db.query(AsrGroundTruthVersion.id).join(
            AsrAudioVersion, AsrAudioVersion.id == AsrGroundTruthVersion.audio_version_id,
        ).filter(
            AsrGroundTruthVersion.audio_id == AsrAudio.id,
            AsrAudioVersion.version == AsrAudio.content_version,
            AsrGroundTruthVersion.is_current.is_(True),
        ).exists()
        query = query.filter(current_ground_truth if ground_truth_status == "BOUND" else ~current_ground_truth)
    total = query.order_by(None).count()
    rows = query.order_by(AsrAudio.created_at.desc(), AsrAudio.id.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    current_versions = db.query(AsrAudioVersion).filter(
        AsrAudioVersion.audio_id.in_([row.id for row in rows] or [-1]),
    ).all()
    version_ids = {(row.audio_id, row.version): row.id for row in current_versions}
    items = [_dump_audio(row) | {"current_audio_version_id": version_ids.get((row.id, row.content_version))} for row in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def check_audio(db: Session, audio_id: int, actor: User) -> dict:
    """分别记录平台出站授权和音频源可达性；HEAD 不支持时保留未知而非判无效。"""
    from app.execution.http.executor import ApiRequestExecutor
    from app.execution.http.outbound_policy import resolve_project_outbound_target

    row = db.get(AsrAudio, audio_id)
    if row is None:
        raise not_found("音频资源不存在")
    get_project_or_404(db, row.project_id, actor)
    target_url = decrypt_secret(row.url_ciphertext)
    decision = resolve_project_outbound_target(db, target_url, row.project_id)
    if decision.rejection_message:
        row.availability = "PLATFORM_DENIED"
        db.commit()
        return {"id": row.id, "availability": row.availability, "platform_access": "DENIED",
                "audio_source": "NOT_CHECKED", "http_status": None}
    result = ApiRequestExecutor().execute(
        db, method="HEAD", url=target_url, project_id=row.project_id, timeout=15,
    )
    if result.status_code == 405:
        row.availability = "UNKNOWN"
        source = "HEAD_NOT_SUPPORTED"
    elif 200 <= result.status_code < 400:
        row.availability = "AVAILABLE"
        source = "REACHABLE"
    elif result.status_code:
        row.availability = "UNREACHABLE"
        source = "HTTP_ERROR"
    else:
        row.availability = "UNKNOWN"
        source = "NETWORK_ERROR"
    db.commit()
    return {
        "id": row.id, "availability": row.availability, "platform_access": "ALLOWED",
        "audio_source": source, "http_status": result.status_code or None,
    }



__all__ = [
    "_dump_audio", "check_audio", "create_audio", "ensure_audio_version", "import_audios",
    "list_audios", "update_audio",
]
