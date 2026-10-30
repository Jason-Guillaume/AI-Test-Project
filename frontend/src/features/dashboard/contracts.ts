// dashboard 领域类型合同；仅暴露当前模块稳定使用的请求、响应与查询类型。


// 看板

// 看板统计口径：告诉前端这次统计的范围与依据。
export interface DashboardScope {
  subject: string; // 口径描述文本，直接展示给用户
  user_id: number; // 被统计的用户 ID
  role: string; // 该用户的平台角色
  is_platform_admin: boolean; // 是否为平台管理员（管理员看全站数据）
  organization_ids: number[]; // 纳入统计的组织 ID 列表
  project_ids: number[]; // 纳入统计的项目 ID 列表
}

// 看板单个统计卡片。
export interface StatCard {
  key: string; // 卡片标识，用于前端按位渲染
  label: string; // 卡片标题
  value: number; // 数值
  hint: string | null; // 辅助说明，如环比或口径备注；可为空
}

// 看板总览接口返回。
export interface DashboardOverview {
  scope: DashboardScope; // 统计口径
  stats: StatCard[]; // 卡片数据列表
}

// 工作台统计图。
export interface DashboardExecutionTrendItem {
  date: string;
  total: number;
  passed: number;
  failed: number;
}

export interface DashboardDailyCount {
  date: string;
  count: number;
}

export interface DashboardDefectSeverityItem {
  severity: 1 | 2 | 3 | 4;
  label: string;
  value: number;
}

export interface DashboardCharts {
  scope: DashboardScope;
  days: number;
  execution_trend: DashboardExecutionTrendItem[];
  defect_severity: DashboardDefectSeverityItem[];
  case_generation: DashboardDailyCount[];
}
