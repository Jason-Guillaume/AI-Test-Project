"""断言引擎（纯逻辑，无 IO）。

对一次执行的响应执行断言列表，返回逐条结果。断言类型：
- STATUS_CODE：HTTP 状态码
- JSON_PATH：响应体 JSONPath（path 字段，如 $.code）
- HEADER：响应头（source 字段为头名）
- RESPONSE_TIME：响应耗时（毫秒）
- CONTAINS / NOT_CONTAINS：响应体文本包含/不包含

operator ∈ {EQ, NE, GT, GE, LT, LE, IN, CONTAINS, EXISTS, NOT_EXISTS}。

JSONPath 提取复用 business.executors.mapping_resolver._jsonpath_extract（§29 复用契约），
不重新实现 JSONPath 解析。
"""

from __future__ import annotations

from typing import Any

from app.features.business.executors.mapping_resolver import _jsonpath_extract as jsonpath_extract


def _coerce_num(value: Any) -> float | None:
    """尝试转为数值；失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def evaluate_operator(actual: Any, expected: Any, operator: str) -> bool:
    """按操作符比较 actual 与 expected。

    - EQ/NE/IN/CONTAINS：字符串归一比较（与 precondition_evaluator 口径一致）。
    - GT/GE/LT/LE：数值比较（无法转数值时退化为字符串比较）。
    - EXISTS/NOT_EXISTS：基于 actual 是否为 None。
    """
    op = (operator or "EQ").upper()
    actual_str = "" if actual is None else str(actual)
    expected_str = "" if expected is None else str(expected)

    if op == "EXISTS":
        return actual is not None
    if op == "NOT_EXISTS":
        return actual is None

    if op in ("GT", "GE", "LT", "LE"):
        a_num = _coerce_num(actual)
        e_num = _coerce_num(expected)
        if a_num is not None and e_num is not None:
            if op == "GT":
                return a_num > e_num
            if op == "GE":
                return a_num >= e_num
            if op == "LT":
                return a_num < e_num
            return a_num <= e_num
        # 退化：字符串比较。
        if op == "GT":
            return actual_str > expected_str
        if op == "GE":
            return actual_str >= expected_str
        if op == "LT":
            return actual_str < expected_str
        return actual_str <= expected_str

    if op == "EQ":
        return actual_str == expected_str
    if op == "NE":
        return actual_str != expected_str
    if op == "IN":
        # 多值用逗号分隔。
        candidates = [c.strip() for c in expected_str.split(",") if c.strip()]
        return actual_str in candidates
    if op == "CONTAINS":
        return expected_str in actual_str
    if op == "NOT_EXISTS":
        return actual is None
    # 未知操作符默认 EQ。
    return actual_str == expected_str


def _extract_actual(response: dict[str, Any], assertion: dict[str, Any]) -> Any:
    """根据断言类型从响应中提取实际值。"""
    atype = (assertion.get("assertion_type") or "STATUS_CODE").upper()
    if atype == "STATUS_CODE":
        return response.get("status_code")
    if atype == "RESPONSE_TIME":
        return response.get("response_time_ms")
    if atype == "HEADER":
        headers = response.get("headers") or {}
        name = assertion.get("source") or ""
        # 头名大小写不敏感查找。
        lower = {str(k).lower(): v for k, v in headers.items()}
        return lower.get(str(name).lower())
    if atype == "JSON_PATH":
        body = response.get("body")
        path = assertion.get("path") or ""
        if not path:
            return None
        return jsonpath_extract(body, path) if body is not None else None
    if atype in ("CONTAINS", "NOT_CONTAINS"):
        return response.get("raw_body") or ""
    return None


def run_assertions(assertions: list[dict[str, Any]], response: dict[str, Any]) -> list[dict[str, Any]]:
    """对响应执行断言列表，返回逐条结果。

    Args:
        assertions: 断言字典列表，每项含 id/assertion_type/source/path/operator/
            expected_value/required。
        response: 响应字典，含 status_code/headers/body(已解析对象或 None)/
            raw_body(字符串)/response_time_ms。

    Returns:
        结果列表，每项 {id, assertion_type, operator, passed, actual, expected,
        required, message}。
    """
    results: list[dict[str, Any]] = []
    for a in assertions:
        atype = (a.get("assertion_type") or "STATUS_CODE").upper()
        operator = a.get("operator") or "EQ"
        expected = a.get("expected_value")
        actual = _extract_actual(response, a)
        # CONTAINS/NOT_CONTAINS 是断言「类型」语义：actual=raw_body，比较 = 子串包含/不包含。
        # 不能走通用 evaluate_operator（NOT_CONTAINS 无对应 operator，默认 EQ 会错判）。
        actual_str = "" if actual is None else str(actual)
        expected_str = "" if expected is None else str(expected)
        if atype == "CONTAINS":
            passed = expected_str in actual_str
        elif atype == "NOT_CONTAINS":
            passed = expected_str not in actual_str
        else:
            passed = evaluate_operator(actual, expected, operator)
        results.append({
            "id": a.get("id"),
            "assertion_type": atype,
            "operator": operator,
            "passed": bool(passed),
            "actual": _stringify(actual),
            "expected": "" if expected is None else str(expected),
            "required": bool(a.get("required", True)),
            "message": _message(atype, operator, actual, expected, passed),
        })
    return results


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        import json
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _message(atype: str, operator: str, actual: Any, expected: Any, passed: bool) -> str:
    verb = "通过" if passed else "失败"
    actual_s = _stringify(actual) or "(空)"
    expected_s = "" if expected is None else str(expected)
    return f"{atype} {operator} {verb}：实际={actual_s}，期望={expected_s}"


def required_all_passed(results: list[dict[str, Any]]) -> bool:
    """所有 required 断言是否全部通过（软断言不阻断）。"""
    return all(r["passed"] for r in results if r.get("required"))
