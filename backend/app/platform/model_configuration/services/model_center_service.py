"""统一模型中心服务：资源权限、修订、参数方案、兼容投影及授权。"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.http.errors import bad_request, forbidden, not_found
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import OrganizationMember, User
from app.core.models.project import Project
from app.core.security.crypto import decrypt_secret, encrypt_secret
from app.core.security.roles import PROJECT_ROLE_EDITOR, has_project_role, is_platform_admin, project_role_for
from app.platform.model_configuration.models import (
    ModelCredential, ModelDefaultBinding, ModelLegacyBinding, ModelParameterProfile,
    ModelResource, ModelResourceGrant, ModelRevision, ModelValidationRun,
)
from app.platform.model_configuration.center_schemas import ModelProfileInput, ModelResourceCreate
from app.platform.model_configuration.schemas import normalize_provider
from app.platform.projects.services.access_service import get_project_or_404

_SUPPORTED_ADAPTERS = {
    "TEXT_GENERATION": {"openai-compatible-chat": "OpenAI 兼容聊天"},
    "ASR": {"generic-json-http": "通用 JSON HTTP 转写",
            "siliconflow-audio-transcriptions": "硅基流动音频文件转写"},
    "DIARIZATION": {"generic-json-http": "通用 JSON HTTP 说话人分段"},
}
_ADAPTER_CAPABILITIES = {
    ("TEXT_GENERATION", "openai-compatible-chat"): {"text_generation"},
    ("ASR", "generic-json-http"): {
        "transcription", "timestamped_segments", "word_timestamps", "native_speaker_labels",
        "channel_metadata", "confidence",
    },
    ("ASR", "siliconflow-audio-transcriptions"): {
        "transcription", "timestamped_segments", "native_speaker_labels",
    },
    ("DIARIZATION", "generic-json-http"): {
        "speaker_intervals", "speaker_text_segments", "native_speaker_labels", "channel_metadata",
        "confidence", "overlap_intervals",
    },
}
_SENSITIVE_HEADER = re.compile(r"(authorization|auth|token|secret|password|api[-_]?key|cookie|signature)", re.I)
_SENSITIVE_IMPORT_KEY = re.compile(r"(authorization|access[-_]?token|auth[-_]?token|secret|password|api[-_]?key|cookie|credential|private[-_]?key)", re.I)
_SAFE_MAPPING_KEYS = {
    "text_pointer", "segments_pointer", "segment_text_pointer", "segment_id_pointer", "speaker_pointer",
    "confidence_pointer", "channel_pointer", "start_pointer", "end_pointer", "time_unit",
    "word_times_pointer", "sample_rate_pointer", "timeline", "model_version", "task_id_pointer",
    "status_pointer", "result_pointer", "success_values", "failure_values",
}


def adapter_catalog() -> dict:
    """仅返回已注册的调用适配器，不将供应商名误当成协议支持声明。"""
    return {
        "providers": [
            {"value": "openai", "label": "OpenAI"}, {"value": "openai-compatible", "label": "OpenAI 兼容"},
            {"value": "deepseek", "label": "DeepSeek"}, {"value": "qwen", "label": "通义千问"},
            {"value": "anthropic", "label": "Anthropic"}, {"value": "custom", "label": "其他供应商"},
            {"value": "siliconflow", "label": "硅基流动"},
        ],
        "categories": [
            {"value": "TEXT_GENERATION", "label": "文本推理"},
            {"value": "ASR", "label": "ASR 转写"},
            {"value": "DIARIZATION", "label": "说话人分段"},
        ],
        "adapters": [
            {"category": category, "value": key, "label": label,
             "capabilities": sorted(_ADAPTER_CAPABILITIES.get((category, key), set()))}
            for category, items in _SUPPORTED_ADAPTERS.items() for key, label in items.items()
        ],
        "execution_modes": ["SYNC", "ASYNC"],
    }


def _require_platform_admin(actor: User) -> None:
    """限制平台共享资源、组织共享授权与平台级默认策略的管理入口。"""
    if not is_platform_admin(actor):
        raise forbidden("仅平台管理员可管理平台共享模型")


def _require_project_editor(db: Session, project_id: int, actor: User) -> Project:
    """统一使用项目可见性与编辑角色判定，越权项目保持 404 隐藏。"""
    project = get_project_or_404(db, project_id, actor)
    if not has_project_role(project_role_for(db, project, actor), PROJECT_ROLE_EDITOR):
        raise forbidden("需要项目编辑者权限")
    return project


def _require_resource_editor(db: Session, resource: ModelResource, actor: User) -> None:
    """平台资源仅管理员可改，项目资源仅所属项目编辑者可改。"""
    if resource.visibility == "PLATFORM":
        _require_platform_admin(actor)
    elif resource.project_id is None:
        raise forbidden("模型资源范围配置无效")
    else:
        _require_project_editor(db, resource.project_id, actor)


def _supported_adapter(category: str, adapter_key: str) -> None:
    """拒绝未注册协议，避免把可选供应商标签误标为可调用。"""
    if adapter_key not in _SUPPORTED_ADAPTERS.get(category, {}):
        raise bad_request("该类别尚未实现所选调用适配器")


def _validate_capabilities(category: str, adapter_key: str, capabilities: list[str]) -> None:
    """能力声明只能选择当前适配器能标准化处理的字段。"""
    supported = _ADAPTER_CAPABILITIES.get((category, adapter_key), set())
    if len(set(capabilities)) != len(capabilities) or any(item not in supported for item in capabilities):
        raise bad_request("能力声明包含当前调用适配器未实现的能力")


def _endpoint(value: str) -> tuple[str, str]:
    """检查 HTTP 地址并生成移除用户信息、查询串和片段的展示地址。"""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise bad_request("模型接口地址必须是有效的 HTTP(S) 地址，且不能包含用户信息或片段")
    display = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:500]
    return value.strip(), display


def _validate_connection_config(category: str, adapter: str, config: dict) -> dict:
    """校验已实现适配器所需的连接字段，不接受未生效的参数。"""
    _supported_adapter(category, adapter)
    if category == "TEXT_GENERATION":
        return dict(config)
    if adapter != "siliconflow-audio-transcriptions" and config.get("request_encoding") not in {None, "json"}:
        raise bad_request("所选适配器不支持该请求编码")
    if adapter == "siliconflow-audio-transcriptions":
        if config.get("async_config") or config.get("method", "POST") != "POST":
            raise bad_request("硅基流动文件转写仅支持同步 POST 请求")
        config["request_encoding"] = "multipart"
        config["request_template"] = {
            "audio_url": "{{audio.url}}", "model": "{{connection.model_id}}",
            "parameters": "{{experiment.parameters}}",
        }
        config.setdefault("response_mapping", {"text_pointer": "/text"})
        for key, default, maximum in (("max_audio_bytes", 50 * 1024 * 1024, 50 * 1024 * 1024),
                                      ("audio_download_timeout_seconds", 60, 180)):
            value = config.setdefault(key, default)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise bad_request("音频下载大小或超时配置超出范围")
    config.setdefault("method", "POST")
    config.setdefault("headers", {})
    config.setdefault("timeout_seconds", 180)
    config.setdefault("max_response_bytes", 8_000_000)
    config.setdefault("async_config", None)
    template = config.get("request_template")
    mapping = config.get("response_mapping")
    if not isinstance(template, dict) or not isinstance(mapping, dict):
        raise bad_request("ASR 适配器配置需包含 JSON 请求模板和响应映射")
    template_text = json.dumps(template, ensure_ascii=False)
    if "{{audio.url}}" not in template_text or "{{experiment.parameters}}" not in template_text:
        raise bad_request("ASR 请求模板必须包含音频 URL 和参数方案变量")
    if category == "ASR" and not isinstance(mapping.get("text_pointer"), str):
        raise bad_request("ASR 响应映射必须声明 text_pointer")
    if category == "DIARIZATION":
        if any(not isinstance(mapping.get(key), str) or not mapping[key].startswith("/")
               for key in ("segments_pointer", "start_pointer", "end_pointer", "speaker_pointer")):
            raise bad_request("说话人分段需映射 segments、start、end 和 speaker 字段")
    headers = config.get("headers", {})
    if not isinstance(headers, dict) or len(headers) > 30:
        raise bad_request("请求头配置无效")
    for key, value in headers.items():
        if _SENSITIVE_HEADER.search(str(key)) or len(str(key)) > 100 or len(str(value)) > 2000:
            raise bad_request("敏感请求头必须通过加密凭据单独配置")
    if "async_config" in config and config["async_config"] is not None and not isinstance(config["async_config"], dict):
        raise bad_request("异步任务配置必须是对象")
    return dict(config)


def _resource_key(category: str, visibility: str) -> str:
    """生成平台资源稳定授权 ID 或项目私有资源键。"""
    prefix = "model" if category == "TEXT_GENERATION" and visibility == "PLATFORM" else "resource"
    return f"{prefix}_{uuid4().hex}"


def _next_profile_version(db: Session, resource_id: int, revision_id: int, name: str) -> int:
    """为同一资源与方案名称分配单调递增版本。"""
    latest = db.query(ModelParameterProfile.version).filter(
        ModelParameterProfile.resource_id == resource_id, ModelParameterProfile.name == name,
        ModelParameterProfile.revision_id == revision_id,
    ).order_by(ModelParameterProfile.version.desc()).first()
    return (latest[0] if latest else 0) + 1


def _safe_config(category: str, config: dict | None) -> dict:
    """回显非敏感协议字段，屏蔽请求头值和未知响应映射字段。"""
    value = dict(config or {})
    headers = value.get("headers") or {}
    safe = {
        "method": value.get("method", "POST"),
        "headers": {str(key): "[已配置]" for key in headers} if isinstance(headers, dict) else {},
        "request_template": {"configured": bool(value.get("request_template"))},
        "timeout_seconds": value.get("timeout_seconds", 180),
        "max_response_bytes": value.get("max_response_bytes", 8_000_000),
        "async_config": {"configured": True} if value.get("async_config") else None,
    }
    if value.get("request_encoding") == "multipart":
        safe.update(request_encoding="multipart", max_audio_bytes=value.get("max_audio_bytes"),
                    audio_download_timeout_seconds=value.get("audio_download_timeout_seconds"))
    mapping = value.get("response_mapping")
    if isinstance(mapping, dict):
        safe["response_mapping"] = {key: item for key, item in mapping.items() if key in _SAFE_MAPPING_KEYS}
    return safe


def _safe_parameter_schema(schema: list[dict] | None) -> list[dict]:
    """只回显参数定义中的已知展示字段，防止元数据夹带秘密。"""
    allowed = {"path", "display_name", "value_type", "minimum", "maximum", "choices", "description",
               "source", "unit", "required", "control", "mutable", "verified"}
    return [{key: value for key, value in item.items() if key in allowed}
            for item in (schema or []) if isinstance(item, dict)]


def _contains_sensitive_import_field(value) -> bool:
    """递归检测导入条目中的秘密字段；凭据请求头名称不是秘密值。"""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in {"credential_header", "secret_header"}:
                continue
            if _SENSITIVE_IMPORT_KEY.search(str(key)) or _contains_sensitive_import_field(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_sensitive_import_field(item) for item in value)
    return False


def _dump_profile(row: ModelParameterProfile) -> dict:
    """序列化参数版本；参数方案不包含连接密文。"""
    return {"id": row.id, "resource_id": row.resource_id, "revision_id": row.revision_id,
            "name": row.name, "version": row.version, "values": row.parameter_values or {},
            "definitions": _safe_parameter_schema(row.definitions), "created_at": row.created_at}


def _dump_revision(db: Session, row: ModelRevision) -> dict:
    """构建不含端点密文、凭据密文和请求头值的修订响应。"""
    credential = db.query(ModelCredential.id).filter(ModelCredential.revision_id == row.id).first()
    profiles = db.query(ModelParameterProfile).filter(
        ModelParameterProfile.resource_id == row.resource_id, ModelParameterProfile.revision_id == row.id,
    ).order_by(ModelParameterProfile.name, ModelParameterProfile.version.desc()).all()
    return {
        "id": row.id, "resource_id": row.resource_id, "version": row.version,
        "provider": row.provider, "adapter_key": row.adapter_key, "model_name": row.model_name,
        "endpoint_display": row.endpoint_display, "config": _safe_config("", row.config_json),
        "capabilities": row.capabilities or [], "parameter_schema": _safe_parameter_schema(row.parameter_schema),
        "enabled": bool(row.enabled), "has_credential": credential is not None,
        "profiles": [_dump_profile(item) for item in profiles], "created_at": row.created_at,
    }


def _dump_resource(db: Session, row: ModelResource) -> dict:
    """构建模型资源摘要和可用修订，诊断状态来自最近一次显式检查。"""
    revisions = db.query(ModelRevision).filter(ModelRevision.resource_id == row.id).order_by(
        ModelRevision.version.desc(), ModelRevision.id.desc(),
    ).all()
    current = next((item for item in revisions if item.id == row.current_revision_id), None)
    latest_check = db.execute(
        text("SELECT id, status, result_json, created_at FROM model_validation_run WHERE resource_id=:id ORDER BY id DESC LIMIT 1"),
        {"id": row.id},
    ).mappings().first()
    diagnostic = None
    if latest_check:
        result = latest_check["result_json"] or {}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                result = {}
        diagnostic = {"id": latest_check["id"], "status": latest_check["status"],
                      "message": (result or {}).get("message"), "checked_at": latest_check["created_at"]}
    defaults = db.query(ModelDefaultBinding).filter(ModelDefaultBinding.resource_id == row.id).all()
    grants = db.query(ModelResourceGrant.project_id).filter(ModelResourceGrant.resource_id == row.id).all()
    return {
        "id": row.id, "resource_key": row.resource_key, "category": row.category,
        "visibility": row.visibility, "project_id": row.project_id, "display_name": row.display_name,
        "status": row.status, "current_revision_id": row.current_revision_id,
        "current_revision": _dump_revision(db, current) if current else None,
        "revisions": [_dump_revision(db, item) for item in revisions], "diagnostic": diagnostic,
        "defaults": [{"purpose": item.purpose, "project_id": item.project_id,
                      "automatic_fallback": item.automatic_fallback,
                      "fallback_resource_ids": item.fallback_resource_ids or []} for item in defaults],
        "grant_project_ids": [item[0] for item in grants],
    }


def _profile_defaults(category: str, profile: dict) -> tuple[dict, list]:
    """为旧 LLM 运行时生成其仅支持的文本参数投影。"""
    values = dict(profile.get("values") or {})
    if category == "TEXT_GENERATION":
        temperature = values.get("temperature", 0.2)
        max_tokens = values.get("max_tokens", 4096)
        if not isinstance(temperature, (int, float)) or not 0 <= float(temperature) <= 2:
            raise bad_request("文本模型 temperature 必须在 0 到 2 之间")
        if not isinstance(max_tokens, int) or not 1 <= max_tokens <= 1_000_000:
            raise bad_request("文本模型 max_tokens 必须是正整数")
        return {"temperature": float(temperature), "max_tokens": max_tokens}, [
            {"path": "temperature", "display_name": "采样温度", "value_type": "number", "minimum": 0, "maximum": 2},
            {"path": "max_tokens", "display_name": "最大输出 Token", "value_type": "integer", "minimum": 1},
        ]
    return values, list(profile.get("definitions") or [])


def _validated_profile(category: str, profile: dict, schema: list[dict]) -> tuple[dict, list]:
    """校验 ASR 参数类型和秘密隔离，并以修订定义补足参数方案定义。"""
    values, definitions = _profile_defaults(category, profile)
    if category in {"ASR", "DIARIZATION"}:
        definitions = definitions or list(schema or [])
        for definition in definitions:
            if (not isinstance(definition, dict) or not isinstance(definition.get("path"), str)
                    or definition["path"] and not definition["path"].startswith("/")
                    or definition.get("value_type") not in {"string", "integer", "number", "boolean", "object", "array"}):
                raise bad_request("参数定义必须使用 JSON Pointer 路径和受支持的数据类型")
            for bound in ("minimum", "maximum"):
                if definition.get(bound) is not None and (
                    not isinstance(definition[bound], (int, float)) or isinstance(definition[bound], bool)
                ):
                    raise bad_request("参数范围必须是数字")
            if definition.get("choices") is not None and not isinstance(definition["choices"], list):
                raise bad_request("参数枚举必须是数组")
        from app.features.asr_evaluation.services.assets_service import _validate_parameters

        _validate_parameters(values, definitions)
    return values, definitions


def _write_revision(db: Session, resource: ModelResource, *, provider: str, adapter_key: str,
                    model_name: str, endpoint_ciphertext: str | None, endpoint_display: str | None,
                    config: dict, capabilities: list[str], parameter_schema: list[dict], enabled: bool,
                    created_by: int | None, legacy_connection_id: int | None = None) -> ModelRevision:
    """在统一入口创建不可变修订并更新逻辑资源的当前修订指针。"""
    latest = db.query(ModelRevision.version).filter(ModelRevision.resource_id == resource.id).order_by(
        ModelRevision.version.desc(),
    ).first()
    revision = ModelRevision(
        resource_id=resource.id, version=(latest[0] if latest else 0) + 1,
        provider=provider, adapter_key=adapter_key, model_name=model_name,
        endpoint_ciphertext=endpoint_ciphertext, endpoint_display=endpoint_display,
        config_json=config, capabilities=capabilities, parameter_schema=parameter_schema,
        enabled=enabled, legacy_connection_id=legacy_connection_id, created_by=created_by,
    )
    db.add(revision)
    db.flush()
    resource.current_revision_id = revision.id
    resource.status = "ACTIVE" if enabled else "DISABLED"
    return revision


def _write_profile(db: Session, resource: ModelResource, revision: ModelRevision, *, name: str,
                   values: dict, definitions: list, created_by: int | None,
                   legacy_parameter_set_id: int | None = None) -> ModelParameterProfile:
    """创建独立参数方案的下一版本，不修改已被任务引用的历史方案。"""
    profile = ModelParameterProfile(
        resource_id=resource.id, revision_id=revision.id, name=name,
        version=_next_profile_version(db, resource.id, revision.id, name),
        parameter_values=values, definitions=definitions, created_by=created_by,
        legacy_parameter_set_id=legacy_parameter_set_id,
    )
    db.add(profile)
    db.flush()
    return profile


def sync_legacy_text_configuration(db: Session, row: ModelConfiguration) -> None:
    """将旧文本模型配置写入口同步到唯一规范资源，保留整数 ID 与 domain_id。"""
    resource = db.query(ModelResource).filter(
        ModelResource.resource_key == row.domain_id,
    ).one_or_none()
    if resource is None:
        resource = ModelResource(
            resource_key=row.domain_id, category="TEXT_GENERATION", visibility="PLATFORM",
            display_name=row.label, status="ACTIVE" if row.is_enabled else "DISABLED",
            legacy_model_id=row.id, created_by=row.created_by,
        )
        db.add(resource)
        db.flush()
    else:
        resource.display_name = row.label
        resource.legacy_model_id = row.id
    revision = _write_revision(
        db, resource, provider=row.provider,
        adapter_key="unregistered:anthropic-native" if row.provider == "anthropic" else "openai-compatible-chat",
        model_name=row.model_name, endpoint_ciphertext=None, endpoint_display=row.api_base,
        config={"timeout": row.timeout, "legacy_model_id": row.id},
        capabilities=["text_generation"],
        parameter_schema=[{"path": "temperature", "display_name": "采样温度", "value_type": "number", "minimum": 0, "maximum": 2},
                          {"path": "max_tokens", "display_name": "最大输出 Token", "value_type": "integer", "minimum": 1}],
        enabled=bool(row.is_enabled), created_by=row.created_by,
    )
    if row.api_key_encrypted:
        db.add(ModelCredential(revision_id=revision.id, ciphertext=row.api_key_encrypted,
                               cipher_format="model-configuration-fernet", header_name="Authorization"))
    profile = _write_profile(
        db, resource, revision, name="默认参数", values={"temperature": row.temperature, "max_tokens": row.max_tokens},
        definitions=revision.parameter_schema, created_by=row.created_by,
    )
    db.add(ModelLegacyBinding(
        legacy_kind="MODEL_REVISION", legacy_id=revision.id, resource_id=resource.id, revision_id=revision.id,
        legacy_domain_id=row.domain_id,
    ))
    if db.query(ModelLegacyBinding).filter(
        ModelLegacyBinding.legacy_kind == "MODEL_CONFIGURATION", ModelLegacyBinding.legacy_id == row.id,
    ).first() is None:
        db.add(ModelLegacyBinding(
            legacy_kind="MODEL_CONFIGURATION", legacy_id=row.id, resource_id=resource.id,
            revision_id=revision.id, legacy_domain_id=row.domain_id,
        ))
    if row.is_default:
        _sync_text_default(db, row, resource, revision, profile)


def _sync_text_default(db: Session, legacy_row: ModelConfiguration, resource: ModelResource,
                       revision: ModelRevision, profile: ModelParameterProfile) -> None:
    """同步旧文本默认语义到用途绑定，保留旧备用整数 ID 的同类别顺序。"""
    current = db.query(ModelDefaultBinding).filter(
        ModelDefaultBinding.category == "TEXT_GENERATION", ModelDefaultBinding.purpose == "TEXT_INFERENCE",
        ModelDefaultBinding.project_id.is_(None),
    ).first()
    if current is None:
        current = ModelDefaultBinding(category="TEXT_GENERATION", purpose="TEXT_INFERENCE")
        db.add(current)
    fallback_ids = []
    for legacy_id in legacy_row.fallback_model_ids or []:
        binding = db.query(ModelLegacyBinding).filter(
            ModelLegacyBinding.legacy_kind == "MODEL_CONFIGURATION", ModelLegacyBinding.legacy_id == legacy_id,
        ).first()
        if binding is not None and binding.resource_id != resource.id:
            fallback_ids.append(binding.resource_id)
    current.resource_id = resource.id
    current.revision_id = revision.id
    current.profile_id = profile.id
    current.fallback_resource_ids = fallback_ids
    current.automatic_fallback = bool(fallback_ids)


def sync_legacy_text_default(db: Session, actor_id: int | None = None) -> None:
    """把旧表当前默认值同步到 TEXT_INFERENCE；无启用模型时清除失效默认。"""
    legacy = db.query(ModelConfiguration).filter(ModelConfiguration.is_default.is_(True)).first()
    current = db.query(ModelDefaultBinding).filter(
        ModelDefaultBinding.category == "TEXT_GENERATION", ModelDefaultBinding.purpose == "TEXT_INFERENCE",
        ModelDefaultBinding.project_id.is_(None),
    ).first()
    if legacy is None:
        if current is not None:
            db.delete(current)
        return
    binding = db.query(ModelLegacyBinding).filter(
        ModelLegacyBinding.legacy_kind == "MODEL_CONFIGURATION", ModelLegacyBinding.legacy_id == legacy.id,
    ).first()
    if binding is None:
        sync_legacy_text_configuration(db, legacy)
        binding = db.query(ModelLegacyBinding).filter(
            ModelLegacyBinding.legacy_kind == "MODEL_CONFIGURATION", ModelLegacyBinding.legacy_id == legacy.id,
        ).first()
    resource = db.get(ModelResource, binding.resource_id) if binding else None
    if resource is None:
        return
    revision = db.query(ModelRevision).filter(ModelRevision.resource_id == resource.id).order_by(
        ModelRevision.version.desc(),
    ).first()
    profile = db.query(ModelParameterProfile).filter(
        ModelParameterProfile.resource_id == resource.id,
        ModelParameterProfile.revision_id == revision.id if revision else False,
    ).order_by(ModelParameterProfile.version.desc()).first()
    if revision is not None and profile is not None:
        _sync_text_default(db, legacy, resource, revision, profile)
        if actor_id is not None:
            current = db.query(ModelDefaultBinding).filter(
                ModelDefaultBinding.category == "TEXT_GENERATION", ModelDefaultBinding.purpose == "TEXT_INFERENCE",
                ModelDefaultBinding.project_id.is_(None),
            ).first()
            if current is not None:
                current.updated_by = actor_id


def sync_legacy_asr_connection(db: Session, row) -> None:
    """将旧 ASR 连接写入口纳入统一资源目录，角色只记录在历史兼容映射。"""
    from app.features.asr_evaluation.models import AsrConnection

    connection = row if isinstance(row, AsrConnection) else db.get(AsrConnection, row)
    if connection is None:
        return
    category = "DIARIZATION" if connection.task_type == "DIARIZATION" else "ASR"
    binding = db.query(ModelLegacyBinding).filter(
        ModelLegacyBinding.legacy_kind == "ASR_CONNECTION", ModelLegacyBinding.legacy_id == connection.id,
    ).first()
    if binding is not None:
        return
    resource = db.query(ModelResource).join(ModelRevision, ModelRevision.resource_id == ModelResource.id).filter(
        ModelResource.project_id == connection.project_id, ModelResource.category == category,
        ModelResource.display_name == connection.name,
    ).order_by(ModelRevision.version.desc()).first()
    if resource is None:
        resource = ModelResource(
            resource_key=_resource_key(category, "PROJECT"), category=category, visibility="PROJECT",
            project_id=connection.project_id, display_name=connection.name,
            status="ACTIVE" if connection.enabled else "DISABLED", created_by=connection.created_by,
        )
        db.add(resource)
        db.flush()
    config = dict(connection.config_json or {})
    provider = connection.provider_id or "custom"
    adapter_key = "generic-json-http" if provider == "generic-json" else f"unregistered:{provider}"
    mapping = config.get("response_mapping") if isinstance(config.get("response_mapping"), dict) else {}
    capabilities = ["transcription"] if category == "ASR" else ["speaker_intervals"]
    if mapping.get("segments_pointer"):
        capabilities.append("timestamped_segments")
    if mapping.get("speaker_pointer"):
        capabilities.append("native_speaker_labels")
    revision = _write_revision(
        db, resource, provider=provider, adapter_key=adapter_key, model_name=connection.model_id,
        endpoint_ciphertext=connection.endpoint_ciphertext, endpoint_display=connection.endpoint_display,
        config=config, capabilities=capabilities, parameter_schema=config.get("parameter_definitions") or [],
        enabled=bool(connection.enabled), created_by=connection.created_by, legacy_connection_id=connection.id,
    )
    if connection.secret_ciphertext:
        db.add(ModelCredential(revision_id=revision.id, ciphertext=connection.secret_ciphertext,
                               cipher_format="shared-fernet", header_name=connection.secret_header))
    db.add(ModelLegacyBinding(
        legacy_kind="ASR_CONNECTION", legacy_id=connection.id, resource_id=resource.id, revision_id=revision.id,
        legacy_role=connection.role, legacy_task_type=connection.task_type,
    ))


def sync_legacy_asr_parameter_set(db: Session, row) -> None:
    """将旧 ASR 参数方案写入口映射到资源修订关联的独立参数版本。"""
    from app.features.asr_evaluation.models import AsrParameterSet

    parameter_set = row if isinstance(row, AsrParameterSet) else db.get(AsrParameterSet, row)
    if parameter_set is None:
        return
    existing = db.query(ModelLegacyBinding).filter(
        ModelLegacyBinding.legacy_kind == "ASR_PARAMETER_SET", ModelLegacyBinding.legacy_id == parameter_set.id,
    ).first()
    if existing is not None:
        return
    connection_binding = db.query(ModelLegacyBinding).filter(
        ModelLegacyBinding.legacy_kind == "ASR_CONNECTION", ModelLegacyBinding.legacy_id == parameter_set.connection_id,
    ).first()
    if connection_binding is None:
        return
    profile = ModelParameterProfile(
        resource_id=connection_binding.resource_id, revision_id=connection_binding.revision_id,
        name=parameter_set.name, version=parameter_set.version,
        parameter_values=parameter_set.parameters or {}, definitions=parameter_set.definitions or [],
        legacy_parameter_set_id=parameter_set.id, created_by=parameter_set.created_by,
    )
    db.add(profile)
    db.flush()
    db.add(ModelLegacyBinding(
        legacy_kind="ASR_PARAMETER_SET", legacy_id=parameter_set.id,
        resource_id=connection_binding.resource_id, revision_id=connection_binding.revision_id,
        legacy_task_type=connection_binding.legacy_task_type,
    ))


def _create_legacy_projection(
    db: Session, *, resource: ModelResource, revision: ModelRevision, profile: ModelProfileInput, credential: str,
) -> None:
    """创建旧运行时兼容投影；所有新建配置仍由模型中心服务统一落库。"""
    from app.features.asr_evaluation.models import AsrConnection, AsrParameterSet
    from app.platform.model_configuration.services.model_config_service import encrypt_api_key

    values, definitions = _validated_profile(resource.category, profile.model_dump(), revision.parameter_schema or [])
    if resource.category == "TEXT_GENERATION":
        row = ModelConfiguration(
            domain_id=resource.resource_key, label=resource.display_name,
            provider=normalize_provider(revision.provider),
            api_base=decrypt_secret(revision.endpoint_ciphertext) or revision.endpoint_display or "",
            api_key_encrypted=encrypt_api_key(credential), model_name=revision.model_name,
            temperature=values["temperature"], max_tokens=values["max_tokens"],
            timeout=int((revision.config_json or {}).get("timeout", 60)),
            is_enabled=revision.enabled, is_default=False, fallback_model_ids=[], sort_order=0,
            created_by=resource.created_by,
        )
        db.add(row)
        db.flush()
        resource.legacy_model_id = row.id
        db.add(ModelLegacyBinding(
            legacy_kind="MODEL_CONFIGURATION", legacy_id=row.id, resource_id=resource.id,
            revision_id=revision.id, legacy_domain_id=resource.resource_key,
        ))
        return

    if resource.visibility != "PROJECT" or resource.project_id is None:
        return

    task_type = "DIARIZATION" if resource.category == "DIARIZATION" else "TRANSCRIPTION"
    config = dict(revision.config_json or {})
    credential_row = db.query(ModelCredential).filter(ModelCredential.revision_id == revision.id).first()
    config["credential_header"] = credential_row.header_name if credential_row else "Authorization"
    connection = AsrConnection(
        project_id=resource.project_id, name=resource.display_name, role=None, task_type=task_type,
        provider_id=revision.provider, model_id=revision.model_name, version=revision.version,
        endpoint_ciphertext=revision.endpoint_ciphertext or encrypt_secret(revision.endpoint_display or ""),
        endpoint_display=revision.endpoint_display or "", config_json=config,
        secret_ciphertext=encrypt_secret(credential) if credential else (credential_row.ciphertext if credential_row else None),
        secret_header=(credential_row.header_name if credential_row else None) or "Authorization",
        enabled=revision.enabled, created_by=resource.created_by,
    )
    db.add(connection)
    db.flush()
    revision.legacy_connection_id = connection.id
    db.add(ModelLegacyBinding(
        legacy_kind="ASR_CONNECTION", legacy_id=connection.id, resource_id=resource.id,
        revision_id=revision.id, legacy_task_type=task_type,
    ))
    parameter_set = AsrParameterSet(
        project_id=resource.project_id, connection_id=connection.id,
        name=profile.name, version=1, parameters=values, definitions=definitions, created_by=resource.created_by,
    )
    db.add(parameter_set)
    db.flush()
    profile_row = db.query(ModelParameterProfile).filter(
        ModelParameterProfile.resource_id == resource.id, ModelParameterProfile.revision_id == revision.id,
        ModelParameterProfile.name == profile.name.strip(),
    ).order_by(ModelParameterProfile.version.desc()).first()
    if profile_row is not None:
        profile_row.legacy_parameter_set_id = parameter_set.id
    db.add(ModelLegacyBinding(
        legacy_kind="ASR_PARAMETER_SET", legacy_id=parameter_set.id, resource_id=resource.id,
        revision_id=revision.id, legacy_task_type=task_type,
    ))


def _sync_revision_projection(db: Session, resource: ModelResource, revision: ModelRevision,
                              profile: ModelParameterProfile | None, *, credential: str | None,
                              credential_supplied: bool) -> None:
    """把新修订投影到现有运行时读取表，旧 ID 与历史修订不变。"""
    from app.features.asr_evaluation.models import AsrConnection, AsrParameterSet

    credential_row = db.query(ModelCredential).filter(ModelCredential.revision_id == revision.id).first()
    if resource.category == "TEXT_GENERATION":
        from app.platform.model_configuration.services.model_config_service import encrypt_api_key

        legacy = db.get(ModelConfiguration, resource.legacy_model_id) if resource.legacy_model_id else None
        if legacy is None:
            raise bad_request("文本模型缺少旧运行时兼容 ID")
        profile_values = dict(profile.parameter_values or {}) if profile else {}
        legacy.label = resource.display_name
        legacy.provider = normalize_provider(revision.provider)
        legacy.api_base = decrypt_secret(revision.endpoint_ciphertext) or revision.endpoint_display or legacy.api_base
        legacy.model_name = revision.model_name
        legacy.temperature = float(profile_values.get("temperature", legacy.temperature))
        legacy.max_tokens = int(profile_values.get("max_tokens", legacy.max_tokens))
        legacy.timeout = int((revision.config_json or {}).get("timeout", legacy.timeout))
        legacy.is_enabled = revision.enabled
        if credential_supplied:
            legacy.api_key_encrypted = encrypt_api_key(credential or "")
        db.add(ModelLegacyBinding(
            legacy_kind="MODEL_REVISION", legacy_id=revision.id, resource_id=resource.id,
            revision_id=revision.id, legacy_domain_id=resource.resource_key,
        ))
        return
    if resource.visibility != "PROJECT" or resource.project_id is None:
        return
    task_type = "DIARIZATION" if resource.category == "DIARIZATION" else "TRANSCRIPTION"
    previous = db.query(AsrConnection).join(
        ModelLegacyBinding, ModelLegacyBinding.legacy_id == AsrConnection.id,
    ).filter(
        ModelLegacyBinding.resource_id == resource.id,
        ModelLegacyBinding.legacy_kind == "ASR_CONNECTION",
        AsrConnection.project_id == resource.project_id,
        AsrConnection.task_type == task_type,
    ).order_by(AsrConnection.version.desc(), AsrConnection.id.desc()).first()
    old_secret = None
    old_header = None
    if not credential_supplied and previous is not None:
        old_secret, old_header = previous.secret_ciphertext, previous.secret_header
    connection = AsrConnection(
        project_id=resource.project_id, name=resource.display_name, role=None, task_type=task_type,
        provider_id=revision.provider, model_id=revision.model_name, version=revision.version,
        endpoint_ciphertext=revision.endpoint_ciphertext or encrypt_secret(revision.endpoint_display or ""),
        endpoint_display=revision.endpoint_display or "", config_json=dict(revision.config_json or {}),
        secret_ciphertext=credential_row.ciphertext if credential_row else old_secret,
        secret_header=credential_row.header_name if credential_row else old_header,
        enabled=revision.enabled, created_by=revision.created_by,
    )
    db.add(connection)
    db.flush()
    revision.legacy_connection_id = connection.id
    db.add(ModelLegacyBinding(
        legacy_kind="ASR_CONNECTION", legacy_id=connection.id, resource_id=resource.id,
        revision_id=revision.id, legacy_task_type=task_type,
    ))
    if profile is not None:
        parameter_set = AsrParameterSet(
            project_id=resource.project_id, connection_id=connection.id,
            name=profile.name, version=profile.version, parameters=profile.parameter_values or {},
            definitions=profile.definitions or [], created_by=profile.created_by,
        )
        db.add(parameter_set)
        db.flush()
        profile.legacy_parameter_set_id = parameter_set.id
        db.add(ModelLegacyBinding(
            legacy_kind="ASR_PARAMETER_SET", legacy_id=parameter_set.id, resource_id=resource.id,
            revision_id=revision.id, legacy_task_type=task_type,
        ))


def create_resource(db: Session, body: ModelResourceCreate, actor: User, *, commit: bool = True) -> dict:
    """创建资源、首个连接修订、凭据和参数方案并生成兼容运行时投影。"""
    if body.visibility == "PLATFORM":
        _require_platform_admin(actor)
    else:
        _require_project_editor(db, int(body.project_id), actor)
        duplicate = db.query(ModelResource.id).filter(
            ModelResource.project_id == body.project_id, ModelResource.category == body.category,
            ModelResource.display_name == body.display_name.strip(), ModelResource.status != "ARCHIVED",
        ).first()
        if duplicate:
            raise bad_request("当前项目已存在同类别同名模型资源")
    _supported_adapter(body.category, body.adapter_key)
    _validate_capabilities(body.category, body.adapter_key, body.capabilities)
    endpoint, endpoint_display = _endpoint(body.endpoint)
    config = _validate_connection_config(body.category, body.adapter_key, body.config)
    if body.credential and not body.credential_header and body.category != "TEXT_GENERATION":
        raise bad_request("填写接口凭据时必须配置凭据请求头")
    if body.grant_project_ids and body.visibility != "PLATFORM":
        raise bad_request("仅平台共享资源可以授权其他项目")

    resource = ModelResource(
        resource_key=_resource_key(body.category, body.visibility), category=body.category,
        visibility=body.visibility, project_id=body.project_id, display_name=body.display_name.strip(),
        status="ACTIVE" if body.enabled else "DISABLED", created_by=actor.id,
    )
    db.add(resource)
    db.flush()
    revision = ModelRevision(
        resource_id=resource.id, version=1, provider=body.provider.strip(), adapter_key=body.adapter_key,
        model_name=body.model_name.strip(), endpoint_ciphertext=encrypt_secret(endpoint),
        endpoint_display=endpoint_display, config_json=config,
        capabilities=body.capabilities, parameter_schema=body.parameter_schema, enabled=body.enabled,
        created_by=actor.id,
    )
    db.add(revision)
    db.flush()
    resource.current_revision_id = revision.id
    if body.credential:
        db.add(ModelCredential(
            revision_id=revision.id, ciphertext=encrypt_secret(body.credential), cipher_format="shared-fernet",
            header_name=body.credential_header,
        ))
    profile = body.initial_profile
    values, definitions = _profile_defaults(body.category, profile.model_dump())
    profile_row = ModelParameterProfile(
        resource_id=resource.id, revision_id=revision.id, name=profile.name.strip(), version=1,
        parameter_values=values, definitions=definitions, created_by=actor.id,
    )
    db.add(profile_row)
    db.flush()
    _create_legacy_projection(db, resource=resource, revision=revision, profile=profile, credential=body.credential)
    for project_id in sorted(set(body.grant_project_ids)):
        _require_project_editor(db, project_id, actor) if not is_platform_admin(actor) else get_project_or_404(db, project_id, actor)
        db.add(ModelResourceGrant(resource_id=resource.id, project_id=project_id, granted_by=actor.id))
    db.flush()
    if commit:
        db.commit()
        db.refresh(resource)
    return _dump_resource(db, resource)


def list_resources(
    db: Session, actor: User, *, category: str | None = None, project_id: int | None = None,
) -> dict:
    """列出管理者可维护的共享资源及所选项目私有资源。"""
    query = db.query(ModelResource)
    if not is_platform_admin(actor):
        if project_id is None:
            raise bad_request("查询项目私有模型时必须指定 project_id")
        _require_project_editor(db, project_id, actor)
        query = query.filter(ModelResource.project_id == project_id)
    elif project_id is not None:
        query = query.filter((ModelResource.project_id.is_(None)) | (ModelResource.project_id == project_id))
    if category:
        query = query.filter(ModelResource.category == category)
    rows = query.order_by(ModelResource.category, ModelResource.display_name, ModelResource.id).limit(1000).all()
    return {"items": [_dump_resource(db, row) for row in rows], "total": len(rows)}


def list_available_models(db: Session, *, project_id: int, category: str | None, actor: User) -> dict:
    """向项目成员提供安全的资源选择摘要，继续应用组织模型白名单与项目授权。"""
    project = get_project_or_404(db, project_id, actor)
    query = db.query(ModelResource).filter(ModelResource.status == "ACTIVE")
    if category:
        query = query.filter(ModelResource.category == category)
    if is_platform_admin(actor):
        query = query.filter((ModelResource.visibility == "PLATFORM") | (ModelResource.project_id == project_id))
        rows = query.all()
    else:
        role = project_role_for(db, project, actor)
        if role is None:
            raise not_found("项目不存在")
        project_rows = query.filter(ModelResource.visibility == "PROJECT", ModelResource.project_id == project_id).all()
        grants = db.query(ModelResourceGrant.resource_id).filter(ModelResourceGrant.project_id == project_id).all()
        granted_ids = {item[0] for item in grants}
        platform_rows = query.filter(ModelResource.visibility == "PLATFORM").all()
        allowed_domain_ids: set[str] = set()
        if project.organization_id is not None:
            allowed_domain_ids = set(db.query(OrganizationMember.allowed_model_ids).filter(
                OrganizationMember.organization_id == project.organization_id, OrganizationMember.user_id == actor.id,
            ).scalar() or [])
        rows = [row for row in project_rows if has_project_role(role, "member")]
        rows.extend(row for row in platform_rows if (
            (row.category == "TEXT_GENERATION" and row.resource_key in allowed_domain_ids)
            or row.id in granted_ids
        ))
    items = []
    for row in rows:
        revision = db.get(ModelRevision, row.current_revision_id) if row.current_revision_id else None
        if revision is None or not revision.enabled:
            continue
        if revision.adapter_key not in _SUPPORTED_ADAPTERS.get(row.category, {}):
            continue
        profiles = db.query(ModelParameterProfile).filter(
            ModelParameterProfile.resource_id == row.id, ModelParameterProfile.revision_id == revision.id,
        ).order_by(ModelParameterProfile.name, ModelParameterProfile.version.desc()).all()
        items.append({
            "id": row.id, "resource_key": row.resource_key, "category": row.category,
            "visibility": row.visibility, "project_id": row.project_id, "display_name": row.display_name,
            "revision": {"id": revision.id, "version": revision.version, "provider": revision.provider,
                         "adapter_key": revision.adapter_key, "model_name": revision.model_name,
                         "capabilities": revision.capabilities or []},
            "profiles": [_dump_profile(item) for item in profiles],
        })
    return {"items": items, "total": len(items)}


def create_revision(db: Session, resource_id: int, body: ModelRevisionInput, actor: User) -> dict:
    """追加不可变连接修订并将其设为当前可用版本。"""
    resource = db.get(ModelResource, resource_id)
    if resource is None:
        raise not_found("模型资源不存在")
    _require_resource_editor(db, resource, actor)
    _supported_adapter(resource.category, body.adapter_key)
    _validate_capabilities(resource.category, body.adapter_key, body.capabilities)
    endpoint, display = _endpoint(body.endpoint)
    config = _validate_connection_config(resource.category, body.adapter_key, body.config)
    previous = db.query(ModelRevision).filter(ModelRevision.resource_id == resource_id).order_by(
        ModelRevision.version.desc(),
    ).first()
    previous_credential = db.query(ModelCredential).filter(ModelCredential.revision_id == previous.id).first() if previous else None
    config["credential_header"] = body.credential_header or (previous_credential.header_name if previous_credential else "Authorization")
    revision = ModelRevision(
        resource_id=resource_id, version=(previous.version + 1 if previous else 1),
        provider=body.provider.strip(), adapter_key=body.adapter_key, model_name=body.model_name.strip(),
        endpoint_ciphertext=encrypt_secret(endpoint), endpoint_display=display, config_json=config,
        capabilities=body.capabilities, parameter_schema=body.parameter_schema, enabled=body.enabled,
        created_by=actor.id,
    )
    db.add(revision)
    db.flush()
    resource.current_revision_id = revision.id
    resource.status = "ACTIVE" if body.enabled else "DISABLED"
    credential_supplied = body.credential is not None
    if body.credential:
        db.add(ModelCredential(revision_id=revision.id, ciphertext=encrypt_secret(body.credential),
                               cipher_format="shared-fernet", header_name=body.credential_header))
    elif body.credential is None and previous_credential is not None:
        db.add(ModelCredential(
            revision_id=revision.id, ciphertext=previous_credential.ciphertext,
            cipher_format=previous_credential.cipher_format, header_name=previous_credential.header_name,
        ))
    previous_profile = db.query(ModelParameterProfile).filter(
        ModelParameterProfile.resource_id == resource.id,
        ModelParameterProfile.revision_id == previous.id if previous else False,
    ).order_by(ModelParameterProfile.version.desc()).first()
    profile_input = body.initial_profile or ModelProfileInput(
        name=previous_profile.name if previous_profile else "默认参数",
        values=dict(previous_profile.parameter_values or {}) if previous_profile else {},
        definitions=list(previous_profile.definitions or []) if previous_profile else [],
    )
    values, definitions = _validated_profile(
        resource.category, profile_input.model_dump(), body.parameter_schema or (previous.parameter_schema if previous else []),
    )
    profile_row = ModelParameterProfile(
        resource_id=resource.id, revision_id=revision.id, name=profile_input.name.strip(),
        version=_next_profile_version(db, resource.id, revision.id, profile_input.name.strip()),
        parameter_values=values, definitions=definitions, created_by=actor.id,
    )
    db.add(profile_row)
    db.flush()
    _sync_revision_projection(
        db, resource, revision, profile_row, credential=body.credential,
        credential_supplied=credential_supplied,
    )
    db.commit()
    db.refresh(revision)
    return _dump_resource(db, resource)


def create_profile(db: Session, resource_id: int, body: ModelProfileCreate, actor: User) -> dict:
    """为资源当前或指定修订新增不可变参数方案版本。"""
    resource = db.get(ModelResource, resource_id)
    revision = db.get(ModelRevision, body.revision_id)
    if resource is None or revision is None or revision.resource_id != resource_id:
        raise not_found("模型修订不存在")
    _require_resource_editor(db, resource, actor)
    profile_dump = {"name": body.name, "values": body.values, "definitions": body.definitions}
    values, definitions = _validated_profile(resource.category, profile_dump, revision.parameter_schema or [])
    row = ModelParameterProfile(
        resource_id=resource.id, revision_id=revision.id, name=body.name.strip(),
        version=_next_profile_version(db, resource.id, revision.id, body.name.strip()),
        parameter_values=values, definitions=definitions, created_by=actor.id,
    )
    db.add(row)
    db.flush()
    if resource.visibility == "PROJECT" and revision.legacy_connection_id is not None:
        from app.features.asr_evaluation.models import AsrConnection, AsrParameterSet

        connection = db.get(AsrConnection, revision.legacy_connection_id)
        if connection is not None and connection.project_id == resource.project_id:
            parameter_set = AsrParameterSet(
                project_id=int(resource.project_id), connection_id=connection.id,
                name=row.name, version=row.version, parameters=row.parameter_values or {},
                definitions=row.definitions or [], created_by=actor.id,
            )
            db.add(parameter_set)
            db.flush()
            row.legacy_parameter_set_id = parameter_set.id
            db.add(ModelLegacyBinding(
                legacy_kind="ASR_PARAMETER_SET", legacy_id=parameter_set.id, resource_id=resource.id,
                revision_id=revision.id, legacy_task_type=connection.task_type,
            ))
    db.commit()
    db.refresh(row)
    return _dump_profile(row)


def set_resource_grants(db: Session, resource_id: int, project_ids: list[int], actor: User) -> dict:
    """替换平台共享资源的项目授权，不改变组织模型 domain_id 白名单。"""
    _require_platform_admin(actor)
    resource = db.get(ModelResource, resource_id)
    if resource is None or resource.visibility != "PLATFORM":
        raise not_found("平台共享模型不存在")
    ids = sorted(set(project_ids))
    for project_id in ids:
        get_project_or_404(db, project_id, actor)
    db.query(ModelResourceGrant).filter(ModelResourceGrant.resource_id == resource_id).delete(synchronize_session=False)
    db.add_all([ModelResourceGrant(resource_id=resource_id, project_id=item, granted_by=actor.id) for item in ids])
    db.commit()
    return {"resource_id": resource_id, "project_ids": ids}


def resolve_task_slots(db: Session, project_id: int, slots: list, actor: User) -> list[dict]:
    """解析项目已授权的槽位到固定资源修订、参数版本和 ASR 兼容投影。"""
    from app.features.asr_evaluation.models import AsrConnection, AsrParameterSet

    project = get_project_or_404(db, project_id, actor)
    available = list_available_models(db, project_id=project_id, category=None, actor=actor)
    allowed = {item["id"] for item in available["items"]}
    if len({item.slot for item in slots}) != len(slots):
        raise bad_request("任务模型槽位不能重复")
    resolved = []
    for item in slots:
        expected_category = "DIARIZATION" if item.slot == "DIARIZATION" else "ASR"
        resource = db.get(ModelResource, item.resource_id)
        revision = db.get(ModelRevision, item.revision_id)
        profile = db.get(ModelParameterProfile, item.profile_id)
        if (resource is None or resource.id not in allowed or resource.category != expected_category or
                revision is None or revision.resource_id != resource.id or not revision.enabled or
                profile is None or profile.resource_id != resource.id or profile.revision_id != revision.id):
            raise not_found("所选项目模型或参数方案不可用")
        _validated_profile(resource.category,
                           {"name": profile.name, "values": profile.parameter_values or {},
                            "definitions": profile.definitions or []},
                           revision.parameter_schema or [])
        connection = None
        if resource.visibility == "PROJECT" and resource.project_id == project_id and revision.legacy_connection_id:
            connection = db.get(AsrConnection, revision.legacy_connection_id)
            if connection is not None and connection.project_id != project_id:
                connection = None
        if connection is None:
            connection = db.query(AsrConnection).join(
                ModelLegacyBinding, ModelLegacyBinding.legacy_id == AsrConnection.id,
            ).filter(
                ModelLegacyBinding.resource_id == resource.id,
                ModelLegacyBinding.revision_id == revision.id,
                ModelLegacyBinding.legacy_kind.in_(["ASR_CONNECTION", "ASR_SHARED_CONNECTION"]),
                AsrConnection.project_id == project_id,
            ).first()
        if connection is None:
            if resource.visibility != "PLATFORM" or resource.id not in allowed:
                raise not_found("项目模型连接版本不存在")
            credential = db.query(ModelCredential).filter(ModelCredential.revision_id == revision.id).first()
            shared_connection = AsrConnection(
                project_id=project_id,
                name=f"{resource.display_name} [{resource.resource_key[-8:]}]"[:120], role=None,
                task_type="DIARIZATION" if expected_category == "DIARIZATION" else "TRANSCRIPTION",
                provider_id=revision.provider, model_id=revision.model_name, version=revision.version,
                endpoint_ciphertext=revision.endpoint_ciphertext or encrypt_secret(revision.endpoint_display or ""),
                endpoint_display=revision.endpoint_display or "", config_json=dict(revision.config_json or {}),
                secret_ciphertext=credential.ciphertext if credential else None,
                secret_header=credential.header_name if credential else None, enabled=revision.enabled,
                created_by=actor.id,
            )
            db.add(shared_connection)
            db.flush()
            db.add(ModelLegacyBinding(
                legacy_kind="ASR_SHARED_CONNECTION", legacy_id=shared_connection.id, resource_id=resource.id,
                revision_id=revision.id, legacy_task_type=shared_connection.task_type,
            ))
            connection = shared_connection
        if connection.project_id != project_id or not connection.enabled:
            raise not_found("项目模型连接不可用")
        parameter_set = None
        if profile.legacy_parameter_set_id:
            candidate = db.get(AsrParameterSet, profile.legacy_parameter_set_id)
            if candidate is not None and candidate.project_id == project_id and candidate.connection_id == connection.id:
                parameter_set = candidate
        if parameter_set is None:
            parameter_set = db.query(AsrParameterSet).filter(
                AsrParameterSet.project_id == project_id, AsrParameterSet.connection_id == connection.id,
                AsrParameterSet.name == profile.name, AsrParameterSet.version == profile.version,
            ).first()
        if parameter_set is None:
            parameter_set = AsrParameterSet(
                project_id=project_id, connection_id=connection.id, name=profile.name,
                version=profile.version, parameters=profile.parameter_values or {},
                definitions=profile.definitions or [], created_by=actor.id,
            )
            db.add(parameter_set)
            db.flush()
            if profile.legacy_parameter_set_id is None and resource.visibility == "PROJECT":
                profile.legacy_parameter_set_id = parameter_set.id
            db.add(ModelLegacyBinding(
                legacy_kind="ASR_SHARED_PARAMETER_SET", legacy_id=parameter_set.id, resource_id=resource.id,
                revision_id=revision.id, legacy_task_type=connection.task_type,
            ))
        resolved.append({
            "slot": item.slot, "resource": resource, "revision": revision, "profile": profile,
            "connection": connection, "parameter_set": parameter_set,
        })
    return resolved


def set_default_binding(db: Session, body: ModelDefaultInput, actor: User) -> dict:
    """按用途设置默认模型与同类别备用列表，评测用途永远关闭自动换模型。"""
    expected_purpose = {
        "TEXT_GENERATION": "TEXT_INFERENCE", "ASR": "ASR_EVALUATION", "DIARIZATION": "DIARIZATION",
    }.get(body.category)
    if body.purpose != expected_purpose:
        raise bad_request("默认用途必须与模型类别匹配")
    if body.project_id is None:
        _require_platform_admin(actor)
    else:
        _require_project_editor(db, body.project_id, actor)
    resource = db.get(ModelResource, body.resource_id)
    revision = db.get(ModelRevision, body.revision_id)
    profile = db.get(ModelParameterProfile, body.profile_id) if body.profile_id else None
    if (resource is None or revision is None or resource.category != body.category or
            revision.resource_id != resource.id or not revision.enabled):
        raise bad_request("默认模型与参数修订类别或资源不匹配")
    if body.project_id is None and resource.visibility != "PLATFORM":
        raise bad_request("项目私有模型不能设为平台默认")
    if body.project_id is not None:
        available_ids = {item["id"] for item in list_available_models(
            db, project_id=body.project_id, category=body.category, actor=actor,
        )["items"]}
        if resource.id not in available_ids:
            raise bad_request("默认模型尚未授权给该项目")
    if profile is not None and (profile.resource_id != resource.id or profile.revision_id != revision.id):
        raise bad_request("参数方案不属于所选模型修订")
    fallbacks = []
    for fallback_id in dict.fromkeys(body.fallback_resource_ids):
        fallback = db.get(ModelResource, fallback_id)
        if fallback is None or fallback.category != body.category or fallback.id == resource.id or fallback.status != "ACTIVE":
            raise bad_request("备用模型必须处于启用状态且与默认模型类别一致")
        if body.project_id is None and fallback.visibility != "PLATFORM":
            raise bad_request("平台默认不能引用项目私有备用模型")
        if body.project_id is not None and fallback_id not in available_ids:
            raise bad_request("备用模型尚未授权给该项目")
        fallbacks.append(fallback.id)
    if "EVALUATION" in body.purpose.upper() and body.automatic_fallback:
        raise bad_request("评测默认禁止自动换模型，避免污染对比结果")
    row = db.query(ModelDefaultBinding).filter(
        ModelDefaultBinding.category == body.category, ModelDefaultBinding.purpose == body.purpose,
        ModelDefaultBinding.project_id == body.project_id,
    ).first()
    if row is None:
        row = ModelDefaultBinding(category=body.category, purpose=body.purpose, project_id=body.project_id)
        db.add(row)
    row.resource_id, row.revision_id, row.profile_id = resource.id, revision.id, profile.id if profile else None
    row.fallback_resource_ids = fallbacks
    row.automatic_fallback = body.automatic_fallback
    row.updated_by = actor.id
    if body.category == "TEXT_GENERATION" and body.project_id is None:
        text_resources = db.query(ModelResource).filter(
            ModelResource.category == "TEXT_GENERATION", ModelResource.visibility == "PLATFORM",
        ).all()
        for item in text_resources:
            legacy = db.get(ModelConfiguration, item.legacy_model_id) if item.legacy_model_id else None
            if legacy is not None:
                legacy.is_default = legacy.id == resource.legacy_model_id
                if legacy.is_default:
                    fallback_rows = db.query(ModelResource.legacy_model_id).filter(
                        ModelResource.id.in_(fallbacks), ModelResource.legacy_model_id.is_not(None),
                    ).all()
                    legacy.fallback_model_ids = [item[0] for item in fallback_rows][:3]
    db.commit()
    return {"id": row.id, "category": row.category, "purpose": row.purpose, "project_id": row.project_id,
            "resource_id": row.resource_id, "revision_id": row.revision_id, "profile_id": row.profile_id,
            "fallback_resource_ids": row.fallback_resource_ids, "automatic_fallback": row.automatic_fallback}


def copy_resource(db: Session, resource_id: int, project_id: int, actor: User) -> dict:
    """复制非敏感连接与参数配置到项目作用域，凭据保持空白并重新授权出站目标。"""
    source = db.get(ModelResource, resource_id)
    if source is None:
        raise not_found("模型资源不存在")
    get_project_or_404(db, project_id, actor)
    if source.visibility == "PROJECT" and source.project_id != project_id:
        raise not_found("模型资源不存在")
    revision = db.get(ModelRevision, source.current_revision_id) if source.current_revision_id else None
    if revision is None:
        raise bad_request("模型资源没有可复制的连接修订")
    profiles = db.query(ModelParameterProfile).filter(
        ModelParameterProfile.resource_id == source.id, ModelParameterProfile.revision_id == revision.id,
    ).order_by(ModelParameterProfile.name, ModelParameterProfile.version.desc()).all()
    selected: dict[str, ModelParameterProfile] = {}
    for item in profiles:
        selected.setdefault(item.name, item)
    initial = next(iter(selected.values()), None)
    body = ModelResourceCreate(
        category=source.category, visibility="PROJECT", project_id=project_id,
        display_name=f"{source.display_name}（副本）"[:160], provider=revision.provider,
        adapter_key=revision.adapter_key, model_name=revision.model_name,
        endpoint=decrypt_secret(revision.endpoint_ciphertext) or revision.endpoint_display or "",
        config=dict(revision.config_json or {}), capabilities=list(revision.capabilities or []),
        parameter_schema=list(revision.parameter_schema or []), enabled=False,
        initial_profile=ModelProfileInput(
            name=initial.name if initial else "默认参数",
            values=dict(initial.parameter_values or {}) if initial else {},
            definitions=list(initial.definitions or []) if initial else [],
        ),
    )
    return create_resource(db, body, actor)


def create_diagnostic(db: Session, resource_id: int, body, actor: User) -> dict:
    """持久化一次已明确确认的模型在线诊断；仅用户主动触发后才入队。"""
    from app.features.asr_evaluation.models import AsrAudio
    from app.features.asr_evaluation.schemas import ModelTaskSlotInput

    resource = db.get(ModelResource, resource_id)
    if resource is None:
        raise not_found("模型资源不存在")
    project = _require_project_editor(db, body.project_id, actor)
    available_ids = {item["id"] for item in list_available_models(
        db, project_id=body.project_id, category=None, actor=actor,
    )["items"]}
    if resource.id not in available_ids:
        raise not_found("模型资源不存在")
    revision = db.get(ModelRevision, resource.current_revision_id) if resource.current_revision_id else None
    if revision is None or not revision.enabled:
        raise bad_request("模型当前没有启用的连接修订")
    profile = db.get(ModelParameterProfile, body.profile_id) if body.profile_id else None
    if profile is None:
        profile = db.query(ModelParameterProfile).filter(
            ModelParameterProfile.resource_id == resource.id, ModelParameterProfile.revision_id == revision.id,
        ).order_by(ModelParameterProfile.version.desc()).first()
    if profile is not None and (profile.resource_id != resource.id or profile.revision_id != revision.id):
        raise bad_request("诊断参数方案不属于当前模型修订")
    if resource.category in {"ASR", "DIARIZATION"}:
        if body.audio_id is None:
            raise bad_request("ASR 与说话人模型诊断必须选择项目音频")
        audio = db.get(AsrAudio, body.audio_id)
        if audio is None or audio.project_id != body.project_id:
            raise not_found("项目音频不存在")
        if profile is None:
            raise bad_request("请先创建该模型修订的参数方案")
        slot = "DIARIZATION" if resource.category == "DIARIZATION" else "TEST"
        resolve_task_slots(db, body.project_id, [ModelTaskSlotInput(
            slot=slot, resource_id=resource.id, revision_id=revision.id, profile_id=profile.id,
        )], actor)
    row = ModelValidationRun(
        resource_id=resource.id, revision_id=revision.id, profile_id=profile.id if profile else None,
        project_id=project.id, audio_id=body.audio_id, status="QUEUED",
        diagnostic_kind=resource.category, result_json={"message": "诊断已排队"}, requested_by=actor.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "resource_id": row.resource_id, "revision_id": row.revision_id,
            "status": row.status, "diagnostic_kind": row.diagnostic_kind, "created_at": row.created_at}


def run_model_diagnostic(run_id: int) -> None:
    """在后台使用已注册适配器真实请求一次，并只保存脱敏状态摘要。"""
    from datetime import datetime, timezone

    from app.core.database.session import SessionLocal
    from app.core.security.crypto import decrypt_secret
    from app.execution.http.executor import ApiRequestExecutor
    from app.features.asr_evaluation.models import AsrAudio, AsrConnection
    from app.features.asr_evaluation.providers.generic_json import DiarizationJsonProvider, GenericJsonProvider

    db = SessionLocal()
    run = db.get(ModelValidationRun, run_id)
    if run is None or run.status not in {"QUEUED", "RUNNING"}:
        db.close()
        return
    run.status = "RUNNING"
    run.started_at = datetime.now(timezone.utc)
    db.commit()
    try:
        resource = db.get(ModelResource, run.resource_id)
        revision = db.get(ModelRevision, run.revision_id)
        profile = db.get(ModelParameterProfile, run.profile_id) if run.profile_id else None
        if resource is None or revision is None or run.project_id is None:
            raise ValueError("诊断配置已不存在")
        credential = db.query(ModelCredential).filter(ModelCredential.revision_id == revision.id).first()
        secret = ""
        if credential is not None:
            if credential.cipher_format == "model-configuration-fernet":
                from app.platform.model_configuration.services.model_config_service import decrypt_api_key
                secret = decrypt_api_key(credential.ciphertext)
            else:
                secret = decrypt_secret(credential.ciphertext)
        if resource.category == "TEXT_GENERATION":
            url = decrypt_secret(revision.endpoint_ciphertext) or revision.endpoint_display or ""
            if not url.rstrip("/").endswith("/chat/completions"):
                url = f"{url.rstrip('/')}/chat/completions"
            headers = {"Content-Type": "application/json"}
            if secret:
                headers["Authorization"] = f"Bearer {secret}"
            response = ApiRequestExecutor().execute(
                db, method="POST", url=url, project_id=run.project_id, headers=headers,
                json_body={"model": revision.model_name,
                           "messages": [{"role": "user", "content": "Return the word ok."}],
                           "temperature": 0, "max_tokens": 1},
                timeout=int((revision.config_json or {}).get("timeout", 30)), max_response_bytes=256_000,
            )
            if response.error_message or response.transport_error_kind or not 200 <= int(response.status_code or 0) < 300:
                raise ValueError(f"模型服务诊断失败（HTTP {response.status_code or '网络错误'}）")
            result = {"message": "模型请求成功", "http_status": int(response.status_code),
                      "response_time_ms": response.response_time_ms}
        else:
            audio = db.get(AsrAudio, run.audio_id) if run.audio_id else None
            connection = db.query(AsrConnection).join(
                ModelLegacyBinding, ModelLegacyBinding.legacy_id == AsrConnection.id,
            ).filter(
                ModelLegacyBinding.resource_id == resource.id, ModelLegacyBinding.revision_id == revision.id,
                AsrConnection.project_id == run.project_id,
            ).order_by(AsrConnection.id.desc()).first()
            if audio is None or connection is None:
                raise ValueError("诊断音频或项目连接投影不存在")
            config = dict(connection.config_json or {})
            execution = {
                "audio_url": decrypt_secret(audio.url_ciphertext),
                "endpoint": decrypt_secret(connection.endpoint_ciphertext), "model_id": connection.model_id,
                "secret": decrypt_secret(connection.secret_ciphertext), "secret_header": connection.secret_header,
                "parameters": (profile.parameter_values or {}) if profile else {}, **config,
            }
            if resource.category == "DIARIZATION":
                provider = DiarizationJsonProvider()
                response = provider.submit(db, project_id=run.project_id, execution=execution,
                                           idempotency_key=f"model-center-diagnostic-{run.id}")
            else:
                provider = GenericJsonProvider()
                response = provider.submit(db, project_id=run.project_id, execution=execution,
                                           idempotency_key=f"model-center-diagnostic-{run.id}")
            result = {"message": "模型接口接受诊断请求", "state": response.get("state", "SUCCEEDED"),
                      "response_time_ms": response.get("response_time_ms")}
        run.status = "SUCCEEDED"
        run.result_json = result
    except Exception as exc:  # noqa: BLE001 - 错误不持久化地址、请求体、凭据或上游原文。
        run.status = "FAILED"
        run.result_json = {"message": str(exc)[:300] if isinstance(exc, ValueError) else "诊断调用失败"}
    finally:
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.close()


def get_diagnostic(db: Session, run_id: int, actor: User) -> dict:
    """读取用户可访问项目内的脱敏诊断状态。"""
    row = db.get(ModelValidationRun, run_id)
    if row is None:
        raise not_found("模型诊断记录不存在")
    if row.project_id is not None:
        get_project_or_404(db, row.project_id, actor)
    else:
        _require_platform_admin(actor)
    return {"id": row.id, "resource_id": row.resource_id, "revision_id": row.revision_id,
            "profile_id": row.profile_id, "status": row.status, "diagnostic_kind": row.diagnostic_kind,
            "result": row.result_json or {}, "created_at": row.created_at,
            "started_at": row.started_at, "finished_at": row.finished_at}


def preview_import(db: Session, items: list[dict], actor: User) -> dict:
    """预检非敏感配置批次；任何凭据字段都会被拒绝，且不会发起模型调用。"""
    _require_platform_admin(actor)
    results = []
    for index, item in enumerate(items):
        errors = []
        if not isinstance(item, dict):
            results.append({"index": index, "valid": False, "errors": ["条目必须是对象"]})
            continue
        if _contains_sensitive_import_field(item):
            results.append({"index": index, "valid": False,
                            "errors": ["预检文件不能包含凭据，请在模型中心单独录入"],
                            "display_name": item.get("display_name"), "category": item.get("category")})
            continue
        try:
            body = ModelResourceCreate(**item)
            _supported_adapter(body.category, body.adapter_key)
            _validate_capabilities(body.category, body.adapter_key, body.capabilities)
            endpoint, _ = _endpoint(body.endpoint)
            _validate_connection_config(body.category, body.adapter_key, body.config)
        except Exception as exc:  # 不回显异常中可能包含的原始输入值。
            if hasattr(exc, "errors") and callable(exc.errors):
                errors.extend(f"{'.'.join(str(part) for part in issue.get('loc', ()))}：{issue.get('msg', '字段无效')}"
                              for issue in exc.errors(include_input=False))
            elif hasattr(exc, "detail"):
                errors.append(str(exc.detail)[:300])
            else:
                errors.append("配置字段校验失败")
            body = None
        results.append({"index": index, "valid": not errors, "errors": errors,
                        "display_name": body.display_name if body else None,
                        "category": body.category if body else None})
    return {"valid_count": sum(item["valid"] for item in results), "invalid_count": sum(not item["valid"] for item in results),
            "items": results, "can_apply": bool(results) and all(item["valid"] for item in results)}


def import_resources(db: Session, items: list[dict], actor: User) -> dict:
    """仅在整批预检通过后原子创建非敏感模型资源，不触发任何在线模型调用。"""
    _require_platform_admin(actor)
    preview = preview_import(db, items, actor)
    if not preview["can_apply"]:
        raise bad_request("导入预检未通过，请修复所有条目后重试")
    created = []
    try:
        for item in items:
            body = ModelResourceCreate(**item)
            created.append(create_resource(db, body, actor, commit=False))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"items": created, "total": len(created), "status": "IMPORTED"}


__all__ = [
    "adapter_catalog", "copy_resource", "create_profile", "create_resource", "create_revision",
    "create_diagnostic", "get_diagnostic", "import_resources", "list_available_models", "list_resources", "preview_import",
    "resolve_task_slots", "run_model_diagnostic", "set_default_binding", "set_resource_grants",
    "sync_legacy_asr_connection", "sync_legacy_asr_parameter_set", "sync_legacy_text_configuration",
    "sync_legacy_text_default",
]
