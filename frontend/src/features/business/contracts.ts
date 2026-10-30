// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。
import type { Paginated } from '@/shared/api/contracts';


// ============================================================ 业务管理
// 字段命名与后端 business schemas 严格对齐（snake_case）。
// 第一阶段 10 个实体 + 聚合详情（BusinessFlowDetail / BusinessActionDetail / BusinessBindingDetail）。
// 权限：读 = 项目可见（viewer+）；写 = 项目成员（member+）；越权按 404 返回，前端不展示。

export type BusinessDomainStatus = 'ACTIVE' | 'INACTIVE';

export type BusinessFlowStatus = 'DRAFT' | 'ACTIVE' | 'DEPRECATED';

export type BusinessActionType = 'NORMAL';

export type BusinessBindingType = 'API' | 'WEB';

export type BusinessPreconditionType = 'VARIABLE' | 'STATE' | 'BUSINESS' | 'TEXT';

export type BusinessPreconditionOperator = 'EQ' | 'NE' | 'IN' | 'CONTAINS' | 'EXISTS' | 'NOT_EXISTS';

export type BusinessVariableDirection = 'INPUT' | 'OUTPUT';

export type BusinessVariableDataType =
  | 'STRING' | 'INTEGER' | 'NUMBER' | 'BOOLEAN' | 'OBJECT' | 'ARRAY';

export type BusinessApiMappingDirection = 'INPUT' | 'OUTPUT';

export type BusinessApiLocation = 'BODY' | 'HEADER' | 'QUERY' | 'PATH' | 'RESPONSE';

export type BusinessRuleType = 'GENERAL' | 'CONSTRAINT' | 'PRECONDITION';

// ---- 业务域 ----
export interface BusinessDomain {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  sort: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface BusinessDomainCreate {
  name: string;
  description?: string | null;
  sort?: number;
  status?: BusinessDomainStatus;
}

export interface BusinessDomainUpdate {
  name?: string;
  description?: string | null;
  sort?: number;
  status?: BusinessDomainStatus;
}

export type BusinessDomainListResponse = Paginated<BusinessDomain>;

// ---- 业务流程 ----
export interface BusinessFlow {
  id: number;
  project_id: number;
  domain_id: number;
  name: string;
  description: string | null;
  status: string;
  version: number;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface BusinessFlowCreate {
  name: string;
  description?: string | null;
  status?: BusinessFlowStatus;
  domain_id: number;
}

export interface BusinessFlowUpdate {
  name?: string;
  description?: string | null;
  status?: BusinessFlowStatus;
  revision?: number;
}

export type BusinessFlowListResponse = Paginated<BusinessFlow>;

// ---- 业务动作 ----
export interface BusinessAction {
  id: number;
  flow_id: number;
  name: string;
  description: string | null;
  action_key: string;
  sort: number;
  action_type: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface BusinessActionCreate {
  name: string;
  description?: string | null;
  action_key: string;
  sort?: number;
  action_type?: BusinessActionType;
}

export interface BusinessActionUpdate {
  name?: string;
  description?: string | null;
  action_key?: string;
  sort?: number;
  action_type?: BusinessActionType;
  revision?: number;
}

export interface BusinessActionReorderItem {
  action_id: number;
  sort: number;
}

export interface BusinessActionReorder {
  items: BusinessActionReorderItem[];
}

// ---- 前置条件 ----
export interface BusinessPrecondition {
  id: number;
  action_id: number;
  type: BusinessPreconditionType;
  target: string;
  operator: BusinessPreconditionOperator;
  expected_value: string | null;
  description: string | null;
  sort: number;
  created_at: string;
  updated_at: string;
}

export interface BusinessPreconditionCreate {
  type: BusinessPreconditionType;
  target: string;
  operator?: BusinessPreconditionOperator;
  expected_value?: string | null;
  description?: string | null;
  sort?: number;
}

export interface BusinessPreconditionUpdate {
  type?: BusinessPreconditionType;
  target?: string;
  operator?: BusinessPreconditionOperator;
  expected_value?: string | null;
  description?: string | null;
  sort?: number;
}

// ---- 业务变量 ----
export interface BusinessVariable {
  id: number;
  action_id: number;
  direction: BusinessVariableDirection;
  name: string;
  data_type: BusinessVariableDataType;
  required: boolean;
  description: string | null;
  sort: number;
  created_at: string;
  updated_at: string;
}

export interface BusinessVariableCreate {
  direction: BusinessVariableDirection;
  name: string;
  data_type?: BusinessVariableDataType;
  required?: boolean;
  description?: string | null;
  sort?: number;
}

export interface BusinessVariableUpdate {
  direction?: BusinessVariableDirection;
  name?: string;
  data_type?: BusinessVariableDataType;
  required?: boolean;
  description?: string | null;
  sort?: number;
}

// ---- 业务状态 ----
export interface BusinessState {
  id: number;
  action_id: number;
  entity: string;
  pre_state: string | null;
  post_state: string | null;
  created_at: string;
  updated_at: string;
}

export interface BusinessStateCreate {
  entity: string;
  pre_state?: string | null;
  post_state?: string | null;
}

export interface BusinessStateUpdate {
  entity?: string;
  pre_state?: string | null;
  post_state?: string | null;
}

// ---- 变量引用 ----
export interface BusinessVariableRef {
  id: number;
  flow_id: number;
  source_action_id: number;
  source_variable: string;
  source_variable_id: number | null;
  target_action_id: number;
  target_variable: string;
  target_variable_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface BusinessVariableRefCreate {
  source_action_id: number;
  source_variable: string;
  target_action_id: number;
  target_variable: string;
}

// ---- 业务绑定 ----
export interface BusinessBinding {
  id: number;
  action_id: number;
  binding_type: BusinessBindingType;
  api_id: number | null;
  name: string | null;
  is_default: boolean;
  sort: number;
  config_json: Record<string, unknown> | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface BusinessBindingCreate {
  binding_type?: BusinessBindingType;
  api_id?: number | null;
  name?: string | null;
  is_default?: boolean;
  sort?: number;
  config_json?: Record<string, unknown> | null;
  enabled?: boolean;
}

export interface BusinessBindingUpdate {
  binding_type?: BusinessBindingType;
  api_id?: number | null;
  name?: string | null;
  is_default?: boolean;
  sort?: number;
  config_json?: Record<string, unknown> | null;
  enabled?: boolean;
}

export interface BusinessBindingDetail extends BusinessBinding {
  valid: boolean;
  invalid_reason: string | null;
  api_name: string | null;
  api_method: string | null;
  api_path: string | null;
  api_status: string | null;
  input_mappings: BusinessApiMapping[];
  output_mappings: BusinessApiMapping[];
}

// ---- API 映射 ----
export interface BusinessApiMapping {
  id: number;
  binding_id: number;
  direction: BusinessApiMappingDirection;
  business_variable: string;
  api_location: BusinessApiLocation;
  api_field: string | null;
  expression: string | null;
  created_at: string;
  updated_at: string;
}

export interface BusinessApiMappingCreate {
  direction: BusinessApiMappingDirection;
  business_variable: string;
  api_location: BusinessApiLocation;
  api_field?: string | null;
  expression?: string | null;
}

export interface BusinessApiMappingUpdate {
  direction?: BusinessApiMappingDirection;
  business_variable?: string;
  api_location?: BusinessApiLocation;
  api_field?: string | null;
  expression?: string | null;
}

// ---- 业务规则 ----
export interface BusinessRule {
  id: number;
  project_id: number;
  flow_id: number | null;
  action_id: number | null;
  name: string;
  description: string | null;
  rule_type: BusinessRuleType;
  expression: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface BusinessRuleCreate {
  name: string;
  description?: string | null;
  rule_type?: BusinessRuleType;
  expression?: string | null;
  enabled?: boolean;
  flow_id?: number | null;
  action_id?: number | null;
}

export interface BusinessRuleUpdate {
  name?: string;
  description?: string | null;
  rule_type?: BusinessRuleType;
  expression?: string | null;
  enabled?: boolean;
}

export type BusinessRuleListResponse = Paginated<BusinessRule>;

// ---- 聚合详情 ----
export interface BusinessActionDetail extends BusinessAction {
  preconditions: BusinessPrecondition[];
  input_variables: BusinessVariable[];
  output_variables: BusinessVariable[];
  states: BusinessState[];
  binding: BusinessBindingDetail | null;
}

export interface BusinessFlowDetail extends BusinessFlow {
  domain_name: string | null;
  actions: BusinessActionDetail[];
  variable_refs: BusinessVariableRef[];
  rules: BusinessRule[];
}

// ---- 执行引擎 ----
export type FlowExecutionStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED';

export type ActionExecutionStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'SKIPPED';

export interface FlowExecutionRequest {
  environment_id: number;
  variables?: Record<string, unknown>;
}

export interface FlowExecution {
  id: number;
  project_id: number;
  flow_id: number;
  environment_id: number | null;
  status: FlowExecutionStatus;
  started_at: string | null;
  finished_at: string | null;
  context_json: Record<string, unknown> | null;
  error_message: string | null;
  error_code: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface ActionExecution {
  id: number;
  flow_execution_id: number;
  action_id: number | null;
  binding_id: number | null;
  sequence: number;
  status: ActionExecutionStatus;
  request_snapshot: Record<string, unknown> | null;
  response_snapshot: Record<string, unknown> | null;
  input_context: Record<string, unknown> | null;
  output_context: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  error_code: string | null;
  unverified_preconditions: Array<Record<string, unknown>> | null;
  created_at: string;
  updated_at: string;
}

export type FlowExecutionActionListResponse = Paginated<ActionExecution>;
