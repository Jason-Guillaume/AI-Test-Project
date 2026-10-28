"""Regression tests for runtime headers in business-flow API actions."""
from app.features.business.executors.business_flow_executor import _merge_action_headers
from app.features.business.executors.context import ExecutionContext


def test_action_headers_include_runtime_context_and_respect_overrides():
    ctx = ExecutionContext({"__web_headers": {"X-Mock-Context": "run-1", "X-Override": "runtime"}})
    headers = _merge_action_headers(ctx, {"X-Override": "environment"}, {"X-Override": "action"})
    assert headers == {"X-Mock-Context": "run-1", "X-Override": "action"}
    assert ctx.get("__web_headers")["X-Override"] == "runtime"


def test_action_headers_ignore_invalid_runtime_headers():
    assert _merge_action_headers(ExecutionContext({"__web_headers": "bad"}), {}, {}) == {}
