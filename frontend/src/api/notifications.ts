import { api } from './client';
import type { NotificationList, NotificationSummary } from '@/types';

/** 通知列表查询参数，作为 GET /notifications 的 query 传给后端。 */
export interface NotificationListQuery {
  page?: number; // 页码，从 1 开始；不传时后端返回第一页
  page_size?: number; // 每页条数；不传时后端用默认值
  event_type?: string; // 按事件类型筛选
  is_read?: boolean; // 只筛已读（true）或未读（false）
  organization_id?: number; // 只看某个组织下的通知
  project_id?: number; // 只看某个项目下的通知
}

/**
 * 通知接口集合，由通知中心页与右上角未读角标调用。
 * 覆盖端点：GET /notifications、GET /notifications/summary、GET /notifications/events、
 * POST /notifications/{id}/read、POST /notifications/read-all、DELETE /notifications/{id}。
 */
export const notificationsApi = {
  /** 分页查询通知列表；返回体除分页字段外额外带 unread_total 供角标显示。 */
  list: (params: NotificationListQuery) =>
    api.get<NotificationList>('/notifications', { params }),
  /** 通知概览统计：总数与未读总数，供角标/提醒条使用，不发起分页查询。 */
  summary: () => api.get<NotificationSummary>('/notifications/summary'),
  /** 取事件类型目录（value/label 对），供筛选下拉框渲染选项。 */
  events: () => api.get<{ value: string; label: string }[]>('/notifications/events'),
  /** 把单条通知标记为已读。 */
  markRead: (id: number) =>
    api.post<unknown>(`/notifications/${id}/read`),
  /** 批量标记已读；ids 省略或为空时不带请求体，后端按「全部」处理。 */
  markAllRead: (ids?: number[]) =>
    api.post<NotificationList>('/notifications/read-all', ids ? { ids } : undefined),
  /** 删除单条通知，无返回体。 */
  remove: (id: number) => api.delete<void>(`/notifications/${id}`),
};
