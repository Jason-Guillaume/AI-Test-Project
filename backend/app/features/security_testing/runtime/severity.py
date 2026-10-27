"""严重级别规则表。

级别只由固定表算出（§8）：LLM 不能覆盖，前端也不能传入决定级别。表外的场景退回
规则上声明的 severity（默认 MEDIUM）。返回 ``None`` 表示「明确不建 Finding」，
与「表里没有匹配」是两回事——后者会走默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.features.security_testing.schemas import SEVERITY_LEVELS

__all__ = ["SeverityContext", "resolve_severity", "SEVERITY_ORDER", "DEFAULT_FINDING_SEVERITY"]

#: 严重级别排序，用于比较「规则声明的默认值是否更低」。
SEVERITY_ORDER: dict[str, int] = {level: idx for idx, level in enumerate(SEVERITY_LEVELS)}

#: 表外场景的默认级别。
DEFAULT_FINDING_SEVERITY = "MEDIUM"

#: 认证类算子：去掉或换错 Token 仍 2xx 属于 HIGH。
_AUTH_MUTATION_TYPES = frozenset({
    "REMOVE_TOKEN", "EMPTY_TOKEN", "INVALID_TOKEN", "MALFORMED_TOKEN",
    "WRONG_AUTH_SCHEME", "EXPIRED_TOKEN", "AUTHORIZATION_MUTATION",
})
#: 跨用户 / 跨资源算子：2xx 且响应包含候选资源 ID 属于 CRITICAL。
_CROSS_RESOURCE_TYPES = frozenset({"CROSS_USER", "IDOR", "RESOURCE_OWNER_CHANGE"})


@dataclass
class SeverityContext:
    """算级别所需的最小上下文。

    只传判定真正用到的字段：状态码、是否 2xx、算子类型、鉴权声明、响应里是否
    包含候选资源 ID、方法。传多了容易让规则表依赖无关数据。
    """

    mutation_type: str
    category: str = ""
    classification: str | None = None
    status_codes: list[int] = field(default_factory=list)
    auth_type: str = "none"
    response_body: Any = None
    candidate_resource_id: Any = None
    method: str | None = None
    rule_severity: str | None = None


def _last_status(codes: list[int] | None) -> int:
    """取最后一次执行的状态码；没有执行记录时返回 0。"""
    values = [int(c) for c in (codes or []) if isinstance(c, (int, float))]
    return int(values[-1]) if values else 0


def _is_2xx(ctx: SeverityContext) -> bool:
    """判断`xx`是否成立。"""
    return 200 <= _last_status(ctx.status_codes) < 300


def _contains_value(node: Any, value: Any) -> bool:
    """响应里是否出现某个值（按字符串比较，容忍 JSON 数字与字符串的差异）。"""
    if isinstance(node, dict):
        return any(_contains_value(item, value) for item in node.values())
    if isinstance(node, list):
        return any(_contains_value(item, value) for item in node)
    return isinstance(node, (str, int, float, bool)) and str(node) == str(value)


def _body_contains_candidate(ctx: SeverityContext) -> bool:
    """响应里是否包含候选资源 ID。

    启发式判定：候选 ID 存在且响应任意位置出现同值即算「读到了对方资源」。
    误判只会把级别从 HIGH 抬到 CRITICAL，不会漏建 Finding。
    """
    if ctx.candidate_resource_id is None or ctx.response_body is None:
        return False
    return _contains_value(ctx.response_body, ctx.candidate_resource_id)


def _skip_finding(ctx: SeverityContext) -> bool:
    """接口声明无需认证时，去掉或换错 Token 仍 2xx 不构成问题。"""
    return (
        str(ctx.auth_type or "none").lower() == "none"
        and ctx.mutation_type in _AUTH_MUTATION_TYPES
        and _is_2xx(ctx)
    )


def _table_lookup(ctx: SeverityContext) -> str | None:
    """§8 规则表。没有匹配返回 None（由调用方退回规则默认值）。"""
    last = _last_status(ctx.status_codes)
    if not 200 <= last < 300:
        return "MEDIUM" if ctx.classification == "UNEXPECTED_SERVER_ERROR" else None

    if ctx.mutation_type in _CROSS_RESOURCE_TYPES:
        return "CRITICAL" if _body_contains_candidate(ctx) else "HIGH"
    if ctx.mutation_type == "CROSS_PROJECT":
        return "HIGH"
    if ctx.mutation_type in _AUTH_MUTATION_TYPES:
        return "HIGH"
    if ctx.mutation_type == "METHOD_MUTATION":
        return "HIGH" if str(ctx.method or "").upper() == "DELETE" else "MEDIUM"
    if ctx.mutation_type in {"REPLAY_SAME_REQUEST", "DUPLICATE_SUBMIT"}:
        return "HIGH"
    if ctx.mutation_type in {"BUSINESS_STATE", "SEQUENCE_BYPASS"}:
        return "LOW" if str(ctx.method or "").upper() == "GET" else "HIGH"
    return None


def resolve_severity(ctx: SeverityContext) -> str | None:
    """算出应记录的严重级别；``None`` 表示不建 Finding。

    只有 ``UNEXPECTED_SERVER_ERROR`` 允许被规则上声明的更低默认值再降一档
    （§8「除非规则另有更低默认值」）；CRITICAL / HIGH 不被规则配置下调。
    """
    if _skip_finding(ctx):
        return None

    level = _table_lookup(ctx)
    if level is None:
        level = ctx.rule_severity if ctx.rule_severity in SEVERITY_LEVELS else DEFAULT_FINDING_SEVERITY

    rule_order = SEVERITY_ORDER.get(ctx.rule_severity or "")
    if (
        level == "MEDIUM"
        and ctx.classification == "UNEXPECTED_SERVER_ERROR"
        and rule_order is not None
        and rule_order < SEVERITY_ORDER["MEDIUM"]
    ):
        level = ctx.rule_severity
    return level
