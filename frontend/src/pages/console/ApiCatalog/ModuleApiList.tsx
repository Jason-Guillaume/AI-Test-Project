// 选中模块后展示模块内的接口清单；点击接口行切换到接口详情。
import { useEffect, useState } from 'react';
import { Button, Space, Tag, Typography } from 'antd';
import { FolderOpenOutlined, RightOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { apiCatalogApi } from '@/api/apiCatalog';
import { ErrorState, LoadingState } from '@/components/PageState';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';
import { API_STATUS_COLOR, METHOD_COLOR } from './constants';
import type { ApiInterface, ApiModule, ApiStatus } from '@/types';

export function ModuleApiList({
  projectId,
  module,
  keyword,
  method,
  status,
  onSelectApi,
}: {
  projectId: number;
  module: ApiModule;
  keyword: string;
  method: string | undefined;
  status: ApiStatus | undefined;
  onSelectApi: (id: number) => void;
}) {
  const [pagination, setPagination] = useState<PaginationState>({ page: 1, page_size: 20 });

  useEffect(() => {
    setPagination((current) => ({ ...current, page: 1 }));
  }, [module.id, keyword, method, status]);

  const query = useQuery({
    queryKey: ['api-catalog', projectId, 'module-apis', module.id, pagination, keyword, method, status],
    queryFn: () => apiCatalogApi.listApis(projectId, {
      ...pagination,
      module_id: module.id,
      keyword: keyword || undefined,
      method,
      status,
    }),
  });

  if (query.isPending) return <LoadingState tip={`正在加载「${module.name}」接口...`} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const columns = [
    {
      title: '方法',
      dataIndex: 'method',
      width: 100,
      render: (value: string) => <Tag color={METHOD_COLOR[value] ?? 'default'}>{value}</Tag>,
    },
    {
      title: '接口名称',
      dataIndex: 'name',
      width: 250,
      render: (value: string) => <Typography.Text strong>{value}</Typography.Text>,
    },
    {
      title: '路径',
      dataIndex: 'path',
      ellipsis: true,
      render: (value: string) => <Typography.Text code title={value}>{value}</Typography.Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (value: ApiStatus) => <Tag color={API_STATUS_COLOR[value]}>{value}</Tag>,
    },
    { title: '版本', dataIndex: 'version', width: 90, render: (value: number) => `v${value}` },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '',
      key: 'open',
      width: 88,
      align: 'right' as const,
      render: (_value: unknown, row: ApiInterface) => (
        <Button type="link" size="small" onClick={(event) => {
          event.stopPropagation();
          onSelectApi(row.id);
        }}>
          查看 <RightOutlined />
        </Button>
      ),
    },
  ];

  return (
    <section className="api-module-interfaces">
      <div className="api-module-interfaces-header">
        <div className="api-module-interfaces-title">
          <span className="api-module-interfaces-icon"><FolderOpenOutlined /></span>
          <div>
            <Typography.Title level={4}>{module.name}</Typography.Title>
            <Typography.Text type="secondary">
              {keyword || method || status ? '当前筛选条件下的接口' : '当前模块下的全部接口'}
            </Typography.Text>
          </div>
        </div>
        <Tag color="blue" className="api-module-interfaces-count">{query.data.total} 个接口</Tag>
      </div>

      <ResourceTable<ApiInterface>
        rowKey={(row) => row.id}
        columns={columns}
        dataSource={query.data.items}
        loading={query.isFetching}
        total={query.data.total}
        pagination={pagination}
        onPaginationChange={setPagination}
        emptyText={keyword || method || status ? '当前筛选条件下没有接口' : '此模块暂无接口'}
        onRowClick={(row) => onSelectApi(row.id)}
        rowStyle={{ cursor: 'pointer' }}
      />
      <Space className="api-module-interfaces-hint" size={6}>
        <Typography.Text type="secondary">点击接口行可查看详情</Typography.Text>
      </Space>
    </section>
  );
}
