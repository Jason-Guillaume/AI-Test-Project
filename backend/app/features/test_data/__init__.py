"""测试数据中心 + Data Factory（feature-local）。

提供三层能力：
- 定义面：Fixture（业务状态配方）+ 输出契约 + 显式依赖；测试数据目录；数据池。
- 配置面：Data Provider（数据工厂）；被测库连接；数据库访问策略。
- 记录面：data_execution / fixture_execution / provider_execution，快照落库前统一脱敏。

约束（与业务执行器同层，不重复实现）：
- 被测目标 HTTP 出站只走 app.execution.http.executor.ApiRequestExecutor；
- 业务流程只走 business.executors.business_flow_executor（execute_flow / run_action）；
- 脱敏只走 business.executors.sensitive.SensitiveDataMasker；
- 环境解析只走 app.core.models.configuration.Environment。

本 feature 的 ORM 模型**不**加入 app/models/__init__.py，由 alembic/versions/0009
显式建表（feature-local 红线）。
"""
