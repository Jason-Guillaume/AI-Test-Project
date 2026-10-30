"""领域路由唯一聚合入口；由 main.py 挂载一次。"""

from __future__ import annotations

from fastapi import APIRouter
from .test_strategies import router as test_strategies_router
from .test_points import router as test_points_router
from .test_cases import router as test_cases_router
from .test_case_preconditions import router as test_case_preconditions_router
from .test_case_data import router as test_case_data_router
from .test_steps import router as test_steps_router
from .test_assertions import router as test_assertions_router
from .test_suites import router as test_suites_router
from .test_suite_cases import router as test_suite_cases_router
from .test_plans import router as test_plans_router
from .test_plan_suites import router as test_plan_suites_router
from .test_runs import router as test_runs_router


router = APIRouter(tags=["测试管理"])


router.include_router(test_strategies_router)


router.include_router(test_points_router)


router.include_router(test_cases_router)


router.include_router(test_case_preconditions_router)


router.include_router(test_case_data_router)


router.include_router(test_steps_router)


router.include_router(test_assertions_router)


router.include_router(test_suites_router)


router.include_router(test_suite_cases_router)


router.include_router(test_plans_router)


router.include_router(test_plan_suites_router)


router.include_router(test_runs_router)
