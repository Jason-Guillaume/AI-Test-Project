"""本领域路由使用的无状态服务装配；不拥有请求事务。"""

from __future__ import annotations

from app.features.api_catalog.services.api_service import ApiService
from app.features.api_catalog.services.debug_service import DebugService
from app.features.api_catalog.services.import_service import ImportService


_API = ApiService()


_IMPORT = ImportService()


_DEBUG = DebugService()
