"""领域路由唯一聚合入口；由 main.py 挂载一次。"""

from __future__ import annotations

from fastapi import APIRouter
from .api_modules import router as api_modules_router
from .apis import router as apis_router
from .api_relations import router as api_relations_router
from .api_import_records import router as api_import_records_router


router = APIRouter(tags=["接口管理"])


router.include_router(api_modules_router)


router.include_router(apis_router)


router.include_router(api_relations_router)


router.include_router(api_import_records_router)
