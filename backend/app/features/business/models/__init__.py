"""业务管理 ORM 模型集合（feature-local）。

与 Bug（0002）、api_catalog（0003）同款约定：这些模型**不**加入 app/models/__init__.py，
而是由 alembic/versions/0004_create_business_tables.py 用显式 op.create_table 建立，
避免与 0001 的 Base.metadata.create_all 冲突。运行期由路由→服务→模型导入链触发加载，
注册进 Base.metadata 供 ORM 查询使用（与 api_catalog 行为一致）。
"""

from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_api_mapping import BusinessApiMapping
from app.features.business.models.business_binding import BusinessBinding
from app.features.business.models.business_domain import BusinessDomain
from app.features.business.models.business_flow import BusinessFlow
from app.features.business.models.business_precondition import BusinessPrecondition
from app.features.business.models.business_rule import BusinessRule
from app.features.business.models.business_state import BusinessState
from app.features.business.models.business_variable import BusinessVariable
from app.features.business.models.business_variable_ref import BusinessVariableRef

__all__ = [
    "BusinessAction",
    "BusinessApiMapping",
    "BusinessBinding",
    "BusinessDomain",
    "BusinessFlow",
    "BusinessPrecondition",
    "BusinessRule",
    "BusinessState",
    "BusinessVariable",
    "BusinessVariableRef",
]
