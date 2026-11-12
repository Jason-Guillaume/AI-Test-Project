"""领域路由唯一聚合入口；由 main.py 挂载一次。"""

from __future__ import annotations

from fastapi import APIRouter
from .fixtures import router as fixtures_router
from .test_data_assets import router as test_data_assets_router
from .data_providers import router as data_providers_router
from .data_pools import router as data_pools_router
from .data_pool_items import router as data_pool_items_router
from .target_databases import router as target_databases_router
from .database_policies import router as database_policies_router
from .data_executions import router as data_executions_router


router = APIRouter(tags=["测试数据中心"])


router.include_router(fixtures_router)


router.include_router(test_data_assets_router)


router.include_router(data_providers_router)


router.include_router(data_pools_router)


router.include_router(data_pool_items_router)


router.include_router(target_databases_router)


router.include_router(database_policies_router)


router.include_router(data_executions_router)
