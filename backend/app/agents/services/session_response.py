"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any


_WEB_STEP_SECRET_FIELDS = ("value", "expected", "upload")


_WEB_STEP_MASK = "[已脱敏]"


def redact_web_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 Web 步骤里承载真实值的字段掩掉，供 agent_message.metadata_json 落库。

    执行结果中的断言 actual / expected 也要掩，避免页面内容通过结果字段回显；运行日志
    已在 Playwright 层按会话秘密清洗。遮罩后仍保留 operation / locator / status 供页面展示。
    """
    masked: list[dict[str, Any]] = []
    for step in steps:
        # 非 dict 条目原样保留：预算守卫只数长度，不因类型问题炸掉整轮留痕。
        if not isinstance(step, dict):
            masked.append(step)
            continue
        item = dict(step)
        for field in _WEB_STEP_SECRET_FIELDS:
            if item.get(field) not in (None, ""):
                item[field] = _WEB_STEP_MASK
        result = item.get("result")
        if isinstance(result, dict) and any(result.get(k) for k in _WEB_STEP_SECRET_FIELDS):
            result = dict(result)
            for field in _WEB_STEP_SECRET_FIELDS:
                if result.get(field) not in (None, ""):
                    result[field] = _WEB_STEP_MASK
        elif isinstance(result, dict):
            result = dict(result)
        if isinstance(result, dict):
            # 断言实际值可能含页面个人信息，不能因字段名不是 value 而回显。
            assertions = result.get("assertions")
            if isinstance(assertions, list):
                result["assertions"] = [
                    {
                        **assertion,
                        **{
                            key: _WEB_STEP_MASK
                            for key in ("actual", "expected")
                            if assertion.get(key) not in (None, "")
                        },
                    }
                    if isinstance(assertion, dict) else assertion
                    for assertion in assertions
                ]
            item["result"] = result
        masked.append(item)
    return masked
