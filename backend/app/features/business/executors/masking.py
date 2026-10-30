"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.business.executors.context import ExecutionContext
from app.core.security.sensitive import SensitiveDataMasker
from app.core.security.sanitizer import mask_known_secrets


def mask_context_for_storage(ctx: ExecutionContext) -> dict:
    """将上下文序列化为可存储的 dict，并脱敏敏感字段。"""
    data = ctx.to_dict()
    if "variables" in data:
        data["variables"] = SensitiveDataMasker.mask_body(data["variables"])
    if "actions" in data:
        for k, v in data["actions"].items():
            data["actions"][k] = SensitiveDataMasker.mask_body(v)
    return mask_web_secrets(data, ctx)


def mask_web_secrets(data, ctx):
    """仅含 Web 动作时清除内存凭据登记并替换已知秘密值，API 原有路径不受影响。"""
    secrets = ctx.get("__web_sensitive_values", [])
    if not secrets:
        return data
    if isinstance(data, dict):
        data = dict(data)
        if isinstance(data.get("variables"), dict):
            data["variables"] = {k: v for k, v in data["variables"].items() if k != "__web_sensitive_values"}
    return mask_known_secrets(data, secrets)


def mask_context_variables(data: dict) -> dict:
    """对上下文字典中的敏感字段进行脱敏。"""
    return SensitiveDataMasker.mask_body(data) if data else {}


def try_parse_json(text: str) -> object:
    """尝试将文本解析为 JSON 对象。"""
    import json
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
