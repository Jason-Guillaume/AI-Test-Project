/**
 * 统一任务详情视图使用的局部快照类型。
 * 描述运行输入快照中可选的 Agent 与安全计划字段，供详情编排层和展示面板共享；不改变后端 wire 类型。
 */
export interface TaskAgentDefinitionSnapshot {
  name?: string;
  version?: number;
  child_agents?: { id: number; name: string; version: number }[];
}

export interface TaskSecurityAssessmentSelection {
  api_id?: number;
  api_ids?: number[];
  web_session_id?: number;
  strategy_ids?: number[];
}

export interface TaskSecurityPlanItem {
  index: number;
  name: string;
  mutation_type: string;
  method?: string | null;
  location?: string | null;
  field?: string | null;
  severity?: string;
  risk_level?: string | null;
  confirmation_required?: boolean;
  blocked_reason?: string | null;
}

export interface TaskSecurityAssessmentPreview {
  estimated_count?: number;
  truncated?: boolean;
  api_ids?: number[];
  items?: TaskSecurityPlanItem[];
  plans?: {
    api: { id: number; name?: string; method?: string; path?: string };
    strategies?: { id: number; name: string }[];
    plan: {
      estimated_count?: number;
      truncated?: boolean;
      items?: TaskSecurityPlanItem[];
    };
  }[];
  web_inspection?: {
    session_id?: number;
    page?: { https?: boolean; response_status?: number | null };
    dom?: Record<string, number | boolean>;
    interpretation?: string;
    signals?: { code: string; title: string; severity: string }[];
  } | null;
}
