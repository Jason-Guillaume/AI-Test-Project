"""测试数据中心服务层（feature-local）。

权限口径与 test_management / business 一致：
- 读：项目 viewer+，不可见与不存在共用 404（隐藏存在性）；
- 写：项目 member+，不足 403；
- 被测库连接与数据库策略：平台管理员（Environment 本身是平台级危险配置）。

service owns commit。
"""


from app.features.test_data.services.access_service import (
    require_admin,
    require_admin_project,
    resolve_fixture_project_id,
    resolve_provider_project_id,
    resolve_asset_project_id,
    resolve_pool_project_id,
    resolve_pool_item_project_id,
    resolve_connection_project_id,
    resolve_execution_project_id,
    resolve_policy_project_id,
)

__all__ = [
    'require_admin',
    'require_admin_project',
    'resolve_fixture_project_id',
    'resolve_provider_project_id',
    'resolve_asset_project_id',
    'resolve_pool_project_id',
    'resolve_pool_item_project_id',
    'resolve_connection_project_id',
    'resolve_execution_project_id',
    'resolve_policy_project_id'
]
