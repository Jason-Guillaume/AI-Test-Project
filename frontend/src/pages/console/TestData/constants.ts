// 测试数据中心下拉选项与字面量映射。
// 字面量值与后端 features/test_data/schemas.py 的枚举严格一致，前端只做展示包装，
// 不在前端重新定义业务语义（脱敏、风险、环境分级以后端为准）。
import type {
  AssetSource,
  AssetStatus,
  CleanupStatus,
  DataExecutionStatus,
  DbEnvironmentClass,
  DbOperation,
  FixtureCleanupPolicy,
  FixtureOnFailure,
  FixturePhase,
  FixtureScope,
  FixtureStatus,
  FixtureStepType,
  PoolItemStatus,
  PoolStatus,
  ProviderExecutionStatus,
  ProviderType,
  RiskLevel,
  ValueType,
} from '@/types';

/** 通用下拉选项：label 为中文展示，value 为后端字面量。 */
export interface Option<T extends string = string> {
  label: string;
  value: T;
}

export const FIXTURE_SCOPE_OPTIONS: Option<FixtureScope>[] = [
  { label: '用例级 CASE', value: 'CASE' },
  { label: '运行级 RUN', value: 'RUN' },
  { label: '项目级 PROJECT', value: 'PROJECT' },
  { label: '全局 GLOBAL', value: 'GLOBAL' },
];
export const FIXTURE_STATUS_OPTIONS: Option<FixtureStatus>[] = [
  { label: '草稿', value: 'DRAFT' },
  { label: '启用', value: 'ACTIVE' },
  { label: '停用', value: 'DISABLED' },
];
export const FIXTURE_CLEANUP_POLICY_OPTIONS: Option<FixtureCleanupPolicy>[] = [
  { label: '用例后清理', value: 'AFTER_CASE' },
  { label: '运行后清理', value: 'AFTER_RUN' },
  { label: '手动清理', value: 'MANUAL' },
  { label: '不清理', value: 'NEVER' },
];
export const FIXTURE_PHASE_OPTIONS: Option<FixturePhase>[] = [
  { label: '生成', value: 'GENERATE' },
  { label: '清理', value: 'CLEANUP' },
];
export const FIXTURE_STEP_TYPE_OPTIONS: Option<FixtureStepType>[] = [
  { label: '引用 Fixture', value: 'FIXTURE' },
  { label: '接口调用', value: 'API' },
  { label: '业务动作', value: 'BUSINESS_ACTION' },
  { label: '业务流程', value: 'BUSINESS_FLOW' },
  { label: 'Faker 造数', value: 'FAKER' },
  { label: '静态值', value: 'STATIC' },
  { label: '数据库插入', value: 'DATABASE_INSERT' },
  { label: '数据库更新', value: 'DATABASE_PATCH' },
  { label: '等待', value: 'WAIT' },
  { label: '数据库查询', value: 'DATABASE_QUERY' },
  { label: '外部 Provider', value: 'EXTERNAL_PROVIDER' },
];
export const FIXTURE_ON_FAILURE_OPTIONS: Option<FixtureOnFailure>[] = [
  { label: '中止', value: 'ABORT' },
  { label: '继续', value: 'CONTINUE' },
];
export const VALUE_TYPE_OPTIONS: Option<ValueType>[] = [
  { label: '字符串 STRING', value: 'STRING' },
  { label: '整数 INTEGER', value: 'INTEGER' },
  { label: '小数 NUMBER', value: 'NUMBER' },
  { label: '布尔 BOOLEAN', value: 'BOOLEAN' },
  { label: '对象 OBJECT', value: 'OBJECT' },
  { label: '数组 ARRAY', value: 'ARRAY' },
];

export const PROVIDER_TYPE_OPTIONS: Option<ProviderType>[] = [
  { label: '静态值 STATIC', value: 'STATIC' },
  { label: '环境变量 ENVIRONMENT', value: 'ENVIRONMENT' },
  { label: 'Faker 造数', value: 'FAKER' },
  { label: '接口创建 API_CREATE', value: 'API_CREATE' },
  { label: '业务动作 BUSINESS_ACTION', value: 'BUSINESS_ACTION' },
  { label: '业务流程 BUSINESS_FLOW', value: 'BUSINESS_FLOW' },
  { label: '既有数据池 EXISTING_POOL', value: 'EXISTING_POOL' },
  { label: '数据库插入 DATABASE_INSERT', value: 'DATABASE_INSERT' },
  { label: '数据库更新 DATABASE_PATCH', value: 'DATABASE_PATCH' },
];
export const RISK_LEVEL_OPTIONS: Option<RiskLevel>[] = [
  { label: '低 LOW', value: 'LOW' },
  { label: '中 MEDIUM', value: 'MEDIUM' },
  { label: '高 HIGH', value: 'HIGH' },
  { label: '极高 CRITICAL', value: 'CRITICAL' },
];
export const RISK_LEVEL_COLOR: Record<RiskLevel, string> = {
  LOW: 'default',
  MEDIUM: 'blue',
  HIGH: 'orange',
  CRITICAL: 'red',
};

export const ASSET_SOURCE_OPTIONS: Option<AssetSource>[] = [
  { label: '静态值', value: 'STATIC' },
  { label: '数据池', value: 'POOL' },
  { label: 'Fixture', value: 'FIXTURE' },
];
export const ASSET_STATUS_OPTIONS: Option<AssetStatus>[] = [
  { label: '启用', value: 'ACTIVE' },
  { label: '停用', value: 'DISABLED' },
  { label: '过期', value: 'EXPIRED' },
];
export const ASSET_STATUS_COLOR: Record<AssetStatus, string> = {
  ACTIVE: 'green',
  DISABLED: 'default',
  EXPIRED: 'orange',
};

export const POOL_STATUS_OPTIONS: Option<PoolStatus>[] = [
  { label: '启用', value: 'ACTIVE' },
  { label: '停用', value: 'DISABLED' },
];
export const POOL_ITEM_STATUS_OPTIONS: Option<PoolItemStatus>[] = [
  { label: '可用', value: 'AVAILABLE' },
  { label: '占用中', value: 'OCCUPIED' },
  { label: '过期', value: 'EXPIRED' },
  { label: '停用', value: 'DISABLED' },
];
export const POOL_ITEM_STATUS_COLOR: Record<PoolItemStatus, string> = {
  AVAILABLE: 'green',
  OCCUPIED: 'orange',
  EXPIRED: 'default',
  DISABLED: 'red',
};

export const DB_OPERATION_OPTIONS: Option<DbOperation>[] = [
  { label: '查询 SELECT', value: 'SELECT' },
  { label: '插入 INSERT', value: 'INSERT' },
  { label: '更新 UPDATE', value: 'UPDATE' },
  { label: '删除 DELETE', value: 'DELETE' },
];
export const DB_ENVIRONMENT_CLASS_OPTIONS: Option<DbEnvironmentClass>[] = [
  { label: '开发 DEV', value: 'DEV' },
  { label: '测试 TEST', value: 'TEST' },
  { label: '预发 STAGING', value: 'STAGING' },
  { label: '生产 PRODUCTION', value: 'PRODUCTION' },
];
export const DB_ENVIRONMENT_CLASS_COLOR: Record<DbEnvironmentClass, string> = {
  DEV: 'blue',
  TEST: 'cyan',
  STAGING: 'orange',
  PRODUCTION: 'red',
};

export const DATA_EXECUTION_STATUS_OPTIONS: Option<DataExecutionStatus>[] = [
  { label: '排队中', value: 'PENDING' },
  { label: '生成中', value: 'GENERATING' },
  { label: '就绪', value: 'READY' },
  { label: '失败', value: 'FAILED' },
  { label: '过期', value: 'EXPIRED' },
  { label: '脏数据', value: 'DIRTY' },
  { label: '清理中', value: 'CLEANING' },
  { label: '已清理', value: 'CLEANED' },
];
export const DATA_EXECUTION_STATUS_COLOR: Record<DataExecutionStatus, string> = {
  PENDING: 'default',
  GENERATING: 'processing',
  READY: 'green',
  FAILED: 'red',
  EXPIRED: 'orange',
  DIRTY: 'gold',
  CLEANING: 'processing',
  CLEANED: 'blue',
};

export const PROVIDER_EXECUTION_STATUS_OPTIONS: Option<ProviderExecutionStatus>[] = [
  { label: '排队中', value: 'PENDING' },
  { label: '执行中', value: 'RUNNING' },
  { label: '成功', value: 'SUCCESS' },
  { label: '失败', value: 'FAILED' },
  { label: '跳过', value: 'SKIPPED' },
];
export const PROVIDER_EXECUTION_STATUS_COLOR: Record<ProviderExecutionStatus, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  SUCCESS: 'green',
  FAILED: 'red',
  SKIPPED: 'orange',
};

export const CLEANUP_STATUS_OPTIONS: Option<CleanupStatus>[] = [
  { label: '待清理', value: 'PENDING' },
  { label: '成功', value: 'SUCCESS' },
  { label: '失败', value: 'FAILED' },
  { label: '跳过', value: 'SKIPPED' },
];
export const CLEANUP_STATUS_COLOR: Record<CleanupStatus, string> = {
  PENDING: 'default',
  SUCCESS: 'green',
  FAILED: 'red',
  SKIPPED: 'orange',
};

/** 按字面量查中文展示；取不到时回退原值，避免页面出现裸 enum 让人困惑。 */
export function labelOf<T extends string>(
  opts: Option<T>[],
  value: T | null | undefined,
): string {
  if (value == null || value === '') return '-';
  return opts.find((o) => o.value === value)?.label ?? value;
}
