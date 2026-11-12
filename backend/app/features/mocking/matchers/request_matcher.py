"""请求匹配：按 Scenario 的 Matcher 规则评估请求快照。

操作符（§八）：EQ / NE / EXISTS / NOT_EXISTS / CONTAINS / IN / JSON_PATH_EQ / JSON_PATH_EXISTS。
来源（§八）：METHOD / PATH / QUERY / HEADER / BODY。

- METHOD：field 忽略，与请求方法比较（大小写不敏感）。
- PATH：field 是路径参数名（path_matcher 已提取），与 expected_value 比较。
- QUERY：field 是查询参数名。
- HEADER：field 是请求头名（大小写、连字符 / 下划线不敏感）。
- BODY：field 是 JSONPath（``$.amount``）或点路径（``amount`` / ``user.id``）；
  JSON_PATH_* 操作符要求 field 以 ``$`` 开头。

JSONPath 自包含最小实现（``$.a.b`` / ``$.a[0].b`` / ``$``），不耦合其它 feature。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def extract_jsonpath(body: Any, expression: str) -> tuple[bool, Any]:
    """最小 JSONPath 提取：``$.a.b`` / ``$.a[0].b`` / ``$``。

    Returns:
        (是否存在, 值)。路径任何一段缺失返回 ``(False, None)``。
    """
    if not isinstance(expression, str) or not expression.startswith("$"):
        return False, None
    expr = expression[1:]
    if not expr:
        return True, body
    current: Any = body
    for part in _parse_parts(expr):
        if part is _INVALID_PART:
            return False, None
        if isinstance(part, int):
            if isinstance(current, list) and 0 <= part < len(current):
                current = current[part]
            else:
                return False, None
        else:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False, None
    return True, current


# 非法括号段（[foo] / [0:2] / []）的占位符。
# 之前解析失败是静默 pass——丢段会让 ``$.a[foo].b`` 退化成 ``$.a.b`` 命中兄弟键，
# 或让 ``$.items[0:2].id`` 退化成 ``$.items.id`` 命中整个 body，
# 直接造成 JSON_PATH_EXISTS / JSON_PATH_EQ 误命中不该命中的场景。
_INVALID_PART: object = object()


def _parse_parts(expr: str) -> list[str | int | object]:
    """把 ``.a[0].b`` 解析成 ``['a', 0, 'b']``。

    括号内容不是整数时追加 ``_INVALID_PART``，由 ``extract_jsonpath`` 整体判不存在，
    而不是丢弃这一段继续匹配。
    """
    parts: list[str | int | object] = []
    current = ""
    for ch in expr:
        if ch == ".":
            if current:
                parts.append(current)
            current = ""
        elif ch == "[":
            if current:
                parts.append(current)
            current = ""
        elif ch == "]":
            try:
                parts.append(int(current))
            except (ValueError, TypeError):
                parts.append(_INVALID_PART)
            current = ""
        else:
            current += ch
    if current:
        parts.append(current)
    return parts


def _dot_path(body: Any, path: str) -> tuple[bool, Any]:
    """点路径提取：``amount`` / ``user.id``（非 JSONPath）。"""
    current: Any = body
    for part in (path or "").split("."):
        if part == "":
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def _normalize_header(name: str) -> str:
    """规范化请求头。"""
    return (name or "").lower().replace("-", "_").replace(" ", "_")


@dataclass
class RequestSnapshot:
    """运行时请求的归一快照，供 Matcher 评估。

    path_params 来自 path_matcher；query / headers / method 来自运行时请求。
    headers 大小写不敏感查找（与 RequestContext 一致）。
    """

    method: str = ""
    path: str = ""
    path_params: dict[str, str] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None

    def header(self, name: str) -> tuple[bool, Any]:
        """按 HTTP 请求头名称读取对应的值。"""
        target = _normalize_header(name)
        for key, value in self.headers.items():
            if _normalize_header(key) == target:
                return True, value
        return False, None


def _resolve_field(snapshot: RequestSnapshot, source: str, field_name: str) -> tuple[bool, Any]:
    """按 source 取字段值，返回 (是否存在, 值)。"""
    src = (source or "").upper()
    if src == "METHOD":
        return True, (snapshot.method or "").upper()
    if src == "PATH":
        if field_name in snapshot.path_params:
            return True, snapshot.path_params[field_name]
        return False, None
    if src == "QUERY":
        if field_name in snapshot.query:
            return True, snapshot.query[field_name]
        return False, None
    if src == "HEADER":
        return snapshot.header(field_name)
    if src == "BODY":
        # JSONPath 优先；否则按点路径取顶层键。
        if field_name.startswith("$"):
            return extract_jsonpath(snapshot.body, field_name)
        return _dot_path(snapshot.body, field_name)
    return False, None


def _values_equal(actual: Any, expected: Any) -> bool:
    """宽松相等：bool/int/str 可跨类型比较，list/dict 走 ==。"""
    if actual == expected:
        return True
    # 字符串与数字跨类型比较：request 里 path/query 多为字符串。
    try:
        return str(actual) == str(expected)
    except (TypeError, ValueError):
        return False


def _contains(actual: Any, expected: Any) -> bool:
    """按指定运算符检查目标值是否包含给定内容。"""
    if isinstance(actual, (list, tuple, str, dict)):
        try:
            return expected in actual
        except TypeError:
            return False
    return _values_equal(actual, expected)


def _upper_expected(value: Any) -> Any:
    """METHOD 期望值归一：标量转大写，``IN`` 用的列表逐项转大写，其它原样返回。"""
    if isinstance(value, list):
        return [item.upper() if isinstance(item, str) else item for item in value]
    return value.upper() if isinstance(value, str) else value


def evaluate_matcher(snapshot: RequestSnapshot, matcher: Any) -> bool:
    """评估单条 Matcher 规则。

    Args:
        snapshot: 请求快照。
        matcher: 带 source / field / operator / expected_value 的对象（ORM 或 dict）。

    Returns:
        该规则是否成立。
    """
    source = getattr(matcher, "source", None) or (matcher.get("source") if isinstance(matcher, dict) else "")
    field_name = getattr(matcher, "field", None) or (matcher.get("field") if isinstance(matcher, dict) else "")
    operator = (getattr(matcher, "operator", None)
                or (matcher.get("operator") if isinstance(matcher, dict) else "")).upper()
    expected = (getattr(matcher, "expected_value", None)
                or (matcher.get("expected_value") if isinstance(matcher, dict) else None))

    exists, actual = _resolve_field(snapshot, source, field_name)
    # METHOD 比较大小写不敏感（见模块 docstring）：用户按 HTTP 习惯写 "get" / "Post"
    # 也要能命中。actual 已由 _resolve_field 归一成大写，这里同步归一 expected，
    # 否则 "get" 会静默不匹配、场景永远落回 default。
    if (source or "").upper() == "METHOD":
        actual = str(actual or "")
        expected = _upper_expected(expected)

    if operator == "EXISTS":
        return exists
    if operator == "NOT_EXISTS":
        return not exists
    if operator == "EQ":
        return exists and _values_equal(actual, expected)
    if operator == "NE":
        return (not exists) or not _values_equal(actual, expected)
    if operator == "CONTAINS":
        return exists and _contains(actual, expected)
    if operator == "IN":
        return exists and isinstance(expected, list) and any(
            _values_equal(actual, item) for item in expected
        )
    if operator == "JSON_PATH_EQ":
        # 与 EQ 同语义，但要求 field 为 JSONPath（已在 _resolve_field 处理）。
        return exists and _values_equal(actual, expected)
    if operator == "JSON_PATH_EXISTS":
        return exists
    # 未知操作符视为不匹配（安全默认）。
    return False


def evaluate_matchers(snapshot: RequestSnapshot, matchers: list[Any]) -> bool:
    """评估一个 Scenario 的全部启用 Matcher，全部成立才算匹配（AND 语义）。"""
    if not matchers:
        # 无规则的场景永远匹配（依赖 priority 排序与默认兜底）。
        return True
    return all(evaluate_matcher(snapshot, m) for m in matchers)


__all__ = [
    "RequestSnapshot",
    "evaluate_matcher",
    "evaluate_matchers",
    "extract_jsonpath",
]
