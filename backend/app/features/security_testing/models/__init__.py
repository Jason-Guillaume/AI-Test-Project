"""Security Testing ORM 模型（Phase 1）。

安全测试解决「一条正常请求变异成什么、变异后算不算有问题」，与功能用例严格分层：
安全用例本体仍是 test_case（case_type='SECURITY'），本包只存扩展数据，不给
test_case / case_execution / test_run / test_report / environment 加列。

七张 feature-local 表，不进 app/models/__init__.py（红线 17），由迁移 0011 显式建表：
- security_project_setting：项目级环境开关。allow_production 落库但不被执行器读取，
  生产永远拒绝，第一阶段不提供「管理员打开生产」的生效路径。
- security_strategy：策略。SYSTEM 模板 project_id 为空、builtin=true、禁止改规则体；
  PROJECT 自定义必须带 project_id。
- security_mutation_rule：结构化变异规则。算子白名单，mutation_config 禁止脚本键。
- security_plan：人工确认前的计划。preview_json 是未落 TestCase 的快照，不是第二套 TestRun。
- security_case：安全用例扩展数据，与 test_case 一对一。baseline_case_id 是追溯用的
  parent，不要在 test_case 上再加 parent_case_id。
- security_execution：一次 CaseExecution 至多一行，承载基线结论、变异 trace（脱敏）
  与五态安全结论。case_execution.status 仍走现有四态映射。
- security_finding：疑似问题。fingerprint 部分唯一索引只对 OPEN / CONFIRMED 生效，
  误报之后允许再开一条新的 OPEN。bug_id 故意不加 FK（Phase 1 不自动建缺陷）。
"""

from app.features.security_testing.models.execution import SecurityExecution
from app.features.security_testing.models.finding import SecurityFinding
from app.features.security_testing.models.plan import SecurityPlan
from app.features.security_testing.models.project_setting import SecurityProjectSetting
from app.features.security_testing.models.rule import SecurityMutationRule
from app.features.security_testing.models.security_case import SecurityCase
from app.features.security_testing.models.strategy import SecurityStrategy

__all__ = [
    "SecurityCase",
    "SecurityExecution",
    "SecurityFinding",
    "SecurityMutationRule",
    "SecurityPlan",
    "SecurityProjectSetting",
    "SecurityStrategy",
]
