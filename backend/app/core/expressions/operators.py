"""跨表达式比较的纯基础操作。

测试断言和 Web 比较共用历史运算语义；业务前置条件只复用文本与逗号列表原语并保留自身语义。
"""

from __future__ import annotations

from typing import Any


def comparison_text(value: Any, *, none_as_empty: bool = False) -> str:
    """把值转换为比较文本；调用方显式选择 None 是否映射为空串。"""
    if value is None and none_as_empty:
        return ""
    return str(value)


def split_csv_values(value: str, *, discard_empty: bool = False) -> list[str]:
    """拆分逗号分隔的比较值并逐项去除空白，按选项保留或丢弃空项。"""
    values = [item.strip() for item in value.split(",")]
    return [item for item in values if item] if discard_empty else values


def coerce_number(value: Any) -> float | None:
    """尝试把值转换为浮点数；布尔值沿用 Python 数值语义。"""
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


def compare_ordered(
    actual: Any,
    expected: Any,
    operator: str,
    *,
    actual_text: str,
    expected_text: str,
) -> bool:
    """执行 GT/GE/LT/LE 比较；双方可转数值时按数值比较，否则按领域文本比较。"""
    actual_number = coerce_number(actual)
    expected_number = coerce_number(expected)
    if actual_number is not None and expected_number is not None:
        left, right = actual_number, expected_number
    else:
        left, right = actual_text, expected_text
    if operator == "GT":
        return left > right
    if operator == "GE":
        return left >= right
    if operator == "LT":
        return left < right
    return left <= right


def evaluate_operator(actual: Any, expected: Any, operator: str) -> bool:
    """保留测试与 Web 断言的比较口径，包括 None、空 IN 项和未知操作符回退。"""
    op = (operator or "EQ").upper()
    actual_text = comparison_text(actual, none_as_empty=True)
    expected_text = comparison_text(expected, none_as_empty=True)
    if op == "EXISTS":
        return actual is not None
    if op == "NOT_EXISTS":
        return actual is None
    if op in ("GT", "GE", "LT", "LE"):
        return compare_ordered(
            actual, expected, op, actual_text=actual_text, expected_text=expected_text,
        )
    if op == "EQ":
        return actual_text == expected_text
    if op == "NE":
        return actual_text != expected_text
    if op == "IN":
        return actual_text in split_csv_values(expected_text, discard_empty=True)
    if op == "CONTAINS":
        return expected_text in actual_text
    # 测试与 Web 断言历史上未知操作符回退为相等；业务前置条件并不采用此回退。
    return actual_text == expected_text


__all__ = [
    "coerce_number", "compare_ordered", "comparison_text", "evaluate_operator", "split_csv_values",
]
