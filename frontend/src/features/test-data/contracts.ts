// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。
import type { Paginated } from '@/shared/api/contracts';

// 列表查询参数：统一带分页默认值，调用方可覆盖。
export interface FixtureListQuery {
  keyword?: string;
  entity_type?: string;
  status?: string;
  scope?: string;
  page?: number;
  page_size?: number;
}

export interface AssetListQuery {
  keyword?: string;
  entity_type?: string;
  source?: string;
  status?: string;
  scope?: string;
  page?: number;
  page_size?: number;
}

export interface ProviderListQuery {
  provider_type?: string;
  enabled?: boolean;
  keyword?: string;
  page?: number;
  page_size?: number;
}

export interface PoolListQuery {
  keyword?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export interface ConnectionListQuery {
  environment_id?: number;
  keyword?: string;
  page?: number;
  page_size?: number;
}

export interface PolicyListQuery {
  environment_id?: number;
  page?: number;
  page_size?: number;
}


// ===========================================================================
// 测试数据中心 / Data Factory（features/test_data/schemas.py 对齐，snake_case）
// 列表接口统一走 Paginated<T>；写操作的请求体与后端 Pydantic 入参一致。
// 安全约定：Provider 配置 extra=forbid；连接响应只回 password_set；value/payload 已脱敏。
// ===========================================================================

// Fixture 作用域 / 状态 / 清理策略 / 步骤类型等字面量类型，供下拉与表单复用。
export type FixtureScope = 'CASE' | 'RUN' | 'PROJECT' | 'GLOBAL';

export type FixtureStatus = 'DRAFT' | 'ACTIVE' | 'DISABLED';

export type FixtureCleanupPolicy = 'AFTER_CASE' | 'AFTER_RUN' | 'MANUAL' | 'NEVER';

export type FixturePhase = 'GENERATE' | 'CLEANUP';

export type FixtureStepType =
  | 'FIXTURE' | 'API' | 'BUSINESS_ACTION' | 'BUSINESS_FLOW'
  | 'FAKER' | 'STATIC' | 'DATABASE_INSERT' | 'DATABASE_PATCH'
  | 'WAIT' | 'DATABASE_QUERY' | 'EXTERNAL_PROVIDER';

export type FixtureOnFailure = 'ABORT' | 'CONTINUE';

export type ValueType = 'STRING' | 'INTEGER' | 'NUMBER' | 'BOOLEAN' | 'OBJECT' | 'ARRAY';

export type ProviderType =
  | 'STATIC' | 'ENVIRONMENT' | 'FAKER' | 'API_CREATE'
  | 'BUSINESS_ACTION' | 'BUSINESS_FLOW' | 'EXISTING_POOL'
  | 'DATABASE_INSERT' | 'DATABASE_PATCH';

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type AssetSource = 'STATIC' | 'POOL' | 'FIXTURE';

export type AssetStatus = 'ACTIVE' | 'DISABLED' | 'EXPIRED';

export type PoolStatus = 'ACTIVE' | 'DISABLED';

export type PoolItemStatus = 'AVAILABLE' | 'OCCUPIED' | 'EXPIRED' | 'DISABLED';

export type LeaseStatus = 'ACTIVE' | 'RELEASED' | 'EXPIRED';

export type DbOperation = 'INSERT' | 'UPDATE' | 'SELECT' | 'DELETE';

export type DbEnvironmentClass = 'DEV' | 'TEST' | 'STAGING' | 'PRODUCTION';

export type DataExecutionStatus =
  | 'PENDING' | 'GENERATING' | 'READY' | 'FAILED'
  | 'EXPIRED' | 'DIRTY' | 'CLEANING' | 'CLEANED';

export type ProviderExecutionStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'SKIPPED';

export type CleanupStatus = 'PENDING' | 'SUCCESS' | 'FAILED' | 'SKIPPED';

// ---- Fixture ----

/** Fixture 步骤（响应）。config_json 为自由结构，按 step_type 解释。 */
export interface FixtureStep {
  id: number;
  fixture_id: number;
  phase: FixturePhase;
  step_type: FixtureStepType;
  name: string;
  sort: number;
  provider_id: number | null;
  config_json: Record<string, unknown> | null;
  on_failure: FixtureOnFailure;
}

/** 输出契约（响应）。 */
export interface FixtureOutput {
  id: number;
  fixture_id: number;
  name: string;
  value_type: ValueType;
  source_path: string;
  description: string | null;
  sort: number;
}

/** 依赖边（响应，附被依赖方 key/name/类型，便于画树）。 */
export interface FixtureDependency {
  id: number;
  fixture_id: number;
  depends_on_fixture_id: number;
  sort: number;
  depends_on_key: string | null;
  depends_on_name: string | null;
  depends_on_entity_type: string | null;
}

/** Fixture 列表项（含聚合计数）。 */
export interface FixtureBrief {
  id: number;
  project_id: number;
  name: string;
  fixture_key: string;
  entity_type: string;
  description: string | null;
  scope: FixtureScope;
  status: FixtureStatus;
  cache_enabled: boolean;
  cleanup_policy: FixtureCleanupPolicy;
  output_names: string[];
  step_count: number;
  generate_step_count: number;
  cleanup_step_count: number;
  dependency_count: number;
  referenced_case_count: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

/** Fixture 详情（列表项 + 步骤 + 输出 + 依赖 + 引用用例）。 */
export interface FixtureDetail extends FixtureBrief {
  steps: FixtureStep[];
  outputs: FixtureOutput[];
  dependencies: FixtureDependency[];
  referenced_cases: { test_case_id: number; sort: number }[];
}

/** 依赖树节点（含子依赖）。 */
export interface FixtureTreeNode {
  id: number;
  fixture_key: string;
  name: string;
  entity_type: string;
  scope: FixtureScope;
  status: FixtureStatus;
  depth: number;
  children: FixtureTreeNode[];
}

// 写入入参
export interface FixtureStepInput {
  phase?: FixturePhase;
  step_type: FixtureStepType;
  name: string;
  sort?: number;
  provider_id?: number | null;
  config_json?: Record<string, unknown> | null;
  on_failure?: FixtureOnFailure;
}

export interface FixtureOutputInput {
  name: string;
  value_type?: ValueType;
  source_path: string;
  description?: string | null;
  sort?: number;
}

export interface FixtureCreate {
  name: string;
  fixture_key: string;
  entity_type: string;
  description?: string | null;
  scope?: FixtureScope;
  status?: FixtureStatus;
  cache_enabled?: boolean;
  cleanup_policy?: FixtureCleanupPolicy;
  steps?: FixtureStepInput[];
  outputs?: FixtureOutputInput[];
  dependencies?: number[];
}

export interface FixtureUpdate {
  name?: string;
  description?: string | null;
  scope?: FixtureScope;
  status?: FixtureStatus;
  cache_enabled?: boolean;
  cleanup_policy?: FixtureCleanupPolicy;
}

export interface FixtureStepsReplace {
  steps: FixtureStepInput[];
}

export interface FixtureOutputsReplace {
  outputs: FixtureOutputInput[];
}

export type FixtureListResponse = Paginated<FixtureBrief>;

// ---- 测试数据目录 ----
export interface TestDataAsset {
  id: number;
  project_id: number;
  name: string;
  entity_type: string;
  source: AssetSource;
  scope: FixtureScope;
  status: AssetStatus;
  fixture_id: number | null;
  value_json: Record<string, unknown> | null; // 已脱敏，敏感值为 ******
  description: string | null;
  referenced_count: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface TestDataAssetCreate {
  name: string;
  entity_type: string;
  source?: AssetSource;
  scope?: FixtureScope;
  status?: AssetStatus;
  fixture_id?: number | null;
  value_json?: Record<string, unknown> | null;
  description?: string | null;
}

export interface TestDataAssetUpdate {
  name?: string;
  entity_type?: string;
  source?: AssetSource;
  scope?: FixtureScope;
  status?: AssetStatus;
  fixture_id?: number | null;
  value_json?: Record<string, unknown> | null;
  description?: string | null;
}

export type TestDataAssetListResponse = Paginated<TestDataAsset>;

// ---- Data Provider ----
export interface DataProvider {
  id: number;
  project_id: number;
  name: string;
  provider_type: ProviderType;
  config_json: Record<string, unknown>; // 不含密码；DATABASE 类只回 connection_id
  enabled: boolean;
  risk_level: RiskLevel;
  description: string | null;
  usage_count: number;
  last_status: ProviderExecutionStatus | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface DataProviderCreate {
  name: string;
  provider_type: ProviderType;
  config_json?: Record<string, unknown>;
  enabled?: boolean;
  risk_level?: RiskLevel | null;
  description?: string | null;
}

export interface DataProviderUpdate {
  name?: string;
  provider_type?: ProviderType;
  config_json?: Record<string, unknown> | null;
  enabled?: boolean;
  risk_level?: RiskLevel | null;
  description?: string | null;
}

export interface DataProviderTestRequest {
  environment_id: number;
  variables?: Record<string, unknown>;
}

/** 手工试跑 Fixture 的请求体：scope 只接收不生效，试跑一律按 CASE 处理。 */
export interface FixtureGenerateRequest {
  environment_id: number;
  scope?: string;
  variables?: Record<string, unknown>;
}

export type DataProviderListResponse = Paginated<DataProvider>;

// ---- 数据池 ----
export interface DataPool {
  id: number;
  project_id: number;
  asset_id: number | null;
  pool_key: string;
  name: string;
  scope: FixtureScope;
  max_concurrency: number;
  lease_ttl_seconds: number;
  status: PoolStatus;
  item_count: number;
  available_count: number;
  active_lease_count: number;
  created_at: string;
  updated_at: string;
}

export interface DataPoolItem {
  id: number;
  pool_id: number;
  status: PoolItemStatus;
  payload_json: Record<string, unknown>; // 已脱敏
  occupied_count: number;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DataPoolCreate {
  name: string;
  pool_key: string;
  asset_id?: number | null;
  scope?: FixtureScope;
  max_concurrency?: number;
  lease_ttl_seconds?: number;
  status?: PoolStatus;
}

export interface DataPoolItemCreate {
  payload_json?: Record<string, unknown>;
  expires_at?: string | null;
  status?: PoolItemStatus;
}

export type DataPoolListResponse = Paginated<DataPool>;

export type DataPoolItemListResponse = Paginated<DataPoolItem>;

// ---- 被测库连接与策略 ----
export interface TargetDbConnection {
  id: number;
  project_id: number;
  environment_id: number;
  environment_name: string | null;
  environment_class: DbEnvironmentClass | null;
  name: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  schema_name: string | null;
  enabled: boolean;
  password_set: boolean; // 只回是否存在密码，绝不回显
  referenced_count: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface TargetDbConnectionCreate {
  environment_id: number;
  name: string;
  host: string;
  port?: number;
  database_name: string;
  username: string;
  password: string; // 创建时唯一一次明文
  schema_name?: string | null;
  enabled?: boolean;
}

export interface TargetDbConnectionUpdate {
  name?: string;
  host?: string;
  port?: number;
  database_name?: string;
  username?: string;
  password?: string;
  schema_name?: string | null;
  enabled?: boolean;
}

export type TargetDbConnectionListResponse = Paginated<TargetDbConnection>;

export interface DatabasePolicy {
  id: number;
  project_id: number;
  environment_id: number;
  enabled: boolean;
  allowed_tables: string[];
  allowed_operations: DbOperation[];
  environment_name: string | null;
  environment_display_name: string | null;
  environment_class: DbEnvironmentClass;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface DatabasePolicyUpsert {
  enabled: boolean;
  allowed_tables?: string[];
  allowed_operations?: DbOperation[];
}

export type DatabasePolicyListResponse = Paginated<DatabasePolicy>;
