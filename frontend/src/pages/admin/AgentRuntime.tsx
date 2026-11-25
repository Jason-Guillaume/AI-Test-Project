import { Alert, Button, Card, Col, Collapse, List, Row, Select, Space, Statistic, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import type { AgentRuntimeOverview } from '@/features/agent-governance/contracts';
import { projectsApi } from '@/features/projects/api/projects';
import { collectPages } from '@/shared/api/pagination';
import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';

const percent = (value: number | null) => value == null ? '未知' : `${(value * 100).toFixed(1)}%`;
const millis = (value: number | null) => value == null ? '未知' : `${Math.round(value).toLocaleString()} ms`;
const cost = (value: number | null) => value == null ? '未配置计价' : value.toFixed(6);

export function AdminAgentRuntimePage() {
  const [days, setDays] = useState(30);
  const [projectId, setProjectId] = useState<number>();
  const [cutoff, setCutoff] = useState(() => Date.now());
  const end = dayjs(cutoff);
  const projects = useQuery({ queryKey: ['projects', 'runtime-quality'],
    queryFn: () => collectPages((page) => projectsApi.list({ page, page_size: 200 })) });
  const projectName = projects.data?.items.find((project) => project.id === projectId)?.name;
  const overview = useQuery({
    queryKey: ['agent-runtime', days, projectId, cutoff],
    queryFn: () => agentGovernanceApi.runtimeOverview({ from_at: end.subtract(days * 24, 'hour').toISOString(),
      to_at: end.toISOString(), project_id: projectId }),
  });
  const refresh = () => {
    const next = Date.now();
    if (next === cutoff) void overview.refetch();
    else setCutoff(next);
  };
  return <PageContainer><PageHeader title="Agent 运行质量" subtitle={`统计范围 · ${projectName ?? (projectId ? `项目 #${projectId}` : '全部项目')}`} />
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card size="small">
        <Space wrap>
          <Select aria-label="统计窗口" value={days} onChange={(value) => { setDays(value); setCutoff(Date.now()); }} options={[
            { value: 7, label: '最近 7 天' }, { value: 30, label: '最近 30 天' }, { value: 90, label: '最近 90 天' },
          ]} style={{ width: 140 }} />
          <Select aria-label="运行项目" allowClear showSearch optionFilterProp="label" placeholder="全部项目"
            style={{ width: 250, maxWidth: '100%' }} value={projectId} loading={projects.isFetching}
            options={projects.data?.items.map((project) => ({ value: project.id, label: project.name }))}
            onChange={(value) => { setProjectId(value); setCutoff(Date.now()); }} />
          <Button loading={overview.isFetching} onClick={refresh}>刷新统计</Button>
          <Tag color="blue">统计截止 {end.format('YYYY-MM-DD HH:mm:ss')}</Tag>
        </Space>
        {projects.isError && <Alert type="error" message="项目列表加载失败" action={<Button onClick={() => projects.refetch()}>重试</Button>} />}
      </Card>
      {overview.isPending ? <LoadingState /> : overview.isError ? <ErrorState error={overview.error} onRetry={refresh} /> : <RuntimeReport data={overview.data} />}
    </Space>
  </PageContainer>;
}

function RuntimeReport({ data }: { data: AgentRuntimeOverview }) {
  const s = data.summary;

  const providerColumns: ColumnsType<AgentRuntimeOverview['providers'][number]> = [
    { title: '供应商', dataIndex: 'provider', key: 'provider' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (value: string) => <Tag color={value === 'HEALTHY' ? 'green' : value === 'DEGRADED' ? 'orange' : value === 'UNHEALTHY' || value === 'DISABLED' ? 'red' : 'default'}>{value}</Tag> },
    { title: '已知终态成功率', key: 'success_rate', render: (_, row) => percent(row.success_rate) },
    { title: '调用', dataIndex: 'calls', key: 'calls' },
    { title: '失败', dataIndex: 'failed', key: 'failed' },
    { title: '未知', dataIndex: 'unknown_calls', key: 'unknown_calls' },
    { title: 'Token', dataIndex: 'tokens', key: 'tokens', render: (value: number) => value.toLocaleString() },
    { title: '启用配置', dataIndex: 'enabled_configs', key: 'enabled_configs' },
    { title: '已计价成本', key: 'cost', render: (_, row) => row.cost_by_currency.length ? row.cost_by_currency.map((item) => `${item.amount.toFixed(6)} ${item.currency}`).join('、') : '未配置计价' },
  ];
  const agentColumns: ColumnsType<AgentRuntimeOverview['agents_by_revision'][number]> = [
    { title: 'Agent', dataIndex: 'agent_name', key: 'agent_name' },
    { title: 'Revision ID', dataIndex: 'revision_id', key: 'revision_id', render: (value: number | null) => value ?? '—' },
    { title: '模型调用', dataIndex: 'calls', key: 'calls' },
    { title: '失败', dataIndex: 'failed', key: 'failed' },
    { title: 'Token', dataIndex: 'tokens', key: 'tokens', render: (value: number) => value.toLocaleString() },
    { title: '成本', key: 'cost', render: (_, row) => row.cost == null ? cost(null) : `${row.cost.toFixed(6)} ${row.cost_currency ?? ''}` },
    { title: '平均延迟', dataIndex: 'avg_latency_ms', key: 'avg_latency_ms', render: (value: number | null) => millis(value) },
  ];
  const modelColumns: ColumnsType<AgentRuntimeOverview['models'][number]> = [
    { title: '模型', dataIndex: 'model_name', key: 'model_name' },
    { title: '配置 ID', dataIndex: 'model_config_id', key: 'model_config_id', render: (value: number | null) => value ?? '—' },
    { title: '版本', dataIndex: 'model_revision', key: 'model_revision', render: (value: string | null) => value ?? '—' },
    { title: '调用', dataIndex: 'calls', key: 'calls' },
    { title: '成功率（已知终态）', dataIndex: 'success_rate', key: 'success_rate', render: (value: number | null, row) => <>{percent(value)} <Typography.Text type="secondary">{row.succeeded}/{row.known_calls}</Typography.Text></> },
    { title: '未知状态', dataIndex: 'unknown_calls', key: 'unknown_calls' },
    { title: 'Token', dataIndex: 'tokens', key: 'tokens', render: (value: number) => value.toLocaleString() },
    { title: '成本', key: 'cost', render: (_, row) => row.cost == null ? cost(null) : `${row.cost.toFixed(6)} ${row.cost_currency ?? ''}` },
    { title: '平均延迟', dataIndex: 'avg_latency_ms', key: 'avg_latency_ms', render: (value: number | null) => millis(value) },
    { title: 'P50', dataIndex: 'p50_latency_ms', key: 'p50_latency_ms', render: (value: number | null, row) => <>{millis(value)} <Typography.Text type="secondary">n={row.latency_sample_count}</Typography.Text></> },
    { title: 'P95', dataIndex: 'p95_latency_ms', key: 'p95_latency_ms', render: (value: number | null) => millis(value) },
  ];
  const toolColumns: ColumnsType<AgentRuntimeOverview['tools'][number]> = [
    { title: '工具', dataIndex: 'tool_key', key: 'tool_key' },
    { title: '调用', dataIndex: 'calls', key: 'calls' },
    { title: '成功', dataIndex: 'succeeded', key: 'succeeded' },
    { title: '执行失败', dataIndex: 'failed', key: 'failed' },
    { title: '治理拒绝', dataIndex: 'rejected', key: 'rejected', render: (value) => value ?? '未知' },
    { title: '平均延迟', dataIndex: 'avg_latency_ms', key: 'avg_latency_ms', render: (value: number | null) => millis(value) },
  ];
  const skillColumns: ColumnsType<AgentRuntimeOverview['skills'][number]> = [
    { title: 'Skill', dataIndex: 'skill_key', key: 'skill_key' },
    { title: 'Revision', dataIndex: 'skill_version', key: 'skill_version', render: (value: number | null) => value ?? '—' },
    { title: '装载', dataIndex: 'loads', key: 'loads' },
    { title: '成功', dataIndex: 'succeeded', key: 'succeeded' },
    { title: '失败', dataIndex: 'failed', key: 'failed' },
    { title: '平均耗时', dataIndex: 'avg_latency_ms', key: 'avg_latency_ms', render: (value: number | null) => millis(value) },
  ];

  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    <Card title="异常运行" size="small">
      <List size="small" dataSource={data.recent_issues ?? []} locale={{ emptyText: data.recent_issues ? '当前范围暂无异常运行' : '异常运行明细未知' }}
        renderItem={(row) => {
          const params = new URLSearchParams({ runId: String(row.run_id), tab: 'events' });
          if (row.event) params.set('eventId', String(row.event.id));
          return <List.Item key={row.run_id}><Space direction="vertical" style={{ overflowWrap: 'anywhere' }}>
            <Space wrap><Typography.Text strong>{row.title}</Typography.Text><Tag color="red">{row.status}</Tag></Space>
            <Typography.Text type="secondary">{row.project_name} · 运行 #{row.run_id} · {row.error_code ?? '错误码未知'}</Typography.Text>
            <Link to={`/console/tasks/${row.task_id}?${params}`}>
              {row.event ? `定位事件 · ${row.event.name} · ${row.event.error_code ?? row.event.status}` : '查看运行记录'}
            </Link>
          </Space></List.Item>;
        }} />
    </Card>

    <Alert type="info" showIcon message={`指标按真实运行事实统计（口径 ${data.metric_definition_version}）；没有价格快照的模型调用不会推算成本。`} description={`模型用量已知 ${s.known_usage_calls} / ${s.model_calls} 次；有价格 ${s.priced_model_calls} / ${s.model_calls} 次。数据水位：任务 ${data.data_watermark.task_runs ? dayjs(data.data_watermark.task_runs).format('MM-DD HH:mm:ss') : '暂无'}，模型 ${data.data_watermark.model_calls ? dayjs(data.data_watermark.model_calls).format('MM-DD HH:mm:ss') : '暂无'}，运行事件 ${data.data_watermark.runtime_events ? dayjs(data.data_watermark.runtime_events).format('MM-DD HH:mm:ss') : '暂无'}。${s.cost_by_currency.length ? ` 已计价成本：${s.cost_by_currency.map((item) => `${item.amount.toFixed(6)} ${item.currency ?? '未注明币种'}`).join('、')}` : ''}`} />
    {data.anomalies.length > 0 && <Alert type="warning" showIcon message={`发现 ${data.anomalies.length} 项运行指标变化`} description={<Space direction="vertical" size={2}>{data.anomalies.map((item, index) => <Typography.Text key={`${item.kind}-${item.model_name ?? item.tool_key ?? item.skill_key ?? item.agent_name ?? index}`}>{item.kind}{item.model_name ? ` · ${item.model_name}` : ''}{item.tool_key ? ` · ${item.tool_key}` : ''}{item.skill_key ? ` · ${item.skill_key} v${item.skill_version ?? '未知'}` : ''}{item.agent_name ? ` · ${item.agent_name} Revision ${item.revision_id ?? '未知'}` : ''}：当前 {item.current}{item.currency ? ` ${item.currency}` : ''}，基线 {item.baseline}{item.currency ? ` ${item.currency}` : ''}（样本 {item.current_samples}/{item.baseline_samples}）</Typography.Text>)}</Space>} />}

    <Row gutter={[12, 12]}>
      <Col xs={12} md={6}><Card><Statistic title="任务运行" value={s.task_runs} suffix={<Typography.Text type="secondary">{s.terminal_runs} 次已终态</Typography.Text>} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="成功率" value={percent(s.success_rate)} suffix={<Typography.Text type="secondary">{s.successful_runs}/{s.terminal_runs}</Typography.Text>} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="失败率" value={percent(s.failure_rate)} valueStyle={{ color: s.failure_rate && s.failure_rate > 0.1 ? '#cf1322' : undefined }} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="取消率" value={percent(s.cancellation_rate)} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="执行成功率（不含取消）" value={percent(s.execution_success_rate)} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="问题完成率" value={percent(s.partial_completion_rate)} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="待核对运行" value={s.reconciliation_required_runs} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="未终态运行" value={s.nonterminal_runs} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="平均耗时" value={millis(s.average_duration_ms)} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="P95 耗时" value={millis(s.p95_duration_ms)} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="重试工作项" value={`${s.retried_work_items} / ${s.started_work_items}`} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="子 Agent 失败率" value={percent(s.subagent_failure_rate)} suffix={<Typography.Text type="secondary">{s.subagent_failed_instances}/{s.subagent_terminal_instances} 个终态实例</Typography.Text>} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="模型调用" value={s.model_calls} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="模型成功率" value={percent(s.model_success_rate)} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="模型平均延迟" value={millis(s.average_model_latency_ms)} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="模型 P50 / P95" value={`${millis(s.p50_model_latency_ms)} / ${millis(s.p95_model_latency_ms)}`} suffix={<Typography.Text type="secondary">{s.model_latency_sample_count} 个有效样本</Typography.Text>} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="Skill 装载成功率" value={percent(s.skill_load_success_rate)} suffix={<Typography.Text type="secondary">{s.skill_loads} 次</Typography.Text>} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="Token" value={s.model_tokens.toLocaleString()} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="模型成本" value={s.cost_amount == null ? (s.cost_by_currency.length ? '多币种' : '未配置计价') : `${s.cost_amount.toFixed(6)} ${s.cost_currency ?? ''}`} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="人工拒绝率（用例草稿）" value={percent(s.manual_rejection_rate)} suffix={<Typography.Text type="secondary">{s.manual_reviewed_drafts} 份已审核</Typography.Text>} /></Card></Col>
      <Col xs={12} md={6}><Card><Statistic title="人工修改率（用例草稿）" value={percent(s.manual_edit_rate)} /></Card></Col>
    </Row>

    <Card title="Agent 修订运行统计" size="small">
      <Table rowKey={(row) => `${row.agent_definition_id ?? 'deleted'}-${row.revision_id ?? 'unknown'}-${row.cost_currency ?? 'none'}`} size="small" columns={agentColumns} dataSource={data.agents_by_revision} pagination={{ pageSize: 8 }} scroll={{ x: 850 }} />
    </Card>
    <Card className="wrapping-card-heading" title="供应商健康与成本" size="small" extra={<Typography.Text type="secondary">健康状态来自已终态调用；成本按币种分开。</Typography.Text>}>
      <Table rowKey="provider" size="small" columns={providerColumns} dataSource={data.providers} pagination={{ pageSize: 8 }} scroll={{ x: 980 }} />
    </Card>
    <Card title="模型调用统计" size="small">
      <Table rowKey={(row) => `${row.model_config_id ?? 'deleted'}-${row.model_name}-${row.model_revision ?? 'unknown'}-${row.cost_currency ?? 'none'}`} size="small" columns={modelColumns} dataSource={data.models} pagination={{ pageSize: 8 }} scroll={{ x: 1150 }} />
    </Card>
    <Card className="wrapping-card-heading" title="工具调用统计" size="small" extra={<Typography.Text type="secondary">Trace 索引覆盖 {s.traced_tool_calls} 次；持久化业务工具回执 {s.durable_tool_invocations} 次。</Typography.Text>}>
      <Table rowKey="tool_key" size="small" columns={toolColumns} dataSource={data.tools} pagination={{ pageSize: 8 }} scroll={{ x: 720 }} />
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>工具执行成功率 {percent(s.traced_tool_success_rate)} · 治理拒绝 {s.traced_tool_rejections ?? '未知'} · 检索 {s.knowledge_retrievals} 次 · 权限检查 {s.knowledge_permission_checks ?? '未知'} 次 · 上下文装配 {s.context_assemblies} 次</Typography.Paragraph>
    </Card>
    <Card className="wrapping-card-heading" title="Skill 装载统计" size="small" extra={<Typography.Text type="secondary">{s.skill_load_failures} 次装载失败</Typography.Text>}>
      <Table rowKey={(row) => `${row.skill_key}-${row.skill_version ?? 'unknown'}`} size="small" columns={skillColumns} dataSource={data.skills} pagination={{ pageSize: 8 }} scroll={{ x: 540 }} />
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>此处统计 Skill 文件装载与渲染状态，不代表 Skill 输出的业务正确率。</Typography.Paragraph>
    </Card>
    <Typography.Text type="secondary">人工拒绝率和修改率只基于已有用例草稿审核记录统计，不代表其他 Agent 类型的反馈，也不构成准确率。</Typography.Text>
    <Collapse items={[{ key: 'definitions', label: '统计口径与数据来源', children: <ul>{Object.entries(data.definitions).map(([key, value]) => <li key={key}><strong>{key}：</strong>{value}</li>)}</ul> }]} />
  </Space>;
}
