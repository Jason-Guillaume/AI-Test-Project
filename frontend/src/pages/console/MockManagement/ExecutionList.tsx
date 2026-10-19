// 调用记录 + 作用域（Context）页。
//
// 数据：
//   - GET /projects/{pid}/mock-executions   参数：service_id / matched / test_run_id / context_id
//   - GET /projects/{pid}/mock-contexts     参数：status / test_run_id
//   - POST /mock-contexts/{context_id}/close
//
// 请求 / 响应快照由后端 SensitiveDataMasker 脱敏后落库，这里只读展示。
// MockContext 的 expires_at 由 Runtime 读取时惰性清理（默认 30 分钟），这里只做展示与手动关闭。
import { useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Drawer,
  Flex,
  Input,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import { ReloadOutlined, StopOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import type { Dayjs } from 'dayjs';
import { getErrorMessage } from '@/api/client';
import { mockManagementApi } from '@/api/mockManagement';
import { EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import type { MockContext, MockContextStatus, MockExecution } from '@/types';
import {
  fmtJson,
  statusCodeColor,
} from './constants';

const STATUS_OPTIONS: { value: MockContextStatus; label: string }[] = [
  { value: 'ACTIVE', label: 'ACTIVE' },
  { value: 'CLOSED', label: 'CLOSED' },
  { value: 'EXPIRED', label: 'EXPIRED' },
];

/** 时间标签：把 ISO 字符串压成 HH:mm:ss。 */
function fmtTs(v: string | null): string {
  if (!v) return '-';
  const m = v.match(/T(\d{2}:\d{2}:\d{2})/);
  return m ? m[1] : v.slice(0, 19);
}

/** 作用域行：状态 + 过期时间 + 覆盖数 + 手动关闭。 */
function ContextsCard({
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

/** 执行详情抽屉：展示已脱敏的请求 / 响应快照。 */
function ExecutionDrawer({
  projectId,
  rowId,
  onClose,
  onFilter,
}: {
  projectId: number | null;
  rowId: number | null;
  onClose: () => void;
  onFilter: (contextId: string) => void;
}) {
  const { message: msg } = App.useApp();
  const queryClient = useQueryClient();
  const detailQuery = useQuery({
    queryKey: ['mock-execution', rowId],
    queryFn: () => mockManagementApi.getExecution(rowId!),
    enabled: rowId != null,
  });
  const row = detailQuery.data;
  const closeMutation = useMutation({
    mutationFn: (cid: string) => mockManagementApi.closeContext(cid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mock-contexts', projectId] });
      msg.success('作用域已关闭');
    },
    onError: (e) => msg.error(getErrorMessage(e, '关闭作用域失败')),
  });

  const block = (label: string, value: unknown) => (
    <div style={{ marginBottom: 12 }}>
      <Typography.Text strong style={{ fontSize: 12 }}>
        {label}
      </Typography.Text>
      <pre
        style={{
          margin: '4px 0 0',
          maxHeight: 260,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          fontSize: 12,
          background: 'var(--ant-color-fill-quaternary, rgba(0,0,0,0.04))',
          padding: 8,
          borderRadius: 4,
        }}
      >
        {fmtJson(value)}
      </pre>
    </div>
  );

  return (
    <Drawer
      title={row ? `调用记录 #${row.id} · ${row.method} ${row.path}` : '调用记录详情'}
      open={rowId != null}
      onClose={onClose}
      width={680}
    >
      {detailQuery.isLoading ? (
        <LoadingState />
      ) : row ? (
        <div>
          <Space wrap size="small" style={{ marginBottom: 12 }}>
            <Tag color="blue">{row.method}</Tag>
            <Tag color={statusCodeColor(row.response_status)}>{row.response_status ?? '-'}</Tag>
            <Tag color={row.matched ? 'green' : 'red'}>{row.matched ? '命中场景' : '未命中'}</Tag>
            {row.service_key ? <Tag color="geekblue">{row.service_key}</Tag> : null}
            {row.scenario_key ? <Tag color="purple">{row.scenario_key}</Tag> : null}
            {row.duration_ms != null ? <Tag>耗时 {row.duration_ms}ms</Tag> : null}
            {row.test_run_id ? <Tag color="geekblue">Run #{row.test_run_id}</Tag> : null}
            {row.error_code ? <Tag color="red">{row.error_code}</Tag> : null}
          </Space>

          {row.error_message && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message={`失败原因：${row.error_message}`}
            />
          )}

          {row.mock_context_id && (
            <Flex justify="space-between" align="center" style={{ marginBottom: 12 }}>
              <Typography.Text copyable={{ text: row.mock_context_id }} code style={{ fontSize: 12 }}>
                Context {row.mock_context_id}
              </Typography.Text>
              <Popconfirm title="关闭该作用域？" onConfirm={() => closeMutation.mutate(row.mock_context_id!)}>
                <Button size="small" icon={<StopOutlined />}>
                  关闭作用域
                </Button>
              </Popconfirm>
            </Flex>
          )}

          {row.request_id && (
            <Typography.Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 12 }}>
              request_id：{row.request_id}
            </Typography.Text>
          )}

          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            请求快照（Authorization、X-Api-Key、password、token 等敏感字段已脱敏）
          </Typography.Text>
          {block('查询参数', row.query_snapshot)}
          {block('请求头', row.header_snapshot)}
          {block('请求体', row.body_snapshot)}
          {block('响应头', row.response_header_snapshot)}
          {block('响应体', row.response_body_snapshot)}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={detailQuery.isFetching}
            style={{ marginTop: 4 }}
            onClick={() => detailQuery.refetch()}
          >
            刷新
          </Button>
          {row.mock_context_id && (
            <Button
              size="small"
              style={{ marginLeft: 8, marginTop: 4 }}
              onClick={() => {
                onFilter(row.mock_context_id!);
                onClose();
              }}
            >
              按此作用域筛选
            </Button>
          )}
        </div>
      ) : (
        <EmptyState description="调用记录不存在" />
      )}
    </Drawer>
  );
}

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
    queryFn: () => mockManagementApi.listServices(projectId!, { page: 1, page_size: 200 }),
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

      <ContextsCard
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

      <ExecutionDrawer
        projectId={projectId}
        rowId={selectedId}
        onClose={() => setFilters((f) => ({ ...f, selected: null }))}
        onFilter={(cid) => setFilters((f) => ({ ...f, context_id: cid, page: 1 }))}
      />
    </PageContainer>
  );
}
