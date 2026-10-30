"""报告领域提示词资源。

报告 AI 总结通过本包读取固定摘要指令；Agent 编排不拥有或加载报告私有提示词。
"""

from functools import lru_cache
from pathlib import Path

REPORT_SUMMARY_PROMPT_V1 = "summary-v1"
_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def load_report_summary_prompt() -> str:
    """读取并缓存报告摘要提示词全文。"""
    return (_PROMPTS_DIR / "report_summary.md").read_text(encoding="utf-8")


__all__ = ["REPORT_SUMMARY_PROMPT_V1", "load_report_summary_prompt"]
