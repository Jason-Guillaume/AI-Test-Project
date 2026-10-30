import { useState } from 'react';
import { Button, Card, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd';
import { ReloadOutlined, StopOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { mockManagementApi } from '@/features/mocking/api/mockManagement';
import type { MockContext, MockContextStatus } from '@/features/mocking/contracts';
import { EmptyState } from '@/shared/ui/PageState';
import { STATUS_OPTIONS, fmtTs } from './contextPresentation';

export /** 作用域行：状态 + 过期时间 + 覆盖数 + 手动关闭。 */
function MockContextsCard({
  projectId,
  testRunId,
  onFilter,
  onClose,
}: {
  projectId: number;
  testRunId?: number;
  onFilter: (contextId: string) => void;
  onClose: (contextId: string) => void;
}) {
  const [status, setStatus] = useState<MockContextStatus | undefined>();
  const queryClient = useQueryClient();
  const ctxQuery = useQuery({
    queryKey: ['mock-contexts', projectId, status, testRunId],
    queryFn: () => mockManagementApi.listContexts(projectId, { status, test_run_id: testRunId, page: 1, page_size: 50 }),
    enabled: projectId != null,
  });
  const rows = (ctxQuery.data ?? []) as unknown as MockContext[];

  const columns: TableColumnsType<MockContext> = [
    {
      title: 'Context ID',
      dataIndex: 'context_id',
      width: 210,
      render: (v: string) => (
        <Typography.Text copyable={{ text: v }} code style={{ fontSize: 12 }}>
          {v}
        </Typography.Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: MockContextStatus) => (
        <Tag color={v === 'ACTIVE' ? 'green' : v === 'CLOSED' ? 'blue' : 'default'}>{v}</Tag>
      ),
    },
    {
      title: '执行',
      width: 120,
      render: (_, r) => (r.test_run_id ? <Tag color="geekblue">Run #{r.test_run_id}</Tag> : <Typography.Text type="secondary">手动</Typography.Text>),
    },
    {
      title: '场景覆盖',
      dataIndex: 'scenario_overrides',
      width: 100,
      render: (v: unknown) => {
        const n = v && typeof v === 'object' ? Object.keys(v as Record<string, unknown>).length : 0;
        return n ? <Tag color="purple">{n} 个场景</Tag> : <Typography.Text type="secondary">-</Typography.Text>;
      },
    },
    { title: '过期时间', dataIndex: 'expires_at', width: 170, render: (v: string) => fmtTs(v) },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: (v: string) => fmtTs(v) },
    {
      title: '操作',
      width: 150,
      render: (_, row) => (
        <Space size="small">
          <Button size="small" onClick={() => onFilter(row.context_id)}>
            筛选调用
          </Button>
          <Popconfirm title="确认关闭该作用域？" description="关闭后不再命中场景覆盖。" onConfirm={() => onClose(row.context_id)}>
            <Button size="small" danger icon={<StopOutlined />}>
              关闭
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      size="small"
      style={{ marginBottom: 16 }}
      title="Mock 作用域（Context · scenario_overrides 并发隔离）"
      extra={
        <Select
          allowClear
          size="small"
          placeholder="按状态"
          style={{ width: 130 }}
          options={STATUS_OPTIONS}
          value={status}
          onChange={setStatus}
        />
      }
    >
      <Table<MockContext>
        rowKey="context_id"
        size="small"
        columns={columns}
        dataSource={rows}
        scroll={{ x: 900 }}
        pagination={false}
        loading={ctxQuery.isLoading}
        locale={{ emptyText: <EmptyState description="还没有执行过带 Mock 的测试用例" /> }}
      />
      {rows.length > 0 && (
        <Button
          size="small"
          icon={<ReloadOutlined />}
          style={{ marginTop: 8 }}
          loading={ctxQuery.isFetching}
          onClick={() => queryClient.invalidateQueries({ queryKey: ['mock-contexts', projectId] })}
        >
          刷新
        </Button>
      )}
    </Card>
  );
}

