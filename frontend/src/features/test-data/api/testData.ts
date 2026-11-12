// 测试数据中心 + Data Factory 接口客户端。
// 字段命名与后端 features/test_data/schemas.py 严格对齐（snake_case）。
// 客户端不带 /api/v1 前缀（由 client.ts 的 baseURL 统一补上）。
//
// 路由形态（挂载 /api/v1 下）：
//   GET    /projects/{pid}/fixtures                      Fixture 列表（viewer+）
//   POST   /projects/{pid}/fixtures                      创建 Fixture（member+）
//   GET    /fixtures/{id}                                Fixture 详情
//   PATCH  /fixtures/{id}                                改基本信息
//   DELETE /fixtures/{id}                                删除（被引用时 409）
//   PUT    /fixtures/{id}/steps                          整体替换步骤（重建依赖边 + 环检测）
//   PUT    /fixtures/{id}/outputs                        整体替换输出契约
//   GET    /fixtures/{id}/dependencies                   依赖树
//   POST   /fixtures/{id}/generate                       手工试跑（含依赖链），返回执行记录详情
//   POST   /fixtures/{id}/cleanup                        手工清理，返回清理执行记录详情
//   资产 / Provider / 池 / 被测库 / 策略 / 执行记录：见各方法注释。
//
// 权限（服务端为准）：读 viewer+，写 member+，被测库连接与策略写仅平台管理员；
// 越权与不存在共用 404，前端不展示。
import { api } from '@/shared/api/client';
import type { DatabasePolicy, DatabasePolicyListResponse, DatabasePolicyUpsert, DataPool, DataPoolCreate, DataPoolItemListResponse, DataPoolItem, DataPoolItemCreate, DataPoolListResponse, DataProvider, DataProviderCreate, DataProviderListResponse, DataProviderTestRequest, DataProviderUpdate, FixtureCreate, FixtureDetail, FixtureGenerateRequest, FixtureListResponse, FixtureOutputsReplace, FixtureStepsReplace, FixtureTreeNode, FixtureUpdate, TargetDbConnection, TargetDbConnectionCreate, TargetDbConnectionListResponse, TargetDbConnectionUpdate, TestDataAsset, TestDataAssetCreate, TestDataAssetListResponse, TestDataAssetUpdate } from '@/features/test-data/contracts';
import type { DataExecutionDetail, DataExecutionListQuery, DataExecutionListResponse } from '@/features/test-data/executionContracts';

import type { FixtureListQuery, AssetListQuery, ProviderListQuery, PoolListQuery, ConnectionListQuery, PolicyListQuery } from '../contracts';






export const testDataApi = {
  // ---- Fixture ----
  /** Fixture 列表（分页信封）。 */
  listFixtures: (projectId: number, params: FixtureListQuery = {}) =>
    api.get<FixtureListResponse>(`/projects/${projectId}/fixtures`, {
      params: { page: 1, page_size: 100, ...params },
    }),
  /** 创建 Fixture：基本信息 + 步骤 + 输出 + 依赖。 */
  createFixture: (projectId: number, body: FixtureCreate) =>
    api.post<FixtureDetail>(`/projects/${projectId}/fixtures`, body),
  /** Fixture 详情（含步骤 / 输出 / 依赖 / 引用用例）。 */
  getFixture: (fixtureId: number) => api.get<FixtureDetail>(`/fixtures/${fixtureId}`),
  /** 改基本信息（不动步骤 / 输出 / 依赖）。 */
  updateFixture: (fixtureId: number, body: FixtureUpdate) =>
    api.patch<FixtureDetail>(`/fixtures/${fixtureId}`, body),
  /** 删除 Fixture（被用例或依赖引用时 409）。 */
  removeFixture: (fixtureId: number) => api.delete<void>(`/fixtures/${fixtureId}`),
  /** 整体替换步骤：后端重建步骤派生依赖边并跑环检测，成环返回 FIXTURE_DEPENDENCY_CYCLE。 */
  replaceSteps: (fixtureId: number, body: FixtureStepsReplace) =>
    api.put<FixtureDetail>(`/fixtures/${fixtureId}/steps`, body),
  /** 整体替换输出契约（名称唯一，冲突 409）。 */
  replaceOutputs: (fixtureId: number, body: FixtureOutputsReplace) =>
    api.put<FixtureDetail>(`/fixtures/${fixtureId}/outputs`, body),
  /** 依赖树（含子依赖），供左树与依赖 Tab。 */
  dependencyTree: (fixtureId: number) =>
    api.get<FixtureTreeNode[]>(`/fixtures/${fixtureId}/dependencies`),
  /**
   * 手工试跑（含依赖链），按 CASE 作用域跑，不写项目级缓存。
   * cleanup_policy=AFTER_CASE 时后端在生成结束后自动执行 Cleanup。
   * 返回执行记录详情：每步 input/output/error 可直接展示。
   */
  generateFixture: (fixtureId: number, body: FixtureGenerateRequest) =>
    api.post<DataExecutionDetail>(`/fixtures/${fixtureId}/generate`, body),
  /**
   * 手工执行该 Fixture 的 CLEANUP 步骤，返回一条 MANUAL 清理记录详情。
   * 无 CLEANUP 步骤时后端返回 SKIPPED，不算失败。
   */
  cleanupFixture: (fixtureId: number) =>
    api.post<DataExecutionDetail>(`/fixtures/${fixtureId}/cleanup`),

  // ---- 测试数据目录 ----
  listAssets: (projectId: number, params: AssetListQuery = {}) =>
    api.get<TestDataAssetListResponse>(`/projects/${projectId}/test-data-assets`, {
      params: { page: 1, page_size: 20, ...params },
    }),
  createAsset: (projectId: number, body: TestDataAssetCreate) =>
    api.post<TestDataAsset>(`/projects/${projectId}/test-data-assets`, body),
  getAsset: (assetId: number) => api.get<TestDataAsset>(`/test-data-assets/${assetId}`),
  updateAsset: (assetId: number, body: TestDataAssetUpdate) =>
    api.patch<TestDataAsset>(`/test-data-assets/${assetId}`, body),
  removeAsset: (assetId: number) => api.delete<void>(`/test-data-assets/${assetId}`),

  // ---- Data Provider ----
  listProviders: (projectId: number, params: ProviderListQuery = {}) =>
    api.get<DataProviderListResponse>(`/projects/${projectId}/data-providers`, {
      params: { page: 1, page_size: 50, ...params },
    }),
  createProvider: (projectId: number, body: DataProviderCreate) =>
    api.post<DataProvider>(`/projects/${projectId}/data-providers`, body),
  getProvider: (providerId: number) => api.get<DataProvider>(`/data-providers/${providerId}`),
  updateProvider: (providerId: number, body: DataProviderUpdate) =>
    api.patch<DataProvider>(`/data-providers/${providerId}`, body),
  enableProvider: (providerId: number) =>
    api.post<DataProvider>(`/data-providers/${providerId}/enable`),
  disableProvider: (providerId: number) =>
    api.post<DataProvider>(`/data-providers/${providerId}/disable`),
  removeProvider: (providerId: number) => api.delete<void>(`/data-providers/${providerId}`),
  /**
   * 试跑单个 Provider（不走 Fixture，不写契约输出），返回执行记录详情。
   * 步骤记录没有 Fixture 归属，挂在 detail.provider_executions 上。
   */
  testProvider: (providerId: number, body: DataProviderTestRequest) =>
    api.post<DataExecutionDetail>(`/data-providers/${providerId}/test`, body),

  // ---- 数据池 ----
  listPools: (projectId: number, params: PoolListQuery = {}) =>
    api.get<DataPoolListResponse>(`/projects/${projectId}/data-pools`, {
      params: { page: 1, page_size: 50, ...params },
    }),
  createPool: (projectId: number, body: DataPoolCreate) =>
    api.post<DataPool>(`/projects/${projectId}/data-pools`, body),
  getPool: (poolId: number) => api.get<DataPool>(`/data-pools/${poolId}`),
  removePool: (poolId: number) => api.delete<void>(`/data-pools/${poolId}`),
  listPoolItems: (poolId: number, params: { page?: number; page_size?: number } = {}) =>
    api.get<DataPoolItemListResponse>(`/data-pools/${poolId}/items`, {
      params: { page: 1, page_size: 50, ...params },
    }),
  createPoolItem: (poolId: number, body: DataPoolItemCreate) =>
    api.post<DataPoolItem>(`/data-pools/${poolId}/items`, body),
  removePoolItem: (itemId: number) => api.delete<void>(`/data-pool-items/${itemId}`),

  // ---- 被测库连接与策略 ----
  listConnections: (projectId: number, params: ConnectionListQuery = {}) =>
    api.get<TargetDbConnectionListResponse>(`/projects/${projectId}/target-databases`, {
      params: { page: 1, page_size: 50, ...params },
    }),
  createConnection: (projectId: number, body: TargetDbConnectionCreate) =>
    api.post<TargetDbConnection>(`/projects/${projectId}/target-databases`, body),
  getConnection: (connectionId: number) =>
    api.get<TargetDbConnection>(`/target-databases/${connectionId}`),
  updateConnection: (connectionId: number, body: TargetDbConnectionUpdate) =>
    api.patch<TargetDbConnection>(`/target-databases/${connectionId}`, body),
  removeConnection: (connectionId: number) =>
    api.delete<void>(`/target-databases/${connectionId}`),
  /** 连通性探测：只 SELECT 1，短连接，返回 {ok, latency_ms, error}。 */
  pingConnection: (connectionId: number) =>
    api.post<{ connection_id: number; ok: boolean; latency_ms: number; error: string | null }>(
      `/target-databases/${connectionId}/ping`,
    ),
  listPolicies: (projectId: number, params: PolicyListQuery = {}) =>
    api.get<DatabasePolicyListResponse>(`/projects/${projectId}/database-policies`, {
      params: { page: 1, page_size: 50, ...params },
    }),
  upsertPolicy: (projectId: number, environmentId: number, body: DatabasePolicyUpsert) =>
    api.put<DatabasePolicy>(
      `/projects/${projectId}/database-policies/${environmentId}`,
      body,
    ),

  // ---- 执行记录（只读列表；手工试跑 / Provider 试跑 / 用例造数都会落这里） ----
  listExecutions: (projectId: number, params: DataExecutionListQuery = {}) =>
    api.get<DataExecutionListResponse>(`/projects/${projectId}/data-executions`, {
      params: { page: 1, page_size: 20, ...params },
    }),
  getExecution: (executionId: number) =>
    api.get<DataExecutionDetail>(`/data-executions/${executionId}`),
};
