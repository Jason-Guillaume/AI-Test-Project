// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。


/** 新建缺陷的请求体。 */
export interface BugCreate {
  project_id: number; // 所属项目 ID
  title: string; // 缺陷标题（必填）
  description?: string; // 描述
  severity?: 1 | 2 | 3 | 4; // 严重度 1-4，默认 2
  status?: BugStatus; // 状态，默认 '待确认'
  steps_to_reproduce?: string; // 复现步骤
  environment?: string; // 环境标识
  assignee_id?: number | null; // 处理人；必须是项目成员；null 表示清空
}

/** 修改缺陷的请求体；全部字段可选，只提交要改的项。 */
export interface BugUpdate {
  title?: string;
  description?: string;
  severity?: 1 | 2 | 3 | 4;
  status?: BugStatus;
  steps_to_reproduce?: string;
  environment?: string;
  assignee_id?: number | null;
}

export type DefectSourceType = 'CASE_EXECUTION' | 'SECURITY_FINDING';

export interface DefectSourceLink {
  id: number;
  project_id: number;
  bug_id: number;
  case_execution_id: number | null;
  security_finding_id: number | null;
  created_at: string;
}

export interface DefectSourceContext {
  project_id: number;
  source_type: DefectSourceType;
  source_id: number;
  test_run_id: number | null;
}


// 缺陷（bug 表对应的 DTO）。字段全部与后端 BugResponse 对齐，snake_case。
export type BugStatus = '待确认' | '处理中' | '已修复' | '已关闭' | '已拒绝';

export type BugSeverity = 1 | 2 | 3 | 4;

export interface Bug {
  id: number; // 缺陷主键
  project_id: number; // 所属项目 ID
  project_name: string | null; // 项目名称；服务端 join 后填充
  title: string; // 缺陷标题
  description: string | null; // 描述
  severity: BugSeverity; // 严重度 1-4（1=致命，4=轻微）
  status: BugStatus; // 状态
  steps_to_reproduce: string | null; // 复现步骤
  environment: string | null; // 环境
  reporter_id: number; // 报告人用户 ID
  reporter_username: string | null; // 报告人用户名
  assignee_id: number | null; // 处理人用户 ID；未分配为 null
  assignee_username: string | null; // 处理人用户名
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
}

// 缺陷列表查询参数。
export interface BugListQuery {
  page?: number; // 页码，从 1 开始
  page_size?: number; // 每页条数
  project_id?: number; // 按项目过滤
  status?: BugStatus; // 按状态过滤
  severity?: BugSeverity; // 按严重度过滤
  assignee_id?: number; // 按处理人过滤
  keyword?: string; // 关键字：命中 title / description
}
