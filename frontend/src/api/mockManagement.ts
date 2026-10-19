// 接口 Mock 与依赖异常模拟（Mock Management Phase 1）接口客户端。
// 字段命名与后端 features/mock_management/schemas.py 严格对齐（snake_case）。
//
// 路由形态（挂载 /api/v1 下，管理面 = 平台 JWT）：
//   GET/POST  /projects/{pid}/mock-services
//   GET/PATCH/DELETE /mock-services/{id}
//   POST      /mock-services/{id}/reset-token
//   GET/POST  /mock-services/{id}/endpoints
//   GET/PATCH/DELETE /mock-endpoints/{id}
//   GET/POST  /mock-endpoints/{id}/scenarios
//   GET/PATCH/DELETE /mock-scenarios/{id}
//   PUT       /mock-scenarios/{id}/matchers（整体替换，重建）
//   POST      /mock-scenarios/{id}/(set-default|duplicate|test)
//   GET       /projects/{pid}/mock-executions、/mock-executions/{id}
//   GET       /projects/{pid}/mock-contexts、/mock-contexts/{context_id}
//   POST      /mock-contexts/{context_id}/close
//   POST      /projects/{pid}/mock-from-api/{api_id}（一键创建）
//   GET/PUT   /test-cases/{id}/mocks（用例 required_mocks）
//
// 安全约定：Runtime Token 只存 hash，明文仅在 create/reset 响应里返回一次；
// 本页任何位置都不展示或存储明文 token，只显示「是否已配置」。
// 调用记录快照由后端 SensitiveDataMasker 脱敏，前端按只读展示。
import { api } from './client';
import type {
  CreateMockFromApiRequest,
  CreateMockFromApiResponse,
  MockContext,
  MockEndpoint,
  MockEndpointCreate,
  MockEndpointListResponse,
  MockEndpointUpdate,
  MockExecution,
  MockExecutionListQuery,
  MockExecutionListResponse,
  MockMatchersReplace,
  MockScenario,
  MockScenarioCreate,
  MockScenarioListResponse,
  MockScenarioUpdate,
  MockService,
  MockServiceCreate,
  MockServiceCreateResponse,
  MockServiceListResponse,
  MockServiceUpdate,
  ScenarioTestRequest,
  ScenarioTestResponse,
  TestCaseMock,
  TestCaseMocksReplace,
} from '@/types';

/** 管理面接口集合（全部走平台 JWT，经 client 的 Authorization 拦截器注入）。 */
export const mockManagementApi = {
  // ------------------------------------------------------------------ MockService
  listServices(
    projectId: number,
    params: { keyword?: string; enabled?: boolean; page?: number; page_size?: number } = {},
  ) {
    return api.get<MockServiceListResponse>(`/projects/${projectId}/mock-services`, {
      params,
    });
  },
  createService(projectId: number, body: MockServiceCreate) {
    return api.post<MockServiceCreateResponse>(`/projects/${projectId}/mock-services`, body);
  },
  getService(id: number) {
    return api.get<MockService>(`/mock-services/${id}`);
  },
  updateService(id: number, body: MockServiceUpdate) {
    return api.patch<MockService>(`/mock-services/${id}`, body);
  },
  removeService(id: number) {
    return api.delete<void>(`/mock-services/${id}`);
  },
  /** 重置 Runtime Token：旧 token 立即失效，新明文只返回一次。 */
  resetToken(id: number) {
    return api.post<MockServiceCreateResponse>(`/mock-services/${id}/reset-token`);
  },

  // ------------------------------------------------------------------ MockEndpoint
  listEndpoints(
    serviceId: number,
    params: { keyword?: string; enabled?: boolean; page?: number; page_size?: number } = {},
  ) {
    return api.get<MockEndpointListResponse>(`/mock-services/${serviceId}/endpoints`, {
      params,
    });
  },
  createEndpoint(serviceId: number, body: MockEndpointCreate) {
    return api.post<MockEndpoint>(`/mock-services/${serviceId}/endpoints`, body);
  },
  getEndpoint(id: number) {
    return api.get<MockEndpoint>(`/mock-endpoints/${id}`);
  },
  updateEndpoint(id: number, body: MockEndpointUpdate) {
    return api.patch<MockEndpoint>(`/mock-endpoints/${id}`, body);
  },
  removeEndpoint(id: number) {
    return api.delete<void>(`/mock-endpoints/${id}`);
  },

  // ------------------------------------------------------------------ MockScenario
  listScenarios(
    endpointId: number,
    params: { keyword?: string; enabled?: boolean; page?: number; page_size?: number } = {},
  ) {
    return api.get<MockScenarioListResponse>(`/mock-endpoints/${endpointId}/scenarios`, {
      params,
    });
  },
  createScenario(endpointId: number, body: MockScenarioCreate) {
    return api.post<MockScenario>(`/mock-endpoints/${endpointId}/scenarios`, body);
  },
  getScenario(id: number) {
    return api.get<MockScenario>(`/mock-scenarios/${id}`);
  },
  updateScenario(id: number, body: MockScenarioUpdate) {
    return api.patch<MockScenario>(`/mock-scenarios/${id}`, body);
  },
  removeScenario(id: number) {
    return api.delete<void>(`/mock-scenarios/${id}`);
  },
  /** 整体替换匹配规则（重建）。 */
  replaceMatchers(id: number, body: MockMatchersReplace) {
    return api.put<MockScenario>(`/mock-scenarios/${id}/matchers`, body);
  },
  setDefault(id: number) {
    return api.post<MockScenario>(`/mock-scenarios/${id}/set-default`);
  },
  /** 复制场景（含匹配规则）；newKey 为必填查询参数，须同接口唯一。 */
  duplicate(id: number, newKey: string) {
    return api.post<MockScenario>(`/mock-scenarios/${id}/duplicate`, undefined, {
      params: { new_key: newKey },
    });
  },
  /** 场景试跑：模拟请求验证 Matcher + 响应构建，不真实调用被测系统。 */
  testScenario(id: number, body: ScenarioTestRequest) {
    return api.post<ScenarioTestResponse>(`/mock-scenarios/${id}/test`, body);
  },

  // ------------------------------------------------------------------ 调用记录 / 作用域
  listExecutions(projectId: number, params: MockExecutionListQuery = {}) {
    return api.get<MockExecutionListResponse>(`/projects/${projectId}/mock-executions`, {
      params,
    });
  },
  getExecution(id: number) {
    return api.get<MockExecution>(`/mock-executions/${id}`);
  },
  listContexts(
    projectId: number,
    params: { status?: string; test_run_id?: number; page?: number; page_size?: number } = {},
  ) {
    return api.get<MockContext[]>(`/projects/${projectId}/mock-contexts`, { params });
  },
  getContext(contextId: string) {
    return api.get<MockContext>(`/mock-contexts/${contextId}`);
  },
  closeContext(contextId: string) {
    return api.post<MockContext>(`/mock-contexts/${contextId}/close`);
  },

  // ------------------------------------------------------------------ API 一键创建 / 用例声明
  createFromApi(projectId: number, apiId: number, body: CreateMockFromApiRequest) {
    return api.post<CreateMockFromApiResponse>(`/projects/${projectId}/mock-from-api/${apiId}`, body);
  },
  listCaseMocks(testCaseId: number) {
    return api.get<TestCaseMock[]>(`/test-cases/${testCaseId}/mocks`);
  },
  replaceCaseMocks(testCaseId: number, body: TestCaseMocksReplace) {
    return api.put<TestCaseMock[]>(`/test-cases/${testCaseId}/mocks`, body);
  },
};

/**
 * 拼装 Mock Runtime 执行面 URL（§十六）：/api/v1/mock/{project_id}/{service_key}/{path}。
 * 执行面不需要平台 JWT，被测系统改调这个地址并用 X-Mock-Token 鉴权。
 */
export function buildRuntimeUrl(
  projectId: number,
  serviceKey: string,
  path: string,
  method = 'GET',
): string {
  const base = `/api/v1/mock/${projectId}/${serviceKey}/${path.replace(/^\/+/, '')}`;
  return method && method !== 'GET' ? `${base}（${method}）` : base;
}
