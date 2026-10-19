"""安全计划项生成：把策略规则展开成预览清单里的条目。

这些函数只读业务侧配置（BusinessAction / BusinessState / BusinessRule）并产出
普通 dict，形状就是 §16.3 的 preview item。不写库、不调用 ``execute_flow``，
跳步也不会给它加 ``skip_ids``：计划项直接指向「被跳过步骤之后」的那个 Action，
前置数据交给 Fixture 准备。

本模块不 import ORM（用 dict / ORM 行都能读），也不查库：``available_fixtures``
由调用方从已经解析好的作用域传进来。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.features.security_testing.runtime.replay import (
    REPLAY_COUNT_KEY,
    REPLAY_INTERVAL_KEY,
    read_replay_params,
)

__all__ = [
    "FIXTURE_REQUIRED",
    "WRITE_METHODS",
    "SAFE_METHODS",
    "ALWAYS_CONFIRMED_TYPES",
    "WRITE_METHOD_TYPES",
    "DUPLICATE_ACTION_HINTS",
    "IDEMPOTENCY_RULE_TYPES",
    "HIGH_RISK_LEVELS",
    "default_state_fixture_key",
    "next_action",
    "is_duplicate_candidate",
    "fixture_gap",
    "needs_confirmation",
    "item_name",
    "build_item",
    "replay_item",
    "duplicate_submit_item",
    "business_state_item",
    "sequence_bypass_item",
]

#: 计划项缺 Fixture 时标记的原因，Runner 执行时记 SKIPPED。
FIXTURE_REQUIRED = "SECURITY_FIXTURE_REQUIRED"

#: 会改动被测系统的方法。
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
#: 只读方法：这些方法上的策略不要求确认。
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

#: §18.4：无论方法是什么都必须人工确认的变异类型。
ALWAYS_CONFIRMED_TYPES = ("REPLAY_SAME_REQUEST", "DUPLICATE_SUBMIT")
#: §18.4：目标方法不是 GET 时必须确认的变异类型。
WRITE_METHOD_TYPES = ("BUSINESS_STATE", "SEQUENCE_BYPASS")

#: 创建 / 提交 / 支付类动作的关键字；DUPLICATE_SUBMIT 只挂到这些动作上。
DUPLICATE_ACTION_HINTS = ("CREATE", "SUBMIT", "PAY", "ORDER", "SAVE", "ADD", "INSERT")

#: ``business_rule.rule_type`` 含这些值表示该动作声明了幂等语义。
IDEMPOTENCY_RULE_TYPES = ("IDEMPOTENCY", "IDEMPOTENT")

#: §18.4：策略级别高到需要确认的值。
HIGH_RISK_LEVELS = ("HIGH", "CRITICAL")

#: 规则与策略上声明的默认级别。
DEFAULT_SEVERITY = "MEDIUM"


def _get(row: Any, name: str, default: Any = None) -> Any:
    """同时接受 ORM 行与 dict 的取值。"""
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _upper(value: Any) -> str:
    return str(value or "").upper()


def default_state_fixture_key(state: Any) -> str:
    """终态 Fixture 的默认键：``{POST_STATE}_{ENTITY}``，例如 ``SUCCESS_TASK``。"""
    post = _upper(_get(state, "post_state")).strip()
    entity = _upper(_get(state, "entity")).strip()
    return f"{post}_{entity}" if post and entity else ""


def _action_sort(action: Any) -> int:
    value = _get(action, "sort")
    return int(value) if isinstance(value, (int, float)) else 0


def next_action(skipped: Any, actions: Sequence[Any] | None) -> Any | None:
    """被跳过步骤之后的第一个动作（sort 更靠后）；没有则返回 None。"""
    floor = _action_sort(skipped)
    later = [action for action in (actions or []) if _action_sort(action) > floor]
    if not later:
        return None
    return min(later, key=_action_sort)


def is_duplicate_candidate(action_key: Any, rule_types: Iterable[Any] | None = ()) -> bool:
    """DUPLICATE_SUBMIT 的候选判定：创建/提交/支付类动作，或幂等规则点名的动作。"""
    key = _upper(action_key)
    if any(hint in key for hint in DUPLICATE_ACTION_HINTS):
        return True
    return any(_upper(rule_type) in IDEMPOTENCY_RULE_TYPES for rule_type in (rule_types or ()))


def fixture_gap(
    mutation_config: Mapping[str, Any] | None,
    available_fixtures: Iterable[str] | None,
) -> str | None:
    """计划项点名了 Fixture 但当前作用域拿不到时给出 blocked_reason。

    ``available_fixtures`` 为 None 表示「还不知道有哪些 Fixture」（预览阶段），
    此时不阻断；已知集合（包括空集）才判断缺口。真执行时缺数据由引擎按
    ``SECURITY_FIXTURE_REQUIRED`` 记 INCONCLUSIVE，不建 Finding。
    """
    if available_fixtures is None:
        return None
    available = {_upper(key) for key in available_fixtures}
    config = mutation_config or {}
    needed: list[str] = []
    for source_key in ("token_source", "resource_source"):
        source = config.get(source_key)
        if isinstance(source, dict) and source.get("fixture_key"):
            needed.append(_upper(source["fixture_key"]))
    candidates = config.get("candidates")
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict) and item.get("fixture_key"):
                needed.append(_upper(item["fixture_key"]))
    if config.get("fixture_key"):
        needed.append(_upper(config["fixture_key"]))
    return FIXTURE_REQUIRED if any(key not in available for key in needed) else None


def needs_confirmation(
    *,
    mutation_type: str,
    method: str | None,
    confirmation_required: bool | None = None,
    strategy_risk_level: str | None = None,
) -> bool:
    """§18.4：这些计划项生成时 ``confirmation_required=true``。

    Args:
        mutation_type: 变异类型。
        method: 变异后的目标方法（METHOD_MUTATION 传目标方法，BUSINESS_STATE 传
            该动作的方法）。
        confirmation_required: 规则自己声明的确认标记。
        strategy_risk_level: 策略级别；HIGH / CRITICAL 且方法不是 GET 时也要确认。
    """
    if confirmation_required:
        return True
    target = _upper(method)
    if mutation_type == "METHOD_MUTATION" and target == "DELETE":
        return True
    if mutation_type in ALWAYS_CONFIRMED_TYPES:
        return True
    if mutation_type in WRITE_METHOD_TYPES and target != "GET":
        return True
    if _upper(strategy_risk_level) in HIGH_RISK_LEVELS and target not in SAFE_METHODS:
        return True
    return False


def item_name(target: Any, mutation_type: str, field: str | None = None) -> str:
    """计划项名：``{基线名}-{mutation_type}-{字段}``。"""
    label = str(target or "目标") or "目标"
    suffix = str(mutation_type or "")
    if field:
        suffix = f"{suffix}-{field}"
    return f"{label}-{suffix}"


def build_item(
    *,
    index: int,
    mutation_type: str,
    target: Any,
    method: str | None = None,
    rule: Any = None,
    strategy: Any = None,
    target_type: str = "API",
    api_id: Any = None,
    business_action_id: Any = None,
    mutation_config: Mapping[str, Any] | None = None,
    available_fixtures: Iterable[str] | None = None,
    blocked_reason: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    """组装一条预览计划项，形状见 §16.3。

    ``severity`` 是规则声明的默认级别（严重级别表的回退值），``risk_level`` 是策略
    级别（供预览展示与 §18.4 的确认判定）。
    """
    config = dict(mutation_config or {})
    field_name = str(field or config.get("field") or "") or None
    rule_severity = str(_get(rule, "severity") or DEFAULT_SEVERITY)
    strategy_risk = str(_get(strategy, "risk_level") or "")
    return {
        "index": index,
        "name": item_name(target, mutation_type, field_name),
        "mutation_type": str(mutation_type),
        "target_type": str(target_type or "API"),
        "api_id": api_id,
        "business_action_id": business_action_id,
        "method": _upper(method) or None,
        "location": _upper(config.get("location")) or None,
        "field": field_name,
        "expectation": str(_get(rule, "expected_security_behavior") or "EXPECTED_DENY"),
        "expected_status_codes": _get(rule, "expected_status_codes"),
        "severity": rule_severity,
        "risk_level": strategy_risk or rule_severity,
        "confirmation_required": needs_confirmation(
            mutation_type=mutation_type,
            method=method,
            confirmation_required=bool(_get(rule, "confirmation_required") or False),
            strategy_risk_level=strategy_risk,
        ),
        "blocked_reason": blocked_reason or fixture_gap(config, available_fixtures),
        "mutation_config": config,
        "source_rule_id": _get(rule, "id"),
        "source_strategy_id": _get(strategy, "id"),
    }


def replay_item(
    *,
    rule: Any,
    target: Any,
    index: int = 0,
    method: str | None = None,
    strategy: Any = None,
    target_type: str = "API",
    api_id: Any = None,
    business_action_id: Any = None,
    available_fixtures: Iterable[str] | None = None,
) -> dict[str, Any]:
    """``REPLAY_SAME_REQUEST`` 计划项：次数与间隔夹进允许范围后再快照。"""
    config = dict(_get(rule, "mutation_config") or {})
    count, interval_ms = read_replay_params(config)
    config[REPLAY_COUNT_KEY] = count
    config[REPLAY_INTERVAL_KEY] = interval_ms
    return build_item(
        index=index,
        mutation_type="REPLAY_SAME_REQUEST",
        target=target,
        method=method,
        rule=rule,
        strategy=strategy,
        target_type=target_type,
        api_id=api_id,
        business_action_id=business_action_id,
        mutation_config=config,
        available_fixtures=available_fixtures,
    )


def duplicate_submit_item(
    *,
    rule: Any,
    action: Any,
    rule_types: Iterable[Any] | None = (),
    index: int = 0,
    method: str | None = None,
    strategy: Any = None,
    business_action_id: Any = None,
    available_fixtures: Iterable[str] | None = None,
) -> dict[str, Any] | None:
    """``DUPLICATE_SUBMIT`` 计划项。

    只挂到创建 / 提交 / 支付类动作，或 ``business_rule.rule_type`` 为 IDEMPOTENCY
    的动作。不是候选返回 None。``business_rule.expression`` 不解析。
    """
    if not is_duplicate_candidate(_get(action, "action_key"), rule_types):
        return None
    config = dict(_get(rule, "mutation_config") or {})
    count, interval_ms = read_replay_params(config)
    config[REPLAY_COUNT_KEY] = count
    config[REPLAY_INTERVAL_KEY] = interval_ms
    return build_item(
        index=index,
        mutation_type="DUPLICATE_SUBMIT",
        target=_get(action, "name"),
        method=method,
        rule=rule,
        strategy=strategy,
        target_type="BUSINESS_ACTION",
        business_action_id=business_action_id or _get(action, "id"),
        mutation_config=config,
        available_fixtures=available_fixtures,
    )


def business_state_item(
    *,
    rule: Any,
    action: Any,
    state: Any,
    index: int = 0,
    method: str | None = None,
    strategy: Any = None,
    business_action_id: Any = None,
    available_fixtures: Iterable[str] | None = None,
) -> dict[str, Any] | None:
    """``BUSINESS_STATE`` 计划项：用终态 Fixture 再调用同一个动作。

    ``post_state`` 有值才生成；fixture_key 由规则配置，缺省用
    ``{POST_STATE}_{ENTITY}``。拿不到 Fixture 时 ``blocked_reason`` 为
    ``SECURITY_FIXTURE_REQUIRED``，但计划项仍然保留（保存为禁用用例）。
    """
    if not str(_get(state, "post_state") or "").strip():
        return None
    config = dict(_get(rule, "mutation_config") or {})
    entity = _upper(_get(state, "entity"))
    if entity:
        config.setdefault("state_entity", entity)
    config["fixture_key"] = str(config.get("fixture_key") or default_state_fixture_key(state))
    if not config["fixture_key"]:
        return None
    return build_item(
        index=index,
        mutation_type="BUSINESS_STATE",
        target=_get(action, "name"),
        method=method,
        rule=rule,
        strategy=strategy,
        target_type="BUSINESS_ACTION",
        business_action_id=business_action_id or _get(action, "id"),
        mutation_config=config,
        available_fixtures=available_fixtures,
    )


def sequence_bypass_item(
    *,
    rule: Any,
    skipped_action: Any,
    actions: Sequence[Any] | None,
    index: int = 0,
    method: str | None = None,
    strategy: Any = None,
    skipped_state: Any = None,
    available_fixtures: Iterable[str] | None = None,
) -> dict[str, Any] | None:
    """``SEQUENCE_BYPASS`` 计划项：目标是「被跳过步骤之后」的那个 Action。

    不给 ``execute_flow`` 增加 ``skip_ids``，也不计划一整条 Flow：计划项的
    ``business_action_id`` 直接指向后置动作，前置数据由 Fixture 准备。被跳过的
    动作没有终态 Fixture 时，计划项标记 blocked（执行时 SKIPPED）。

    ``skipped_action`` 之后没有更靠后的步骤时返回 None：跳不过任何东西。
    """
    target_action = next_action(skipped_action, actions)
    if target_action is None:
        return None
    config = dict(_get(rule, "mutation_config") or {})
    config["skipped_action_id"] = _get(skipped_action, "id")
    if skipped_state is not None:
        config.setdefault("fixture_key", default_state_fixture_key(skipped_state))
    return build_item(
        index=index,
        mutation_type="SEQUENCE_BYPASS",
        target=_get(target_action, "name"),
        method=method,
        rule=rule,
        strategy=strategy,
        target_type="BUSINESS_ACTION",
        business_action_id=_get(target_action, "id"),
        mutation_config=config,
        available_fixtures=available_fixtures,
    )
