"""接口管理 feature-local ORM 模型集合。

与缺陷（defects/models/bug.py）同款：这些表**不**注册进 `app/models/__init__.py`，
由显式迁移 `alembic/versions/0003_create_api_catalog_tables.py` 用 `op.create_table` 建立，
避免进入 `0001` 的 `Base.metadata.create_all` 与 `0003` 产生双写冲突。

各表职责见各自模块 docstring。
"""

from app.features.api_catalog.models.api_change_log import ApiChangeLog
from app.features.api_catalog.models.api_import_record import ApiImportRecord
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_module import ApiModule
from app.features.api_catalog.models.api_parameter import ApiParameter
from app.features.api_catalog.models.api_relation import ApiRelation
from app.features.api_catalog.models.api_request_body import ApiRequestBody
from app.features.api_catalog.models.api_response import ApiResponse

__all__ = [
    "ApiChangeLog",
    "ApiImportRecord",
    "ApiInterface",
    "ApiModule",
    "ApiParameter",
    "ApiRelation",
    "ApiRequestBody",
    "ApiResponse",
]
