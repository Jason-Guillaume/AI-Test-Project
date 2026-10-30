"""测试管理服务层。"""

from app.features.test_management.services.case_service import CaseService
from app.features.test_management.services.plan_service import PlanService
from app.features.test_management.services.point_service import PointService
from app.features.test_management.services.run_service import RunService
from app.features.test_management.services.selected_case_run_service import create_test_run
from app.features.test_management.services.strategy_service import StrategyService
from app.features.test_management.services.suite_service import SuiteService

__all__ = [
    "CaseService",
    "PlanService",
    "PointService",
    "RunService",
    "create_test_run",
    "StrategyService",
    "SuiteService",
    "resolve_strategy_project_id",
    "resolve_point_project_id",
    "resolve_case_project_id",
    "resolve_suite_project_id",
    "resolve_plan_project_id",
    "resolve_run_project_id",
]

from app.features.test_management.services.access_service import (
    resolve_strategy_project_id,
    resolve_point_project_id,
    resolve_case_project_id,
    resolve_suite_project_id,
    resolve_plan_project_id,
    resolve_run_project_id,
)
