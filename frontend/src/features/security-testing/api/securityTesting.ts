// 安全测试（Security Testing Phase 1）接口客户端。
// 字段命名与后端 features/security_testing/schemas.py 严格对齐（snake_case）。
//
// 路由形态（挂载 /api/v1 下，管理面 = 平台 JWT）：
//   GET/PUT   /projects/{pid}/security-setting
//   GET/POST  /projects/{pid}/security-strategies（GET 支持 category/enabled 过滤）
//   GET/PATCH/DELETE /security-strategies/{id}
//   POST      /security-strategies/{id}/rules
//   PATCH/DELETE /security-rules/{id}
//   POST      /projects/{pid}/security-plans/preview
//   POST      /security-plans/{id}/confirm、/discard
//   GET       /projects/{pid}/security-cases（支持 api_id/strategy_id/mutation_type/enabled）
//   GET/PATCH /security-cases/{id}（PATCH 只改启用状态）
//   POST      /security-cases/{id}/confirm-risk（人工高风险确认；Agent 工具不调用）
//   POST      /projects/{pid}/security-runs（批量执行，复用既有 TestRun）
//   GET       /security-executions/{id}
//   GET       /projects/{pid}/security-findings（支持 severity/status/api_id）
//   GET/PATCH /security-findings/{id}（PATCH 只改状态）
//
// 安全红线（§需求说明）：
//   - 安全模块只改请求与解释结果；不做注入 / 扫描器 / 自动建缺陷；
//   - 不在生产环境发安全变异请求（allow_production 恒不生效）；
//   - confirm-risk 与 execute 都只能由人在本页触发，不会自动执行；
//   - 疑似问题文案统一「疑似问题」，SecurityFinding.bug_id 恒为 null，无「转 Bug」入口。
import { api } from '@/shared/api/client';
import type { MutationRule, MutationRuleCreate, MutationRuleUpdate, PlanConfirmRequest, PlanConfirmResponse, PlanPreviewRequest, PlanPreviewResponse, SecurityCase, SecurityCaseDetail, SecurityCaseListResponse, SecurityCaseUpdate, SecurityExecution, SecurityFinding, SecurityFindingListResponse, SecurityFindingUpdate, SecurityPlan, SecurityRunRequest, SecuritySetting, SecuritySettingUpdate, SecurityStrategy, SecurityStrategyCreate, SecurityStrategyListResponse, SecurityStrategyUpdate } from '@/features/security-testing/contracts';
import type { TestRun } from '@/features/test-management/contracts';







/** 安全测试管理面接口集合（全部走平台 JWT）。 */
export const securityApi = {
  // ------------------------------------------------------------------ 项目设置
  getSetting: (projectId: number) =>
    api.get<SecuritySetting>(`/projects/${projectId}/security-setting`),
  updateSetting: (projectId: number, body: SecuritySettingUpdate) =>
    api.put<SecuritySetting>(`/projects/${projectId}/security-setting`, body),

  // ------------------------------------------------------------------ 策略
  listStrategies(
    projectId: number,
    params: { category?: string; enabled?: boolean; page?: number; page_size?: number } = {},
  ) {
    return api.get<SecurityStrategyListResponse>(`/projects/${projectId}/security-strategies`, {
      params,
    });
  },
  createStrategy: (projectId: number, body: SecurityStrategyCreate) =>
    api.post<SecurityStrategy>(`/projects/${projectId}/security-strategies`, body),
  getStrategy: (strategyId: number) =>
    api.get<SecurityStrategy>(`/security-strategies/${strategyId}`),
  updateStrategy: (strategyId: number, body: SecurityStrategyUpdate) =>
    api.patch<SecurityStrategy>(`/security-strategies/${strategyId}`, body),
  removeStrategy: (strategyId: number) =>
    api.delete<void>(`/security-strategies/${strategyId}`),

  // ------------------------------------------------------------------ 变异规则
  createRule: (strategyId: number, body: MutationRuleCreate) =>
    api.post<MutationRule>(`/security-strategies/${strategyId}/rules`, body),
  updateRule: (ruleId: number, body: MutationRuleUpdate) =>
    api.patch<MutationRule>(`/security-rules/${ruleId}`, body),
  removeRule: (ruleId: number) => api.delete<void>(`/security-rules/${ruleId}`),

  // ------------------------------------------------------------------ 计划（preview/confirm/discard）
  /** 预览：只算一遍，不落 TestCase。落库的 security_plan 是未确认快照。 */
  previewPlan: (projectId: number, body: PlanPreviewRequest) =>
    api.post<PlanPreviewResponse>(`/projects/${projectId}/security-plans/preview`, body),
  /** 把选中的预览项写成 case_type='SECURITY' 的用例 + security_case 扩展行。 */
  confirmPlan: (planId: number, body: PlanConfirmRequest) =>
    api.post<PlanConfirmResponse>(`/security-plans/${planId}/confirm`, body),
  discardPlan: (planId: number) =>
    api.post<SecurityPlan>(`/security-plans/${planId}/discard`),

  // ------------------------------------------------------------------ 用例
  listCases(
    projectId: number,
    params: {
      api_id?: number;
      strategy_id?: number;
      mutation_type?: string;
      enabled?: boolean;
      page?: number;
      page_size?: number;
    } = {},
  ) {
    return api.get<SecurityCaseListResponse>(`/projects/${projectId}/security-cases`, {
      params,
    });
  },
  getCase: (securityCaseId: number) =>
    api.get<SecurityCaseDetail>(`/security-cases/${securityCaseId}`),
  updateCase: (securityCaseId: number, body: SecurityCaseUpdate) =>
    api.patch<SecurityCase>(`/security-cases/${securityCaseId}`, body),
  /** 高风险确认只能人工走这个端点；Agent 工具不调用它。 */
  confirmRisk: (securityCaseId: number) =>
    api.post<SecurityCase>(`/security-cases/${securityCaseId}/confirm-risk`),
  /** 批量执行：内部临时 TestPlan + Suite，复用既有 RunService。 */
  runSecurity: (projectId: number, body: SecurityRunRequest) =>
    api.post<TestRun>(`/projects/${projectId}/security-runs`, body),

  // ------------------------------------------------------------------ 执行记录
  getExecution: (securityExecutionId: number) =>
    api.get<SecurityExecution>(`/security-executions/${securityExecutionId}`),

  // ------------------------------------------------------------------ 疑似问题（Finding）
  listFindings(
    projectId: number,
    params: {
      severity?: string;
      status?: string;
      api_id?: number;
      page?: number;
      page_size?: number;
    } = {},
  ) {
    return api.get<SecurityFindingListResponse>(`/projects/${projectId}/security-findings`, {
      params,
    });
  },
  getFinding: (findingId: number) =>
    api.get<SecurityFinding>(`/security-findings/${findingId}`),
  /** 只允许改状态；非法迁移由服务层 400。 */
  updateFinding: (findingId: number, body: SecurityFindingUpdate) =>
    api.patch<SecurityFinding>(`/security-findings/${findingId}`, body),
};
