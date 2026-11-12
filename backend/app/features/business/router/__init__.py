"""领域路由唯一聚合入口；由 main.py 挂载一次。"""

from __future__ import annotations

from fastapi import APIRouter
from .business_domains import router as business_domains_router
from .business_flows import router as business_flows_router
from .business_actions import router as business_actions_router
from .business_preconditions import router as business_preconditions_router
from .business_variables import router as business_variables_router
from .business_states import router as business_states_router
from .business_bindings import router as business_bindings_router
from .business_api_mappings import router as business_api_mappings_router
from .business_variable_refs import router as business_variable_refs_router
from .business_rules import router as business_rules_router
from .business_executions import router as business_executions_router


router = APIRouter(tags=["业务管理"])


router.include_router(business_domains_router)


router.include_router(business_flows_router)


router.include_router(business_actions_router)


router.include_router(business_preconditions_router)


router.include_router(business_variables_router)


router.include_router(business_states_router)


router.include_router(business_bindings_router)


router.include_router(business_api_mappings_router)


router.include_router(business_variable_refs_router)


router.include_router(business_rules_router)


router.include_router(business_executions_router)
