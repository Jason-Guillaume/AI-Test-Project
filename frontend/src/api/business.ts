// 业务管理相关接口。字段命名与后端 business schemas 严格对齐（snake_case）。
// 权限：读 = 项目可见（viewer+）；写（建/改/删/重排）= 项目 member+；越权按 404 返回，前端不展示。
//
// 路由形态：单 APIRouter 挂在 /api/v1 下，资源级路径（无额外前缀）：
//   /projects/{project_id}/business-domains、/business-domains/{domain_id}
//   /projects/{project_id}/business-flows、/business-flows/{flow_id}(/detail)
//   /business-flows/{flow_id}/actions、/business-actions/{action_id}
//   /business-actions/{action_id}/(preconditions|variables|states|bindings)
//   /business-(preconditions|variables|states|bindings|api-mappings)/{id}
//   /business-flows/{flow_id}/variable-refs、/business-variable-refs/{id}
//   /projects/{project_id}/business-rules、/business-rules/{rule_id}
import { api } from './client';
import type {
  BusinessAction,
  BusinessActionCreate,
  BusinessActionDetail,
  BusinessActionReorder,
  BusinessActionUpdate,
  BusinessApiMapping,
  BusinessApiMappingCreate,
  BusinessApiMappingUpdate,
  BusinessBindingDetail,
  BusinessBindingCreate,
  BusinessBindingUpdate,
  BusinessDomain,
  BusinessDomainCreate,
  BusinessDomainUpdate,
  BusinessFlow,
  BusinessFlowCreate,
  BusinessFlowDetail,
  BusinessFlowUpdate,
  BusinessPrecondition,
  BusinessPreconditionCreate,
  BusinessPreconditionUpdate,
  BusinessRule,
  BusinessRuleCreate,
  BusinessRuleUpdate,
  BusinessState,
  BusinessStateCreate,
  BusinessStateUpdate,
  BusinessVariable,
  BusinessVariableCreate,
  BusinessVariableRef,
  BusinessVariableRefCreate,
  BusinessVariableUpdate,
  Paginated,
} from '@/types';

/**
 * 业务管理接口集合，由业务管理页与流程详情页调用。
 * 端点覆盖：业务域/流程/动作 CRUD + 重排、前置条件/变量/状态 CRUD、
 * 绑定（含失效判定）+ API 映射 CRUD、变量引用 CRUD、业务规则 CRUD、流程聚合详情。
 */
export const businessApi = {
  // ---- 业务域 ----
  listDomains: (projectId: number, params: { page?: number; page_size?: number; keyword?: string; status?: string }) =>
    api.get<Paginated<BusinessDomain>>(`/projects/${projectId}/business-domains`, { params }),
  createDomain: (projectId: number, body: BusinessDomainCreate) =>
    api.post<BusinessDomain>(`/projects/${projectId}/business-domains`, body),
  getDomain: (domainId: number) => api.get<BusinessDomain>(`/business-domains/${domainId}`),
  updateDomain: (domainId: number, body: BusinessDomainUpdate) =>
    api.patch<BusinessDomain>(`/business-domains/${domainId}`, body),
  removeDomain: (domainId: number) => api.delete<void>(`/business-domains/${domainId}`),

  // ---- 业务流程 ----
  listFlows: (projectId: number, params: { page?: number; page_size?: number; domain_id?: number; status?: string; keyword?: string }) =>
    api.get<Paginated<BusinessFlow>>(`/projects/${projectId}/business-flows`, { params }),
  createFlow: (projectId: number, body: BusinessFlowCreate) =>
    api.post<BusinessFlow>(`/projects/${projectId}/business-flows`, body),
  getFlow: (flowId: number) => api.get<BusinessFlow>(`/business-flows/${flowId}`),
  getFlowDetail: (flowId: number) => api.get<BusinessFlowDetail>(`/business-flows/${flowId}/detail`),
  updateFlow: (flowId: number, body: BusinessFlowUpdate) =>
    api.patch<BusinessFlow>(`/business-flows/${flowId}`, body),
  removeFlow: (flowId: number) => api.delete<void>(`/business-flows/${flowId}`),

  // ---- 业务动作 ----
  listActions: (flowId: number) => api.get<BusinessAction[]>(`/business-flows/${flowId}/actions`),
  createAction: (flowId: number, body: BusinessActionCreate) =>
    api.post<BusinessAction>(`/business-flows/${flowId}/actions`, body),
  updateAction: (actionId: number, body: BusinessActionUpdate) =>
    api.patch<BusinessAction>(`/business-actions/${actionId}`, body),
  removeAction: (actionId: number) => api.delete<void>(`/business-actions/${actionId}`),
  reorderActions: (flowId: number, body: BusinessActionReorder) =>
    api.patch<BusinessAction[]>(`/business-flows/${flowId}/actions/reorder`, body),

  // ---- 前置条件 ----
  listPreconditions: (actionId: number) =>
    api.get<BusinessPrecondition[]>(`/business-actions/${actionId}/preconditions`),
  createPrecondition: (actionId: number, body: BusinessPreconditionCreate) =>
    api.post<BusinessPrecondition>(`/business-actions/${actionId}/preconditions`, body),
  updatePrecondition: (preconditionId: number, body: BusinessPreconditionUpdate) =>
    api.patch<BusinessPrecondition>(`/business-preconditions/${preconditionId}`, body),
  removePrecondition: (preconditionId: number) =>
    api.delete<void>(`/business-preconditions/${preconditionId}`),

  // ---- 业务变量 ----
  listVariables: (actionId: number) =>
    api.get<BusinessVariable[]>(`/business-actions/${actionId}/variables`),
  createVariable: (actionId: number, body: BusinessVariableCreate) =>
    api.post<BusinessVariable>(`/business-actions/${actionId}/variables`, body),
  updateVariable: (variableId: number, body: BusinessVariableUpdate) =>
    api.patch<BusinessVariable>(`/business-variables/${variableId}`, body),
  removeVariable: (variableId: number) => api.delete<void>(`/business-variables/${variableId}`),

  // ---- 业务状态 ----
  listStates: (actionId: number) => api.get<BusinessState[]>(`/business-actions/${actionId}/states`),
  createState: (actionId: number, body: BusinessStateCreate) =>
    api.post<BusinessState>(`/business-actions/${actionId}/states`, body),
  updateState: (stateId: number, body: BusinessStateUpdate) =>
    api.patch<BusinessState>(`/business-states/${stateId}`, body),
  removeState: (stateId: number) => api.delete<void>(`/business-states/${stateId}`),

  // ---- 业务绑定（含失效判定 + 映射） ----
  listBindings: (actionId: number) =>
    api.get<BusinessBindingDetail[]>(`/business-actions/${actionId}/bindings`),
  createBinding: (actionId: number, body: BusinessBindingCreate) =>
    api.post<BusinessBindingDetail>(`/business-actions/${actionId}/bindings`, body),
  getBinding: (bindingId: number) => api.get<BusinessBindingDetail>(`/business-bindings/${bindingId}`),
  updateBinding: (bindingId: number, body: BusinessBindingUpdate) =>
    api.patch<BusinessBindingDetail>(`/business-bindings/${bindingId}`, body),
  removeBinding: (bindingId: number) => api.delete<void>(`/business-bindings/${bindingId}`),

  // ---- API 映射 ----
  listMappings: (bindingId: number) =>
    api.get<BusinessApiMapping[]>(`/business-bindings/${bindingId}/mappings`),
  createMapping: (bindingId: number, body: BusinessApiMappingCreate) =>
    api.post<BusinessApiMapping>(`/business-bindings/${bindingId}/mappings`, body),
  updateMapping: (mappingId: number, body: BusinessApiMappingUpdate) =>
    api.patch<BusinessApiMapping>(`/business-api-mappings/${mappingId}`, body),
  removeMapping: (mappingId: number) => api.delete<void>(`/business-api-mappings/${mappingId}`),

  // ---- 变量引用 ----
  listVariableRefs: (flowId: number) =>
    api.get<BusinessVariableRef[]>(`/business-flows/${flowId}/variable-refs`),
  createVariableRef: (flowId: number, body: BusinessVariableRefCreate) =>
    api.post<BusinessVariableRef>(`/business-flows/${flowId}/variable-refs`, body),
  removeVariableRef: (refId: number) => api.delete<void>(`/business-variable-refs/${refId}`),

  // ---- 业务规则 ----
  listRules: (projectId: number, params: { page?: number; page_size?: number; flow_id?: number; action_id?: number }) =>
    api.get<Paginated<BusinessRule>>(`/projects/${projectId}/business-rules`, { params }),
  createRule: (projectId: number, body: BusinessRuleCreate) =>
    api.post<BusinessRule>(`/projects/${projectId}/business-rules`, body),
  updateRule: (ruleId: number, body: BusinessRuleUpdate) =>
    api.patch<BusinessRule>(`/business-rules/${ruleId}`, body),
  removeRule: (ruleId: number) => api.delete<void>(`/business-rules/${ruleId}`),
};

// 写入载荷的类型再导出一份，供页面组件 Form 直接引用（避免重复定义）。
export type {
  BusinessDomainCreate,
  BusinessDomainUpdate,
  BusinessFlowCreate,
  BusinessFlowUpdate,
  BusinessActionCreate,
  BusinessActionUpdate,
  BusinessActionReorder,
  BusinessPreconditionCreate,
  BusinessPreconditionUpdate,
  BusinessVariableCreate,
  BusinessVariableUpdate,
  BusinessStateCreate,
  BusinessStateUpdate,
  BusinessBindingCreate,
  BusinessBindingUpdate,
  BusinessApiMappingCreate,
  BusinessApiMappingUpdate,
  BusinessVariableRefCreate,
  BusinessRuleCreate,
  BusinessRuleUpdate,
  BusinessActionDetail,
  BusinessBindingDetail,
  BusinessFlowDetail,
};
