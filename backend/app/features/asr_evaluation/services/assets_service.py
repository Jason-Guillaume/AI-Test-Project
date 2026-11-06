"""音频、连接、参数与计划资产服务。

所有写操作在服务层校验项目权限并提交事务；音频和接口 URL、长期凭据用 core.security.crypto 加密，
返回值只含脱敏地址和 secret 是否已配置。连接和参数修改以新版本保存，历史任务使用自己的密文快照。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.core.security.roles import PROJECT_ROLE_EDITOR, has_project_role, project_role_for
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.platform.model_configuration.services.model_center_service import (
    resolve_task_slots, sync_legacy_asr_connection, sync_legacy_asr_parameter_set,
)
from app.platform.model_configuration.models import ModelTaskSlot
from app.features.asr_evaluation.models import AsrAudio, AsrAudioVersion, AsrConnection, AsrParameterSet, AsrSchedule
from app.features.asr_evaluation.schemas import (
    AudioItemInput, ConnectionCreate, ParameterSetCreate, ScheduleCreate,
)
from app.features.asr_evaluation.providers.generic_json import render_template

_SENSITIVE_NAME = re.compile(r"(authorization|token|secret|password|api[-_]?key|cookie)", re.I)


def _safe_url_display(url: str) -> str:
    """移除用户信息、查询串和片段，避免签名 URL 在页面、错误或导出中泄漏。"""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))[:500]


def _require_editor(db: Session, project_id: int, actor: User) -> None:
    """接口连接和计划需要 editor 权限；跨项目访问仍按 404 隐藏。"""
    project = get_project_or_404(db, project_id, actor)
    if not has_project_role(project_role_for(db, project, actor), PROJECT_ROLE_EDITOR):
        from app.core.http.errors import forbidden
        raise forbidden("需要项目编辑者权限")


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


def _dump_connection(row: AsrConnection) -> dict:
    """返回连接安全摘要；请求头和值模板不回显，防止误存的令牌进入日志或页面。"""
    config = row.config_json or {}
    response_mapping = config.get("response_mapping", {})
    safe_mapping = {
        key: response_mapping[key] for key in (
            "text_pointer", "segments_pointer", "segment_text_pointer", "segment_id_pointer", "speaker_pointer",
            "confidence_pointer", "channel_pointer", "start_pointer", "end_pointer", "time_unit",
            "word_times_pointer", "sample_rate_pointer", "timeline", "model_version",
        ) if isinstance(response_mapping, dict) and key in response_mapping
    }
    return {
        "id": row.id, "project_id": row.project_id, "name": row.name, "role": row.role,
        "task_type": row.task_type,
        "provider_id": row.provider_id, "model_id": row.model_id, "version": row.version,
        "endpoint_display": row.endpoint_display, "method": config.get("method", "POST"),
        "headers": {key: "[已配置]" for key in (config.get("headers") or {})},
        "request_template": {"configured": bool(config.get("request_template"))},
        "response_mapping": safe_mapping,
        "parameter_definitions": config.get("parameter_definitions") or [],
        "async_config": {"configured": True} if config.get("async_config") else None,
        "timeout_seconds": config.get("timeout_seconds", 180),
        "max_response_bytes": config.get("max_response_bytes", 8_000_000),
        "has_secret": bool(row.secret_ciphertext), "secret_header": row.secret_header,
        "enabled": row.enabled, "created_at": row.created_at,
    }


def _validate_connection(body: ConnectionCreate) -> tuple[str, dict]:
    """校验模板变量和敏感 Header 分离规则，避免遗漏音频 URL 或参数对象。"""
    endpoint = str(body.endpoint)
    parsed = urlsplit(endpoint)
    if parsed.username or parsed.password or parsed.fragment:
        raise bad_request("接口地址不能包含用户信息或片段")
    for name, value in body.headers.items():
        if _SENSITIVE_NAME.search(name) or name.lower() in {"host", "content-length", "connection"}:
            raise bad_request("鉴权与敏感请求头请使用独立凭据字段")
        if len(name) > 100 or len(value) > 2000:
            raise bad_request("请求头字段超出长度限制")
    if body.secret and not body.secret_header:
        raise bad_request("填写凭据时必须指定凭据请求头")
    if body.secret_header and _SENSITIVE_NAME.search(body.secret_header) is None:
        raise bad_request("凭据请求头名称应明确包含 Authorization、Token 或 Key")
    sample_context = {
        "audio": {"url": "https://audio.example.org/sample.mp3"},
        "connection": {"model_id": body.model_id}, "experiment": {"parameters": {"nested": {"enabled": True}}},
    }
    try:
        rendered = render_template(body.request_template, sample_context)
    except ValueError as exc:
        raise bad_request(str(exc)) from None
    flattened = json.dumps(body.request_template, ensure_ascii=False)
    if "{{audio.url}}" not in flattened or "{{experiment.parameters}}" not in flattened:
        raise bad_request("请求模板必须同时包含 {{audio.url}} 和 {{experiment.parameters}}")
    if not isinstance(rendered, dict):
        raise bad_request("请求模板根节点必须是 JSON 对象")
    text_pointer = body.response_mapping.get("text_pointer")
    if body.task_type == "TRANSCRIPTION" and (
        not isinstance(text_pointer, str) or not (text_pointer == "" or text_pointer.startswith("/"))
    ):
        raise bad_request("转写连接的响应文本映射必须是 JSON Pointer")
    if body.task_type == "DIARIZATION":
        required = ("segments_pointer", "start_pointer", "end_pointer", "speaker_pointer")
        if any(not isinstance(body.response_mapping.get(field), str) or not body.response_mapping[field].startswith("/")
               for field in required):
            raise bad_request("说话人连接需配置时间区间、分段和说话人字段映射")
    for field in (
        "text_pointer", "segments_pointer", "segment_text_pointer", "segment_id_pointer", "speaker_pointer",
        "confidence_pointer", "channel_pointer", "start_pointer", "end_pointer", "word_times_pointer",
    ):
        pointer = body.response_mapping.get(field)
        if pointer is not None and (
            not isinstance(pointer, str) or not (pointer == "" or pointer.startswith("/"))
        ):
            raise bad_request(f"{field} 必须是 JSON Pointer")
    if body.async_config:
        task_pointer = body.async_config.get("task_id_pointer")
        status_pointer = body.async_config.get("status_pointer")
        poll_template = body.async_config.get("poll_url_template")
        if not all(isinstance(item, str) and item.startswith("/") for item in (task_pointer, status_pointer)):
            raise bad_request("异步任务 ID 和状态必须使用 JSON Pointer")
        if not isinstance(poll_template, str) or "{{task_id}}" not in poll_template:
            raise bad_request("异步轮询地址必须包含 {{task_id}}")
        if body.async_config.get("poll_method", "GET").upper() not in {"GET", "POST"}:
            raise bad_request("轮询方法仅支持 GET 或 POST")
    return endpoint, rendered


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
    keyword: str | None = None,
) -> dict:
    """分页列出项目可见音频，不暴露签名查询串。"""
    get_project_or_404(db, project_id, actor)
    query = db.query(AsrAudio).filter(AsrAudio.project_id == project_id)
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        query = query.filter(AsrAudio.name.ilike(f"%{normalized_keyword}%"))
    total = query.order_by(None).count()
    rows = query.order_by(AsrAudio.created_at.desc(), AsrAudio.id.desc()).offset(
        (page - 1) * page_size,
    ).limit(page_size).all()
    return {"items": [_dump_audio(row) for row in rows], "total": total, "page": page, "page_size": page_size}


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


def create_connections(db: Session, body: ConnectionCreate, actor: User) -> dict:
    """创建连接新版本；同名连接版本不可变，空凭据沿用上一版加密值。"""
    _require_editor(db, body.project_id, actor)
    endpoint, _ = _validate_connection(body)
    latest = db.query(AsrConnection).filter(
        AsrConnection.project_id == body.project_id, AsrConnection.name == body.name.strip(),
    ).order_by(AsrConnection.version.desc()).first()
    if latest and (latest.role != body.role or latest.task_type != body.task_type):
        raise bad_request("同名连接不能更改任务类型或待测/参考角色")
    row = AsrConnection(
        project_id=body.project_id, name=body.name.strip(), role=body.role, task_type=body.task_type,
        provider_id=body.provider_id,
        model_id=body.model_id.strip(), version=(latest.version + 1 if latest else 1),
        endpoint_ciphertext=encrypt_secret(endpoint), endpoint_display=_safe_url_display(endpoint),
        config_json={
            "method": body.method, "headers": body.headers, "request_template": body.request_template,
            "response_mapping": body.response_mapping, "async_config": body.async_config,
            "parameter_definitions": body.parameter_definitions,
            "timeout_seconds": body.timeout_seconds, "max_response_bytes": body.max_response_bytes,
        },
        secret_ciphertext=encrypt_secret(body.secret) if body.secret else (latest.secret_ciphertext if latest else None),
        secret_header=body.secret_header or (latest.secret_header if latest else None), created_by=actor.id,
    )
    db.add(row)
    db.flush()
    sync_legacy_asr_connection(db, row)
    db.commit()
    db.refresh(row)
    return _dump_connection(row)


def list_connections(db: Session, project_id: int, actor: User, *, task_type: str = "TRANSCRIPTION") -> list[dict]:
    """列出指定任务类型的项目连接版本，避免说话人连接混入三方 ASR 角色选择器。"""
    get_project_or_404(db, project_id, actor)
    rows = db.query(AsrConnection).filter(
        AsrConnection.project_id == project_id, AsrConnection.task_type == task_type,
    ).order_by(
        AsrConnection.name, AsrConnection.version.desc(),
    ).limit(1000).all()
    return [_dump_connection(row) for row in rows]


def create_parameter_set(db: Session, body: ParameterSetCreate, actor: User) -> dict:
    """校验并创建参数方案新版本；未知字段可透传但不会生成自动数值建议。"""
    _require_editor(db, body.project_id, actor)
    connection = db.get(AsrConnection, body.connection_id)
    if connection is None or connection.project_id != body.project_id or connection.task_type != "TRANSCRIPTION":
        raise not_found("转写模型连接不存在")
    definitions = [item.model_dump(exclude={"default"} if "default" not in item.model_fields_set else set())
                   for item in body.definitions]
    try:
        _validate_parameters(body.parameters, definitions)
    except ValueError as exc:
        if getattr(exc, "status_code", None):
            raise
        raise bad_request(str(exc)) from None
    latest = db.query(AsrParameterSet).filter(
        AsrParameterSet.connection_id == body.connection_id, AsrParameterSet.name == body.name.strip(),
    ).order_by(AsrParameterSet.version.desc()).first()
    row = AsrParameterSet(
        project_id=body.project_id, connection_id=body.connection_id, name=body.name.strip(),
        version=latest.version + 1 if latest else 1, parameters=body.parameters,
        definitions=definitions, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    sync_legacy_asr_parameter_set(db, row)
    db.commit()
    db.refresh(row)
    return _dump_parameter_set(row)


def _dump_parameter_set(row: AsrParameterSet) -> dict:
    """序列化不可变参数版本及定义来源。"""
    return {
        "id": row.id, "project_id": row.project_id, "connection_id": row.connection_id,
        "name": row.name, "version": row.version, "parameters": row.parameters,
        "definitions": row.definitions or [], "created_at": row.created_at,
    }


def list_parameter_sets(db: Session, project_id: int, actor: User) -> list[dict]:
    """列出项目参数快照，按创建时间倒序返回。"""
    get_project_or_404(db, project_id, actor)
    rows = db.query(AsrParameterSet).filter(AsrParameterSet.project_id == project_id).order_by(
        AsrParameterSet.created_at.desc(),
    ).limit(500).all()
    return [_dump_parameter_set(row) for row in rows]


def _next_daily(now: datetime, timezone_name: str, local_time: str) -> datetime:
    """按 IANA 时区计算下一次每日触发时间并转换为 UTC。"""
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise bad_request("时区名称无效") from None
    hour, minute = (int(item) for item in local_time.split(":"))
    local_now = now.astimezone(zone)
    candidate = datetime.combine(local_now.date(), time(hour, minute), tzinfo=zone)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _parse_aware_datetime(value: str) -> datetime:
    """解析带显式时区偏移的一次性执行时间并转换到 UTC。"""
    try:
        parsed_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise bad_request("一次性计划需要有效的 scheduled_at") from None
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise bad_request("一次性计划时间必须带时区偏移")
    return parsed_time.astimezone(timezone.utc)


def create_schedule(db: Session, body: ScheduleCreate, actor: User) -> dict:
    """校验固定资源范围后创建一次性或每日夜间计划。"""
    _require_editor(db, body.project_id, actor)
    resolved_slots = resolve_task_slots(db, body.project_id, body.model_slots, actor) if body.model_slots else None
    if resolved_slots is not None:
        from app.features.asr_evaluation.models import AsrAudio

        asr_slots = [item for item in resolved_slots if item["slot"] != "DIARIZATION"]
        if {item["slot"] for item in asr_slots} != {"TEST", "REFERENCE_A", "REFERENCE_B"}:
            raise bad_request("夜间计划必须配置待测、参考 A 和参考 B")
        connection_ids = [item["connection"].id for item in asr_slots]
        if len(set(connection_ids)) != 3:
            raise bad_request("计划的三个 ASR 槽位必须选择不同模型")
        if len({item["resource"].id for item in asr_slots}) != 3:
            raise bad_request("计划的待测模型与两个参考模型必须是三个不同的授权模型资源")
        parameter_set = next(item["parameter_set"] for item in asr_slots if item["slot"] == "TEST")
        audio_count = db.query(AsrAudio.id).filter(
            AsrAudio.project_id == body.project_id, AsrAudio.id.in_(body.audio_ids),
        ).count()
        if len(set(body.audio_ids)) != len(body.audio_ids) or audio_count != len(body.audio_ids):
            raise not_found("计划引用的音频资源不存在或重复")
    else:
        if body.connection_ids is None or body.parameter_set_id is None:
            raise bad_request("计划模型槽位配置缺失")
        _validate_schedule_assets(db, body.project_id, body.audio_ids, body.connection_ids, body.parameter_set_id)
        resolved_slots = []
        connection_ids = body.connection_ids
        parameter_set = db.get(AsrParameterSet, body.parameter_set_id)
    now = datetime.now(timezone.utc)
    if body.schedule_type == "ONCE":
        run_at = _parse_aware_datetime(body.scheduled_at or "")
        if run_at <= now:
            raise bad_request("计划执行时间必须晚于当前时间")
        next_run = run_at
    else:
        next_run = _next_daily(now, body.timezone, body.local_time)
    row = AsrSchedule(
        project_id=body.project_id, name=body.name.strip(), audio_ids=sorted(set(body.audio_ids)),
        connection_ids=connection_ids, parameter_set_id=parameter_set.id,
        schedule_type=body.schedule_type, timezone=body.timezone, local_time=body.local_time,
        scheduled_at=next_run if body.schedule_type == "ONCE" else None, next_run_at=next_run,
        created_by=actor.id,
    )
    db.add(row)
    db.flush()
    for item in resolved_slots:
        db.add(ModelTaskSlot(
            task_kind="ASR_SCHEDULE", task_id=row.id, slot=item["slot"],
            resource_id=item["resource"].id, revision_id=item["revision"].id,
            profile_id=item["profile"].id, legacy_connection_id=item["connection"].id,
        ))
    db.commit()
    db.refresh(row)
    return _dump_schedule(row)


def _validate_schedule_assets(db: Session, project_id: int, audio_ids: list[int], connection_ids: list[int], parameter_set_id: int) -> None:
    """确保计划固定绑定同项目的音频、三角色连接与待测参数版本。"""
    if len(set(audio_ids)) != len(audio_ids) or len(set(connection_ids)) != 3:
        raise bad_request("音频和三方接口不能重复")
    audios = db.query(AsrAudio).filter(AsrAudio.project_id == project_id, AsrAudio.id.in_(audio_ids)).count()
    connections = db.query(AsrConnection).filter(
        AsrConnection.project_id == project_id, AsrConnection.id.in_(connection_ids), AsrConnection.enabled.is_(True),
        AsrConnection.task_type == "TRANSCRIPTION",
    ).all()
    parameter_set = db.get(AsrParameterSet, parameter_set_id)
    if audios != len(audio_ids) or len(connections) != 3:
        raise not_found("计划引用的音频或连接不存在")
    if sum(row.role == "TEST" for row in connections) != 1 or sum(row.role == "REFERENCE" for row in connections) != 2:
        raise bad_request("计划必须包含一个待测连接和两个参考连接")
    test_connection = next(row for row in connections if row.role == "TEST")
    if parameter_set is None or parameter_set.project_id != project_id or parameter_set.connection_id != test_connection.id:
        raise not_found("参数方案不属于所选待测连接")


def _dump_schedule(row: AsrSchedule) -> dict:
    """序列化计划和下次触发事实。"""
    return {
        "id": row.id, "project_id": row.project_id, "name": row.name,
        "audio_ids": row.audio_ids, "connection_ids": row.connection_ids,
        "parameter_set_id": row.parameter_set_id, "schedule_type": row.schedule_type,
        "timezone": row.timezone, "local_time": row.local_time, "scheduled_at": row.scheduled_at,
        "next_run_at": row.next_run_at, "enabled": row.enabled,
        "last_trigger_status": row.last_trigger_status, "last_trigger_at": row.last_trigger_at,
    }


def list_schedules(db: Session, project_id: int, actor: User) -> list[dict]:
    """列出项目计划及已保存的下次触发时间。"""
    get_project_or_404(db, project_id, actor)
    rows = db.query(AsrSchedule).filter(AsrSchedule.project_id == project_id).order_by(AsrSchedule.id.desc()).limit(200).all()
    result = []
    for row in rows:
        item = _dump_schedule(row)
        item["model_slots"] = [{
            "slot": slot.slot, "resource_id": slot.resource_id, "revision_id": slot.revision_id,
            "profile_id": slot.profile_id, "legacy_connection_id": slot.legacy_connection_id,
        } for slot in db.query(ModelTaskSlot).filter(
            ModelTaskSlot.task_kind == "ASR_SCHEDULE", ModelTaskSlot.task_id == row.id,
        ).order_by(ModelTaskSlot.id).all()]
        result.append(item)
    return result


def update_schedule(db: Session, schedule_id: int, *, enabled: bool, actor: User) -> dict:
    """暂停或恢复计划；恢复时重算过期的每日触发时间，避免意外补跑。"""
    row = db.get(AsrSchedule, schedule_id)
    if row is None:
        raise not_found("评测计划不存在")
    _require_editor(db, row.project_id, actor)
    now = datetime.now(timezone.utc)
    next_run = _as_utc(row.next_run_at)
    if enabled and row.schedule_type == "ONCE" and (next_run is None or next_run <= now):
        raise bad_request("一次性计划的执行时间已过，不能恢复；请新建计划")
    if enabled and row.schedule_type == "DAILY" and next_run is not None and next_run <= now:
        row.next_run_at = _next_daily(now, row.timezone, row.local_time)
    row.enabled = enabled
    db.commit()
    db.refresh(row)
    return _dump_schedule(row)


def _as_utc(value: datetime | None) -> datetime | None:
    """把数据库返回的带时区或无时区时间统一解释成 UTC。"""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


__all__ = [
    "_dump_audio", "_dump_connection", "_dump_parameter_set", "_dump_schedule",
    "_validate_schedule_assets", "_parse_aware_datetime", "check_audio", "create_audio", "create_connections", "create_parameter_set", "import_audios",
    "create_schedule", "ensure_audio_version", "list_audios", "list_connections", "list_parameter_sets", "list_schedules", "update_audio",
    "update_schedule",
]
