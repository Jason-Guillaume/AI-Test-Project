// 测试数据 Tab：项目内测试数据资产表。
//
// §7.2：列 名称、实体类型、来源、Scope、状态、更新时间、被引用次数。
// 工具栏：搜索框、来源筛选、Scope 筛选、状态下拉、新增按钮。
// 新增/编辑走 TestDataModal；删除用 Popconfirm 二次确认（资产删除非数据库直写，
// 但仍保留确认，避免误删被引用数据）。
import { useState } from 'react';
import { App, Button, Input, Popconfirm, Select, Space, Tag } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { testDataApi } from '@/api/testData';
import { getErrorMessage } from '@/api/client';
import { ErrorState, EmptyState, LoadingState } from '@/components/PageState';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';
import {
  ASSET_SOURCE_OPTIONS,
  ASSET_STATUS_COLOR,
  ASSET_STATUS_OPTIONS,
  FIXTURE_SCOPE_OPTIONS,
  labelOf,
} from './constants';
import { TestDataModal } from './TestDataModal';
import type { AssetSource, AssetStatus, FixtureScope, TestDataAsset } from '@/types';

/**
 * 测试数据资产列表。
 */
export function TestDataTab({ projectId }: { projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [keyword, setKeyword] = useState('');
  const [source, setSource] = useState<string | undefined>(undefined);
  const [scope, setScope] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 20,
  });
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<TestDataAsset | null>(null);

  const query = useQuery({
    queryKey: ['test-data', 'assets', projectId, { keyword, source, scope, status, pagination }],
    queryFn: () =>
      testDataApi.listAssets(projectId, {
        keyword: keyword || undefined,
        source,
        scope,
        status,
        page: pagination.page,
        page_size: pagination.page_size,
      }),
    enabled: projectId != null,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => testDataApi.removeAsset(id),
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'assets'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const rows = query.data?.items ?? [];

  return (
    <>
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          style={{ width: 200 }}
          allowClear
          placeholder="搜索名称/实体类型"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Select
          style={{ width: 130 }}
          allowClear
          placeholder="来源：全部"
          value={source}
          onChange={(v) => setSource(v ?? undefined)}
          options={ASSET_SOURCE_OPTIONS}
        />
        <Select
          style={{ width: 150 }}
          allowClear
          placeholder="作用域：全部"
          value={scope}
          onChange={(v) => setScope(v ?? undefined)}
          options={FIXTURE_SCOPE_OPTIONS}
        />
        <Select
          style={{ width: 130 }}
          allowClear
          placeholder="状态：全部"
          value={status}
          onChange={(v) => setStatus(v ?? undefined)}
          options={ASSET_STATUS_OPTIONS}
        />
        <Button
          type="primary"
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
        >
          新增
        </Button>
      </Space>

      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : rows.length === 0 ? (
        <EmptyState description="暂无测试数据，点「新增」创建第一条" />
      ) : (
        <ResourceTable<TestDataAsset>
          rowKey={(r) => r.id}
          dataSource={rows}
          loading={query.isFetching}
          total={query.data.total}
          pagination={pagination}
          onPaginationChange={setPagination}
          columns={[
            { title: '名称', dataIndex: 'name' },
            { title: '实体类型', dataIndex: 'entity_type', width: 120 },
            {
              title: '来源',
              dataIndex: 'source',
              width: 90,
              render: (v: AssetSource) => <Tag>{labelOf(ASSET_SOURCE_OPTIONS, v)}</Tag>,
            },
            {
              title: '作用域',
              dataIndex: 'scope',
              width: 100,
              render: (v: FixtureScope) => labelOf(FIXTURE_SCOPE_OPTIONS, v),
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 90,
              render: (v: AssetStatus) => (
                <Tag color={ASSET_STATUS_COLOR[v]}>{labelOf(ASSET_STATUS_OPTIONS, v)}</Tag>
              ),
            },
            {
              title: '被引用',
              dataIndex: 'referenced_count',
              width: 80,
              render: (v: number) => v,
            },
            {
              title: '更新时间',
              dataIndex: 'updated_at',
              width: 170,
              render: (v: string) => new Date(v).toLocaleString(),
            },
            {
              title: '操作',
              key: 'actions',
              width: 120,
              render: (_: unknown, r: TestDataAsset) => (
                <Space size={4}>
                  <a
                    onClick={() => {
                      setEditing(r);
                      setModalOpen(true);
                    }}
                  >
                    编辑
                  </a>
                  <Popconfirm
                    title="删除该测试数据？"
                    description="被用例引用时后端会拒绝。"
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                    onConfirm={() => deleteMutation.mutate(r.id)}
                  >
                    <a style={{ color: '#ff4d4f' }}>删除</a>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
          emptyText="暂无测试数据"
        />
      )}

      <TestDataModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        projectId={projectId}
        editing={editing}
      />
    </>
  );
}
