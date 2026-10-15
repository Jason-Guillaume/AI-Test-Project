"""前置条件评估器。

第一阶段支持：
- VARIABLE 类型：EQ / NE / IN / CONTAINS / EXISTS / NOT_EXISTS
- STATE 类型：EQ / NE / IN / CONTAINS

BUSINESS / TEXT 类型标记为 MANUAL / NOT_EXECUTABLE（第一阶段不自动执行）。
"""

from __future__ import annotations


class PreconditionResult:
    """前置条件评估结果。"""

    __slots__ = ("passed", "condition_id", "target", "reason")

    def __init__(self, passed: bool, condition_id: int | None = None,
                 target: str | None = None, reason: str | None = None):
        self.passed = passed
        self.condition_id = condition_id
        self.target = target
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "condition_id": self.condition_id,
            "target": self.target,
            "reason": self.reason,
        }


def evaluate_preconditions(
    preconditions: list[dict],
    context: dict[str, object],
) -> tuple[list[PreconditionResult], bool]:
    """评估所有前置条件。

    Args:
        preconditions: 前置条件列表，每项包含 id, type, target, operator, expected_value。
        context: 运行时上下文变量。

    Returns:
        (results, all_passed) 元组。
    """
    results: list[PreconditionResult] = []
    all_passed = True

    for pc in preconditions:
        pc_type = (pc.get("type") or "VARIABLE").upper()
        target = pc.get("target") or ""
        operator = (pc.get("operator") or "EQ").upper()
        expected_value = pc.get("expected_value")
        pc_id = pc.get("id")

        # BUSINESS / TEXT 类型不自动执行。
        if pc_type in ("BUSINESS", "TEXT"):
            results.append(PreconditionResult(
                passed=True,
                condition_id=pc_id,
                target=target,
                reason=f"{pc_type} 类型前置条件第一阶段不自动执行（MANUAL/NOT_EXECUTABLE）",
            ))
            continue

        # VARIABLE / STATE 类型：从 context 中查找 target 对应的值。
        actual_value = context.get(target)

        if operator in ("EXISTS", "NOT_EXISTS"):
            exists = actual_value is not None
            passed = exists if operator == "EXISTS" else not exists
        else:
            # 值比较：EQ / NE / IN / CONTAINS
            if actual_value is None:
                passed = operator == "NE"
            else:
                passed = _compare(actual_value, operator, expected_value)

        if not passed:
            all_passed = False
            results.append(PreconditionResult(
                passed=False,
                condition_id=pc_id,
                target=target,
                reason=f"前置条件不满足：{target} {operator} {expected_value}（实际值：{actual_value}）",
            ))
        else:
            results.append(PreconditionResult(
                passed=True,
                condition_id=pc_id,
                target=target,
            ))

    return results, all_passed


def _compare(actual: object, operator: str, expected: object) -> bool:
    """比较实际值与期望值。"""
    if operator == "EQ":
        return str(actual) == str(expected)
    if operator == "NE":
        return str(actual) != str(expected)
    if operator == "IN":
        expected_list = str(expected).split(",") if isinstance(expected, str) else [str(expected)]
        return str(actual) in [v.strip() for v in expected_list]
    if operator == "CONTAINS":
        return str(expected) in str(actual)
    return False
