// 通知中心：当前用户收件箱、已读操作。
// 本模块导出 ConsoleNotificationsPage，由路由 /console/notifications 挂载。
import { App, Button, Select, Space, Tag } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { notificationsApi } from '@/api/notifications';
import { getErrorMessage } from '@/api/client';
import type { Notification, NotificationList } from '@/types';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';

/**
 * 用户控制台的通知中心页组件。
 *
 * 用途：分页展示当前用户的通知收件箱，支持按已读状态与事件类型筛选，
 *       并提供单条标记已读、全部标记已读、删除通知的操作。
 * 数据来源：notificationsApi.list（分页列表）与 notificationsApi.events（筛选项字典），
 *       均为只读请求；写操作通过三个 mutation 发起。
 * 失败呈现：列表接口失败时整页换成 ErrorState（带重试）；
 *       单个 mutation 失败只弹 message.error，不中断页面。
 * 空态：分页到空页时由 ResourceTable 展示空表格。
 */
export function ConsoleNotificationsPage() {
  const { message } = App.useApp();
  // 用来在 mutation 成功后主动刷新通知相关缓存
  const queryClient = useQueryClient();
  // 分页状态：默认第一页、每页 10 条
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 10,
  });
  // 已读状态筛选：undefined 表示不筛选，等价于「全部」
  const [isRead, setIsRead] = useState<boolean | undefined>(undefined);
  // 事件类型筛选：undefined 表示不筛选
  const [eventType, setEventType] = useState<string | undefined>(undefined);

  // 分页参数与筛选条件统一拼成一份 query 对象；
  // 依赖是 pagination/isRead/eventType 三个 state，任一变化都会重新计算
  const query = useMemo(
    () => ({
      page: pagination.page,
      page_size: pagination.page_size,
      // undefined 不会被序列化成查询串，因此后端拿到的是「未指定」
      is_read: isRead,
      event_type: eventType,
    }),
    [pagination, isRead, eventType],
  );

  // 通知列表查询；queryKey 带 query 对象，参数一变就重新请求
  const listQuery = useQuery({
    queryKey: ['notifications', query],
    queryFn: () => notificationsApi.list(query),
  });

  // 事件类型字典，用于填充筛选下拉的选项；与列表查询互相独立
  // 查询失败或加载中时 data 为 undefined，下面用 ?? [] 兜底成空选项
  const eventsQuery = useQuery({
    queryKey: ['notifications', 'events'],
    queryFn: () => notificationsApi.events(),
  });

  // 标记单条为已读；成功后使整个 notifications 前缀的缓存失效以刷新列表与未读数
  const markReadMutation = useMutation({
    mutationFn: notificationsApi.markRead,
    onSuccess: () => {
      message.success('已标记为已读');
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  // 全部标记已读
  const markAllMutation = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => {
      message.success('已全部标记为已读');
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  // 删除通知；已软删除的数据不会再出现在列表中
  const deleteMutation = useMutation({
    mutationFn: notificationsApi.remove,
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });

  // 加载中：整页只放一个 LoadingState，避免半渲染的布局跳动
  if (listQuery.isPending) return <LoadingState />;
  // 请求失败：换成可重试的 ErrorState，不渲染空表格以免误导用户
  if (listQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />
      </PageContainer>
    );

  // 走到这里 isPending/isError 都为 false，data 一定已就绪，可直接断言类型
  const data: NotificationList = listQuery.data;

  return (
    <PageContainer>
      <Space
        style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}
      >
        <Space>
          <Select /* allowClear：点击清空即回到不筛选状态，值为 undefined */ allowClear
            placeholder="按状态筛选"
            style={{ width: 140 }}
            value={isRead}
            onChange={(v) => {
              setIsRead(v);
              // 切换筛选后回到第一页，否则可能停留在已被过滤掉的页码
              setPagination((p) => ({ ...p, page: 1 }));
            }}
            options={[
              { value: true, label: '已读' },
              { value: false, label: '未读' },
            ]}
          />
          <Select /* 事件类型字典，选项来自 eventsQuery */ allowClear
            placeholder="按事件类型筛选"
            style={{ width: 200 }}
            value={eventType}
            onChange={(v) => {
              setEventType(v);
              // 同上：切换筛选后重置到第一页
              setPagination((p) => ({ ...p, page: 1 }));
            }}
            options={(eventsQuery.data ?? []).map((e) => ({
              value: e.value,
              label: e.label,
            }))}
          />
          <Tag /* 未读总数来自列表接口的 unread_total 字段，不是分页后条数 */ color="orange">未读 {data.unread_total}</Tag>
        </Space>
        <Button /* 批量操作：loading 绑定 mutation 状态，避免重复点击 */ onClick={() => markAllMutation.mutate()} loading={markAllMutation.isPending}>
          全部标记已读
        </Button>
      </Space>

      <ResourceTable
        rowKey={(r) => r.id}
        columns={[
          { title: '标题', dataIndex: 'title' },
          { title: '事件类型', dataIndex: 'event_type' },
          { title: '正文', dataIndex: 'body', ellipsis: true },
          {
            title: '状态',
            dataIndex: 'is_read',
            render: (v: boolean) => (v ? <Tag>已读</Tag> : <Tag color="blue">未读</Tag>),
          },
          { title: '时间', dataIndex: 'created_at' },
          {
            title: '操作',
            key: 'actions',
            render: (_: unknown, row: Notification) => (
              <Space>
                {row.event_type.startsWith('task.') && typeof (row.payload?.detail as Record<string, unknown> | undefined)?.task_id === 'number' && (
                  <Link to={`/console/tasks/${(row.payload?.detail as { task_id: number }).task_id}${typeof (row.payload?.detail as Record<string, unknown>).run_id === 'number' ? `?runId=${(row.payload?.detail as { run_id: number }).run_id}` : ''}`}>查看任务</Link>
                )}
                {!row.is_read && (
                  <Button /* 已读的通知不再展示「标记已读」按钮，减少无意义的操作 */ size="small"
                    onClick={() => markReadMutation.mutate(row.id)}
                  >
                    标记已读
                  </Button>
                )}
                <Button
                  size="small"
                  danger
                  onClick={() => deleteMutation.mutate(row.id)}
                >
                  删除
                </Button>
              </Space>
            ),
          },
        ]}
        dataSource={data.items}
        loading={listQuery.isFetching}
        total={data.total}
        pagination={pagination}
        onPaginationChange={setPagination}
      />
    </PageContainer>
  );
}
