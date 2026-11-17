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
  active_share_count?: number; // 仍有效的分享数量
}

/** 推送时可选的展示字段。未勾选的字段不会进入公开页面。 */
export type DefectShareField =
  | 'bug_no' | 'title' | 'severity' | 'status' | 'project_name' | 'description'
  | 'steps_to_reproduce' | 'environment' | 'expected_result' | 'actual_result'
  | 'created_at' | 'source_summary' | 'reporter' | 'assignee'
  | 'api_execution' | 'agent_execution' | 'security_record' | 'request_response'
  | 'error_stack' | 'screenshots' | 'allure';

/** 创建或批量推送的选项。 */
export interface DefectShareOptions {
  channel_id: number;
  visible_fields?: DefectShareField[];
  expires_in_days?: 7 | 30 | 90 | null;
  permanent?: boolean;
  allow_view?: boolean;
  allow_resolve?: boolean;
}

/** 推送结果。share_url 只在这次响应里出现。 */
export interface DefectSharePushResult {
  share_id: string;
  share_url: string;
  url_is_absolute: boolean;
  bug_id: number;
  bug_no: string;
  channel_id: number | null;
  channel_name: string;
  allow_view: boolean;
  allow_resolve: boolean;
  expires_at: string | null;
  visible_fields: string[];
  notification_status: string;
  error_message: string | null;
  retry_count: number;
}

/** 推送前预览。 */
export interface DefectSharePreview {
  defect_count: number;
  channel_name: string;
  channel_enabled: boolean;
  webhook_configured: boolean;
  expires_label: string;
  allow_resolve: boolean;
  visible_fields: string[];
  message_preview: string;
  public_url_valid?: boolean;
  public_url_error?: string | null;
}

/** 分享历史中的一条记录，不含可再次打开页面的凭证。 */
export interface DefectShareSummary {
  share_id: string;
  bug_id: number;
  channel_id: number | null;
  channel_name: string;
  pushed_by_username: string | null;
  pushed_at: string;
  expires_at: string | null;
  expires_label: string;
  share_status: string;
  allow_view: boolean;
  allow_resolve: boolean;
  view_count: number;
  last_viewed_at: string | null;
  resolution_status: string;
  latest_resolution: DefectExternalAction | null;
  notification_status: string | null;
  error_message: string | null;
  retry_count: number;
}

/** 外部修复记录。姓名是自报信息。 */
export interface DefectExternalAction {
  action_type: string;
  old_status: string;
  new_status: string;
  actor_type: string;
  actor_display_name: string | null;
  repair_description: string;
  fix_version: string | null;
  commit_sha: string | null;
  created_at: string;
  identity_note: string;
}

/** 单条分享详情。 */
export interface DefectShareDetail extends DefectShareSummary {
  visible_fields: string[];
  content_snapshot: Record<string, unknown>;
  external_actions: DefectExternalAction[];
  notifications: Array<{ id: number; status: string; error_message: string | null; retry_count: number; sent_at: string | null; created_at: string }>;
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
