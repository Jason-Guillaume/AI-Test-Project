"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.api_catalog.models.api_parameter import ApiParameter
from app.features.api_catalog.models.api_request_body import ApiRequestBody
from app.features.api_catalog.models.api_response import ApiResponse
from app.features.api_catalog.schemas import ApiBodyIn, ApiParameterIn, ApiResponseIn


def diff_params(old: list[ApiParameter], new: list[ApiParameterIn]) -> dict:
    """计算 API 参数定义之间的差异。"""
    old_keys = {p.name: (p.type, bool(p.required)) for p in old}
    new_keys = {p.name: (p.type or "string", bool(p.required)) for p in new}
    added = [n for n in new_keys if n not in old_keys]
    removed = [n for n in old_keys if n not in new_keys]
    changed = []
    for n in new_keys:
        if n in old_keys and old_keys[n] != new_keys[n]:
            changed.append(n)
    if not (added or removed or changed):
        return {}
    return {"params": {"added": added, "removed": removed, "changed": changed}}


def diff_body(old: ApiRequestBody | None, new: ApiBodyIn) -> dict:
    """计算 API 请求体定义之间的差异。"""
    if old is None:
        return {} if new.body_type == "none" else {"body": "added"}
    if (old.body_type, old.content_type) != (new.body_type, new.content_type):
        return {"body": {"before": old.body_type, "after": new.body_type}}
    return {}


def diff_responses(old: list[ApiResponse], new: list[ApiResponseIn]) -> dict:
    """计算 API 响应定义之间的差异。"""
    old_codes = {r.status_code for r in old}
    new_codes = {r.status_code for r in new}
    added = sorted(c for c in new_codes if c not in old_codes)
    removed = sorted(c for c in old_codes if c not in new_codes)
    if not (added or removed):
        return {}
    return {"status_codes": {"added": added, "removed": removed}}
