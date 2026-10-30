import { collectPages } from '@/shared/api/pagination';
import { useMemo, useState } from 'react';
import { Alert, Button, Card, Col, DatePicker, Flex, Input, Row, Select, Space, Table, Tag, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import type { Dayjs } from 'dayjs';
import { mockManagementApi } from '@/features/mocking/api/mockManagement';
import { EmptyState, PageContainer } from '@/shared/ui/PageState';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import type { MockExecution } from '@/features/mocking/contracts';
import { statusCodeColor } from './constants';
import { MockContextsCard } from './components/MockContextsCard';
import { MockExecutionDrawer } from './components/MockExecutionDrawer';
import { fmtTs } from './components/contextPresentation';

/** 调用记录与执行作用域页。 */
export function ConsoleMockExecutionListPage() {
  const { currentProjectId } = useConsoleScope();
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState({
    service_id: undefined as number | undefined,
    matched: undefined as boolean | undefined,
    test_run_id: undefined as number | undefined,
    context_id: undefined as string | undefined,
    start: null as Dayjs | null,
    end: null as Dayjs | null,
    page: 1,
    selected: null as number | null,
  });

  const projectId = currentProjectId;
  const servicesQuery = useQuery({
    queryKey: ['mock-services-for-filter', projectId],
    queryFn: () => collectPages((page) => mockManagementApi.listServices(projectId!, { page, page_size: 200 })),
    enabled: projectId != null,
  });
  const services = servicesQuery.data?.items ?? [];

  const execQuery = useQuery({
    queryKey: [
      'mock-executions',
      projectId,
      filters.service_id,
      filters.matched,
      filters.test_run_id,
      filters.context_id,
    ],
    queryFn: () =>
      mockManagementApi.listExecutions(projectId!, {
        service_id: filters.service_id,
        matched: filters.matched,
        test_run_id: filters.test_run_id,
        context_id: filters.context_id,
        page: filters.page,
        page_size: 50,
      }),
    enabled: projectId != null,
  });
  const all = useMemo(() => execQuery.data?.items ?? [], [execQuery.data]);
  const rows = useMemo(
    () =>
      !filters.start && !filters.end
        ? all
        : all.filter((r) => {
            if (!r.created_at) return true;
            const t = new Date(r.created_at).getTime();
            if (filters.start && t < filters.start.startOf('day').valueOf()) return false;
            if (filters.end && t > filters.end.endOf('day').valueOf()) return false;
            return true;
          }),
    [all, filters.start, filters.end],
  );
  const total = execQuery.data?.total ?? rows.length;
  const page = execQuery.data?.page ?? filters.page;
  const pageSize = execQuery.data?.page_size ?? 50;

  const columns: TableColumnsType<MockExecution> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string) => fmtTs(v),
    },
    {
      title: '服务 / 接口',
      width: 240,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <span>
            {r.service_key ?? '-'}
            {r.endpoint_path ? <Typography.Text type="secondary"> · {r.endpoint_path}</Typography.Text> : null}
          </span>
        </Space>
      ),
    },
    {
      title: '请求',
      width: 140,
      render: (_, r) => (
        <Tag color="blue">
          {r.method} {r.path}
        </Tag>
      ),
    },
    {
      title: '状态码',
      dataIndex: 'response_status',
      width: 90,
      render: (v: number | null) => (v ? <Tag color={statusCodeColor(v)}>{v}</Tag> : '-'),
    },
    {
      title: '匹配',
      dataIndex: 'matched',
      width: 110,
      render: (v: boolean, r) => (
        <Space direction="vertical" size={0}>
          <Tag color={v ? 'green' : 'red'}>{v ? '命中' : '未命中'}</Tag>
          {v && r.scenario_key ? <Tag color="purple">{r.scenario_key}</Tag> : null}
        </Space>
      ),
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      width: 90,
      render: (v: number | null) => (v != null ? `${v}ms` : '-'),
    },
    {
      title: '执行',
      width: 110,
      render: (_, r) => (r.test_run_id ? <Tag color="geekblue">#{r.test_run_id}</Tag> : '-'),
    },
    {
      title: '错误码',
      dataIndex: 'error_code',
      width: 200,
      ellipsis: true,
      render: (v: string | null, r) => (v ? <Tag color="red">{v}</Tag> : r.error_message ? <Tag color="orange">error</Tag> : '-'),
    },
    {
      title: '操作',
      width: 100,
      fixed: 'right',
      render: (_, row) => (
        <Button
          size="small"
          onClick={() => setFilters((f) => ({ ...f, selected: row.id }))}
        >
          详情
        </Button>
      ),
    },
  ];

  const selectedId = filters.selected;

  if (projectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }} wrap="wrap" gap="middle">
        <Typography.Title level={5} style={{ margin: 0 }}>
          Mock 调用记录
        </Typography.Title>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 0 }}
          message="快照已脱敏，仅供排障；不含 Token 明文。"
        />
      </Flex>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={[8, 8]} align="bottom">
          <Col>
            <Typography.Text type="secondary">服务</Typography.Text>
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              style={{ width: 220, display: 'block' }}
              placeholder="全部服务"
              options={services.map((s) => ({ value: s.id, label: `${s.service_key}（${s.name}）` }))}
              value={filters.service_id}
              onChange={(v) => setFilters((f) => ({ ...f, service_id: v, page: 1 }))}
            />
          </Col>
          <Col>
            <Typography.Text type="secondary">匹配结果</Typography.Text>
            <Select
              allowClear
              style={{ width: 130, display: 'block' }}
              placeholder="全部"
              options={[
                { value: true, label: '命中' },
                { value: false, label: '未命中' },
              ]}
              value={filters.matched}
              onChange={(v) => setFilters((f) => ({ ...f, matched: v, page: 1 }))}
            />
          </Col>
          <Col>
            <Typography.Text type="secondary">执行 ID</Typography.Text>
            <Input
              type="number"
              placeholder="test_run_id"
              style={{ width: 130, display: 'block' }}
              value={filters.test_run_id ?? ''}
              onChange={(e) => {
                const v = e.target.value;
                setFilters((f) => ({ ...f, test_run_id: v ? Number(v) : undefined, page: 1 }));
              }}
            />
          </Col>
          <Col>
            <Typography.Text type="secondary">作用域</Typography.Text>
            <Input
              placeholder="context_id"
              style={{ width: 200, display: 'block' }}
              value={filters.context_id ?? ''}
              onChange={(e) => setFilters((f) => ({ ...f, context_id: e.target.value || undefined, page: 1 }))}
            />
          </Col>
          <Col>
            <Typography.Text type="secondary">时间范围</Typography.Text>
            <DatePicker.RangePicker
              size="middle"
              style={{ width: 260, display: 'block' }}
              value={[filters.start, filters.end]}
              onChange={(range) => setFilters((f) => ({ ...f, start: range?.[0] ?? null, end: range?.[1] ?? null }))}
            />
          </Col>
          <Col>
            <Button
              icon={<ReloadOutlined />}
              onClick={() =>
                setFilters({
                  service_id: undefined,
                  matched: undefined,
                  test_run_id: undefined,
                  context_id: undefined,
                  start: null,
                  end: null,
                  page: 1,
                  selected: null,
                })
              }
            >
              重置
            </Button>
          </Col>
        </Row>
      </Card>

      <MockContextsCard
        projectId={projectId}
        testRunId={filters.test_run_id}
        onFilter={(cid) => setFilters((f) => ({ ...f, context_id: cid, page: 1 }))}
        onClose={(cid) => {
          void mockManagementApi.closeContext(cid).then(() => {
            queryClient.invalidateQueries({ queryKey: ['mock-contexts', projectId] });
          });
        }}
      />

      <Table<MockExecution>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={rows}
        scroll={{ x: 1400 }}
        loading={execQuery.isLoading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p) => setFilters((f) => ({ ...f, page: p })),
        }}
        locale={{ emptyText: <EmptyState description="还没有 Mock 调用记录" /> }}
      />

      <MockExecutionDrawer
        projectId={projectId}
        rowId={selectedId}
        onClose={() => setFilters((f) => ({ ...f, selected: null }))}
        onFilter={(cid) => setFilters((f) => ({ ...f, context_id: cid, page: 1 }))}
      />
    </PageContainer>
  );
}
