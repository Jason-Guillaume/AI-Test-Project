"""测试报告服务层。

- report_service.ReportService：报告生成（ReportBuilder）/ 详情 / 列表 / 删除 / 重生成 AI 总结；
- ai_summary.generate_summary：LLM 结构化总结（Pydantic 校验，失败返回 None，不影响基础报告）。

统计字段一律由代码计算；LLM 只做总结 / 风险解释 / 失败聚类 / 建议（§五）。
"""
from app.features.reports.services.report_service import ReportService

__all__ = ["ReportService"]
