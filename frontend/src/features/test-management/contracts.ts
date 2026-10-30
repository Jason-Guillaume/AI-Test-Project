// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。
import type { Paginated } from '@/shared/api/contracts';


// ============================================================ 测试管理
// 字段命名与后端 test_management schemas 严格对齐（snake_case）。
// 覆盖：测试资产 TestStrategy / TestPoint / TestCase（含前置条件 / 测试数据 / 步骤 / 断言
// 子实体 + 聚合详情 TestCaseDetail）、测试管理 TestSuite / TestPlan / TestRun / CaseExecution。
// §27：source_type 预留 AI 取值（当前仅 MANUAL，后端校验；前端下拉只给 MANUAL）。
// §25：所有测试资产归属 Project，跨项目访问按 404 返回，前端不展示。
// §26：TestCase.revision 乐观锁——并发更新冲突返回 409，前端提示「当前测试用例已被其他用户修改」。
// §16：TestCase 通过 target_type 路由执行器：API→ApiRequestExecutor、
//      BUSINESS_FLOW→BusinessFlowExecutor、BUSINESS_ACTION→复用业务执行器单步。

// ---- 枚举字面量（与后端 Literal/常量元组逐项对齐）----
export type TestStrategyCategory =
  | 'FUNCTIONAL' | 'PARAMETER' | 'BOUNDARY' | 'AUTH' | 'PERMISSION'
  | 'BUSINESS' | 'EXCEPTION' | 'IDEMPOTENCY' | 'SECURITY' | 'DATA_CONSISTENCY';

export type TestPriority = 'P0' | 'P1' | 'P2' | 'P3';

export type TestTargetType = 'API' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION' | 'WEB';

export type TestStatus = 'DRAFT' | 'ACTIVE' | 'DEPRECATED';

export type TestSourceType = 'MANUAL' | 'AI';

// §27：AI 预留，当前不产生
export type TestCaseType =
  | 'FUNCTIONAL' | 'BUSINESS' | 'NEGATIVE' | 'BOUNDARY' | 'PERMISSION' | 'SECURITY' | 'EXCEPTION';

export type TestPreconditionType =
  | 'VARIABLE' | 'TEXT' | 'FIXTURE' | 'API' | 'BUSINESS_ACTION' | 'BUSINESS_FLOW';

export type TestOperator =
  | 'EQ' | 'NE' | 'GT' | 'GE' | 'LT' | 'LE' | 'IN' | 'CONTAINS' | 'EXISTS' | 'NOT_EXISTS';

export type TestValueType = 'STRING' | 'INTEGER' | 'NUMBER' | 'BOOLEAN' | 'OBJECT' | 'ARRAY';

export type TestDataSourceType = 'STATIC' | 'ENVIRONMENT' | 'VARIABLE' | 'RUNTIME' | 'FAKER' | 'FIXTURE';

export type TestStepType = 'SETUP' | 'ACTION' | 'ASSERT' | 'CLEANUP';

export type TestAssertionType =
  | 'STATUS_CODE' | 'JSON_PATH' | 'HEADER' | 'RESPONSE_TIME' | 'CONTAINS' | 'NOT_CONTAINS';

export type TestSuiteType = 'SMOKE' | 'REGRESSION' | 'BUSINESS' | 'CUSTOM';

export type TestPlanStatus = 'DRAFT' | 'ACTIVE' | 'DISABLED';

export type TestExecutionMode = 'MANUAL' | 'SCHEDULED' | 'CI';

export type TestRunStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED';

export type CaseExecutionStatus = 'PENDING' | 'RUNNING' | 'PASSED' | 'FAILED' | 'SKIPPED' | 'ERROR';

export type CaseExecutorType = 'API' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION';

// §16 路由依据

// ---- 测试策略 ----
export interface TestStrategy {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  category: string;
  enabled: boolean;
  source_type: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface TestStrategyCreate {
  name: string;
  description?: string | null;
  category?: TestStrategyCategory;
  enabled?: boolean;
}

export interface TestStrategyUpdate {
  name?: string;
  description?: string | null;
  category?: TestStrategyCategory;
  enabled?: boolean;
}

// ---- 测试点 ----
export interface TestPoint {
  id: number;
  project_id: number;
  strategy_id: number | null;
  name: string;
  description: string | null;
  priority: string;
  target_type: string;
  api_id: number | null;
  business_flow_id: number | null;
  business_action_id: number | null;
  status: string;
  source_type: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface TestPointCreate {
  name: string;
  description?: string | null;
  priority?: TestPriority;
  target_type?: TestTargetType;
  strategy_id?: number | null;
  api_id?: number | null;
  business_flow_id?: number | null;
  business_action_id?: number | null;
  status?: TestStatus;
}

export interface TestPointUpdate {
  name?: string;
  description?: string | null;
  priority?: TestPriority;
  target_type?: TestTargetType;
  strategy_id?: number | null;
  api_id?: number | null;
  business_flow_id?: number | null;
  business_action_id?: number | null;
  status?: TestStatus;
}

// ---- 测试用例 ----
export interface TestCase {
  id: number;
  project_id: number;
  test_point_id: number | null;
  name: string;
  description: string | null;
  priority: string;
  case_type: string;
  target_type: string;
  api_id: number | null;
  business_flow_id: number | null;
  business_action_id: number | null;
  status: string;
  enabled: boolean;
  revision: number; // §26 乐观锁版本号
  source_type: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface TestCaseCreate {
  name: string;
  description?: string | null;
  priority?: TestPriority;
  case_type?: TestCaseType;
  target_type?: TestTargetType;
  test_point_id?: number | null;
  api_id?: number | null;
  business_flow_id?: number | null;
  business_action_id?: number | null;
  status?: TestStatus;
  enabled?: boolean;
}

export interface TestCaseUpdate {
  name?: string;
  description?: string | null;
  priority?: TestPriority;
  case_type?: TestCaseType;
  target_type?: TestTargetType;
  test_point_id?: number | null;
  api_id?: number | null;
  business_flow_id?: number | null;
  business_action_id?: number | null;
  status?: TestStatus;
  enabled?: boolean;
  revision?: number; // §26：更新时携带当前 revision，不匹配 → 409
}

// ---- 用例子实体：前置条件 ----
export interface TestCasePrecondition {
  id: number;
  test_case_id: number;
  type: string;
  target: string | null;
  operator: string;
  expected_value: string | null;
  description: string | null;
  config_json: Record<string, unknown> | null;
  sort: number;
  created_at: string;
  updated_at: string;
}

export interface TestCasePreconditionCreate {
  type?: TestPreconditionType;
  target?: string | null;
  operator?: TestOperator;
  expected_value?: string | null;
  description?: string | null;
  config_json?: Record<string, unknown> | null;
  sort?: number;
}

export interface TestCasePreconditionUpdate {
  type?: TestPreconditionType;
  target?: string | null;
  operator?: TestOperator;
  expected_value?: string | null;
  description?: string | null;
  config_json?: Record<string, unknown> | null;
  sort?: number;
}

// ---- 用例子实体：测试数据 ----
export interface TestCaseData {
  id: number;
  test_case_id: number;
  name: string;
  value_type: string;
  value: string | null;
  source_type: string;
  required: boolean;
  description: string | null;
  config_json: Record<string, unknown> | null;
  sort: number;
  created_at: string;
  updated_at: string;
}

export interface TestCaseDataCreate {
  name: string;
  value_type?: TestValueType;
  value?: string | null;
  source_type?: TestDataSourceType;
  required?: boolean;
  description?: string | null;
  config_json?: Record<string, unknown> | null;
  sort?: number;
}

// 注意：Update 不含 name（数据项名不可改，与后端 TestCaseDataUpdate 一致）。
export interface TestCaseDataUpdate {
  value_type?: TestValueType;
  value?: string | null;
  source_type?: TestDataSourceType;
  required?: boolean;
  description?: string | null;
  config_json?: Record<string, unknown> | null;
  sort?: number;
}

// ---- 用例子实体：所需 Fixture（执行前由平台按依赖顺序生成）----
export interface TestCaseFixture {
  id: number;
  test_case_id: number;
  fixture_id: number;
  fixture_key: string;
  name: string;
  entity_type: string | null;
  scope: 'PROJECT' | 'GLOBAL';
  status: string;
  outputs: string[];
  sort: number;
}

export interface TestCaseFixtureCreate {
  fixture_key: string;
  sort?: number;
}

// ---- 用例子实体：步骤 ----
export interface TestStep {
  id: number;
  test_case_id: number;
  name: string;
  step_type: string;
  target_type: string | null;
  target_id: number | null;
  sort: number;
  config_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface TestStepCreate {
  name: string;
  step_type?: TestStepType;
  target_type?: TestTargetType | null;
  target_id?: number | null;
  sort?: number;
  config_json?: Record<string, unknown> | null;
}

export interface TestStepUpdate {
  name?: string;
  step_type?: TestStepType;
  target_type?: TestTargetType | null;
  target_id?: number | null;
  sort?: number;
  config_json?: Record<string, unknown> | null;
}

// ---- 用例子实体：断言 ----
export interface TestAssertion {
  id: number;
  test_case_id: number;
  step_id: number | null;
  assertion_type: string;
  source: string | null;
  path: string | null;
  operator: string;
  expected_value: string | null;
  required: boolean;
  sort: number;
  created_at: string;
  updated_at: string;
}

export interface TestAssertionCreate {
  assertion_type?: TestAssertionType;
  source?: string | null;
  path?: string | null;
  operator?: TestOperator;
  expected_value?: string | null;
  required?: boolean;
  step_id?: number | null;
  sort?: number;
}

export interface TestAssertionUpdate {
  assertion_type?: TestAssertionType;
  source?: string | null;
  path?: string | null;
  operator?: TestOperator;
  expected_value?: string | null;
  required?: boolean;
  step_id?: number | null;
  sort?: number;
}

// ---- 用例聚合详情（编辑器一次性拉取，减少往返）----
export interface TestCaseDetail extends TestCase {
  preconditions: TestCasePrecondition[];
  test_data: TestCaseData[];
  steps: TestStep[];
  assertions: TestAssertion[];
  fixtures: TestCaseFixture[];
}

// ---- 测试套件 ----
export interface TestSuite {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  suite_type: string;
  enabled: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface TestSuiteCreate {
  name: string;
  description?: string | null;
  suite_type?: TestSuiteType;
  enabled?: boolean;
}

export interface TestSuiteUpdate {
  name?: string;
  description?: string | null;
  suite_type?: TestSuiteType;
  enabled?: boolean;
}

export interface TestSuiteCaseAdd {
  test_case_id: number;
  sort?: number;
  enabled?: boolean;
}

export interface TestSuiteCaseResponse {
  id: number;
  suite_id: number;
  test_case_id: number;
  sort: number;
  enabled: boolean;
  created_at: string;
}

// ---- 测试计划 ----
export interface TestPlan {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  environment_id: number | null;
  status: string;
  execution_mode: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface TestPlanCreate {
  name: string;
  description?: string | null;
  environment_id?: number | null;
  status?: TestPlanStatus;
  execution_mode?: TestExecutionMode;
}

export interface TestPlanUpdate {
  name?: string;
  description?: string | null;
  environment_id?: number | null;
  status?: TestPlanStatus;
  execution_mode?: TestExecutionMode;
}

export interface TestPlanSuiteAdd {
  suite_id: number;
  sort?: number;
}

export interface TestPlanSuiteResponse {
  id: number;
  plan_id: number;
  suite_id: number;
  sort: number;
  created_at: string;
}

// ---- 测试执行 ----
export interface TestRunCreateRequest {
  environment_id?: number | null; // 覆盖计划环境；为空用计划环境
}

export interface TestRun {
  id: number;
  project_id: number;
  plan_id: number | null;
  environment_id: number | null;
  status: string;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  error: number;
  started_at: string | null;
  finished_at: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

// list_runs 返回分页信封（后端 TestRunListResponse）。
export type TestRunListResponse = Paginated<TestRun>;

export interface CaseExecution {
  id: number;
  test_run_id: number;
  test_case_id: number | null;
  status: string;
  executor_type: string | null;
  request_snapshot: Record<string, unknown> | null;
  response_snapshot: Record<string, unknown> | null;
  assertion_results: Array<Record<string, unknown>> | null;
  context_json: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

// list_case_executions 返回分页信封（后端 CaseExecutionListResponse）。
export type CaseExecutionListResponse = Paginated<CaseExecution>;
