// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。
import type { Paginated } from '@/shared/api/contracts';

/** 通知列表查询参数，作为 GET /notifications 的 query 传给后端。 */
export interface NotificationListQuery {
  page?: number; // 页码，从 1 开始；不传时后端返回第一页
  page_size?: number; // 每页条数；不传时后端用默认值
  event_type?: string; // 按事件类型筛选
  is_read?: boolean; // 只筛已读（true）或未读（false）
  organization_id?: number; // 只看某个组织下的通知
  project_id?: number; // 只看某个项目下的通知
}


// 通知

// 单条通知。
export interface Notification {
  id: number; // 通知 ID
  event_type: string; // 事件类型，决定前端如何渲染与跳转
  title: string; // 通知标题
  body: string | null; // 通知正文，可为空
  payload: Record<string, unknown> | null; // 事件附加数据，结构随 event_type 变化
  project_id: number | null; // 关联项目 ID；null 表示非项目级事件
  organization_id: number | null; // 关联组织 ID；null 表示非组织级事件
  is_read: boolean; // 是否已读
  read_at: string | null; // 已读时间；未读为 null
  created_at: string; // 产生时间
}

// 通知列表返回：分页信封 + 未读总数。
export interface NotificationList extends Paginated<Notification> {
  unread_total: number; // 当前用户未读通知总数，用于角标
}

// 通知概览统计（角标/提醒条用）。
export interface NotificationSummary {
  total: number; // 通知总数
  unread_total: number; // 未读总数
}

// ---- 飞书通知渠道与发送记录（Phase 2）----
// 字段与后端 features/notifications/schemas_channel.py 严格对齐（snake_case）。
// 安全红线：后端响应**永不**回吐 webhook_url / secret 明文，仅回 webhook_configured
// （布尔）与 webhook_masked（脱敏 URL）。

export type NotifyCondition = 'ALWAYS' | 'ONLY_FAILED' | 'ONLY_HIGH_RISK';

export type NotifyStatus = 'PENDING' | 'SUCCESS' | 'FAILED';

export interface ChannelCreateRequest {
  name: string;
  channel_type?: 'FEISHU_WEBHOOK';
  /** 飞书 webhook URL（明文入参，后端加密入库；仅写入不回读） */
  webhook_url: string;
  /** 飞书签名密钥（明文入参，后端加密入库；不填则不签名） */
  secret?: string | null;
  enabled?: boolean;
  notify_condition?: NotifyCondition;
  keyword?: string | null;
}

/** 更新渠道；webhook_url / secret 留空（undefined）表示不变，传空串表示清除。 */
export interface ChannelUpdateRequest {
  name?: string;
  webhook_url?: string;
  secret?: string;
  enabled?: boolean;
  notify_condition?: NotifyCondition;
  keyword?: string;
}

export interface NotificationChannel {
  id: number;
  project_id: number;
  name: string;
  channel_type: string;
  enabled: boolean;
  notify_condition: NotifyCondition;
  /** 是否已配置 webhook URL（不含 URL 本身） */
  webhook_configured: boolean;
  /** 脱敏 webhook URL，如 https://open.feishu.cn/...**** */
  webhook_masked: string;
  keyword: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

// list_channels 返回分页信封。
export type ChannelListResponse = Paginated<NotificationChannel>;

/** 发送审计记录（不含卡片原文 request_snapshot）。 */
export interface NotificationRecord {
  id: number;
  project_id: number;
  channel_id: number;
  report_id: number | null;
  status: NotifyStatus;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
}

// 发送记录列表返回分页信封。
export type NotificationRecordListResponse = Paginated<NotificationRecord>;

/** 触发发送（手动 / 连通性测试）的即时结果。 */
export interface SendResult {
  record_id: number | null;
  status: NotifyStatus;
  error_message: string | null;
  /** 因渠道禁用或通知条件不满足而跳过（未发送） */
  skipped: boolean;
}

export interface NotifyReportRequest {
  /** 渠道 ID；省略时后端取项目首个启用渠道，均无则跳过（skipped=true），而不是 422。 */
  channel_id?: number;
}
