// 执行记录 Tab。
//
// §7.5：表列 Fixture、Provider、TestRun、TestCase、Status、Duration、Cleanup、时间。
// 行点击 / 「详情」打开 ExecutionDetailDrawer —— 每步 input / output / error 都在这里看。
// 敏感字段以后端已脱敏 JSON 为准，前端不还原。
import { useState } from 'react';
import { Button, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { testDataApi } from '@/api/testData';
import { ErrorState, LoadingState } from '@/components/PageState';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';
import {
  CLEANUP_STATUS_COLOR,
  DATA_EXECUTION_STATUS_COLOR,
  labelOf,
  DATA_EXECUTION_STATUS_OPTIONS,
} from './constants';
import { ExecutionDetailDrawer } from './ExecutionDetailDrawer';
import type { DataExecution } from '@/types';

/**
 * 执行记录列表。手工试跑 / Provider 试跑 / 用例造数都会在这里留痕。
 */
export function ExecutionTab({ projectId }: { projectId: number }) {
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 20,
  });
  // 抽屉：seed 为 null 时由抽屉自己按 id 拉取。
  const [detailId, setDetailId] = useState<number | null>(null);

  const query = useQuery({
    queryKey: ['test-data', 'executions', projectId, pagination],
    queryFn: () => testDataApi.listExecutions(projectId, pagination),
    enabled: projectId != null,
  });

  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const rows = query.data.items ?? [];

  return (
    <>
      <ResourceTable<DataExecution>
        rowKey={(r) => r.id}
        dataSource={rows}
        loading={query.isFetching}
        total={query.data.total}
        pagination={pagination}
        onPaginationChange={setPagination}
        onRowClick={(r) => setDetailId(r.id)}
        rowStyle={{ cursor: 'pointer' }}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 70 },
          {
            title: 'TestRun',
            dataIndex: 'test_run_id',
            width: 100,
            render: (v: number | null) => (v == null ? '-' : `#${v}`),
          },
          {
            title: 'TestCase 执行',
            dataIndex: 'case_execution_id',
            width: 120,
            render: (v: number | null) => (v == null ? '-' : `#${v}`),
          },
          {
            title: '状态',
            dataIndex: 'status',
            width: 110,
            render: (v: DataExecution['status']) => (
              <Tag color={DATA_EXECUTION_STATUS_COLOR[v]}>{labelOf(DATA_EXECUTION_STATUS_OPTIONS, v)}</Tag>
            ),
          },
          {
            title: '耗时(ms)',
            dataIndex: 'duration_ms',
            width: 100,
            render: (v: number | null) => (v == null ? '-' : v),
          },
          {
            title: '清理',
            dataIndex: 'cleanup_status',
            width: 100,
            render: (v: string | null) =>
              v ? (
                <Tag color={CLEANUP_STATUS_COLOR[v as keyof typeof CLEANUP_STATUS_COLOR] ?? 'default'}>
                  {v}
                </Tag>
              ) : (
                '-'
              ),
          },
          {
            title: 'Fixture',
            dataIndex: 'fixture_key_count',
            width: 90,
          },
          {
            title: '步骤',
            dataIndex: 'provider_step_count',
            width: 90,
          },
          {
            title: '时间',
            dataIndex: 'created_at',
            render: (v: string) => new Date(v).toLocaleString(),
          },
          {
            title: '操作',
            key: 'actions',
            width: 80,
            render: (_: unknown, r: DataExecution) => (
              <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); setDetailId(r.id); }}>
                详情
              </Button>
            ),
          },
        ]}
        emptyText="暂无执行记录"
      />

      <ExecutionDetailDrawer
        open={detailId != null}
        executionId={detailId}
        seed={null}
        onClose={() => setDetailId(null)}
      />
    </>
  );
}
