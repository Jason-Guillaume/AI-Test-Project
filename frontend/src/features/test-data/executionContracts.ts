// 测试数据运行记录的只读响应合同。
import type { Paginated } from '@/shared/api/contracts';
import type { CleanupStatus, DataExecutionStatus, ProviderExecutionStatus } from './contracts';

// ---- 执行记录（只读；Phase A 列表恒空） ----
export interface ProviderExecution {
  id: number;
  fixture_execution_id: number | null;
  data_execution_id: number | null;
  project_id: number;
  provider_id: number | null;
  provider_type: string;
  step_id: number | null;
  status: ProviderExecutionStatus;
  input_snapshot: Record<string, unknown> | null; // 已脱敏
  output_snapshot: Record<string, unknown> | null; // 已脱敏
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  cleanup_status: CleanupStatus | null;
}

export interface FixtureExecution {
  id: number;
  data_execution_id: number;
  project_id: number;
  fixture_id: number | null;
  fixture_key: string;
  status: DataExecutionStatus;
  scope: string;
  cache_hit: boolean;
  input_snapshot: Record<string, unknown> | null;
  output_snapshot: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  cleanup_status: CleanupStatus | null;
  cleanup_error_code: string | null;
  cleanup_error_message: string | null;
  provider_executions: ProviderExecution[];
}

export interface DataExecution {
  id: number;
  project_id: number;
  test_run_id: number | null;
  case_execution_id: number | null;
  environment_id: number | null;
  status: DataExecutionStatus;
  scope: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  cleanup_status: CleanupStatus | null;
  cleanup_error_code: string | null;
  cleanup_error_message: string | null;
  fixture_key_count: number;
  provider_step_count: number;
  created_at: string;
}

export interface DataExecutionDetail extends DataExecution {
  fixture_executions: FixtureExecution[];
  /**
   * 没有归属 Fixture 的步骤记录：手工试跑单个 Provider 时
   * fixture_execution_id 为空，只能挂在这一层。
   */
  provider_executions: ProviderExecution[];
}

export interface DataExecutionListQuery {
  status?: DataExecutionStatus;
  test_run_id?: number;
  page?: number;
  page_size?: number;
}

export type DataExecutionListResponse = Paginated<DataExecution>;
