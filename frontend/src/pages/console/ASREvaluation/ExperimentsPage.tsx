// 参数实验页：候选值与基线版本隔离，复跑创建独立的夜间三方任务。
import { Alert, App, Button, Card, Descriptions, Empty, Space, Table, Tag, Typography } from 'antd';
import { PlayCircleOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import type { AsrComparison, AsrExperiment, AsrJob, JsonValue } from '@/features/asr-evaluation/contracts';
import { AsrFrame } from './AsrFrame';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { getErrorMessage } from '@/shared/api/client';
import { ContentReviewPanel } from './ContentReviewPanel';
import { experimentStatusLabel, parameterChangeSummary, parameterDiffs } from '@/features/asr-evaluation/experimentPresentation.mjs';

/** 显示候选实验真实生命周期，不将草稿描述成运行结果。 */
function experimentStatus(status: string) {
  const labels: Record<string, [string, string]> = {
    DRAFT: ['待复跑', 'default'], PENDING: ['等待提交', 'default'], QUEUED: ['排队中', 'processing'],
    SUBMITTING: ['提交中', 'processing'], RUNNING: ['复跑中', 'processing'], REMOTE_RUNNING: ['远端处理中', 'processing'],
    SUCCEEDED: ['已完成', 'success'], COMPLETED: ['已完成', 'success'], PARTIAL_FAILED: ['部分失败', 'warning'],
    FAILED: ['失败', 'error'], CANCELLED: ['已取消', 'default'], RECONCILIATION_REQUIRED: ['状态待核实', 'warning'],
  };
  const [, color] = labels[status] ?? [status, 'default'];
  const label = experimentStatusLabel(status);
  return <Tag color={color}>{label}</Tag>;
}

function valueLabel(value: JsonValue | undefined): string {
  return value === undefined ? '未配置' : JSON.stringify(value);
}

/** 同屏呈现基线和候选的真实待测运行，不推导准确率或提升结论。 */
function ExperimentReadout({ experiment }: { experiment: AsrExperiment }) {
  const baselineQuery = useQuery<AsrComparison>({
    queryKey: ['asr', 'experiment-baseline-readout', experiment.comparison_id],
    queryFn: ({ signal }) => asrEvaluationApi.getComparison(experiment.comparison_id, signal),
  });
  const candidateJobQuery = useQuery<AsrJob>({
    queryKey: ['asr', 'experiment-candidate-readout', experiment.candidate_job_id],
    enabled: Boolean(experiment.candidate_job_id),
    refetchInterval: (query) => ['QUEUED', 'RUNNING'].includes(query.state.data?.status ?? '') ? 3000 : false,
    queryFn: ({ signal }) => asrEvaluationApi.getJob(experiment.candidate_job_id!, { signal }),
  });
  const candidateComparisonId = candidateJobQuery.data?.comparisons?.[0]?.id;
  const candidateComparisonQuery = useQuery<AsrComparison>({
    queryKey: ['asr', 'experiment-candidate-comparison', candidateComparisonId],
    enabled: Boolean(candidateComparisonId),
    queryFn: ({ signal }) => asrEvaluationApi.getComparison(candidateComparisonId!, signal),
  });
  const baseline = baselineQuery.data?.models.find((item) => item.role === 'TEST');
  const candidate = candidateJobQuery.data?.runs?.find((item) => item.role === 'TEST');
  return <div className="asr-experiment-readout-grid">
    <Card size="small" title="基线 · 待测模型">
      {baselineQuery.isError ? <Typography.Text type="danger">基线读取失败</Typography.Text> : baselineQuery.isPending ? '正在读取…' : <>
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="状态">{experimentStatus(baseline?.status ?? 'UNKNOWN')}</Descriptions.Item>
          <Descriptions.Item label="模型">{baseline?.name ?? '未报告'}</Descriptions.Item>
          <Descriptions.Item label="处理耗时">{baseline?.duration_ms == null ? '未报告' : `${baseline.duration_ms} 毫秒`}</Descriptions.Item>
          <Descriptions.Item label="人工复核">{baselineQuery.data?.summary.reviewed_blocks ?? 0} 块已确认 · {baselineQuery.data?.summary.unresolved_blocks ?? 0} 块未解决</Descriptions.Item>
        </Descriptions>
        <Typography.Paragraph className="asr-experiment-transcript">{baseline?.transcript || '基线暂无可显示的转写文本'}</Typography.Paragraph>
      </>}
    </Card>
    <Card size="small" title="候选 · 待测模型">
      {!experiment.candidate_job_id ? <Typography.Text type="secondary">候选尚未复跑</Typography.Text>
        : candidateJobQuery.isError ? <Typography.Text type="danger">候选任务读取失败</Typography.Text>
          : candidateJobQuery.isPending ? '正在读取…' : <>
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="状态">{experimentStatus(candidate?.status ?? candidateJobQuery.data.status)}</Descriptions.Item>
              <Descriptions.Item label="模型">{candidate?.model_id ?? '未报告'}</Descriptions.Item>
              <Descriptions.Item label="处理耗时">{candidate?.duration_ms == null ? '未报告' : `${candidate.duration_ms} 毫秒`}</Descriptions.Item>
              <Descriptions.Item label="人工复核">{candidateComparisonQuery.data
                ? `${candidateComparisonQuery.data.summary.reviewed_blocks} 块已确认 · ${candidateComparisonQuery.data.summary.unresolved_blocks} 块未解决`
                : candidateComparisonQuery.isError
                  ? <Space><Typography.Text type="danger">候选对比读取失败</Typography.Text><Button size="small" onClick={() => void candidateComparisonQuery.refetch()}>重试读取</Button></Space>
                  : candidateComparisonId ? '正在读取候选对比…'
                    : ['COMPLETED', 'PARTIAL_FAILED'].includes(candidateJobQuery.data.status)
                      ? '候选任务完成，但没有生成可比对结果' : '等待候选识别完成后生成对比'}</Descriptions.Item>
            </Descriptions>
            <Typography.Paragraph className="asr-experiment-transcript">{candidate?.transcript || '候选尚未返回转写文本'}</Typography.Paragraph>
          </>}
    </Card>
  </div>;
}

/** 查看候选参数版本，显式启动新的三方复跑。 */
export function ExperimentsPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const key = currentProjectId ? asrQueryKeys.project(currentProjectId, 'experiments') : ['asr', 'experiments', null];
  const experimentsQuery = useQuery<AsrExperiment[]>({
    queryKey: key, enabled: Boolean(currentProjectId),
    refetchInterval: (query) => query.state.data?.some((row) => ['QUEUED', 'RUNNING'].includes(row.candidate_job_status ?? '')) ? 3000 : false,
    queryFn: async ({ signal }) => (await asrEvaluationApi.listExperiments(currentProjectId!, signal)).items,
  });
  const runMutation = useMutation({
    mutationFn: (id: number) => asrEvaluationApi.runExperiment(id),
    onSuccess: (data) => {
      message.success(`已创建三方候选复跑任务 ASR-${data.job.id}`);
      void queryClient.invalidateQueries({ queryKey: key });
      navigate(`/console/asr/jobs/${data.job.id}`);
    },
    onError: (error) => message.error(getErrorMessage(error, '候选复跑启动失败；候选和原基线均保留，可修正原因后重试。')),
  });
  const columns = [
    { title: '实验', dataIndex: 'id', key: 'id', render: (value: number) => `EXP-${value}` },
    { title: '音频 / 基线对比', key: 'baseline', render: (_: unknown, row: AsrExperiment) => <Space direction="vertical" size={0}>
      <Typography.Text ellipsis style={{ maxWidth: 220 }}>{row.audio_name ?? '音频名称未报告'}</Typography.Text>
      <a onClick={() => navigate(`/console/asr/comparisons/${row.comparison_id}`)}>对比 #{row.comparison_id}</a>
    </Space> },
    { title: '修改说明', dataIndex: 'change_summary', key: 'change_summary' },
    { title: '变更参数', key: 'candidate_parameters', render: (_: unknown, row: AsrExperiment) => {
      return parameterChangeSummary(row.baseline_parameters, row.candidate_parameters);
    } },
    { title: '参考结果', key: 'reference_reuse', render: (_: unknown, row: AsrExperiment) => row.reuse_reference_results
      ? `复用对比 #${row.reference_source_comparison_id}` : '重新请求' },
    { title: '状态', dataIndex: 'status', key: 'status', render: experimentStatus },
    { title: '最近失败原因', dataIndex: 'failure_reason', key: 'failure_reason', render: (value: string | null) => value || '—' },
    { title: '候选任务', dataIndex: 'candidate_job_id', key: 'candidate_job_id', render: (value: number | null) => value ? <a onClick={() => navigate(`/console/asr/jobs/${value}`)}>ASR-{value}</a> : '尚未复跑' },
    { title: '操作', key: 'action', render: (_: unknown, row: AsrExperiment) => <Button
      size="small" type="primary" icon={<PlayCircleOutlined />} disabled={!['DRAFT', 'FAILED'].includes(row.status)}
      loading={runMutation.isPending && runMutation.variables === row.id}
      onClick={() => runMutation.mutate(row.id)}
    >{row.status === 'FAILED' ? '重试三方复跑' : '启动三方复跑'}</Button> },
  ];
  if (!currentProjectId) return <AsrFrame title="参数实验"><Empty description="先选择项目" /></AsrFrame>;
  if (experimentsQuery.isPending) return <AsrFrame title="参数实验"><LoadingState /></AsrFrame>;
  if (experimentsQuery.isError) return <AsrFrame title="参数实验"><ErrorState error={experimentsQuery.error} onRetry={experimentsQuery.refetch} /></AsrFrame>;
  return (
    <AsrFrame title="参数实验">
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Typography.Paragraph type="secondary">
          候选参数保存在独立版本。默认重新请求三家模型；创建候选时可明确选择复用当前对比中两条成功且平台音频资源版本未变的参考结果，来源写入任务快照。同一 URL 不证明远端内容未替换，请先确认内容相同。两家参考输出始终不是标准答案。
        </Typography.Paragraph>
        {(experimentsQuery.data ?? []).length === 0
          ? <Empty description="尚无候选实验。请在识别对比页创建已定义参数的候选版本。" />
          : <Table<AsrExperiment> rowKey="id" columns={columns} dataSource={experimentsQuery.data ?? []} pagination={{ pageSize: 10 }} scroll={{ x: 1100 }}
              expandable={{ expandedRowRender: (row) => {
                const diffs = parameterDiffs(row.baseline_parameters, row.candidate_parameters);
                const sameAudio = row.baseline_audio_content_version != null && row.candidate_audio_content_version != null
                  && row.baseline_audio_content_version === row.candidate_audio_content_version;
                const comparableAudio = row.baseline_audio_content_version != null && row.candidate_audio_content_version != null;
                return <Space direction="vertical" style={{ display: 'flex' }}>
                  <Card size="small" title={`实验 EXP-${row.id} · ${row.change_summary}`}>
                    <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }}>
                      <Descriptions.Item label="基线">{row.baseline_parameter_name ?? `参数方案 #${row.baseline_parameter_set_id}`} · v{row.baseline_parameter_version ?? '未报告'}</Descriptions.Item>
                      <Descriptions.Item label="音频">{row.audio_name ?? '未报告'}</Descriptions.Item>
                      <Descriptions.Item label="基线音频版本">{row.baseline_audio_content_version == null ? '未报告' : `v${row.baseline_audio_content_version}`}</Descriptions.Item>
                      <Descriptions.Item label="候选音频版本">{row.candidate_audio_content_version == null ? '未报告' : `v${row.candidate_audio_content_version}`}</Descriptions.Item>
                      <Descriptions.Item label="参考结果">{row.reuse_reference_results ? `复用对比 #${row.reference_source_comparison_id}` : '重新请求'}</Descriptions.Item>
                      <Descriptions.Item label="候选任务状态">{row.candidate_job_status ? experimentStatus(row.candidate_job_status) : '尚未复跑'}</Descriptions.Item>
                    </Descriptions>
                    {comparableAudio && !sameAudio && <Typography.Paragraph type="warning">前后音频版本不同，结果变化不能单独归因于参数。</Typography.Paragraph>}
                    {row.status === 'RECONCILIATION_REQUIRED' && <Alert type="warning" showIcon message="候选请求状态待核实，已暂停自动复跑"
                      description={<Space direction="vertical"><span>{row.reconciliation_reason || '远端提交结果尚未核实，系统不会自动重发。'}</span>
                        <span>{row.reconciliation_action || '打开候选任务核对远端状态，再人工决定后续操作。'}</span>
                        {row.candidate_job_id && <a onClick={() => navigate(`/console/asr/jobs/${row.candidate_job_id}`)}>打开候选任务 ASR-{row.candidate_job_id}</a>}</Space>} />}
                    <Typography.Text strong>参数变化</Typography.Text>
                    {row.baseline_parameters == null
                      ? <Typography.Paragraph type="secondary">缺少基线参数快照，无法比较候选前后值。</Typography.Paragraph>
                      : diffs.length ? <Table size="small" rowKey="path" pagination={false} dataSource={diffs} columns={[
                      { title: '参数路径', dataIndex: 'path', key: 'path' },
                      { title: '基线值', key: 'baseline', render: (_: unknown, item: typeof diffs[number]) => <Typography.Text code>{valueLabel(item.baseline)}</Typography.Text> },
                      { title: '候选值', key: 'candidate', render: (_: unknown, item: typeof diffs[number]) => <Typography.Text code>{valueLabel(item.candidate)}</Typography.Text> },
                    ]} /> : <Typography.Paragraph type="secondary">候选参数与记录的基线参数相同，没有参数差异。</Typography.Paragraph>}
                    <Typography.Text type="secondary">前后转写、处理耗时和人工复核状态并列展示；这些差异本身不构成准确率或效果提升结论。</Typography.Text>
                    <ExperimentReadout experiment={row} />
                    <Space wrap>
                      <a onClick={() => navigate(`/console/asr/comparisons/${row.comparison_id}`)}>查看基线对比</a>
                      {row.candidate_job_id && <a onClick={() => navigate(`/console/asr/jobs/${row.candidate_job_id}`)}>查看候选任务与结果</a>}
                    </Space>
                    {row.failure_reason && <Typography.Paragraph type="danger">{row.failure_reason}</Typography.Paragraph>}
                  </Card>
                  <ContentReviewPanel kind="experiments" resourceId={row.id} projectId={row.project_id} />
                </Space>;
              } }} />}
        <Card size="small" className="asr-model-card">
          <Typography.Text strong>结果解释</Typography.Text>
          <Typography.Paragraph className="asr-muted-note">
            复跑前后仍按人工校对片段、文本差异、长段输出与耗时逐项核验。两家云端参考文本的一致程度不是正确性依据。
          </Typography.Paragraph>
        </Card>
      </Space>
    </AsrFrame>
  );
}
