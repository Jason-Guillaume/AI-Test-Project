"""本领域路由使用的无状态服务装配；不拥有请求事务。"""

from __future__ import annotations

from app.features.security_testing.services.case_service import SecurityCaseService
from app.features.security_testing.services.execution_query_service import ExecutionQueryService
from app.features.security_testing.services.finding_service import FindingService
from app.features.security_testing.services.plan_service import PlanService
from app.features.security_testing.services.rule_service import SecurityRuleService
from app.features.security_testing.services.setting_service import SecuritySettingService
from app.features.security_testing.services.strategy_service import SecurityStrategyService


_SETTING = SecuritySettingService()


_STRATEGY = SecurityStrategyService()


_RULE = SecurityRuleService()


_PLAN = PlanService()


_CASE = SecurityCaseService()


_FINDING = FindingService()


_EXECUTION = ExecutionQueryService()
