"""本领域路由使用的无状态服务装配；不拥有请求事务。"""

from __future__ import annotations

from app.features.test_management.services.case_service import CaseService
from app.features.test_management.services.plan_service import PlanService
from app.features.test_management.services.point_service import PointService
from app.features.test_management.services.run_service import RunService
from app.features.test_management.services.strategy_service import StrategyService
from app.features.test_management.services.suite_service import SuiteService


_STRATEGY = StrategyService()


_POINT = PointService()


_CASE = CaseService()


_SUITE = SuiteService()


_PLAN = PlanService()


_RUN = RunService()
