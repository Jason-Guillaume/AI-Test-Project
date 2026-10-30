"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import json
from typing import Any
from app.features.business.models.execution import ActionExecution, FlowExecution
from app.features.test_management.executors.assertion_engine import required_all_passed


def build_response_dict(resp) -> dict[str, Any]:
    """构建响应字典。"""
    return {
        "status_code": resp.status_code,
        "headers": dict(resp.response_headers or {}),
        "body": try_parse_json(resp.response_body),
        "raw_body": resp.response_body or "",
        "response_time_ms": resp.response_time_ms,
    }


def build_flow_response(execution: FlowExecution, action_execs: list[ActionExecution]) -> dict[str, Any]:
    """把业务流执行结果合成成断言引擎可消费的响应字典。

    业务流用例通常断言：STATUS_CODE==200（流程成功）与 JSON_PATH（上下文变量）。
    """
    status_code = 200 if execution.status == "SUCCESS" else 500
    context = execution.context_json if isinstance(execution.context_json, dict) else {}
    total_ms = sum((ae.duration_ms or 0) for ae in action_execs)
    return {
        "status_code": status_code,
        "headers": {},
        "body": context,
        "raw_body": json.dumps(context, ensure_ascii=False, default=str),
        "response_time_ms": total_ms,
    }


def decide_status(resp, assertion_results: list[dict[str, Any]]) -> tuple[str, str | None, str | None]:
    """处理`decide`状态相关数据。"""
    if resp.error_message:
        if "超时" in resp.error_message:
            return "ERROR", "HTTP_TIMEOUT", resp.error_message
        return "ERROR", "HTTP_REQUEST_FAILED", resp.error_message
    if not resp.success:
        return "FAILED", "HTTP_REQUEST_FAILED", f"HTTP {resp.status_code}"
    if not required_all_passed(assertion_results):
        return "FAILED", "ASSERTION_FAILED", "断言未全部通过"
    return "PASSED", None, None


def decide_flow_status(
    execution: FlowExecution, assertion_results: list[dict[str, Any]],
) -> tuple[str, str | None, str | None]:
    """处理`decide`流程状态相关数据。"""
    if execution.status != "SUCCESS":
        return "FAILED", execution.error_code or "FLOW_FAILED", execution.error_message or "业务流程执行失败"
    if not required_all_passed(assertion_results):
        return "FAILED", "ASSERTION_FAILED", "断言未全部通过"
    return "PASSED", None, None


def try_parse_json(text: str) -> object:
    """尝试将响应文本解析为 JSON；解析失败时返回空结果。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
