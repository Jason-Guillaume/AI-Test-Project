// 选中模块后展示模块内的接口清单；点击接口行切换到接口详情。
// 批量选择只作用于当前筛选下的本页数据；删除允许部分成功，失败项保留勾选并给出名称、路径和原因。
import { useEffect, useRef, useState } from 'react';
import { App, Button, Space, Tag, Typography } from 'antd';
import { FolderOpenOutlined, RightOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { dataLifecycleApi, type BatchLifecycleReceipt } from '@/features/data-lifecycle/api';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { ResourceTable, type PaginationState } from '@/shared/ui/ResourceTable';
import { sequenceColumn } from '@/shared/lib/sequence';
import { API_STATUS_COLOR, METHOD_COLOR } from './constants';
import type { ApiInterface, ApiModule, ApiStatus } from '@/features/api-catalog/contracts';


/** 当前页元信息，供未分类复选框判断本页是否已全部选中。 */
export interface ModulePageMeta {
  loading: boolean;
  ids: number[];
}

export function ModuleApiList({
  projectId,
  module,
  modulePath,
  keyword,
  method,
  status,
  selectedApiId,
  onSelectApi,
  selectedIds,
  onSelectionChange,
  onPageMeta,
  onClearFilters,
  onCreate,
  onImport,
}: {
  projectId: number;
  module: ApiModule;
  modulePath: string;
  keyword: string;
  method: string | undefined;
  status: ApiStatus | undefined;
  selectedApiId: number | null;
  onSelectApi: (id: number | null) => void;
  selectedIds: number[];
  onSelectionChange: (ids: number[]) => void;
  onPageMeta: (meta: ModulePageMeta) => void;
  onClearFilters: () => void;
  onCreate: () => void;
  onImport: () => void;
}) {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [pagination, setPagination] = useState<PaginationState>({ page: 1, page_size: 20 });
  const hasFilters = Boolean(keyword || method || status);
  // 选择回调随已选数量变化；用 ref 保持最新引用，避免勾选动作触发范围重置。
  const onSelectionChangeRef = useRef(onSelectionChange);
  useEffect(() => {
    onSelectionChangeRef.current = onSelectionChange;
  }, [onSelectionChange]);

  // 切换模块或筛选条件时回到第一页并清空选择，避免把上一范围的勾选带到新列表。
  useEffect(() => {
    setPagination((current) => ({ ...current, page: 1 }));
    onSelectionChangeRef.current([]);
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

  // 把当前页 ID 交给父级，未分类复选框据此判断勾选与半选状态。
  useEffect(() => {
    onPageMeta({
      loading: query.isPending || query.isFetching,
      ids: (query.data?.items ?? []).map((row) => row.id),
    });
  }, [query.data, query.isPending, query.isFetching, onPageMeta]);

  /** 翻页属于显式切换范围，直接清空本页勾选，不弹确认。 */
  const changePagination = (next: PaginationState) => {
    setPagination(next);
    onSelectionChange([]);
  };

  const deleteMany = useMutation({
    mutationFn: () => dataLifecycleApi.deleteMany('api_interface', projectId, selectedIds),
    onSuccess: (receipt: BatchLifecycleReceipt) => {
      const failedIds = receipt.items.filter((item) => !item.succeeded).map((item) => item.id);
      const succeededIds = receipt.items.filter((item) => item.succeeded).map((item) => item.id);
      // 失败项仍留在列表中，保留勾选便于用户逐条定位后重试。
      onSelectionChange(failedIds);
      if (selectedApiId != null && succeededIds.includes(selectedApiId)) onSelectApi(null);
      queryClient.invalidateQueries({ queryKey: ['api-catalog', projectId] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });

      // 末页被删空时回到仍然有效的页码，避免停在空白页。
      const remaining = Math.max(0, (query.data?.total ?? 0) - receipt.succeeded);
      const lastPage = Math.max(1, Math.ceil(remaining / pagination.page_size));
      if (pagination.page > lastPage) {
        setPagination((current) => ({ ...current, page: lastPage }));
      }

      if (receipt.failed > 0) {
        const rowById = new Map((query.data?.items ?? []).map((row) => [row.id, row]));
        modal.info({
          title: `批量删除完成：成功 ${receipt.succeeded} 条，失败 ${receipt.failed} 条`,
          width: 640,
          content: (
            <Space direction="vertical" style={{ width: '100%' }}>
              {receipt.items.filter((item) => !item.succeeded).map((item) => {
                const row = rowById.get(item.id);
                const label = row ? `${row.method} ${row.path} · ${row.name}` : `接口 #${item.id}`;
                return (
                  <Typography.Text key={item.id} type="danger">
                    {label}：{item.error ?? '删除失败'}
                  </Typography.Text>
                );
              })}
            </Space>
          ),
          okText: '关闭',
        });
      } else {
        modal.success({
          title: `已将 ${receipt.succeeded} 个接口移入回收站`,
          content: '请求参数、响应定义和变更历史保留在原始接口记录中。',
          okText: '查看回收站',
          onOk: () => navigate('/console/recycle-bin'),
        });
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '批量删除失败')),
  });

  if (query.isPending) return <LoadingState tip={`正在加载「${module.name}」接口...`} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const columns = [
    sequenceColumn<ApiInterface>({ page: pagination.page, pageSize: pagination.page_size }),
    {
      title: '方法',
      dataIndex: 'method',
      width: 100,
      render: (value: string) => <Tag color={METHOD_COLOR[value] ?? 'default'}>{value}</Tag>,
    },
    {
      title: '接口名称',
      dataIndex: 'name',
      width: 220,
      render: (value: string) => <Typography.Text strong>{value}</Typography.Text>,
    },
    {
      title: '路径',
      dataIndex: 'path',
      width: 320,
      render: (value: string) => (
        <Typography.Text
          code
          copyable={{ text: value, tooltips: ['复制路径', '已复制'] }}
          ellipsis={{ tooltip: value }}
          style={{ maxWidth: 290 }}
        >
          {value}
        </Typography.Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: ApiStatus) => <Tag color={API_STATUS_COLOR[value]}>{value}</Tag>,
    },
    { title: '版本', dataIndex: 'version', width: 80, render: (value: number) => `v${value}` },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 170,
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

  const emptyText = (
    <div className="api-module-empty">
      <Typography.Text type="secondary">
        {hasFilters ? '当前筛选条件下没有接口' : '此模块暂无接口'}
      </Typography.Text>
      <Space wrap>
        {hasFilters ? (
          <Button size="small" onClick={onClearFilters}>清除筛选</Button>
        ) : (
          <>
            <Button size="small" type="primary" onClick={onCreate}>新建接口</Button>
            <Button size="small" onClick={onImport}>导入接口</Button>
          </>
        )}
      </Space>
    </div>
  );

  return (
    <section className="api-module-interfaces">
      <div className="api-module-interfaces-header">
        <div className="api-module-interfaces-title">
          <span className="api-module-interfaces-icon"><FolderOpenOutlined /></span>
          <div>
            <Typography.Title level={4}>{modulePath}</Typography.Title>
            <Typography.Text type="secondary">
              {hasFilters ? '当前筛选条件下的接口' : '当前模块下的全部接口'}
            </Typography.Text>
          </div>
        </div>
        <Space wrap>
          <Tag color="blue" className="api-module-interfaces-count">{query.data.total} 个接口</Tag>
          {selectedIds.length > 0 && (
            <Typography.Text type="secondary">已选 {selectedIds.length} 个接口</Typography.Text>
          )}
          {selectedIds.length > 0 && (
            <Button size="small" onClick={() => onSelectionChange([])}>清除选择</Button>
          )}
          <Button
            danger
            disabled={!selectedIds.length}
            loading={deleteMany.isPending}
            onClick={() => {
              if (deleteMany.isPending) return;
              modal.confirm({
                title: `删除选中的 ${selectedIds.length} 个接口？`,
                content: '仍被测试用例引用的接口会逐条拒绝删除，其余接口可部分成功；失败项会保留勾选。',
                okButtonProps: { danger: true },
                okText: `删除 ${selectedIds.length} 个`,
                onOk: () => deleteMany.mutateAsync(),
              });
            }}
          >删除选中</Button>
        </Space>
      </div>

      {hasFilters && (
        <div className="api-module-filter-summary">
          <Typography.Text type="secondary">
            筛选：{[
              keyword && `关键词「${keyword}」`,
              method && `方法 ${method}`,
              status && `状态 ${status}`,
            ].filter(Boolean).join(' · ')}
          </Typography.Text>
          <Button type="link" size="small" onClick={onClearFilters}>清除筛选</Button>
        </div>
      )}

      <ResourceTable<ApiInterface>
        rowKey={(row) => row.id}
        columns={columns}
        dataSource={query.data.items}
        loading={query.isFetching}
        total={query.data.total}
        pagination={pagination}
        onPaginationChange={changePagination}
        emptyText={emptyText}
        onRowClick={(row) => onSelectApi(row.id)}
        rowStyle={{ cursor: 'pointer' }}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: (keys) => onSelectionChange(keys.map(Number)),
        }}
      />
      <Space className="api-module-interfaces-hint" size={6}>
        <Typography.Text type="secondary">点击接口行可查看详情；表头复选框选择本页</Typography.Text>
      </Space>
    </section>
  );
}