"""测试报告 AI 总结生成（§九）。

LLM 只负责总结 / 风险解释 / 失败聚类 / 建议；统计字段一律由代码计算（§五）。
输入 payload 已由 ReportService._build_ai_payload 脱敏（§三一）。

失败策略：LLM 调用异常（LLMError）或 Pydantic 校验失败 → 返回 None；
ReportService 据此将 ai_summary 置空，报告仍 COMPLETED（§九）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from app.features.agent.prompts import load_prompt
from app.features.agent.providers.sanitizer import mask_secret_values
from app.features.reports.schemas import AISummary

logger = logging.getLogger(__name__)


def _scrub(value: Any) -> Any:
    """按「值形态」掩码 LLM 输出里的 webhook / 签名密钥（§22）。

    入参 payload 已脱敏，但 LLM 可能把脱敏前的原文或别处的凭证回显进总结文本；
    该文本随后会入库、进 GET /reports 响应、进飞书卡片，必须在入库前再掩一次。
    """
    if isinstance(value, str):
        return mask_secret_values(value)
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value

# 送给 LLM 的结构化输出 schema（描述性；生产 Provider 实际用 response_format=json_object，
# 真正强校验由下方 AISummary Pydantic 模型完成，双重保险）。
_AI_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "description": "总体结论"},
        "key_findings": {"type": "array", "items": {"type": "string"}, "description": "主要发现"},
        "potential_issues": {
            "type": "array", "items": {"type": "string"},
            "description": "疑似产品问题（需人工确认，不得写成「已发现 Bug」）",
        },
        "test_data_issues": {"type": "array", "items": {"type": "string"}, "description": "测试数据问题"},
        "environment_issues": {"type": "array", "items": {"type": "string"}, "description": "环境问题"},
        "recommendations": {"type": "array", "items": {"type": "string"}, "description": "改进建议"},
        "risk_summary": {"type": "string", "description": "风险解释（风险等级由代码决定）"},
    },
    "required": ["overview", "key_findings", "recommendations", "risk_summary"],
}


def generate_summary(provider: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    """调用 LLM 生成结构化报告总结。

    Args:
        provider: LLMProvider（Protocol）；测试可注入 FakeLLMProvider。
        payload: 已脱敏的报告数据（ReportService._build_ai_payload 产出）。

    Returns:
        校验通过的 AISummary dict（纯结构化字段）；LLM 失败 / 校验失败返回 None。
        返回 None 时调用方应将 ai_summary 置空、报告仍 COMPLETED（§九）。
    """
    system = load_prompt("report_summary")
    user_content = json.dumps(payload, ensure_ascii=False)
    try:
        raw = provider.generate_structured(
            system, user_content, _AI_SUMMARY_SCHEMA, kind="report_summary",
            validator=AISummary.model_validate,
        )
    except Exception as exc:  # noqa: BLE001 — LLMError 等一律兜底为 None，不外抛。
        logger.warning("报告 AI 总结 LLM 调用失败：%s", exc)
        return None
    if not isinstance(raw, dict):
        logger.warning("报告 AI 总结返回非对象：%r", type(raw).__name__)
        return None
    try:
        summary = AISummary.model_validate(raw)
    except ValidationError as exc:
        logger.warning("报告 AI 总结 Pydantic 校验失败：%s", exc)
        return None
    # 纯结构化字段入库；版本号由 ReportService 写入 report.ai_summary_version，避免冗余。
    data = summary.model_dump(mode="json")
    # LLM 输出可能是回显：按值形态再掩一次，确保凭证不落库、不进接口响应与飞书卡片。
    return {key: _scrub(val) for key, val in data.items()}
