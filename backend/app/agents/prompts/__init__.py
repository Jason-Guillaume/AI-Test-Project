"""Agent prompt 模板：版本常量 + 加载器。

prompt 为纯文本常量（系统指令），与业务数据隔离（§35）：节点把 prompt 作为
system role，业务上下文作为 user content。版本号用于追溯生成的资产（generation_version）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent

# prompt 版本号（写入 test_point/test_case.generation_version 用于追溯）。
TEST_INTENT_PROMPT_V1 = "intent-v1"
# V2：意图枚举加入 INTERACTIVE_WEB_AUTHORING（Web 智能体二期）。分类器契约变化，
# 旧版 intent.md 不收录该意图，会让 observe→decide→act 链路在生产环境不可达。
TEST_INTENT_PROMPT_V2 = "intent-v2"
# V3：加入 REQUEST_SECURITY_SCAN 意图和 ZAP 计划人工确认约束。
TEST_INTENT_PROMPT_V3 = "intent-v3"
TEST_POINT_PROMPT_V1 = "point-v1"
TEST_CASE_PROMPT_V1 = "case-v1"
TEST_RESULT_ANALYSIS_PROMPT_V1 = "result-v1"
# Phase 2 二轮：Web 智能体页面决策（observe→decide→act 循环）。
WEB_DECIDE_PROMPT_V1 = "web_decide-v1"

_PROMPT_FILES = {
    "intent": "intent.md",
    "test_point": "test_point.md",
    "test_case": "test_case.md",
    "result_analysis": "result_analysis.md",
    "web_decide": "web_decide.md",
}


@lru_cache(maxsize=8)
def load_prompt(name: str) -> str:
    """按名称加载 prompt 全文（缓存）。未知名称抛 KeyError。"""
    filename = _PROMPT_FILES[name]
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")
