// 参数实验页：候选值与基线版本隔离，复跑创建独立的夜间三方任务。
import { App, Button, Card, Empty, Space, Table, Tag, Typography } from 'antd';
import { PlayCircleOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import type { AsrExperiment } from '@/features/asr-evaluation/contracts';
import { AsrFrame } from './AsrFrame';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { getErrorMessage } from '@/shared/api/client';

/** 显示候选实验真实生命周期，不将草稿描述成运行结果。 */
function experimentStatus(status: string) {
  const labels: Record<string, [string, string]> = {
    DRAFT: ['待复跑', 'default'], RUNNING: ['复跑中', 'processing'],
    COMPLETED: ['已完成', 'success'], FAILED: ['复跑失败', 'error'],
  };
  const [label, color] = labels[status] ?? [status, 'default'];
  return <Tag color={color}>{label}</Tag>;
}

/** 查看候选参数版本，显式启动新的三方复跑。 */
export function ExperimentsPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const key = currentProjectId ? asrQueryKeys.project(currentProjectId, 'experiments') : ['asr', 'experiments', null];
  const experimentsQuery = useQuery({
    queryKey: key, enabled: Boolean(currentProjectId),
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
    { title: '对比版本', dataIndex: 'comparison_id', key: 'comparison_id', render: (value: number) => <a onClick={() => navigate(`/console/asr/comparisons/${value}`)}>对比 #{value}</a> },
    { title: '基线参数版本', dataIndex: 'baseline_parameter_set_id', key: 'baseline_parameter_set_id', render: (value: number) => `参数方案 #${value}` },
    { title: '修改说明', dataIndex: 'change_summary', key: 'change_summary' },
    { title: '候选参数', key: 'candidate_parameters', render: (_: unknown, row: AsrExperiment) => <Typography.Text code>{JSON.stringify(row.candidate_parameters)}</Typography.Text> },
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
  if (!currentProjectId) return <AsrFrame title="参数对比"><Empty description="先选择项目" /></AsrFrame>;
  if (experimentsQuery.isPending) return <AsrFrame title="参数对比"><LoadingState /></AsrFrame>;
  if (experimentsQuery.isError) return <AsrFrame title="参数对比"><ErrorState error={experimentsQuery.error} onRetry={experimentsQuery.refetch} /></AsrFrame>;
  return (
    <AsrFrame title="参数对比">
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Typography.Paragraph type="secondary">
          候选参数保存在独立版本。默认重新请求三家模型；创建候选时可明确选择复用当前对比中两条成功且平台音频资源版本未变的参考结果，来源写入任务快照。同一 URL 不证明远端内容未替换，请先确认内容相同。两家参考输出始终不是标准答案。
        </Typography.Paragraph>
        {(experimentsQuery.data ?? []).length === 0
          ? <Empty description="尚无候选实验。请在识别对比页创建已定义参数的候选版本。" />
          : <Table<AsrExperiment> rowKey="id" columns={columns} dataSource={experimentsQuery.data ?? []} pagination={{ pageSize: 10 }} scroll={{ x: 1200 }} />}
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
