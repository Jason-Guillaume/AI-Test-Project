// mocking 领域类型合同；仅暴露当前模块稳定使用的请求、响应与查询类型。
import type { Paginated } from '@/shared/api/contracts';


// 接口 Mock 与依赖异常模拟（Mock Management Phase 1）
//
// 字段命名与后端 features/mock_management/schemas.py 严格对齐（snake_case）。
// 安全约定：MockService 只返回 runtime_token_set 布尔值，绝不回显 token hash；
// 明文 runtime_token 仅在创建 / 重置接口响应里出现一次。

export type MockBehaviorType = 'STATIC_RESPONSE' | 'DELAY_RESPONSE' | 'TIMEOUT' | 'EMPTY_RESPONSE';

export type MockMatcherSource = 'METHOD' | 'PATH' | 'QUERY' | 'HEADER' | 'BODY';

export type MockMatcherOperator =
  | 'EQ'
  | 'NE'
  | 'EXISTS'
  | 'NOT_EXISTS'
  | 'CONTAINS'
  | 'IN'
  | 'JSON_PATH_EQ'
  | 'JSON_PATH_EXISTS';

export type MockContextStatus = 'ACTIVE' | 'CLOSED' | 'EXPIRED';

export type MockScope = 'SETUP' | 'EXECUTION' | 'BOTH';

/** Mock 依赖服务（maps / 支付 / AI 模型…）。 */
export interface MockService {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  service_key: string;
  base_path: string | null;
  enabled: boolean;
  default_scenario_id: number | null;
  public_runtime: boolean;
  /** 是否已配置 Runtime Token；token 本身永不回显。 */
  runtime_token_set: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  revision: number;
  runtime_url: string | null;
  endpoint_count: number;
  scenario_count: number;
}

export interface MockServiceCreate {
  name: string;
  description?: string | null;
  service_key: string;
  base_path?: string | null;
  enabled?: boolean;
  public_runtime?: boolean;
  /** 可选自定义明文 token；不传则后端自动生成。 */
  runtime_token?: string | null;
}

export interface MockServiceUpdate {
  name?: string;
  description?: string | null;
  base_path?: string | null;
  enabled?: boolean;
  public_runtime?: boolean;
  default_scenario_id?: number | null;
  /** 乐观锁版本号，不匹配返回 409。 */
  revision: number;
}

/** 创建 / 重置 token 的响应：明文 token 只在这里出现一次。 */
export interface MockServiceCreateResponse {
  service: MockService;
  runtime_token: string;
}

export type MockServiceListResponse = Paginated<MockService>;

/** Mock 接口。(service, method, path) 唯一。 */
export interface MockEndpoint {
  id: number;
  project_id: number;
  mock_service_id: number;
  api_id: number | null;
  name: string;
  method: string;
  path: string;
  description: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  revision: number;
  scenario_count: number;
}

export interface MockEndpointCreate {
  name: string;
  method: string;
  path: string;
  description?: string | null;
  api_id?: number | null;
  enabled?: boolean;
}

export interface MockEndpointUpdate {
  name?: string;
  method?: string;
  path?: string;
  description?: string | null;
  enabled?: boolean;
  revision: number;
}

export type MockEndpointListResponse = Paginated<MockEndpoint>;

/** 场景的匹配规则（source/field/operator/expected_value）。 */
export interface MockMatcher {
  id: number;
  scenario_id: number;
  source: MockMatcherSource;
  field: string;
  operator: MockMatcherOperator;
  expected_value: unknown;
  priority: number;
  enabled: boolean;
  created_at: string;
}

export interface MockMatcherCreate {
  source: MockMatcherSource;
  field: string;
  operator: MockMatcherOperator;
  expected_value?: unknown;
  priority?: number;
  enabled?: boolean;
}

export interface MockMatchersReplace {
  matchers: MockMatcherCreate[];
  /** 乐观锁：整体替换是重建式写入，带上 revision 可避免并发会话互相覆盖。 */
  revision?: number;
}

/** 一个 Endpoint 的一个行为场景。 */
export interface MockScenario {
  id: number;
  project_id: number;
  mock_endpoint_id: number;
  name: string;
  scenario_key: string;
  description: string | null;
  enabled: boolean;
  is_default: boolean;
  priority: number;
  behavior_type: MockBehaviorType;
  delay_ms: number | null;
  status_code: number;
  response_headers: Record<string, string> | null;
  response_body: unknown;
  response_template: unknown;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  revision: number;
  matchers: MockMatcher[];
  call_count: number;
}

export interface MockScenarioCreate {
  name: string;
  scenario_key: string;
  description?: string | null;
  enabled?: boolean;
  is_default?: boolean;
  priority?: number;
  behavior_type?: MockBehaviorType;
  delay_ms?: number | null;
  status_code?: number;
  response_headers?: Record<string, string> | null;
  response_body?: unknown;
  response_template?: unknown;
  matchers?: MockMatcherCreate[];
}

export interface MockScenarioUpdate {
  name?: string;
  description?: string | null;
  enabled?: boolean;
  is_default?: boolean;
  priority?: number;
  behavior_type?: MockBehaviorType;
  delay_ms?: number | null;
  status_code?: number;
  response_headers?: Record<string, string> | null;
  response_body?: unknown;
  response_template?: unknown;
  revision: number;
}

export type MockScenarioListResponse = Paginated<MockScenario>;

/** 场景试跑请求：模拟一个请求验证 Matcher + 响应构建，不真调被测系统。 */
export interface ScenarioTestRequest {
  method?: string;
  path?: string;
  query?: Record<string, unknown>;
  headers?: Record<string, string>;
  body?: unknown;
}

export interface ScenarioTestResponse {
  matched: boolean;
  scenario_id: number | null;
  scenario_key: string | null;
  status_code: number | null;
  headers: Record<string, string>;
  body: unknown;
  duration_ms: number;
  delay_ms: number;
}

/** Mock 调用记录（请求 / 响应快照已脱敏）。 */
export interface MockExecution {
  id: number;
  project_id: number;
  mock_service_id: number | null;
  mock_endpoint_id: number | null;
  mock_scenario_id: number | null;
  request_id: string | null;
  method: string;
  path: string;
  query_snapshot: unknown;
  header_snapshot: unknown;
  body_snapshot: unknown;
  response_status: number | null;
  response_header_snapshot: unknown;
  response_body_snapshot: unknown;
  matched: boolean;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  test_run_id: number | null;
  case_execution_id: number | null;
  mock_context_id: string | null;
  created_at: string;
  service_key: string | null;
  service_name: string | null;
  endpoint_path: string | null;
  scenario_key: string | null;
}

export interface MockExecutionListQuery {
  /** 后端查询参数名为 service_id。 */
  service_id?: number;
  matched?: boolean;
  test_run_id?: number;
  case_execution_id?: number;
  context_id?: string;
  page?: number;
  page_size?: number;
}

export type MockExecutionListResponse = Paginated<MockExecution>;

/** 用例执行激活的 Mock 上下文（scenario_overrides，支持并发隔离）。 */
export interface MockContext {
  id: number;
  context_id: string;
  project_id: number;
  test_run_id: number | null;
  case_execution_id: number | null;
  scenario_overrides: unknown;
  status: MockContextStatus;
  expires_at: string;
  created_at: string;
  closed_at: string | null;
}

/** 用例声明的 required_mocks（关联 service/endpoint/scenario + scope）。 */
export interface TestCaseMock {
  id: number;
  test_case_id: number;
  mock_service_id: number;
  mock_endpoint_id: number;
  mock_scenario_id: number;
  scope: MockScope;
  sort: number;
  created_at: string;
  service_key: string | null;
  service_name: string | null;
  endpoint_path: string | null;
  endpoint_method: string | null;
  scenario_key: string | null;
  scenario_name: string | null;
}

export interface TestCaseMockCreate {
  mock_service_id: number;
  mock_endpoint_id: number;
  mock_scenario_id: number;
  scope?: MockScope;
  sort?: number;
}

export interface TestCaseMocksReplace {
  mocks: TestCaseMockCreate[];
}

/** 从 API Catalog 一键创建 Mock（service + endpoint + 推荐场景模板）。 */
export interface CreateMockFromApiRequest {
  service_key: string;
  service_name?: string | null;
  endpoint_name?: string | null;
  templates?: string[];
  public_runtime?: boolean;
  runtime_token?: string | null;
}

export interface CreateMockFromApiResponse {
  service: MockService;
  endpoint_id: number;
  scenario_ids: number[];
  runtime_token: string | null;
}
