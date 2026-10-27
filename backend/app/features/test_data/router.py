"""测试数据中心路由。

单 APIRouter（无自身前缀），挂在 /api/v1 下。资源级路径：
- /projects/{project_id}/(fixtures|test-data-assets|data-providers|data-pools|target-databases|database-policies|data-executions)
- /(fixtures|test-data-assets|data-providers|data-pools|data-pool-items|target-databases|data-executions)/{id}
- /fixtures/{id}/(steps|outputs|dependencies|generate|cleanup)
- /data-providers/{id}/(enable|disable|test)
- /data-pools/{id}/items、/data-pools/{id}/leases、/data-pool-items/{id}/release
- /target-databases/{id}/ping
- /projects/{project_id}/database-policies/{environment_id}

权限：读 viewer+、写 member+；被测库连接与数据库策略写操作仅平台管理员；
越权与不存在共用 404。端点统一 sync def；service owns commit。

Phase B：generate/cleanup/test 三条运行时接口接 DataFactory / CleanupRunner，
统一返回造数执行记录详情（§Phase B）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.test_data.schemas import (
    DatabasePolicyListResponse,
    DatabasePolicyResponse,
    DatabasePolicyUpsert,
    DataExecutionDetailResponse,
    DataExecutionListResponse,
    DataPoolCreate,
    DataPoolItemListResponse,
    DataPoolItemCreate,
    DataPoolItemResponse,
    DataPoolItemUpdate,
    DataPoolLeaseListResponse,
    DataPoolListResponse,
    DataPoolResponse,
    DataPoolUpdate,
    DataProviderCreate,
    DataProviderListResponse,
    DataProviderResponse,
    DataProviderTestRequest,
    DataProviderUpdate,
    FixtureCreate,
    FixtureDetailResponse,
    FixtureGenerateRequest,
    FixtureListResponse,
    FixtureOutputsReplace,
    FixtureStepsReplace,
    FixtureTreeNodeResponse,
    FixtureUpdate,
    TargetDbConnectionCreate,
    TargetDbConnectionListResponse,
    TargetDbConnectionResponse,
    TargetDbConnectionUpdate,
    TestDataAssetCreate,
    TestDataAssetListResponse,
    TestDataAssetResponse,
    TestDataAssetUpdate,
)
from app.features.test_data.services.asset_service import AssetService
from app.features.test_data.services.connection_service import (
    ConnectionService,
    PolicyService,
)
from app.features.test_data.services.execution_query_service import (
    ExecutionQueryService,
)
from app.features.test_data.services.fixture_service import FixtureService
from app.features.test_data.services.pool_service import PoolService
from app.features.test_data.services.provider_service import ProviderService
from app.features.test_data.services.runtime_service import RuntimeService
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["测试数据中心"])

# 服务无状态，路由层复用单例。
_FIXTURE = FixtureService()
_ASSET = AssetService()
_PROVIDER = ProviderService()
_POOL = PoolService()
_CONNECTION = ConnectionService()
_POLICY = PolicyService()
_EXECUTION = ExecutionQueryService()
_RUNTIME = RuntimeService()


# --------------------------------------------------------------------------- 6.1 固定数据 Fixture


@router.get("/projects/{project_id}/fixtures", response_model=FixtureListResponse)
def list_fixtures(
    project_id: int,
    keyword: str | None = Query(None),
    entity_type: str | None = Query(None),
    status: str | None = Query(None),
    scope: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureListResponse:
    """列出`fixtures`。"""
    return _FIXTURE.list_fixtures(
        db, project_id, user,
        keyword=keyword, entity_type=entity_type, status=status, scope=scope,
        page=page, page_size=page_size,
    )


@router.post("/projects/{project_id}/fixtures", response_model=FixtureDetailResponse, status_code=201)
def create_fixture(
    project_id: int,
    body: FixtureCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """创建固定数据。"""
    return _FIXTURE.create_fixture(db, project_id, body, actor=user)


@router.get("/fixtures/{fixture_id}", response_model=FixtureDetailResponse)
def get_fixture(
    fixture_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """获取固定数据。"""
    return _FIXTURE.get_fixture(db, fixture_id, user)


@router.patch("/fixtures/{fixture_id}", response_model=FixtureDetailResponse)
def update_fixture(
    fixture_id: int,
    body: FixtureUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """更新固定数据。"""
    return _FIXTURE.update_fixture(db, fixture_id, body, actor=user)


@router.delete("/fixtures/{fixture_id}", status_code=204)
def delete_fixture(
    fixture_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除固定数据。"""
    _FIXTURE.delete_fixture(db, fixture_id, actor=user)


@router.put("/fixtures/{fixture_id}/steps", response_model=FixtureDetailResponse)
def replace_fixture_steps(
    fixture_id: int,
    body: FixtureStepsReplace,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """替换固定数据的生成步骤。"""
    return _FIXTURE.replace_steps(db, fixture_id, body, actor=user)


@router.put("/fixtures/{fixture_id}/outputs", response_model=FixtureDetailResponse)
def replace_fixture_outputs(
    fixture_id: int,
    body: FixtureOutputsReplace,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """替换固定数据的输出契约。"""
    return _FIXTURE.replace_outputs(db, fixture_id, body, actor=user)


@router.get("/fixtures/{fixture_id}/dependencies", response_model=list[FixtureTreeNodeResponse])
def fixture_dependency_tree(
    fixture_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FixtureTreeNodeResponse]:
    """构建固定数据及其依赖关系树。"""
    return _FIXTURE.dependency_tree(db, fixture_id, user)


@router.post("/fixtures/{fixture_id}/generate", response_model=DataExecutionDetailResponse)
def generate_fixture(
    fixture_id: int,
    body: FixtureGenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionDetailResponse:
    """手工试跑：返回执行记录详情（每步 input/output/error）。"""
    data_exec = _RUNTIME.generate(db, fixture_id, body, actor=user)
    return _EXECUTION.get_execution(db, data_exec.id, user)


@router.post("/fixtures/{fixture_id}/cleanup", response_model=DataExecutionDetailResponse)
def cleanup_fixture(
    fixture_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionDetailResponse:
    """按最近一次试跑输出做 MANUAL cleanup。"""
    data_exec = _RUNTIME.cleanup(db, fixture_id, actor=user)
    return _EXECUTION.get_execution(db, data_exec.id, user)


# --------------------------------------------------------------------------- 6.2 测试数据目录


@router.get(
    "/projects/{project_id}/test-data-assets", response_model=TestDataAssetListResponse,
)
def list_assets(
    project_id: int,
    keyword: str | None = Query(None),
    entity_type: str | None = Query(None),
    source: str | None = Query(None),
    status: str | None = Query(None),
    scope: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestDataAssetListResponse:
    """列出`assets`。"""
    return _ASSET.list_assets(
        db, project_id, user,
        keyword=keyword, entity_type=entity_type, source=source, status=status, scope=scope,
        page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/test-data-assets",
    response_model=TestDataAssetResponse, status_code=201,
)
def create_asset(
    project_id: int,
    body: TestDataAssetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestDataAssetResponse:
    """创建资产。"""
    return _ASSET.create_asset(db, project_id, body, actor=user)


@router.get("/test-data-assets/{asset_id}", response_model=TestDataAssetResponse)
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestDataAssetResponse:
    """获取资产。"""
    return _ASSET.get_asset(db, asset_id, user)


@router.patch("/test-data-assets/{asset_id}", response_model=TestDataAssetResponse)
def update_asset(
    asset_id: int,
    body: TestDataAssetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestDataAssetResponse:
    """更新资产。"""
    return _ASSET.update_asset(db, asset_id, body, actor=user)


@router.delete("/test-data-assets/{asset_id}", status_code=204)
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除资产。"""
    _ASSET.delete_asset(db, asset_id, actor=user)


# --------------------------------------------------------------------------- 6.3 数据提供器 数据提供器 Data Provider


@router.get(
    "/projects/{project_id}/data-providers", response_model=DataProviderListResponse,
)
def list_providers(
    project_id: int,
    provider_type: str | None = Query(None),
    enabled: bool | None = Query(None),
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderListResponse:
    """列出`providers`。"""
    return _PROVIDER.list_providers(
        db, project_id, user,
        provider_type=provider_type, enabled=enabled, keyword=keyword,
        page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/data-providers",
    response_model=DataProviderResponse, status_code=201,
)
def create_provider(
    project_id: int,
    body: DataProviderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """创建提供器。"""
    return _PROVIDER.create_provider(db, project_id, body, actor=user)


@router.get("/data-providers/{provider_id}", response_model=DataProviderResponse)
def get_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """获取提供器。"""
    return _PROVIDER.get_provider(db, provider_id, user)


@router.patch("/data-providers/{provider_id}", response_model=DataProviderResponse)
def update_provider(
    provider_id: int,
    body: DataProviderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """更新提供器。"""
    return _PROVIDER.update_provider(db, provider_id, body, actor=user)


@router.post("/data-providers/{provider_id}/enable", response_model=DataProviderResponse)
def enable_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """启用数据提供器。"""
    return _PROVIDER.set_enabled(db, provider_id, enabled=True, actor=user)


@router.post("/data-providers/{provider_id}/disable", response_model=DataProviderResponse)
def disable_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """停用数据提供器。"""
    return _PROVIDER.set_enabled(db, provider_id, enabled=False, actor=user)


@router.delete("/data-providers/{provider_id}", status_code=204)
def delete_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除提供器。"""
    _PROVIDER.delete_provider(db, provider_id, actor=user)


@router.post("/data-providers/{provider_id}/test", response_model=DataExecutionDetailResponse)
def test_provider(
    provider_id: int,
    body: DataProviderTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionDetailResponse:
    """手工试跑单个 Provider，走完整安全策略。"""
    data_exec = _RUNTIME.test_provider(db, provider_id, body, actor=user)
    return _EXECUTION.get_execution(db, data_exec.id, user)


# --------------------------------------------------------------------------- 6.4 池


@router.get("/projects/{project_id}/data-pools", response_model=DataPoolListResponse)
def list_pools(
    project_id: int,
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolListResponse:
    """列出`pools`。"""
    return _POOL.list_pools(
        db, project_id, user, keyword=keyword, status=status, page=page, page_size=page_size,
    )


@router.post("/projects/{project_id}/data-pools", response_model=DataPoolResponse, status_code=201)
def create_pool(
    project_id: int,
    body: DataPoolCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolResponse:
    """创建连接池。"""
    return _POOL.create_pool(db, project_id, body, actor=user)


@router.get("/data-pools/{pool_id}", response_model=DataPoolResponse)
def get_pool(
    pool_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolResponse:
    """获取连接池。"""
    return _POOL.get_pool(db, pool_id, user)


@router.patch("/data-pools/{pool_id}", response_model=DataPoolResponse)
def update_pool(
    pool_id: int,
    body: DataPoolUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolResponse:
    """更新连接池。"""
    return _POOL.update_pool(db, pool_id, body, actor=user)


@router.delete("/data-pools/{pool_id}", status_code=204)
def delete_pool(
    pool_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除连接池。"""
    _POOL.delete_pool(db, pool_id, actor=user)


@router.get("/data-pools/{pool_id}/items", response_model=DataPoolItemListResponse)
def list_pool_items(
    pool_id: int,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolItemListResponse:
    """列出连接池条目。"""
    return _POOL.list_items(
        db, pool_id, user, status=status, page=page, page_size=page_size,
    )


@router.post(
    "/data-pools/{pool_id}/items", response_model=DataPoolItemResponse, status_code=201,
)
def create_pool_item(
    pool_id: int,
    body: DataPoolItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolItemResponse:
    """创建连接池条目。"""
    return _POOL.create_item(db, pool_id, body, actor=user)


@router.patch("/data-pool-items/{item_id}", response_model=DataPoolItemResponse)
def update_pool_item(
    item_id: int,
    body: DataPoolItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolItemResponse:
    """更新连接池条目。"""
    return _POOL.update_item(db, item_id, body, actor=user)


@router.post("/data-pool-items/{item_id}/release", response_model=DataPoolItemResponse)
def release_pool_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolItemResponse:
    """释放连接池条目。"""
    return _POOL.release_item(db, item_id, actor=user)


@router.delete("/data-pool-items/{item_id}", status_code=204)
def delete_pool_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除连接池条目。"""
    _POOL.delete_item(db, item_id, actor=user)


@router.get("/data-pools/{pool_id}/leases", response_model=DataPoolLeaseListResponse)
def list_pool_leases(
    pool_id: int,
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataPoolLeaseListResponse:
    """列出连接池`leases`。"""
    result = _POOL.list_leases(
        db, pool_id, user, status=status, page=page, page_size=page_size,
    )
    return DataPoolLeaseListResponse(**result)


# --------------------------------------------------------------------------- 6.5 目标库与策略


@router.get(
    "/projects/{project_id}/target-databases", response_model=TargetDbConnectionListResponse,
)
def list_target_databases(
    project_id: int,
    environment_id: int | None = Query(None),
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetDbConnectionListResponse:
    """列出目标`databases`。"""
    return _CONNECTION.list_connections(
        db, project_id, user,
        environment_id=environment_id, keyword=keyword, page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/target-databases",
    response_model=TargetDbConnectionResponse, status_code=201,
)
def create_target_database(
    project_id: int,
    body: TargetDbConnectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetDbConnectionResponse:
    """创建目标数据库。"""
    return _CONNECTION.create_connection(db, project_id, body, actor=user)


@router.get(
    "/target-databases/{connection_id}", response_model=TargetDbConnectionResponse,
)
def get_target_database(
    connection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetDbConnectionResponse:
    """获取目标数据库。"""
    return _CONNECTION.get_connection(db, connection_id, user)


@router.patch(
    "/target-databases/{connection_id}", response_model=TargetDbConnectionResponse,
)
def update_target_database(
    connection_id: int,
    body: TargetDbConnectionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TargetDbConnectionResponse:
    """更新目标数据库。"""
    return _CONNECTION.update_connection(db, connection_id, body, actor=user)


@router.delete("/target-databases/{connection_id}", status_code=204)
def delete_target_database(
    connection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除目标数据库。"""
    _CONNECTION.delete_connection(db, connection_id, actor=user)


@router.post("/target-databases/{connection_id}/ping")
def ping_target_database(
    connection_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """检查连通性`target`数据库。"""
    return _CONNECTION.ping(db, connection_id, user)


@router.get(
    "/projects/{project_id}/database-policies", response_model=DatabasePolicyListResponse,
)
def list_database_policies(
    project_id: int,
    environment_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatabasePolicyListResponse:
    """列出数据库`policies`。"""
    return _POLICY.list_policies(
        db, project_id, user,
        environment_id=environment_id, page=page, page_size=page_size,
    )


@router.put(
    "/projects/{project_id}/database-policies/{environment_id}",
    response_model=DatabasePolicyResponse,
)
def upsert_database_policy(
    project_id: int,
    environment_id: int,
    body: DatabasePolicyUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatabasePolicyResponse:
    """新增或更新数据库策略。"""
    return _POLICY.upsert_policy(
        db, project_id, environment_id, body, actor=user,
    )


# --------------------------------------------------------------------------- 6.6 执行记录（只读；Phase A 运行时尚未产出，列表为空）


@router.get(
    "/projects/{project_id}/data-executions", response_model=DataExecutionListResponse,
)
def list_data_executions(
    project_id: int,
    status: str | None = Query(None),
    test_run_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionListResponse:
    """列出数据`executions`。"""
    return _EXECUTION.list_executions(
        db, project_id, user, status=status, test_run_id=test_run_id,
        page=page, page_size=page_size,
    )


@router.get(
    "/data-executions/{data_execution_id}", response_model=DataExecutionDetailResponse,
)
def get_data_execution(
    data_execution_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionDetailResponse:
    """获取数据执行记录。"""
    return _EXECUTION.get_execution(db, data_execution_id, user)
