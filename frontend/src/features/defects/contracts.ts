// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。

/** 缺陷前后端划分：前端、前后端与接口（原「后端」已并入「接口」）；历史存量缺陷允许为空（展示为「未划分」）。 */
export type BugCategory = '前端' | '前后端' | '接口';

/** 缺陷列表筛选用的归属值，包含历史「未划分」。 */
export type BugCategoryFilter = BugCategory | '未划分';

/** 接口缺陷的请求方法集合。 */
export type ApiMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS';

/** 接口缺陷专属字段：仅 category='接口' 时表单展示。 */
export interface BugApiFields {
  api_method?: ApiMethod | null; // 请求方法
  api_url?: string | null; // 请求地址（完整 URL 或路径）
  api_request_headers?: string | null; // 请求头（JSON 或原始文本）
  api_request_body?: string | null; // 请求体
  api_response?: string | null; // 实际响应结果（脱敏后填写）
}

/** 新建缺陷的请求体。新单统一进入待确认队列，不再选择处理人。 */
export interface BugCreate extends BugApiFields {
  project_id: number; // 所属项目 ID
  title: string; // 缺陷标题（必填）
  category?: BugCategory; // 前后端划分；可待确认时补齐
  description?: string; // 描述
  expected_result?: string | null;
  actual_result?: string | null;
  severity?: BugSeverity; // 严重度 1-4，缺省按模板默认值或 2
  priority?: BugPriority; // 处理优先级 1-4
  steps_to_reproduce?: string; // 复现步骤
  environment?: string; // 环境标识，支持「待确认」
  affected_version?: string; // 影响版本，支持「待确认」
  is_draft?: boolean; // 保存草稿；草稿不进入队列
  request_key?: string; // 创建幂等键（8-100 字符），避免超时重试重复建单
}

/** 批量创建中的单条缺陷入参；信息较少的记录进入待确认队列后再补齐。 */
export interface BugBatchCreateItem {
  title: string; // 缺陷标题（必填）
  category?: BugCategory; // 前后端划分；可待确认时补齐
  description?: string; // 描述
  expected_result?: string | null;
  actual_result?: string | null;
  severity?: BugSeverity; // 严重度 1-4，默认 2
  priority?: BugPriority; // 处理优先级 1-4
  steps_to_reproduce?: string; // 复现步骤
  environment?: string; // 发现环境
  affected_version?: string; // 影响版本
}

/** 批量创建缺陷请求体。 */
export interface BugBatchCreate {
  project_id: number; // 所属项目 ID
  items: BugBatchCreateItem[]; // 待创建明细列表（1-100 条）
}

/** 批量创建缺陷响应体。 */
export interface BugBatchCreateResponse {
  items: Bug[]; // 创建成功后的缺陷列表
  created_count: number; // 成功条数
}

/** 批量创建服务端返回的单行校验错误结构。 */
export interface BugBatchRowError {
  row: number; // 1-based 行号
  field: string; // 出错字段名
  message: string; // 错误原因
}

/** 修改缺陷的请求体；只改事实字段，状态通过队列动作变更。 */
export interface BugUpdate extends BugApiFields {
  title?: string;
  category?: BugCategory | null;
  description?: string;
  expected_result?: string | null;
  actual_result?: string | null;
  severity?: BugSeverity;
  priority?: BugPriority;
  steps_to_reproduce?: string;
  environment?: string;
  affected_version?: string;
  expected_version?: number; // 乐观并发：基于读取时的记录版本提交
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

/** 处理优先级 1-4，与严重度独立。 */
export type BugPriority = 1 | 2 | 3 | 4;

export interface Bug extends BugApiFields {
  id: number; // 缺陷主键
  project_id: number; // 所属项目 ID
  project_name: string | null; // 项目名称；服务端 join 后填充
  title: string; // 缺陷标题
  category: BugCategory | null; // 前后端划分；历史存量允许为 null
  description: string | null; // 描述
  expected_result: string | null;
  actual_result: string | null;
  severity: BugSeverity; // 严重度 1-4
  priority: BugPriority; // 处理优先级 1-4
  status: BugStatus; // 状态（存储值）
  status_display: string; // 展示状态：已修复展示为「待验证」
  steps_to_reproduce: string | null; // 复现步骤
  environment: string | null; // 环境
  affected_version: string | null; // 影响版本
  fix_version: string | null; // 可回归的版本/构建/环境
  record_version: number; // 记录版本，乐观并发用
  is_draft: boolean; // 草稿未进入队列
  archived_at: string | null; // 归档时间
  archive_reason: string | null; // 归档原因
  duplicate_of_bug_id: number | null; // 判重指向的主单
  reporter_id: number; // 报告人用户 ID（仅追溯）
  reporter_username: string | null; // 报告人用户名
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
  active_share_count?: number; // 仍有效的分享数量
}

/** 队列动作。 */
export type BugAction =
  | 'confirm' | 'ready_for_regression' | 'regression_pass' | 'regression_fail'
  | 'reject' | 'mark_duplicate' | 'reopen';

/** 队列动作入参。 */
export interface BugActionRequest {
  action: BugAction;
  note?: string;
  expected_version?: number;
  fix_version?: string;
  feedback_source?: string;
  verification_execution_id?: number;
  verification_environment?: string;
  duplicate_of_bug_id?: number;
  severity?: BugSeverity;
  priority?: BugPriority;
  steps_to_reproduce?: string;
  expected_result?: string;
  actual_result?: string;
  environment?: string;
  affected_version?: string;
}

/** 缺陷活动事件。 */
export interface BugActivity {
  id: number;
  bug_id: number;
  action: string;
  action_label: string;
  actor_id: number | null;
  actor_name: string | null;
  actor_type: 'INTERNAL' | 'EXTERNAL_SHARE' | 'SYSTEM';
  old_status: string | null;
  new_status: string | null;
  note: string | null;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface BugActionResponse {
  bug: Bug;
  activity: BugActivity;
}

/** 项目队列计数；与同条件列表总数一致。 */
export interface BugQueueCounts {
  project_id: number;
  unclosed: number;
  pending_confirm: number;
  in_progress: number;
  pending_verify: number;
  reported_by_me: number;
  closed: number;
  rejected: number;
  archived: number;
  drafts: number;
}

/** 质量统计。 */
export interface BugStats {
  project_id: number;
  period_days: number;
  backlog: Record<string, number>;
  first_confirm_hours_avg: number | null;
  first_confirm_sample: number;
  pending_verify_hours_avg: number | null;
  pending_verify_sample: number;
  regression_total: number;
  regression_failed: number;
  regression_failure_rate: number | null;
}

/** 批量治理动作。 */
export interface BugBatchActionRequest {
  project_id: number;
  ids: number[];
  action: 'set_priority' | 'archive' | 'restore';
  priority?: BugPriority;
  reason?: string;
}

export interface BugBatchActionReceipt {
  succeeded: number;
  failed: number;
  items: Array<{ id: number; succeeded: boolean; error: string | null }>;
}

/** 项目级缺陷开关。 */
export interface DefectProjectSetting {
  project_id: number;
  queue_enabled: boolean;
  reminder_enabled: boolean;
  stale_reminder_days: number;
}

/** 项目模板配置：字段显隐、默认值与分阶段必填；不含人员指派。 */
export interface DefectTemplateConfig {
  hidden_fields: string[];
  defaults: Record<string, unknown>;
  required_on_create: string[];
  required_on_confirm: string[];
  required_on_regression: string[];
}

export interface DefectTemplate {
  id: number;
  project_id: number;
  version: number;
  status: 'draft' | 'published' | 'retired';
  config: DefectTemplateConfig;
  created_by_username: string | null;
  created_at: string;
  published_at: string | null;
}

export interface DefectTemplatePreview {
  sample: Record<string, unknown>;
  hidden_fields: string[];
  required_on_create: string[];
  required_on_confirm: string[];
  required_on_regression: string[];
}

/** 推送时可选的展示字段。未勾选的字段不会进入公开页面。 */
export type DefectShareField =
  | 'bug_no' | 'title' | 'severity' | 'status' | 'project_name' | 'description'
  | 'steps_to_reproduce' | 'environment' | 'expected_result' | 'actual_result'
  | 'created_at' | 'reporter'
  | 'api_execution' | 'agent_execution' | 'security_record' | 'request_response'
  | 'error_stack' | 'screenshots' | 'allure' | 'api_method' | 'api_url'
  | 'api_request_headers' | 'api_request_body' | 'api_response' | 'attachments';

/** 创建或批量推送的选项。 */
export interface DefectShareOptions {
  channel_id: number;
  visible_fields?: DefectShareField[];
  expires_in_days?: 7 | 30 | 90 | null;
  permanent?: boolean;
  allow_view?: boolean;
  allow_resolve?: boolean;
  request_key?: string;
}

/** 推送结果。share_url 只在这次响应里出现。 */
export interface DefectSharePushResult {
  share_id: string;
  share_url: string | null;
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
  batch_share_id?: string | null;
}

export interface DefectShareBatchItemResult {
  share_id: string;
  bug_id: number;
  bug_no: string;
  notification_status: string;
}

export interface DefectShareBatchResult {
  batch_share_id: string | null;
  batch_share_url: string | null;
  url_is_absolute: boolean;
  items: DefectShareBatchItemResult[];
  card_count: number;
  notification_status: string;
  error_message: string | null;
  retry_count: number;
  duplicate_request: boolean;
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
  category?: BugCategoryFilter; // 按前后端划分过滤
  status?: BugStatus; // 按状态过滤
  severity?: BugSeverity; // 按严重度过滤
  priority?: BugPriority; // 按优先级过滤
  affected_version?: string; // 按影响版本过滤
  status_group?: 'unclosed'; // 未关闭队列
  mine?: boolean; // 我提交的
  include_archived?: boolean; // 含已归档
  include_drafts?: boolean; // 含我的草稿
  view?: 'archived' | 'drafts'; // 归档视图 / 我的草稿视图（与队列计数同口径）
  sort?: 'updated'; // 按更新时间排序
  keyword?: string; // 关键字：命中 title / description
}
