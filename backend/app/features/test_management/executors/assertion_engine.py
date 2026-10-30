"""断言引擎（纯逻辑，无 IO）。

对一次执行的响应执行断言列表，返回逐条结果。断言类型：
- STATUS_CODE：HTTP 状态码
- JSON_PATH：响应体 JSONPath（path 字段，如 $.code）
- HEADER：响应头（source 字段为头名）
- RESPONSE_TIME：响应耗时（毫秒）
- CONTAINS / NOT_CONTAINS：响应体文本包含/不包含

operator ∈ {EQ, NE, GT, GE, LT, LE, IN, CONTAINS, EXISTS, NOT_EXISTS}。

JSONPath 提取与 Web 比较使用 core.expressions 公开基础能力；断言类型与通过结论仍归本模块。
"""

from __future__ import annotations

from typing import Any

from app.core.expressions.operators import evaluate_operator
from app.core.expressions.paths import extract_jsonpath


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
        return extract_jsonpath(body, path) if body is not None else None
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
    """将断言实际值转换为可比较的字符串。"""
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
    """处理消息相关数据。"""
    verb = "通过" if passed else "失败"
    actual_s = _stringify(actual) or "(空)"
    expected_s = "" if expected is None else str(expected)
    return f"{atype} {operator} {verb}：实际={actual_s}，期望={expected_s}"


def required_all_passed(results: list[dict[str, Any]]) -> bool:
    """所有 required 断言是否全部通过（软断言不阻断）。"""
    return all(r["passed"] for r in results if r.get("required"))
