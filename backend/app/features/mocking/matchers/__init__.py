"""Mock Matcher：路径匹配 + 请求匹配（Phase 1）。

两个职责：
- path_matcher：把请求 path 与 Endpoint 的 path 模式（支持 ``{param}``）匹配，提取路径参数。
  第一阶段只支持固定段与单段 ``{param}``，不支持复杂正则（§十）。
- request_matcher：按 Scenario 的 Matcher 规则（source/field/operator/expected_value）评估
  请求快照。操作符：EQ/NE/EXISTS/NOT_EXISTS/CONTAINS/IN/JSON_PATH_EQ/JSON_PATH_EXISTS（§八）。

JSONPath 匹配保留更严格的非法片段与存在性语义，不依赖 business 或 test_management 内部实现。
"""

from __future__ import annotations

from app.features.mocking.matchers.path_matcher import match_path
from app.features.mocking.matchers.request_matcher import (
    RequestSnapshot,
    evaluate_matchers,
)
from app.features.mocking.matchers.request_matcher import extract_jsonpath

__all__ = [
    "RequestSnapshot",
    "evaluate_matchers",
    "extract_jsonpath",
    "match_path",
]
