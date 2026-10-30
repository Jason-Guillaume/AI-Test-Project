"""安全期望判定（纯函数）。

输入期望与实际结果，输出 ``security_result`` + ``classification`` + 一句中文结论。

结论只有五态（§5.6）：PASS / POTENTIAL_ISSUE / FAILED_EXECUTION / INCONCLUSIVE /
SKIPPED。不使用「已确认漏洞」这一态，也不引入 ``VULNERABLE``。

判定原则（§8）：状态码本身不够。2xx 只在「本应拒绝或本应校验失败」时构成疑似问题；
5xx 归 ``UNEXPECTED_SERVER_ERROR``，严重级别停在 MEDIUM；3xx 与无法从响应判断的
情况都记 INCONCLUSIVE，不建 Finding。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.http.errors import CODE_SECURITY_EXPECTATION_INVALID, AppError

from app.features.security_testing.runtime.types import MutationTraceEntry
from app.features.security_testing.schemas import SECURITY_EXPECTATIONS

__all__ = ["AssertionResult", "assert_expectation", "DEFAULT_DENY_CODES", "DEFAULT_VALIDATION_CODES"]

#: EXPECTED_DENY 的默认状态码集合。
DEFAULT_DENY_CODES = (401, 403, 404)
#: EXPECTED_VALIDATION_ERROR 的默认状态码集合。
DEFAULT_VALIDATION_CODES = (400, 422)
#: 响应里可能承载业务主键的字段名，用于比较两次执行是否产生了新结果。
_BUSINESS_ID_KEYS = ("id", "task_id", "resource_id", "record_id", "data_id")
_BUSINESS_WRAPPERS = ("data", "result", "item", "body")


@dataclass
class AssertionResult:
    """一次变异的判定结果。

    ``classification`` 为空表示没有可归类的细分原因（例如 EXPECTED_ALLOW 通过）。
    ``message`` 是固定的中文文案，不来自 LLM。
    """

    security_result: str
    classification: str | None = None
    message: str = ""


def _bucket(code: int) -> str:
    """状态码分段：2xx / 3xx / 4xx / 5xx / other。"""
    if 200 <= code < 300:
        return "2xx"
    if 300 <= code < 400:
        return "3xx"
    if 400 <= code < 500:
        return "4xx"
    if 500 <= code < 600:
        return "5xx"
    return "other"


def _codes_text(codes: list[int] | None) -> str:
    """期望状态码的中文写法，空列表显示「默认」。"""
    values = list(codes or [])
    if not values:
        return "默认"
    return "、".join(str(c) for c in values)


def _label(rule_name: str | None, mutation_type: str) -> str:
    """结论文案里的人类可读动作名，优先用规则名。"""
    return str(rule_name or mutation_type or "变异").strip() or "变异"


def _result(security_result: str, classification: str | None, message: str) -> AssertionResult:
    """根据断言条件生成断言结果。"""
    return AssertionResult(security_result=security_result, classification=classification, message=message)


def _pass(label: str, code: int, classification: str | None, expected_codes: list[int] | None = None) -> AssertionResult:
    """符合预期的结论；给了期望状态码就带上，便于 Finding 列表阅读。"""
    if expected_codes:
        return _result("PASS", classification, f"{label} 返回 {code}，符合预期（期望 {_codes_text(expected_codes)}）")
    return _result("PASS", classification, f"{label} 返回 {code}，符合预期")


def _deny_or_validation(
    expected: str,
    codes: list[int],
    *,
    label: str,
    response_body: Any,
    trace: list[MutationTraceEntry] | None,
    expected_status_codes: list[int] | None,
    baseline_auth_present: bool,
) -> AssertionResult:
    """EXPECTED_DENY 与 EXPECTED_VALIDATION_ERROR 的判定。

    只看最后一次执行的状态码：多条状态码属于重放场景，走 EXPECTED_IDEMPOTENT。
    """
    if not codes:
        return _result("INCONCLUSIVE", None, f"{label} 没有实际状态码，无法判断")
    code = codes[-1]
    bucket = _bucket(code)
    defaults = DEFAULT_DENY_CODES if expected == "EXPECTED_DENY" else DEFAULT_VALIDATION_CODES
    expected_set = set(expected_status_codes) if expected_status_codes else set(defaults)
    met_class = "EXPECTED_DENY_MET" if expected == "EXPECTED_DENY" else "EXPECTED_VALIDATION_MET"

    if code in expected_set:
        return _pass(label, code, met_class, list(expected_status_codes or defaults))

    if bucket == "5xx":
        return _result(
            "POTENTIAL_ISSUE", "UNEXPECTED_SERVER_ERROR",
            f"{label} 导致服务器错误（实际 {code}），期望 {_codes_text(list(expected_status_codes or defaults))}",
        )

    if bucket == "2xx":
        if expected == "EXPECTED_VALIDATION_ERROR":
            if _echoes_invalid(trace, response_body):
                return _result(
                    "POTENTIAL_ISSUE", "POTENTIAL_ISSUE",
                    f"{label} 返回 2xx 且响应回显了非法值，服务端可能未校验",
                )
            return _result(
                "INCONCLUSIVE", None,
                f"{label} 返回 2xx，响应里没有可判断是否采纳非法值的字段",
            )
        if not baseline_auth_present:
            return _result("INCONCLUSIVE", None, f"{label} 的基线本身没有鉴权头，无法下结论")
        return _result(
            "POTENTIAL_ISSUE", "POTENTIAL_ISSUE",
            f"{label} 返回 {code}，期望 {_codes_text(list(expected_status_codes or defaults))}",
        )

    if bucket == "3xx":
        return _result("INCONCLUSIVE", None, f"{label} 返回重定向 {code}，无法判断最终授权结果")

    return _result("INCONCLUSIVE", None, f"{label} 返回 {code}，无法判断是否被拒绝或校验")


def _assert_allow(codes: list[int], label: str) -> AssertionResult:
    """EXPECTED_ALLOW：本阶段只用于「低权限允许访问公开资源」这类正向场景。"""
    if not codes:
        return _result("INCONCLUSIVE", None, f"{label} 没有实际状态码，无法判断")
    code = codes[-1]
    if _bucket(code) == "2xx":
        return _result("PASS", None, f"{label}返回 {code}，符合预期")
    if _bucket(code) == "5xx":
        return _result("POTENTIAL_ISSUE", "UNEXPECTED_SERVER_ERROR",
                       f"{label}导致服务器错误（实际 {code}）")
    return _result("INCONCLUSIVE", None, f"{label}返回 {code}，期望允许访问")


def _assert_idempotent(
    codes: list[int],
    bodies: list[Any],
    label: str,
) -> AssertionResult:
    """EXPECTED_IDEMPOTENT：比较第二次执行是否产生了新的业务结果。"""
    if len(codes) < 2:
        return _result("INCONCLUSIVE", None, f"{label} 只执行了一次，无法比较幂等性")
    first, last = codes[0], codes[-1]
    first_body = bodies[0] if bodies else None
    last_body = bodies[-1] if bodies else None

    if _bucket(last) == "5xx":
        return _result("POTENTIAL_ISSUE", "UNEXPECTED_SERVER_ERROR",
                       f"{label} 第 {len(codes)} 次执行导致服务器错误（实际 {last}）")
    if last in (400, 409):
        return _result("PASS", "EXPECTED_IDEMPOTENT_MET",
                       f"{label} 第 {len(codes)} 次执行返回 {last}，没有产生新的业务结果")
    if _bucket(first) == "2xx" and _bucket(last) == "2xx":
        first_id = _extract_business_id(first_body)
        last_id = _extract_business_id(last_body)
        if first_id is None or last_id is None:
            return _result(
                "INCONCLUSIVE", None,
                f"{label} 两次都是 2xx，但响应里没有可比较的业务 ID",
            )
        if str(first_id) == str(last_id):
            return _result("PASS", "EXPECTED_IDEMPOTENT_MET",
                           f"{label} 两次执行返回同一个业务 ID（{first_id}），幂等")
        return _result(
            "POTENTIAL_ISSUE", "POTENTIAL_ISSUE",
            f"{label} 两次执行返回不同业务 ID（{first_id} → {last_id}），产生了新的业务结果",
        )
    return _result("INCONCLUSIVE", None, f"{label} 的状态码组合（{' → '.join(str(c) for c in codes)}）无法判断幂等性")


def _contains_key_value(node: Any, field: str | None, value: Any) -> bool:
    """递归查找「键名 == field 且值 == value」。"""
    if isinstance(node, dict):
        for key, item in node.items():
            if str(key) == str(field) and item == value:
                return True
            if _contains_key_value(item, field, value):
                return True
    elif isinstance(node, list):
        return any(_contains_key_value(item, field, value) for item in node)
    return False


def _echoes_invalid(trace: list[MutationTraceEntry] | None, response_body: Any) -> bool:
    """2xx 响应是否回显了变异进去的非法值。

    只有「回显了」才算真的接受了非法输入；否则 2xx 可能只是忽略了该字段。
    """
    if not isinstance(response_body, (dict, list)):
        return False
    for entry in trace or []:
        value = entry.after
        if value is None or isinstance(value, (dict, list)):
            continue
        if _contains_key_value(response_body, entry.field, value):
            return True
    return False


def _extract_business_id(body: Any) -> Any:
    """从响应里找业务主键；找不到返回 None。"""
    if isinstance(body, dict):
        for key in _BUSINESS_ID_KEYS:
            if key in body and body[key] is not None:
                return body[key]
        for wrapper in _BUSINESS_WRAPPERS:
            nested = body.get(wrapper)
            if isinstance(nested, (dict, list)):
                found = _extract_business_id(nested)
                if found is not None:
                    return found
    elif isinstance(body, list) and body:
        return _extract_business_id(body[0])
    return None


def assert_expectation(
    expected: str,
    status_codes: int | list[int],
    *,
    rule_name: str | None = None,
    mutation_type: str = "",
    response_body: Any = None,
    response_bodies: list[Any] | None = None,
    trace: list[MutationTraceEntry] | None = None,
    expected_status_codes: list[int] | None = None,
    auth_type: str = "none",
    baseline_auth_present: bool = True,
) -> AssertionResult:
    """判定一条变异结果。

    Args:
        expected: 安全期望（EXPECTED_DENY / EXPECTED_VALIDATION_ERROR /
            EXPECTED_ALLOW / EXPECTED_IDEMPOTENT）。
        status_codes: 实际状态码；单条变异传一个整数，重放传全部状态码。
        rule_name: 规则名，用于生成中文结论；为空时退回 mutation_type。
        mutation_type: 变异类型，用于区分认证类 5xx 与参数类 5xx 的文案。
        response_body: 最后一次执行的响应体。
        response_bodies: 重放场景下每次执行的响应体。
        trace: 变异 trace，用于判断 2xx 是否回显了非法值。
        expected_status_codes: 规则上点名的期望状态码。
        auth_type: 接口声明的鉴权类型；``none`` 表示接口本身不需要认证。
        baseline_auth_present: 基线请求是否带鉴权头。

    Returns:
        AssertionResult：五态结论 + 分类 + 中文文案。

    Raises:
        AppError: 期望取值不在白名单（``SECURITY_EXPECTATION_INVALID``）。
    """
    if expected not in SECURITY_EXPECTATIONS:
        raise AppError(f"不支持的安全期望：{expected}", code=CODE_SECURITY_EXPECTATION_INVALID)

    codes = [status_codes] if isinstance(status_codes, int) else list(status_codes or [])
    bodies = list(response_bodies or ([response_body] if response_body is not None else []))
    label = _label(rule_name, mutation_type)

    if expected == "EXPECTED_IDEMPOTENT":
        return _assert_idempotent(codes, bodies, label)
    if expected == "EXPECTED_ALLOW":
        return _assert_allow(codes, label)
    return _deny_or_validation(
        expected,
        codes,
        label=label,
        response_body=bodies[-1] if bodies else None,
        trace=trace,
        expected_status_codes=expected_status_codes,
        baseline_auth_present=baseline_auth_present,
    )
