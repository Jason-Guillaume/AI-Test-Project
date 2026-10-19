"""候选资源解析：从 Fixture 输出取「另一个用户 / 另一个项目的资源」。

Cross User / Cross Project / Role Downgrade / Resource Owner Change / IDOR 的数据
只有一个来源——已经注入的 Fixture 输出契约（`resolve_template` 解析后的
`ResolveScope`）。这里故意没有第二条数据来源：

- 不猜 ID：不用随机数、不用「当前 ID ± 1」、不用平台自己的 ``project_id``；
- 不读 ``data_pool_item``，不调 Provider，不创建或修改平台用户；
- 候选必须来自另一个 Fixture（例如 ``USER_B.token``、``TASK_B.task_id``）。

「拿不到候选」分两种，调用方（Phase E 的 Runner）按错误码区分处理：

- ``RuleNotApplicableError``（``SECURITY_MUTATION_INVALID``）：规则没有点名候选。
  配置缺陷，该规则跳过。
- ``AppError(SECURITY_FIXTURE_REQUIRED)``：规则点名的 Fixture 没有产出该输出。
  测试数据缺口，Runner 把这条变异记 ``INCONCLUSIVE``、``error_code`` 写
  ``SECURITY_FIXTURE_REQUIRED``，且不建 Finding（§10）。
"""

from __future__ import annotations

from typing import Any

from app.shared.errors import (
    CODE_SECURITY_FIXTURE_REQUIRED,
    CODE_SECURITY_MUTATION_INVALID,
    AppError,
)

from app.features.security_testing.runtime.types import MutationRuleView, ResolveScope, RuleNotApplicableError

__all__ = [
    "Source",
    "parse_source",
    "resolve_value",
    "read_sources",
    "resource_target",
]

#: ``mutation_config`` 里放候选来源的键名。前两个是主形态，``candidates`` 是并列写法。
TOKEN_SOURCE_KEY = "token_source"
RESOURCE_SOURCE_KEY = "resource_source"
CANDIDATES_KEY = "candidates"

#: 资源替换只允许落在这三个位置；鉴权头走 token 侧，不走资源侧。
RESOURCE_LOCATIONS = ("PATH", "QUERY", "BODY")

#: 输出名里出现这些词就认为它是一把 Token，用来在 ``candidates`` 里区分身份侧与资源侧。
_TOKEN_HINTS = ("token", "jwt", "credential", "auth")


#: 规范化后的候选来源：``{"fixture_key": "USER_B", "output": "token"}``。
Source = dict[str, str]


def parse_source(value: Any, *, label: str = "候选来源") -> Source | None:
    """把 ``mutation_config`` 里的候选来源读成规范化 dict。

    形状不对或缺 ``fixture_key`` / ``output`` 时返回 ``None``：这表示规则没有
    点名候选，属于「跳过」而不是「崩溃」，由调用方决定是报错还是继续看另一个来源。
    """
    if not isinstance(value, dict):
        return None
    fixture_key = str(value.get("fixture_key") or "").strip()
    output = str(value.get("output") or "").strip()
    if not fixture_key or not output:
        return None
    return {"fixture_key": fixture_key, "output": output}


def resolve_value(source: Source | None, scope: ResolveScope, *, label: str) -> Any:
    """取一个候选值；拿不到就抛 ``SECURITY_FIXTURE_REQUIRED``。

    这里不做任何「找补」：不会退回随机值、当前值 ±1、平台 project.id，也不会从
    平台用户表里取一个 Token。缺数据就是缺数据，让上层记 INCONCLUSIVE。
    """
    if source is None:
        raise RuleNotApplicableError(
            f"{label} 没有在 mutation_config 里点名（需要 fixture_key + output）",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    value = scope.get(source)
    if value is None or (isinstance(value, str) and not str(value).strip()):
        raise AppError(
            f"{label} 需要 Fixture {source['fixture_key']}.{source['output']} 的输出，"
            f"测试数据里没有（不猜 ID，不用当前值 ±1，不用平台 project.id）",
            code=CODE_SECURITY_FIXTURE_REQUIRED,
        )
    return value


def _looks_like_token(output: str) -> bool:
    """按输出名判断这是否是一把 Token（``candidates`` 里据此分流）。"""
    lowered = str(output or "").lower()
    return any(hint in lowered for hint in _TOKEN_HINTS)


def read_sources(rule: MutationRuleView) -> tuple[Source | None, Source | None]:
    """读出 ``(token 侧候选, 资源侧候选)``。

    优先用显式的 ``token_source`` / ``resource_source``；两者都没写时才看
    ``candidates`` 列表，其中输出名像 Token 的进身份侧，其余进资源侧。
    """
    config = rule.mutation_config or {}
    token = parse_source(config.get(TOKEN_SOURCE_KEY))
    resource = parse_source(config.get(RESOURCE_SOURCE_KEY))

    if token is None and resource is None:
        candidates = config.get(CANDIDATES_KEY)
        if isinstance(candidates, list):
            for item in candidates:
                source = parse_source(item)
                if source is None:
                    continue
                if token is None and _looks_like_token(source["output"]):
                    token = source
                elif resource is None:
                    resource = source
    return token, resource


def _resource_location_and_field(rule: MutationRuleView) -> tuple[str, str]:
    """资源替换的位置与字段名：``mutation_config`` 优先，其次规则列上的值。"""
    config = rule.mutation_config or {}
    location = str(config.get("location") or rule.target_location or "").upper()
    field = str(config.get("field") or rule.target_field or "").strip()
    return location, field


def resource_target(rule: MutationRuleView, scope: ResolveScope, *, label: str) -> tuple[str, str, Any]:
    """解析「替换哪个位置的哪个字段、替换成什么值」。

    Returns:
        ``(location, field, value)``，其中 location 必为 PATH / QUERY / BODY。

    Raises:
        RuleNotApplicableError: 没点名资源候选，或没点名 location / field。
        AppError: 点名的 Fixture 没有产出该输出（``SECURITY_FIXTURE_REQUIRED``）。
    """
    _, resource = read_sources(rule)
    value = resolve_value(resource, scope, label=label)

    location, field = _resource_location_and_field(rule)
    if location not in RESOURCE_LOCATIONS or not field:
        raise RuleNotApplicableError(
            f"{rule.mutation_type} 需要在 mutation_config 里点名 location（PATH/QUERY/BODY）与 field",
            code=CODE_SECURITY_MUTATION_INVALID,
        )
    return location, field, value
