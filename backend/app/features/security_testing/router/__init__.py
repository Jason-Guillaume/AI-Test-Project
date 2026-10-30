"""领域路由唯一聚合入口；由 main.py 挂载一次。"""

from __future__ import annotations

from fastapi import APIRouter
from .security_setting import router as security_setting_router
from .security_strategies import router as security_strategies_router
from .security_rules import router as security_rules_router
from .security_plans import router as security_plans_router
from .security_cases import router as security_cases_router
from .security_runs import router as security_runs_router
from .security_executions import router as security_executions_router
from .security_findings import router as security_findings_router


router = APIRouter(tags=["Security 管理"])


router.include_router(security_setting_router)


router.include_router(security_strategies_router)


router.include_router(security_rules_router)


router.include_router(security_plans_router)


router.include_router(security_cases_router)


router.include_router(security_runs_router)


router.include_router(security_executions_router)


router.include_router(security_findings_router)
