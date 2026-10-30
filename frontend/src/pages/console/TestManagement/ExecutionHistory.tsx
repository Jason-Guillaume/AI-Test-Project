// 执行历史页（用户视角）。
// 分页列出项目内 TestRun，逐行「查看详情」抽屉展开该次运行的 CaseExecution 列表，
// 每条用例执行再打开宽屏抽屉查看步骤时间线 / 断言 / 截图 / Trace / 请求响应快照。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；越权 404，前端不展示。
// 颜色与状态语义统一走 test-management/status 与 theme token，不在本页重复定义色板。
import { useEffect, useState } from 'react';
import { App, Button, Empty, Table, theme, Typography } from 'antd';
import { EyeOutlined, FileTextOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { TableColumnsType } from 'antd';
import { getErrorMessage } from '@/shared/api/client';
import { reportsApi } from '@/features/reports/api/reports';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { CaseExecutionDetail } from '@/widgets/execution-detail/CaseExecutionDetail';
import { DetailDrawer } from '@/shared/ui/DetailDrawer';
import { EmptyState, ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { TaskSourceLinks } from '@/features/tasks/components/TaskSourceLinks';
import { fmtDuration, fmtTime } from '@/shared/lib/format';
import {
  CASE_EXECUTION_STATUS_COLOR,
  CASE_EXECUTION_STATUS_LABEL,
  TEST_RUN_STATUS_COLOR,
} from '@/features/test-management/status';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { TEST_RUN_STATUS_OPTIONS } from './constants';
import type { CaseExecution, TestRun } from '@/features/test-management/contracts';


/** 执行历史页。 */
export function ConsoleExecutionHistoryPage() {
  const { currentProjectId } = useConsoleScope();
  const { token } = theme.useToken();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [drawerRunId, setDrawerRunId] = useState<number | null>(null);
  const [selectedCe, setSelectedCe] = useState<CaseExecution | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedProjectId = Number(searchParams.get('projectId'));
  const requestedExecutionId = Number(searchParams.get('caseExecutionId'));
  const { message: msg } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const linkedExecutionQuery = useQuery({
    queryKey: ['case-executions', drawerRunId],
    queryFn: () => testManagementApi.listCaseExecutions(drawerRunId!),
    enabled: drawerRunId != null && requestedExecutionId > 0 && (!requestedProjectId || requestedProjectId === currentProjectId),
  });

  useEffect(() => {
    if (requestedExecutionId > 0 && linkedExecutionQuery.data) {
      setSelectedCe(linkedExecutionQuery.data.items.find(item => item.id === requestedExecutionId) ?? null);
    }
  }, [linkedExecutionQuery.data, requestedExecutionId]);

  useEffect(() => {
    const requestedRunId = Number(searchParams.get('runId'));
    if (Number.isInteger(requestedRunId) && requestedRunId > 0) setDrawerRunId(requestedRunId);
  }, [searchParams]);

  // 为一次已完成的执行生成正式测试报告；同一执行已有 COMPLETED 报告时后端幂等返回已有。
  const generateReportMutation = useMutation({
    mutationFn: (runId: number) => reportsApi.generate(runId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['test-reports'] });
      msg.success(`报告已就绪（${data.status}），正在打开详情`);
      navigate(`/console/test-reports/${data.report_id}`);
    },
    onError: (e) => msg.error(getErrorMessage(e, '报告生成失败')),
  });

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
  if (requestedProjectId > 0 && requestedProjectId !== currentProjectId) {
    return <PageContainer><EmptyState description={`此运行链接指向项目 #${requestedProjectId}，请先在顶部切换项目`} /></PageContainer>;
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
      render: (v: string) => (
        <StatusBadge value={v} options={TEST_RUN_STATUS_OPTIONS} colors={TEST_RUN_STATUS_COLOR} />
      ),
    },
    { title: '总数', dataIndex: 'total', width: 70 },
    {
      title: '通过',
      dataIndex: 'passed',
      width: 70,
      render: (v: number) => <Typography.Text style={{ color: token.colorSuccess }}>{v}</Typography.Text>,
    },
    {
      title: '失败',
      dataIndex: 'failed',
      width: 70,
      render: (v: number) => <Typography.Text style={{ color: token.colorError }}>{v}</Typography.Text>,
    },
    { title: '跳过', dataIndex: 'skipped', width: 70 },
    {
      title: '错误',
      dataIndex: 'error',
      width: 70,
      render: (v: number) => <Typography.Text style={{ color: token.colorWarning }}>{v}</Typography.Text>,
    },
    { title: '计划ID', dataIndex: 'plan_id', width: 80, render: (v: number | null) => v ?? '-' },
    { title: '开始', dataIndex: 'started_at', width: 150, render: (v: string | null) => fmtTime(v) },
    { title: '结束', dataIndex: 'finished_at', width: 150, render: (v: string | null) => fmtTime(v) },
    {
      title: '操作',
      width: 190,
      render: (_, row) => (
        <span style={{ display: 'inline-flex', gap: 8 }}>
          <Button size="small" icon={<EyeOutlined />} onClick={() => setDrawerRunId(row.id)}>
            查看详情
          </Button>
          <Button
            size="small"
            icon={<FileTextOutlined />}
            loading={generateReportMutation.isPending}
            disabled={row.status === 'RUNNING' || row.status === 'PENDING'}
            onClick={() => generateReportMutation.mutate(row.id)}
          >
            生成报告
          </Button>
        </span>
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
      ) : runsQuery.isError ? (
        /* 接口失败必须报错：否则 500 会渲染成「暂无执行记录」，用户会以为没有执行过 */
        <ErrorState error={runsQuery.error} onRetry={runsQuery.refetch} />
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
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      )}

      <RunDetailDrawer
        runId={drawerRunId}
        onClose={() => { setDrawerRunId(null); setSearchParams({}); }}
        onSelect={(ce) => setSelectedCe(ce)}
      />
      <CaseExecutionDetail open={selectedCe !== null} execution={selectedCe} onClose={() => setSelectedCe(null)} />
    </PageContainer>
  );
}

/** 单次运行详情抽屉：用例执行列表。 */
function RunDetailDrawer({
  runId,
  onClose,
  onSelect,
}: {
  runId: number | null;
  onClose: () => void;
  onSelect: (ce: CaseExecution) => void;
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
      render: (v: string) => (
        <StatusBadge
          value={v}
          labels={{ ...CASE_EXECUTION_STATUS_LABEL }}
          colors={{ ...CASE_EXECUTION_STATUS_COLOR }}
        />
      ),
    },
    { title: '执行器', dataIndex: 'executor_type', width: 120, render: (v: string | null) => v ?? '-' },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      width: 100,
      render: (v: number | null) => fmtDuration(v),
    },
    { title: '错误码', dataIndex: 'error_code', width: 120, render: (v: string | null) => v ?? '-' },
    { title: '错误信息', dataIndex: 'error_message', ellipsis: true, render: (v: string | null) => v ?? '-' },
    {
      title: '操作',
      width: 110,
      render: (_, row) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => onSelect(row)}>
          查看
        </Button>
      ),
    },
  ];

  return (
    <DetailDrawer
      open={runId != null}
      onClose={onClose}
      title={runId != null ? `执行 #${runId}` : '执行详情'}
      width={760}
      loading={caseExecQuery.isLoading}
      error={caseExecQuery.isError ? caseExecQuery.error : undefined}
      empty={caseExecQuery.isSuccess && items.length === 0 ? '无用例执行记录' : null}
    >
      <Table
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={false}
        locale={{ emptyText: <Empty description="无用例执行记录" /> }}
      />
      <div style={{ marginTop: 16 }}>
        <TaskSourceLinks resourceType="TEST_RUN" resourceId={runId} />
      </div>
    </DetailDrawer>
  );
}
