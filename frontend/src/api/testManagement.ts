// 测试管理相关接口。字段命名与后端 test_management schemas 严格对齐（snake_case）。
// 权限（§25）：读 = 项目可见（viewer+）；写 = 项目成员（member+）；越权按 404 返回，前端不展示。
//
// 路由形态：单 APIRouter 挂在 /api/v1 下，资源级路径（无额外前缀）：
//   /projects/{project_id}/test-(strategies|points|cases|suites|plans|runs)
//   /test-(strategies|points|cases|suites|plans)/{id}
//   /test-cases/{id}/(detail|preconditions|data|fixtures|steps|assertions) 与子实体 /test-case-*/{id}
//   /test-suites/{id}/cases、/test-suite-cases/{id}
//   /test-plans/{id}/suites、/test-plan-suites/{id}
//   /test-plans/{plan_id}/runs（触发执行）、/test-runs/{id}(/cases)
//
// 返回形态注意：多数列表端点后端用 response_model=list 直接返回 **裸数组**（.items），
// 不带分页信封；仅 list_runs / list_case_executions 返回 {items,total,page,page_size} 信封。
// 本文件的返回类型已据此标注，切勿误用 Paginated<T>。
import { api } from './client';
import type {
  CaseExecutionListResponse,
  TestCase,
  TestCaseCreate,
  TestCaseData,
  TestCaseDataCreate,
  TestCaseDataUpdate,
  TestCaseDetail,
  TestCaseFixture,
  TestCaseFixtureCreate,
  TestCasePrecondition,
  TestCasePreconditionCreate,
  TestCasePreconditionUpdate,
  TestCaseUpdate,
  TestAssertion,
  TestAssertionCreate,
  TestAssertionUpdate,
  TestPlan,
  TestPlanCreate,
  TestPlanSuiteAdd,
  TestPlanSuiteResponse,
  TestPlanUpdate,
  TestPoint,
  TestPointCreate,
  TestPointUpdate,
  TestRun,
  TestRunCreateRequest,
  TestRunListResponse,
  TestStep,
  TestStepCreate,
  TestStepUpdate,
  TestStrategy,
  TestStrategyCreate,
  TestStrategyUpdate,
  TestSuite,
  TestSuiteCaseAdd,
  TestSuiteCaseResponse,
  TestSuiteCreate,
  TestSuiteUpdate,
} from '@/types';

/**
 * 测试管理接口集合。
 *
 * 列表端点默认拉取 page_size=100（后端多数返回裸数组、无 total，第一阶段不做分页 UI）；
 * 调用方仍可覆盖 page/page_size 与各过滤项。
 */
export const testManagementApi = {
  // ---- 测试策略 ----
  listStrategies: (
    projectId: number,
    params: { page?: number; page_size?: number; category?: string; keyword?: string } = {},
  ) =>
    api.get<TestStrategy[]>(`/projects/${projectId}/test-strategies`, {
      params: { page: 1, page_size: 100, ...params },
    }),
  createStrategy: (projectId: number, body: TestStrategyCreate) =>
    api.post<TestStrategy>(`/projects/${projectId}/test-strategies`, body),
  getStrategy: (strategyId: number) => api.get<TestStrategy>(`/test-strategies/${strategyId}`),
  updateStrategy: (strategyId: number, body: TestStrategyUpdate) =>
    api.patch<TestStrategy>(`/test-strategies/${strategyId}`, body),
  removeStrategy: (strategyId: number) => api.delete<void>(`/test-strategies/${strategyId}`),

  // ---- 测试点 ----
  listPoints: (
    projectId: number,
    params: {
      page?: number;
      page_size?: number;
      strategy_id?: number;
      target_type?: string;
      status?: string;
      keyword?: string;
    } = {},
  ) =>
    api.get<TestPoint[]>(`/projects/${projectId}/test-points`, {
      params: { page: 1, page_size: 100, ...params },
    }),
  createPoint: (projectId: number, body: TestPointCreate) =>
    api.post<TestPoint>(`/projects/${projectId}/test-points`, body),
  getPoint: (pointId: number) => api.get<TestPoint>(`/test-points/${pointId}`),
  updatePoint: (pointId: number, body: TestPointUpdate) =>
    api.patch<TestPoint>(`/test-points/${pointId}`, body),
  removePoint: (pointId: number) => api.delete<void>(`/test-points/${pointId}`),

  // ---- 测试用例 ----
  listCases: (
    projectId: number,
    params: {
      page?: number;
      page_size?: number;
      test_point_id?: number;
      target_type?: string;
      status?: string;
      keyword?: string;
    } = {},
  ) =>
    api.get<TestCase[]>(`/projects/${projectId}/test-cases`, {
      params: { page: 1, page_size: 100, ...params },
    }),
  createCase: (projectId: number, body: TestCaseCreate) =>
    api.post<TestCase>(`/projects/${projectId}/test-cases`, body),
  getCase: (caseId: number) => api.get<TestCase>(`/test-cases/${caseId}`),
  getCaseDetail: (caseId: number) => api.get<TestCaseDetail>(`/test-cases/${caseId}/detail`),
  updateCase: (caseId: number, body: TestCaseUpdate) =>
    api.patch<TestCase>(`/test-cases/${caseId}`, body),
  removeCase: (caseId: number) => api.delete<void>(`/test-cases/${caseId}`),

  // ---- 用例子实体：前置条件 ----
  listPreconditions: (caseId: number) =>
    api.get<TestCasePrecondition[]>(`/test-cases/${caseId}/preconditions`),
  createPrecondition: (caseId: number, body: TestCasePreconditionCreate) =>
    api.post<TestCasePrecondition>(`/test-cases/${caseId}/preconditions`, body),
  updatePrecondition: (preconditionId: number, body: TestCasePreconditionUpdate) =>
    api.patch<TestCasePrecondition>(`/test-case-preconditions/${preconditionId}`, body),
  removePrecondition: (preconditionId: number) =>
    api.delete<void>(`/test-case-preconditions/${preconditionId}`),

  // ---- 用例子实体：测试数据 ----
  listData: (caseId: number) => api.get<TestCaseData[]>(`/test-cases/${caseId}/data`),
  createData: (caseId: number, body: TestCaseDataCreate) =>
    api.post<TestCaseData>(`/test-cases/${caseId}/data`, body),
  updateData: (dataId: number, body: TestCaseDataUpdate) =>
    api.patch<TestCaseData>(`/test-case-data/${dataId}`, body),
  removeData: (dataId: number) => api.delete<void>(`/test-case-data/${dataId}`),

  // ---- 用例子实体：所需 Fixture ----
  listCaseFixtures: (caseId: number) =>
    api.get<TestCaseFixture[]>(`/test-cases/${caseId}/fixtures`),
  // 整体替换（全量 upsert，空数组表示清空）。
  replaceCaseFixtures: (caseId: number, fixtures: TestCaseFixtureCreate[]) =>
    api.put<TestCaseFixture[]>(`/test-cases/${caseId}/fixtures`, { fixtures }),

  // ---- 用例子实体：步骤 ----
  listSteps: (caseId: number) => api.get<TestStep[]>(`/test-cases/${caseId}/steps`),
  createStep: (caseId: number, body: TestStepCreate) =>
    api.post<TestStep>(`/test-cases/${caseId}/steps`, body),
  updateStep: (stepId: number, body: TestStepUpdate) =>
    api.patch<TestStep>(`/test-steps/${stepId}`, body),
  removeStep: (stepId: number) => api.delete<void>(`/test-steps/${stepId}`),

  // ---- 用例子实体：断言 ----
  listAssertions: (caseId: number) =>
    api.get<TestAssertion[]>(`/test-cases/${caseId}/assertions`),
  createAssertion: (caseId: number, body: TestAssertionCreate) =>
    api.post<TestAssertion>(`/test-cases/${caseId}/assertions`, body),
  updateAssertion: (assertionId: number, body: TestAssertionUpdate) =>
    api.patch<TestAssertion>(`/test-assertions/${assertionId}`, body),
  removeAssertion: (assertionId: number) =>
    api.delete<void>(`/test-assertions/${assertionId}`),

  // ---- 测试套件 ----
  listSuites: (
    projectId: number,
    params: { page?: number; page_size?: number; suite_type?: string; keyword?: string } = {},
  ) =>
    api.get<TestSuite[]>(`/projects/${projectId}/test-suites`, {
      params: { page: 1, page_size: 100, ...params },
    }),
  createSuite: (projectId: number, body: TestSuiteCreate) =>
    api.post<TestSuite>(`/projects/${projectId}/test-suites`, body),
  getSuite: (suiteId: number) => api.get<TestSuite>(`/test-suites/${suiteId}`),
  updateSuite: (suiteId: number, body: TestSuiteUpdate) =>
    api.patch<TestSuite>(`/test-suites/${suiteId}`, body),
  removeSuite: (suiteId: number) => api.delete<void>(`/test-suites/${suiteId}`),

  // ---- 套件-用例关联 ----
  listSuiteCases: (suiteId: number) =>
    api.get<TestSuiteCaseResponse[]>(`/test-suites/${suiteId}/cases`),
  addSuiteCase: (suiteId: number, body: TestSuiteCaseAdd) =>
    api.post<TestSuiteCaseResponse>(`/test-suites/${suiteId}/cases`, body),
  removeSuiteCase: (suiteCaseId: number) =>
    api.delete<void>(`/test-suite-cases/${suiteCaseId}`),

  // ---- 测试计划 ----
  listPlans: (
    projectId: number,
    params: { page?: number; page_size?: number; status?: string; keyword?: string } = {},
  ) =>
    api.get<TestPlan[]>(`/projects/${projectId}/test-plans`, {
      params: { page: 1, page_size: 100, ...params },
    }),
  createPlan: (projectId: number, body: TestPlanCreate) =>
    api.post<TestPlan>(`/projects/${projectId}/test-plans`, body),
  getPlan: (planId: number) => api.get<TestPlan>(`/test-plans/${planId}`),
  updatePlan: (planId: number, body: TestPlanUpdate) =>
    api.patch<TestPlan>(`/test-plans/${planId}`, body),
  removePlan: (planId: number) => api.delete<void>(`/test-plans/${planId}`),

  // ---- 计划-套件关联 ----
  listPlanSuites: (planId: number) =>
    api.get<TestPlanSuiteResponse[]>(`/test-plans/${planId}/suites`),
  addPlanSuite: (planId: number, body: TestPlanSuiteAdd) =>
    api.post<TestPlanSuiteResponse>(`/test-plans/${planId}/suites`, body),
  removePlanSuite: (planSuiteId: number) =>
    api.delete<void>(`/test-plan-suites/${planSuiteId}`),

  // ---- 测试执行（§32 同步执行，返回完成的 TestRun）----
  createRun: (planId: number, body: TestRunCreateRequest) =>
    api.post<TestRun>(`/test-plans/${planId}/runs`, body),
  getRun: (runId: number) => api.get<TestRun>(`/test-runs/${runId}`),
  // list_case_executions 返回分页信封（CaseExecutionListResponse）。
  listCaseExecutions: (runId: number) =>
    api.get<CaseExecutionListResponse>(`/test-runs/${runId}/cases`),
  // list_runs 返回分页信封（TestRunListResponse）。
  listRuns: (
    projectId: number,
    params: { page?: number; page_size?: number } = {},
  ) =>
    api.get<TestRunListResponse>(`/projects/${projectId}/test-runs`, {
      params: { page: 1, page_size: 20, ...params },
    }),
};

// 写入载荷的类型再导出一份，供页面组件 Form 直接引用（避免重复定义）。
export type {
  TestStrategyCreate,
  TestStrategyUpdate,
  TestPointCreate,
  TestPointUpdate,
  TestCaseCreate,
  TestCaseUpdate,
  TestCasePreconditionCreate,
  TestCasePreconditionUpdate,
  TestCaseDataCreate,
  TestCaseDataUpdate,
  TestStepCreate,
  TestStepUpdate,
  TestAssertionCreate,
  TestAssertionUpdate,
  TestSuiteCreate,
  TestSuiteUpdate,
  TestSuiteCaseAdd,
  TestPlanCreate,
  TestPlanUpdate,
  TestPlanSuiteAdd,
  TestRunCreateRequest,
  TestCaseDetail,
  TestCaseFixture,
  TestCaseFixtureCreate,
};
