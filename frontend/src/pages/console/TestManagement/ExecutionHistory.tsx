// 执行历史页（用户视角）。
// 分页列出项目内 TestRun（listRuns 返回分页信封 {items,total,page,page_size}），
// 逐行「查看详情」抽屉展开该次运行的 CaseExecution 列表（listCaseExecutions 返回分页信封），
// 每条用例执行可进一步查看断言结果与请求/响应/上下文快照。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；越权 404，前端不展示。
import { useState } from 'react';
import {
  Button,
  Drawer,
  Empty,
  Modal,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import { EyeOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { testManagementApi } from '@/api/testManagement';
import { EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { CASE_EXECUTION_STATUS_OPTIONS, TEST_RUN_STATUS_OPTIONS } from './constants';
import type { CaseExecution, TestRun } from '@/types';

const RUN_STATUS_COLOR: Record<string, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  SUCCESS: 'green',
  FAILED: 'red',
  CANCELLED: 'default',
};
const CASE_STATUS_COLOR: Record<string, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  PASSED: 'green',
  FAILED: 'red',
  SKIPPED: 'default',
  ERROR: 'warning',
};

const runStatusLabel = (v: string) =>
  TEST_RUN_STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v;
const caseStatusLabel = (v: string) =>
  CASE_EXECUTION_STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v;

/** JSON 快照只读视图。 */
function JsonView({ value }: { value: unknown }) {
  if (value == null) return <Empty description="无数据" />;
  return (
    <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 320, overflow: 'auto', background: '#fafafa', padding: 8, borderRadius: 6, fontSize: 12 }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/** 执行历史页。 */
export function ConsoleExecutionHistoryPage() {
  const { currentProjectId } = useConsoleScope();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [drawerRunId, setDrawerRunId] = useState<number | null>(null);
  const [selectedCe, setSelectedCe] = useState<CaseExecution | null>(null);

  const runsQuery = useQuery({
    queryKey: ['test-runs', currentProjectId, page, pageSize],
    queryFn: () => testManagementApi.listRuns(currentProjectId!, { page, page_size: pageSize }),
    enabled: currentProjectId != null,
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const runs: TestRun[] = runsQuery.data?.items ?? [];
  const total = runsQuery.data?.total ?? 0;
  const currentPage = runsQuery.data?.page ?? page;

  const columns: TableColumnsType<TestRun> = [
    { title: 'ID', dataIndex: 'id', width: 64 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v: string) => <Tag color={RUN_STATUS_COLOR[v] ?? 'default'}>{runStatusLabel(v)}</Tag>,
    },
    { title: '总数', dataIndex: 'total', width: 70 },
    { title: '通过', dataIndex: 'passed', width: 70, render: (v: number) => <span style={{ color: '#52c41a' }}>{v}</span> },
    { title: '失败', dataIndex: 'failed', width: 70, render: (v: number) => <span style={{ color: '#ff4d4f' }}>{v}</span> },
    { title: '跳过', dataIndex: 'skipped', width: 70 },
    { title: '错误', dataIndex: 'error', width: 70, render: (v: number) => <span style={{ color: '#faad14' }}>{v}</span> },
    { title: '计划ID', dataIndex: 'plan_id', width: 80, render: (v: number | null) => v ?? '-' },
    { title: '开始', dataIndex: 'started_at', width: 150, render: (v: string | null) => v?.slice(0, 16).replace('T', ' ') ?? '-' },
    { title: '结束', dataIndex: 'finished_at', width: 150, render: (v: string | null) => v?.slice(0, 16).replace('T', ' ') ?? '-' },
    {
      title: '操作',
      width: 110,
      render: (_, row) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => setDrawerRunId(row.id)}>
          查看详情
        </Button>
      ),
    },
  ];

  return (
    <PageContainer>
      <Typography.Title level={5} style={{ marginTop: 0 }}>
        执行历史
      </Typography.Title>

      {runsQuery.isLoading ? (
        <LoadingState />
      ) : runs.length === 0 ? (
        <EmptyState description="暂无执行记录" />
      ) : (
        <Table
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={runs}
          pagination={{
            current: currentPage,
            pageSize,
            total,
            showSizeChanger: true,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
        />
      )}

      <RunDetailDrawer
        runId={drawerRunId}
        onClose={() => setDrawerRunId(null)}
        selectedCe={selectedCe}
        setSelectedCe={setSelectedCe}
      />
    </PageContainer>
  );
}

/** 单次运行详情抽屉：用例执行列表。 */
function RunDetailDrawer({
  runId,
  onClose,
  selectedCe,
  setSelectedCe,
}: {
  runId: number | null;
  onClose: () => void;
  selectedCe: CaseExecution | null;
  setSelectedCe: (v: CaseExecution | null) => void;
}) {
  const caseExecQuery = useQuery({
    queryKey: ['case-executions', runId],
    queryFn: () => testManagementApi.listCaseExecutions(runId!),
    enabled: runId != null,
  });
  const items: CaseExecution[] = caseExecQuery.data?.items ?? [];

  const columns: TableColumnsType<CaseExecution> = [
    { title: '用例ID', dataIndex: 'test_case_id', width: 80, render: (v: number | null) => v ?? '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v: string) => <Tag color={CASE_STATUS_COLOR[v] ?? 'default'}>{caseStatusLabel(v)}</Tag>,
    },
    { title: '执行器', dataIndex: 'executor_type', width: 120, render: (v: string | null) => v ?? '-' },
    { title: '耗时(ms)', dataIndex: 'duration_ms', width: 100, render: (v: number | null) => v ?? '-' },
    { title: '错误码', dataIndex: 'error_code', width: 120, render: (v: string | null) => v ?? '-' },
    { title: '错误信息', dataIndex: 'error_message', ellipsis: true, render: (v: string | null) => v ?? '-' },
    {
      title: '操作',
      width: 110,
      render: (_, row) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => setSelectedCe(row)}>
          查看
        </Button>
      ),
    },
  ];

  return (
    <Drawer title={runId != null ? `执行 #${runId}` : '执行详情'} width={760} open={runId != null} onClose={onClose} destroyOnClose>
      <Table
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={false}
        loading={caseExecQuery.isLoading}
        locale={{ emptyText: <Empty description="无用例执行记录" /> }}
      />
      <CaseExecutionModal ce={selectedCe} onClose={() => setSelectedCe(null)} />
    </Drawer>
  );
}

/** 用例执行详情弹窗：断言结果 + 请求/响应/上下文快照。 */
function CaseExecutionModal({ ce, onClose }: { ce: CaseExecution | null; onClose: () => void }) {
  if (ce == null) return null;
  const assertionRows = ce.assertion_results ?? [];

  const assertionColumns: TableColumnsType<Record<string, unknown>> = [
    { title: '断言', dataIndex: 'path', render: (v) => String(v ?? '-') },
    { title: '操作符', dataIndex: 'operator', width: 90, render: (v) => String(v ?? '-') },
    { title: '期望', dataIndex: 'expected', ellipsis: true, render: (v) => String(v ?? '-') },
    { title: '实际', dataIndex: 'actual', ellipsis: true, render: (v) => String(v ?? '-') },
    {
      title: '结果',
      dataIndex: 'passed',
      width: 80,
      render: (v: unknown) =>
        v ? <Tag color="green">通过</Tag> : <Tag color="red">失败</Tag>,
    },
  ];

  return (
    <Modal
      title={ce != null ? `用例执行 #${ce.id}` : '用例执行'}
      open={ce != null}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
      width={720}
    >
      <Tabs
        items={[
          {
            key: 'assertions',
            label: '断言结果',
            children:
              assertionRows.length === 0 ? (
                <Empty description="无断言结果" />
              ) : (
                <Table
                  rowKey={(_, idx) => String(idx)}
                  size="small"
                  columns={assertionColumns}
                  dataSource={assertionRows as Record<string, unknown>[]}
                  pagination={false}
                />
              ),
          },
          {
            key: 'request',
            label: '请求快照',
            children: <JsonView value={ce.request_snapshot} />,
          },
          {
            key: 'response',
            label: '响应快照',
            children: <JsonView value={ce.response_snapshot} />,
          },
          {
            key: 'context',
            label: '上下文',
            children: <JsonView value={ce.context_json} />,
          },
        ]}
      />
    </Modal>
  );
}
