"""测试管理模块。

整合「测试资产」（TestStrategy / TestPoint / TestCase 及其前置条件、测试数据、
步骤、断言）与「测试管理」（TestSuite / TestPlan / TestRun / CaseExecution），
统一作为 Agent 未来生成测试点与测试用例的标准数据模型底座。

三层职责严格区分（与业务管理解耦）：
- Business Management：业务怎么运行
- Test Asset：需要测试什么、具体怎么验证
- Test Management：哪些测试何时执行、执行结果如何管理

执行复用契约（禁止重新实现）：
- API 类型 TestCase → ApiRequestExecutor（复用 httpx + 出站白名单）
- BUSINESS_FLOW 类型 TestCase → business.executors.business_flow_executor.execute_flow
- 敏感数据脱敏 → business.executors.sensitive.SensitiveDataMasker
- JSONPath 读取 → core.expressions；断言判定仍归 test_management

本阶段不接入 LLM / LangGraph / Agent；但所有资产表均预留 source_type=AI。
"""
