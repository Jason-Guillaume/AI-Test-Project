"""Trace 生成与脱敏。

``security_execution.mutation_trace`` 与 ``evidence`` 里不允许出现 Token / 口令 /
Cookie 原值：所有 before/after 在写库前都过一次 ``mask_value``，敏感键替换成
``******``。判定沿用业务执行器的 ``is_sensitive_key``（精确匹配键名，不做子串
猜测），所以 ``task_id`` 这类资源 ID 保持明文——它是定位问题的必要信息。
"""

from __future__ import annotations

from typing import Any

from app.features.business.executors.sensitive import is_sensitive_key, mask_body, mask_headers, mask_text

from app.features.security_testing.runtime.types import (
    BaselineRequest,
    MutationTraceEntry,
)

__all__ = [
    "MASKED",
    "mask_value",
    "entries_to_dicts",
    "request_snapshot",
    "request_diff",
]

#: 脱敏占位符，与 ``sensitive.py`` 里的取值保持一致。
MASKED = "******"


def mask_value(key: str | None, value: Any) -> Any:
    """敏感键的值替换成 ``******``；其余键原样返回。

    dict / list 值无论键名都会递归脱敏——它们可能是嵌套 body。
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return mask_body(value)
    if isinstance(key, str) and is_sensitive_key(key):
        return MASKED
    return value


def _mask_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """按键名脱敏一个扁平映射（header / query / path 参数）。"""
    return {
        str(k): (MASKED if is_sensitive_key(str(k)) else str(v))
        for k, v in (mapping or {}).items()
    }


def entries_to_dicts(entries: list[MutationTraceEntry]) -> list[dict[str, Any]]:
    """trace 的落库形态（已脱敏）。"""
    return [entry.to_dict() for entry in entries]


def request_snapshot(req: BaselineRequest) -> dict[str, Any]:
    """脱敏后的完整请求快照，用于 ``execution.evidence`` 的基线/变异对比。"""
    body_type = "json"
    body: Any = None
    if req.json_body is not None:
        body = mask_body(req.json_body)
    elif req.form_body is not None:
        body_type = "form"
        body = mask_body(req.form_body)
    elif req.raw_body is not None:
        body_type = "raw"
        body = mask_text(req.raw_body)

    return {
        "method": (req.method or "").upper(),
        "path": req.path,
        "path_params": _mask_mapping(req.path_params),
        "query": _mask_mapping(req.query),
        "headers": mask_headers({str(k): str(v) for k, v in (req.headers or {}).items()}),
        "cookies": _mask_mapping(req.cookies),
        "body": body,
        "body_type": body_type if body is not None else "none",
        "content_type": req.content_type,
    }


def _diff_mapping(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    location: str,
    mutation_type: str,
    prefix: str | None,
) -> list[MutationTraceEntry]:
    """对比两个扁平映射，逐键产出 trace。"""
    before = dict(before or {})
    after = dict(after or {})
    entries: list[MutationTraceEntry] = []
    for key in sorted(set(before) | set(after), key=str):
        if str(before.get(key)) == str(after.get(key)):
            continue
        field = f"{prefix}.{key}" if prefix else str(key)
        entries.append(
            MutationTraceEntry(
                mutation_type=mutation_type,
                location=location,
                field=field,
                before=before.get(key),
                after=after.get(key),
            )
        )
    return entries


def request_diff(
    before: BaselineRequest,
    after: BaselineRequest,
    mutation_type: str,
) -> list[MutationTraceEntry]:
    """对比两份请求逐字段产出 trace。

    算子应该自己写带语义的 trace（例如 CONTENT_TYPE_MUTATION 要说明 body 改走
    raw_body）；这份对比是引擎的兜底——算子改了请求却没写 trace 时，
    「每次变异必须留下说明」仍然成立。
    """
    entries: list[MutationTraceEntry] = []
    if (before.method or "").upper() != (after.method or "").upper():
        entries.append(
            MutationTraceEntry(mutation_type, "METHOD", "method", before.method, after.method)
        )
    entries.extend(_diff_mapping(before.path_params, after.path_params, "PATH", mutation_type, None))
    entries.extend(_diff_mapping(before.query, after.query, "QUERY", mutation_type, None))
    entries.extend(_diff_mapping(before.headers, after.headers, "HEADER", mutation_type, None))
    entries.extend(_diff_mapping(before.cookies, after.cookies, "COOKIE", mutation_type, None))
    for side, field_name in ((("form_body", None), "form_body"), (("json_body", "$"), "json_body")):
        attr, prefix = side
        before_value = getattr(before, attr)
        after_value = getattr(after, attr)
        if isinstance(before_value, dict) and isinstance(after_value, dict):
            entries.extend(_diff_mapping(before_value, after_value, "BODY", mutation_type, prefix))
        elif before_value != after_value:
            # 一侧不再是映射（例如 json body 被整段换成 raw 文本），整体记一条。
            entries.append(
                MutationTraceEntry(mutation_type, "BODY", field_name, before_value, after_value)
            )
    if before.raw_body != after.raw_body:
        entries.append(
            MutationTraceEntry(
                mutation_type, "BODY", "raw_body",
                before.raw_body, after.raw_body,
            )
        )
    if before.content_type != after.content_type:
        entries.append(
            MutationTraceEntry(mutation_type, "HEADER", "Content-Type", before.content_type, after.content_type)
        )
    return entries
