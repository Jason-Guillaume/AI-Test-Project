// 执行历史页（用户视角）。
// 分页列出项目内 TestRun，逐行「查看详情」抽屉展开该次运行的 CaseExecution 列表，
// 每条用例执行再打开宽屏抽屉查看步骤时间线 / 断言 / 截图 / Trace / 请求响应快照。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；越权 404，前端不展示。
// 颜色与状态语义统一走 test-management/status 与 theme token，不在本页重复定义色板。
import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, App, Button, Card, Empty, Flex, Input, Modal, Select, Space, Table, Tag, theme, Typography } from 'antd';
import { EyeOutlined, FileTextOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
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
import { clearTaskCreateUncertainty, readTaskCreateUncertainty, rememberTaskCreateUncertainty } from '@/features/tasks/createUncertainty';
import { isAxiosError } from 'axios';
import { TEST_RUN_STATUS_OPTIONS } from './constants';
import type { CaseExecution, TestRun } from '@/features/test-management/contracts';
import type { RunCompareItem } from '@/features/test-management/contracts';
import { bugsApi } from '@/features/defects/api/defects';


/** 执行历史页。 */
export function ConsoleExecutionHistoryPage() {
  const { currentProjectId } = useConsoleScope();
  const { token } = theme.useToken();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [drawerRunId, setDrawerRunId] = useState<number | null>(null);
  const [selectedCe, setSelectedCe] = useState<CaseExecution | null>(null);
  const [baselineRunId, setBaselineRunId] = useState<number>();
  const [candidateRunId, setCandidateRunId] = useState<number>();
  const [comparePage, setComparePage] = useState(1);
  const [defectItem, setDefectItem] = useState<RunCompareItem | null>(null);
  const [defectMode, setDefectMode] = useState<'create' | 'existing'>('create');
  const [defectTitle, setDefectTitle] = useState('');
  const [defectDescription, setDefectDescription] = useState('');
  const [selectedBugId, setSelectedBugId] = useState<number>();
  const [bugKeyword, setBugKeyword] = useState('');
  const [defectProjectId, setDefectProjectId] = useState<number | null>(null);
  const [unknownDefectLink, setUnknownDefectLink] = useState(false);
  const defectIntent = useRef<{ fingerprint: string; requestKey: string } | null>(null);
  const comparisonDefaultsSet = useRef(false);
  const previousProjectId = useRef(currentProjectId);
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedProjectId = Number(searchParams.get('projectId'));
  const requestedExecutionId = Number(searchParams.get('caseExecutionId'));
  const { message: msg } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const currentProjectRef = useRef(currentProjectId);
  currentProjectRef.current = currentProjectId;
  const linkedExecutionQuery = useQuery({
    queryKey: ['case-executions', currentProjectId, drawerRunId],
    queryFn: () => testManagementApi.listCaseExecutions(drawerRunId!),
    enabled: drawerRunId != null && requestedExecutionId > 0 && currentProjectId != null && (!requestedProjectId || requestedProjectId === currentProjectId),
  });

  useEffect(() => {
    if (requestedExecutionId > 0 && linkedExecutionQuery.data) {
      setSelectedCe(linkedExecutionQuery.data.items.find(item => item.id === requestedExecutionId) ?? null);
    }
  }, [linkedExecutionQuery.data, requestedExecutionId]);

  useEffect(() => {
    const requestedRunId = Number(searchParams.get('runId'));
    if (Number.isInteger(requestedRunId) && requestedRunId > 0) setDrawerRunId(requestedRunId);
  }, [currentProjectId, requestedProjectId, searchParams]);

  useEffect(() => {
    if (previousProjectId.current === currentProjectId) return;
    previousProjectId.current = currentProjectId;
    setPage(1);
    setDrawerRunId(null);
    setSelectedCe(null);
    setBaselineRunId(undefined);
    setCandidateRunId(undefined);
    setComparePage(1);
    setDefectItem(null);
    setDefectProjectId(null);
    setUnknownDefectLink(false);
    setSelectedBugId(undefined);
    setBugKeyword('');
    defectIntent.current = null;
    comparisonDefaultsSet.current = false;
  }, [currentProjectId]);

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
  useEffect(() => {
    const lastPage = Math.max(1, Math.ceil((runsQuery.data?.total ?? 0) / pageSize));
    if (page > lastPage) setPage(lastPage);
  }, [page, pageSize, runsQuery.data?.total]);
  const runs = useMemo(() => (runsQuery.data?.items ?? []).filter((run) => run.project_id === currentProjectId), [currentProjectId, runsQuery.data?.items]);
  useEffect(() => {
    if (comparisonDefaultsSet.current || runs.length < 2) return;
    comparisonDefaultsSet.current = true;
    setCandidateRunId(runs[0].id);
    setBaselineRunId(runs[1].id);
  }, [runs]);
  const comparisonQuery = useQuery({
    queryKey: ['test-run-compare', currentProjectId, baselineRunId, candidateRunId, comparePage],
    queryFn: () => testManagementApi.compareRuns(baselineRunId!, candidateRunId!, { page: comparePage, page_size: 50 }),
    enabled: currentProjectId != null && baselineRunId != null && candidateRunId != null
      && baselineRunId !== candidateRunId && runs.some((run) => run.id === baselineRunId)
      && runs.some((run) => run.id === candidateRunId),
  });
  const comparisonMatchesProject = comparisonQuery.data?.project_id === currentProjectId
    && comparisonQuery.data.baseline.project_id === currentProjectId
    && comparisonQuery.data.candidate.project_id === currentProjectId;
  const comparisonSelectionValid = currentProjectId != null && baselineRunId != null && candidateRunId != null
    && runs.some((run) => run.id === baselineRunId) && runs.some((run) => run.id === candidateRunId);
  const visibleDefectItem = defectProjectId === currentProjectId ? defectItem : null;
  const activeDefectContext = useRef<{ projectId: number | null; sourceId: number | null }>({ projectId: defectProjectId, sourceId: defectItem?.candidate_execution_id ?? null });
  activeDefectContext.current = { projectId: defectProjectId, sourceId: defectItem?.candidate_execution_id ?? null };
  const bugsQuery = useQuery({
    queryKey: ['bugs', 'compare-link', currentProjectId, defectProjectId, bugKeyword],
    queryFn: () => bugsApi.list({ project_id: currentProjectId!, page: 1, page_size: 50, keyword: bugKeyword || undefined }),
    enabled: visibleDefectItem != null && defectMode === 'existing' && currentProjectId != null,
  });
  const linkDefectMutation = useMutation({
    mutationFn: (submission: { projectId: number; sourceId: number; fingerprint: string; requestKey: string; body: Parameters<typeof bugsApi.linkSource>[0] }) =>
      bugsApi.linkSource(submission.body),
    onSuccess: async (_, submission) => {
      clearTaskCreateUncertainty(submission.requestKey);
      if (defectIntent.current?.requestKey === submission.requestKey) defectIntent.current = null;
      setUnknownDefectLink(false);
      msg.success(defectMode === 'existing' ? '失败执行已关联到缺陷' : '缺陷与失败执行已关联');
      await queryClient.invalidateQueries({ queryKey: ['bugs'] });
      if (currentProjectRef.current === submission.projectId && activeDefectContext.current.projectId === submission.projectId
        && activeDefectContext.current.sourceId === submission.sourceId) {
        setDefectItem(null);
        setDefectProjectId(null);
      }
    },
    onError: (error, submission) => {
      msg.error(getErrorMessage(error, '缺陷关联失败'));
      if (!isAxiosError(error) || !error.response || error.response.status >= 500) {
        rememberTaskCreateUncertainty({ kind: 'defect', project_id: submission.projectId, request_key: submission.requestKey, recorded_at: Date.now() });
        setUnknownDefectLink(true);
      } else clearTaskCreateUncertainty(submission.requestKey);
    },
  });

  const submitDefectLink = () => {
    if (linkDefectMutation.isPending) return;
    const item = visibleDefectItem;
    const comparison = comparisonQuery.data;
    if (!item?.candidate_execution_id || currentProjectId == null || !comparisonMatchesProject || !comparison) return;
    const bodyWithoutKey: Omit<Parameters<typeof bugsApi.linkSource>[0], 'request_key'> = defectMode === 'existing'
      ? { source_type: 'CASE_EXECUTION' as const, source_id: item.candidate_execution_id, bug_id: selectedBugId }
      : {
        source_type: 'CASE_EXECUTION' as const,
        source_id: item.candidate_execution_id,
        bug: {
          project_id: currentProjectId,
          title: defectTitle.trim(),
          description: defectDescription.trim() || `运行对比发现新失败，候选执行 #${item.candidate_execution_id}。请从执行详情查看脱敏证据。`,
          severity: 2,
          status: '待确认',
          steps_to_reproduce: `测试运行 #${candidateRunId} 中用例 #${item.test_case_id} 执行失败。`,
          environment: `环境 #${comparison.candidate.environment_id ?? '未知'}`,
        },
      };
    const fingerprint = JSON.stringify({ project_id: currentProjectId, body: bodyWithoutKey });
    const retryingIntent = defectIntent.current?.fingerprint === fingerprint ? defectIntent.current : null;
    const previousUnknown = readTaskCreateUncertainty();
    if (previousUnknown && retryingIntent?.requestKey !== previousUnknown.request_key) {
      msg.warning('请先到任务列表或缺陷列表核对上一条结果未知的请求，再开始新的关联');
      return;
    }
    const intent = retryingIntent ?? { fingerprint, requestKey: `compare-defect-${crypto.randomUUID()}` };
    defectIntent.current = intent;
    rememberTaskCreateUncertainty({ kind: 'defect', project_id: currentProjectId, request_key: intent.requestKey, recorded_at: Date.now() });
    linkDefectMutation.mutate({
      projectId: currentProjectId,
      sourceId: item.candidate_execution_id,
      ...intent,
      body: { ...bodyWithoutKey, request_key: intent.requestKey },
    });
  };

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

  const runRows: TestRun[] = runs;
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

      <Card title="运行对比" size="small" style={{ marginBottom: 16 }}>
        <Flex gap={12} wrap="wrap" align="center">
          <Select
            aria-label="基准测试运行"
            value={runRows.some((run) => run.id === baselineRunId) ? baselineRunId : undefined}
            placeholder="选择基准运行"
            options={runRows.map((run) => ({ value: run.id, label: `运行 #${run.id} · ${run.status} · ${run.created_at}` }))}
            onChange={(value) => { setBaselineRunId(value); setComparePage(1); }}
            style={{ minWidth: 260 }}
          />
          <Select
            aria-label="候选测试运行"
            value={runRows.some((run) => run.id === candidateRunId) ? candidateRunId : undefined}
            placeholder="选择候选运行"
            options={runRows.map((run) => ({ value: run.id, label: `运行 #${run.id} · ${run.status} · ${run.created_at}` }))}
            onChange={(value) => { setCandidateRunId(value); setComparePage(1); }}
            style={{ minWidth: 260 }}
          />
          {comparisonQuery.isFetching && <Typography.Text type="secondary">正在比较…</Typography.Text>}
        </Flex>
        {comparisonSelectionValid && comparisonQuery.isError && <Alert style={{ marginTop: 12 }} type="error" showIcon message="运行不可比较或读取失败" description={getErrorMessage(comparisonQuery.error, '请确认两次运行在同一项目、执行类型一致且均已结束。')} action={<Button size="small" onClick={() => void comparisonQuery.refetch()}>重试</Button>} />}
        {comparisonMatchesProject && comparisonQuery.data && (
          <>
            <Space wrap style={{ marginTop: 12 }}>
              <Tag color="red">新增失败 {comparisonQuery.data.counts.new_failures}</Tag>
              <Tag color="green">已恢复 {comparisonQuery.data.counts.restored}</Tag>
              <Tag color="volcano">持续失败 {comparisonQuery.data.counts.persistent_failures}</Tag>
              <Tag>新增用例 {comparisonQuery.data.counts.added}</Tag>
              <Tag>移除用例 {comparisonQuery.data.counts.removed}</Tag>
              <Tag>无法判定 {comparisonQuery.data.counts.unresolved + comparisonQuery.data.counts.unalignable}</Tag>
              {comparisonQuery.data.environment_changed && <Tag color="gold">执行环境不同</Tag>}
            </Space>
            <Table<RunCompareItem>
              rowKey={(item) => `${item.test_case_id ?? 'none'}-${item.baseline_execution_id ?? 0}-${item.candidate_execution_id ?? 0}`}
              style={{ marginTop: 12 }}
              size="small"
              dataSource={comparisonQuery.data.items}
              pagination={{ current: comparePage, pageSize: 50, total: comparisonQuery.data.total, onChange: setComparePage, showSizeChanger: false }}
              columns={[
                { title: '用例', dataIndex: 'case_name' },
                { title: '结论', dataIndex: 'state', render: (value: RunCompareItem['state']) => <Tag color={value === 'new_failure' || value === 'persistent_failure' ? 'red' : value === 'restored' || value === 'passed' ? 'green' : 'default'}>{({ new_failure: '新增失败', restored: '已恢复', persistent_failure: '持续失败', passed: '通过', added: '新增用例', removed: '已移除', unresolved: '无法判定', unalignable: '无法对齐' } as Record<string, string>)[value]}</Tag> },
                { title: '基准', render: (_, item) => item.baseline_execution_id ? <Link to={`/console/execution-history?runId=${comparisonQuery.data?.baseline.id}&caseExecutionId=${item.baseline_execution_id}&projectId=${currentProjectId}`}>{item.baseline_status}</Link> : item.baseline_status ?? '—' },
                { title: '候选', render: (_, item) => item.candidate_execution_id ? <Link to={`/console/execution-history?runId=${comparisonQuery.data?.candidate.id}&caseExecutionId=${item.candidate_execution_id}&projectId=${currentProjectId}`}>{item.candidate_status}</Link> : item.candidate_status ?? '—' },
                { title: '耗时变化', dataIndex: 'duration_delta_ms', render: (value: number | null) => value == null ? '未知' : `${value > 0 ? '+' : ''}${value} ms` },
                { title: '说明', dataIndex: 'note', ellipsis: true },
                { title: '处理', render: (_, item) => item.state === 'new_failure' && item.candidate_execution_id ? <Button size="small" onClick={() => { setDefectProjectId(currentProjectId); setDefectItem(item); setDefectTitle(`回归新增失败：${item.case_name}`); setDefectDescription(''); setDefectMode('create'); setSelectedBugId(undefined); setUnknownDefectLink(false); defectIntent.current = null; }}>关联缺陷</Button> : '—' },
              ]}
            />
          </>
        )}
      </Card>

      {runsQuery.isLoading ? (
        <LoadingState />
      ) : runsQuery.isError ? (
        /* 接口失败必须报错：否则 500 会渲染成「暂无执行记录」，用户会以为没有执行过 */
        <ErrorState error={runsQuery.error} onRetry={runsQuery.refetch} />
      ) : runRows.length === 0 ? (
        <EmptyState description="暂无执行记录" />
      ) : (
        <Table
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={runRows}
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
        projectId={currentProjectId}
        onClose={() => { setDrawerRunId(null); setSearchParams({}); }}
        onSelect={(ce) => setSelectedCe(ce)}
      />
      <CaseExecutionDetail open={selectedCe !== null} execution={selectedCe} onClose={() => setSelectedCe(null)} />
      <Modal
        title="关联回归失败"
        open={visibleDefectItem != null}
        onCancel={() => { setDefectItem(null); setDefectProjectId(null); }}
        onOk={submitDefectLink}
        okText="确认关联"
        confirmLoading={linkDefectMutation.isPending}
        okButtonProps={{ disabled: defectMode === 'create' ? !defectTitle.trim() : !selectedBugId }}
      >
        {visibleDefectItem && <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text>候选执行 #{visibleDefectItem.candidate_execution_id} · {visibleDefectItem.case_name}。关联后保留执行来源，可在缺陷详情追溯。</Typography.Text>
          {unknownDefectLink && <Alert type="warning" showIcon message="缺陷关联结果未知" description="可以用相同内容安全重试，或先检查当前项目的缺陷列表。" action={<Button size="small" onClick={() => navigate('/console/defects')}>查看缺陷</Button>} />}
          <Select value={defectMode} options={[{ value: 'create', label: '创建新缺陷' }, { value: 'existing', label: '关联已有缺陷' }]} onChange={setDefectMode} />
          {defectMode === 'create' ? <>
            <Input value={defectTitle} onChange={(event) => setDefectTitle(event.target.value)} maxLength={200} placeholder="缺陷标题" />
            <Input.TextArea value={defectDescription} onChange={(event) => setDefectDescription(event.target.value)} maxLength={1000} rows={3} placeholder="描述（可选）；原始响应和凭据不会自动复制" />
          </> : <>
            <Input.Search value={bugKeyword} onChange={(event) => setBugKeyword(event.target.value)} placeholder="搜索当前项目缺陷" />
            <Select showSearch optionFilterProp="label" value={selectedBugId} onChange={setSelectedBugId} loading={bugsQuery.isLoading} options={(bugsQuery.data?.items ?? []).map((bug) => ({ value: bug.id, label: `#${bug.id} ${bug.title}` }))} placeholder="选择当前项目中的缺陷" style={{ width: '100%' }} />
          </>}
        </Space>}
      </Modal>
    </PageContainer>
  );
}

/** 单次运行详情抽屉：用例执行列表。 */
function RunDetailDrawer({
  runId,
  projectId,
  onClose,
  onSelect,
}: {
  runId: number | null;
  projectId: number | null;
  onClose: () => void;
  onSelect: (ce: CaseExecution) => void;
}) {
  const caseExecQuery = useQuery({
    queryKey: ['case-executions', projectId, runId],
    queryFn: () => testManagementApi.listCaseExecutions(runId!),
    enabled: runId != null && projectId != null,
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
