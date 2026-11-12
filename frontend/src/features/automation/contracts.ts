// 云效自动化测试中心的接口契约。凭证只在创建和更新请求里出现。

export interface AutomationIntegration {
  id: number;
  project_id: number;
  name: string;
  api_base_url: string;
  organization_id: string;
  deployment: 'central' | 'region';
  token_configured: boolean;
  callback_key: string;
  callback_secret_configured: boolean;
  callback_path: string;
  default_timeout_seconds: number;
  created_at: string;
}

export interface AutomationProject {
  id: number;
  project_id: number;
  integration_config_id: number;
  name: string;
  description: string;
  repository_url: string;
  repository_id: string;
  pipeline_id: string;
  pipeline_name: string;
  default_branch: string;
  default_environment: string;
  pytest_args: string;
  test_tags: string;
  test_scope: string;
  pipeline_params: Record<string, string>;
  timeout_seconds: number;
  notification_channel_id: number | null;
  notify_condition: 'ALWAYS' | 'ONLY_FAILED' | 'NEVER';
  enabled: boolean;
  last_status: string | null;
  last_execution_at: string | null;
  created_at: string;
}

export interface AutomationExecution {
  id: number;
  project_id: number;
  automation_project_id: number;
  automation_project_name: string;
  pipeline_id: string;
  pipeline_run_id: string | null;
  trigger_source: string;
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED' | 'TIMEOUT';
  branch: string;
  environment_name: string;
  pytest_args: string;
  test_tags: string;
  test_scope: string;
  git_commit: string;
  external_status: string;
  log_excerpt: string;
  error_message: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  notify_status: string;
  report_id: number | null;
  created_at: string;
}

export interface AutomationReport {
  id: number;
  execution_id: number;
  project_id: number;
  automation_project_id: number;
  automation_project_name: string;
  status: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  broken_cases: number;
  skipped_cases: number;
  unknown_cases: number;
  pass_rate: number;
  duration_ms: number | null;
  suite_summary: Array<{ name: string; total: number; passed: number; failed: number; broken: number; skipped: number }>;
  history_included: boolean;
  branch: string;
  environment_name: string;
  git_commit: string;
  generated_at: string | null;
  created_at: string;
}

export interface ReportGrant {
  token: string;
  expires_at: string;
  index_url: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
