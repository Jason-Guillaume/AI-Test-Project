// 飞书通知渠道与发送记录相关接口。字段与后端 schemas_channel.py 严格对齐（snake_case）。
//
// 路由形态（挂载 /api/v1 下）：
//   POST   /projects/{project_id}/notification-channels   新建渠道（member+）
//   GET    /projects/{project_id}/notification-channels   渠道列表（viewer+）
//   GET    /notification-channels/{channel_id}            渠道详情（viewer+）
//   PATCH  /notification-channels/{channel_id}            编辑渠道（member+）
//   DELETE /notification-channels/{channel_id}            删除渠道（member+）
//   POST   /notification-channels/{channel_id}/test       连通性测试（member+）
//   GET    /notification-channels/{channel_id}/records    渠道发送记录（viewer+）
//   POST   /reports/{report_id}/notify                    手动触发报告通知（member+）
//   GET    /reports/{report_id}/notifications             报告发送记录（viewer+）
//
// 安全红线：webhook_url / secret 只写不读——创建/更新时明文提交、后端加密入库；
// 响应只回 webhook_configured（布尔）与 webhook_masked（脱敏 URL）。前端不得要求展示明文。
import { api } from './client';
import type {
  ChannelCreateRequest,
  ChannelListResponse,
  ChannelUpdateRequest,
  NotificationChannel,
  NotificationRecordListResponse,
  NotifyReportRequest,
  SendResult,
} from '@/types';

export const notificationChannelsApi = {
  /** 新建渠道（webhook_url / secret 明文入参，后端加密存储）。 */
  create: (projectId: number, body: ChannelCreateRequest) =>
    api.post<NotificationChannel>(`/projects/${projectId}/notification-channels`, body),

  /** 渠道列表（分页信封）。 */
  list: (projectId: number, params: { page?: number; page_size?: number } = {}) =>
    api.get<ChannelListResponse>(`/projects/${projectId}/notification-channels`, {
      params: { page: 1, page_size: 50, ...params },
    }),

  /** 渠道详情（webhook 脱敏）。 */
  get: (channelId: number) => api.get<NotificationChannel>(`/notification-channels/${channelId}`),

  /** 编辑渠道；webhook_url / secret 不传表示不变，传空串表示清除签名。 */
  update: (channelId: number, body: ChannelUpdateRequest) =>
    api.patch<NotificationChannel>(`/notification-channels/${channelId}`, body),

  /** 删除渠道（连带删除其发送记录）。 */
  remove: (channelId: number) => api.delete<void>(`/notification-channels/${channelId}`),

  /** 连通性测试：发送一条测试卡片，不关联报告。 */
  test: (channelId: number) => api.post<SendResult>(`/notification-channels/${channelId}/test`),

  /** 渠道的发送审计记录。 */
  listChannelRecords: (channelId: number, params: { page?: number; page_size?: number } = {}) =>
    api.get<NotificationRecordListResponse>(`/notification-channels/${channelId}/records`, {
      params: { page: 1, page_size: 20, ...params },
    }),

  /** 手动触发某报告的飞书通知（指定渠道）。 */
  notifyReport: (reportId: number, body: NotifyReportRequest) =>
    api.post<SendResult>(`/reports/${reportId}/notify`, body),

  /** 报告的发送审计记录。 */
  listReportNotifications: (reportId: number, params: { page?: number; page_size?: number } = {}) =>
    api.get<NotificationRecordListResponse>(`/reports/${reportId}/notifications`, {
      params: { page: 1, page_size: 20, ...params },
    }),
};
