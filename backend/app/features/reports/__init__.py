"""测试报告特性模块（接口测试 Agent Phase 2）。

职责范围：
- 维护正式测试报告（TestReport）数据模型与持久化；
- ReportBuilder 基于 TestRun + CaseExecution + AssertionResult 由代码统计汇总，
  LLM 仅负责总结 / 风险归纳 / 失败聚类 / 建议；
- 报告 API（生成 / 详情 / 列表 / 删除 / 重生成 AI 总结）；
- AI Summary 结构化输出（Pydantic 校验，失败不影响基础报告）。

未接入（属后续阶段）：PDF/Word/Excel 导出、匿名公网分享、跨项目聚合看板。
报告详情页实时读取 Report + TestRun + CaseExecution + Assertions，报告本身不复制执行明细。
"""
