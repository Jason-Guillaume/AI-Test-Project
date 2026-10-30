"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from app.features.security_testing.runtime import candidate_resolver
from app.features.security_testing.runtime.types import MutationRuleView, ResolveScope


def candidate_value(config: dict[str, Any], outputs: dict[str, dict[str, Any]]) -> Any:
    """从 Fixture 输出取候选资源 ID，供严重级别表判断响应是否泄露它。

    取不到不影响判定本身，只影响严重级别（没有候选就没法说「泄露了它」）。
    """
    if not isinstance(config, dict):
        return None
    try:
        rule_view = MutationRuleView(
            mutation_type="", mutation_config=dict(config), target_location="", target_field=None
        )
        _location, _field, value = candidate_resolver.resource_target(
            rule_view, ResolveScope(fixtures=outputs), label="候选资源"
        )
        return value
    except Exception:  # noqa: BLE001 - 缺 Fixture 时按「无候选」继续。
        return None
