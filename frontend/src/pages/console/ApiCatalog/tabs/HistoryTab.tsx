// 变更记录 Tab：分页展示接口的 change_log。
// 只读，不发写请求。查询 key 与详情同根 ['api-catalog']，导入/编辑后会被失效刷新。
import { useState } from 'react';
import { Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { ErrorState, LoadingState } from '@/components/PageState';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';
import type { ApiChangeLog, ApiInterfaceDetail, ChangeType } from '@/types';

// 变更类型色板：增=绿、删=红、改=橙/金，便于扫读。
const CHANGE_TYPE_COLOR: Record<ChangeType, string> = {
  CREATED: 'green',
  UPDATED: 'blue',
  PARAM_ADDED: 'cyan',
  PARAM_REMOVED: 'red',
  PARAM_TYPE_CHANGED: 'gold',
  REQUIRED_CHANGED: 'orange',
  RESPONSE_CHANGED: 'purple',
  MODULE_CHANGED: 'default',
};

/**
 * 变更记录 Tab。
 *
 * 纯读组件：发一次 listHistory 请求，分页参数变化重新拉取。
 * 失败整块 ErrorState；空列表走 ResourceTable 空态。
 */
export function HistoryTab({ api }: { api: ApiInterfaceDetail }) {
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 10,
  });
  const query = useQuery({
    queryKey: ['api-catalog', 'api', api.id, 'history', pagination],
    queryFn: () => apiCatalogApi.listHistory(api.id, pagination),
  });

  if (query.isPending) return <LoadingState />;
  if (query.isError)
    return <ErrorState error={query.error} onRetry={query.refetch} />;

  const data = query.data;
  return (
    <ResourceTable<ApiChangeLog>
      rowKey={(r) => r.id}
      columns={[
        {
          title: '类型',
          dataIndex: 'change_type',
          width: 150,
          render: (v: ChangeType) => (
            <Tag color={CHANGE_TYPE_COLOR[v]}>{v}</Tag>
          ),
        },
        {
          title: '摘要',
          dataIndex: 'summary',
          render: (v: string | null) => v ?? '-',
        },
        {
          title: '变更前指纹',
          dataIndex: 'source_hash_before',
          width: 150,
          render: (v: string | null) =>
            v ? (
              <Typography.Text code copyable>
                {v.slice(0, 12)}
              </Typography.Text>
            ) : (
              '-'
            ),
        },
        {
          title: '变更后指纹',
          dataIndex: 'source_hash_after',
          width: 150,
          render: (v: string | null) =>
            v ? (
              <Typography.Text code copyable>
                {v.slice(0, 12)}
              </Typography.Text>
            ) : (
              '-'
            ),
        },
        {
          title: '时间',
          dataIndex: 'created_at',
          width: 180,
          render: (v: string) => new Date(v).toLocaleString(),
        },
      ]}
      dataSource={data.items}
      loading={query.isFetching}
      total={data.total}
      pagination={pagination}
      onPaginationChange={setPagination}
      emptyText="暂无变更记录"
    />
  );
}
