// 统一任务列表与任务执行台；会话、方案和产物均从后端持久化状态恢复。
import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Empty,
  Flex,
  Input,
  List,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CheckOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import type { TableColumnsType } from 'antd';
import { getErrorMessage } from '@/api/client';
import {
  tasksApi,
  type Task,
  type TaskAgentInstance,
  type TaskEvent,
  type TaskCommandRequest,
  type TaskMessage,
  type TaskResourceRef,
  type TaskToolInvocation,
  type TaskWorkItem,
} from '@/api/tasks';
import { TaskCreateModal } from '@/components/tasks/TaskCreateModal';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { fmtTime } from '@/shared/format';
import { useConsoleScope } from '@/hooks/useConsoleScope';

const STATUS_LABEL: Record<string, string> = {
  QUEUED: '排队中', RUNNING: '运行中', WAITING_CONFIRMATION: '待确认',
  READY: '就绪', WAITING_APPROVAL: '待确认', WAITING_DEPENDENCY: '等待前置节点',
  PAUSE_REQUESTED: '暂停中', PAUSED: '已暂停', CANCEL_REQUESTED: '取消中',
  WAITING_EXTERNAL: '等待外部处理',
  SUCCEEDED: '已完成', SUCCEEDED_WITH_ISSUES: '完成但有问题', FAILED: '失败',
  CANCELLED: '已取消', SUPERSEDED: '已被新目标替代', RECONCILIATION_REQUIRED: '待核对',
};
const STAGE_LABEL: Record<string, string> = {
  MODEL_RETRY: '模型重试中', WAITING_MODEL: '等待修复模型配置',
  SECURITY_EXECUTION: '安全变异执行中',
};
const EVENT_LABEL: Record<string, string> = {
  'llm.primary_succeeded': '主模型调用成功',
  'llm.fallback_succeeded': '备用模型接手成功',
  'llm.retry_scheduled': '模型路由失败，已安排自动重试',
  'llm.fallback_exhausted': '模型路由耗尽，任务等待配置修复',
};
const ROLE_LABEL: Record<string, string> = {
  MAIN: '任务主 Agent', PLANNER: 'Planner', API_WORKER: 'API Worker',
  UI_WORKER: 'UI Worker', SECURITY_WORKER: '安全 Worker', REVIEWER: '审阅 Agent',
  REPORT_AGENT: '报告 Agent', SUB_AGENT: '子 Agent',
};
const TOOL_CALL_STATUS: Record<string, string> = {
  STARTED: '调用中', SUCCEEDED: '成功', FAILED: '失败', CANCELLED: '未调用', NEEDS_RECONCILIATION: '待核对',
};
const TERMINAL = new Set(['SUCCEEDED', 'SUCCEEDED_WITH_ISSUES', 'FAILED', 'CANCELLED', 'SUPERSEDED']);
const STOP_POLLING = new Set([...TERMINAL, 'RECONCILIATION_REQUIRED', 'PAUSED']);

/** 展示用户有权查看的任务与最近一次持久化运行。 */
export function ConsoleTasksPage() {
  const { currentProjectId } = useConsoleScope();
  const [createOpen, setCreateOpen] = useState(false);
  const [taskPage, setTaskPage] = useState(1);
  const [taskPageSize, setTaskPageSize] = useState(20);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialProjectId = Number(searchParams.get('projectId')) || undefined;
  const initialCaseId = Number(searchParams.get('caseId')) || undefined;
  const requestedType = searchParams.get('type');
  const initialTargetType = requestedType === 'WEB' || requestedType === 'SECURITY' || requestedType === 'WEB_AUTHORING' ? requestedType : 'API';
  useEffect(() => {
    if (searchParams.get('create') === '1') setCreateOpen(true);
  }, [searchParams]);
  useEffect(() => { setTaskPage(1); }, [currentProjectId]);
  const tasksQuery = useQuery({
    queryKey: ['tasks', 'list', currentProjectId, taskPage, taskPageSize],
    queryFn: () => tasksApi.list({ page: taskPage, page_size: taskPageSize, project_id: currentProjectId ?? undefined }),
    refetchInterval: 5000,
  });
  const tasks = tasksQuery.data?.items ?? [];
  const columns: TableColumnsType<Task> = [
    { title: '任务', dataIndex: 'title', render: (_, task) => <Link to={`/console/tasks/${task.id}`}>{task.title}</Link> },
    { title: '目标', dataIndex: 'goal', ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 140, render: (_, task) => <Tag>{STATUS_LABEL[task.latest_run?.status ?? task.status] ?? task.status}</Tag> },
    { title: '阶段', dataIndex: 'stage', width: 120, render: (_, task) => task.latest_run?.stage ?? '—' },
    { title: '更新时间', dataIndex: 'updated_at', width: 180, render: (value: string) => fmtTime(value) },
    { title: '操作', width: 100, render: (_, task) => <Button type="link" onClick={() => navigate(`/console/tasks/${task.id}`)}>打开</Button> },
  ];

  return (
    <PageContainer>
      <Flex justify="space-between" align="start" wrap="wrap" gap={12}>
        <div>
          <Typography.Title level={4} style={{ marginTop: 0 }}>统一任务</Typography.Title>
          <Typography.Text type="secondary">任务在后台持久运行；范围可来自已确认的 API/Web 用例、交互式 Web 编写目标，或由安全 Agent 对已登记 API 生成受控变异计划。</Typography.Text>
        </div>
        <Button type="primary" onClick={() => setCreateOpen(true)}>创建统一任务</Button>
      </Flex>
      {tasksQuery.isLoading ? <LoadingState /> : tasksQuery.isError ? (
        <ErrorState error={tasksQuery.error} onRetry={tasksQuery.refetch} />
      ) : tasks.length === 0 ? (
        <EmptyState description="当前范围暂无任务" />
      ) : (
        <Table
          rowKey="id"
          style={{ marginTop: 20 }}
          columns={columns}
          dataSource={tasks}
          pagination={{ current: taskPage, pageSize: taskPageSize, total: tasksQuery.data?.total, showSizeChanger: true, onChange: (page, size) => { setTaskPage(page); setTaskPageSize(size); } }}
          onRow={(task) => ({ onClick: () => navigate(`/console/tasks/${task.id}`), style: { cursor: 'pointer' } })}
        />
      )}
      <TaskCreateModal
        open={createOpen}
        onClose={() => { setCreateOpen(false); setSearchParams({}); }}
        onCreated={(task) => navigate(`/console/tasks/${task.id}`)}
        initialProjectId={initialProjectId}
        initialCaseIds={initialCaseId ? [initialCaseId] : []}
        initialTargetType={initialTargetType}
      />
    </PageContainer>
  );
}

/** 按运行和参与者 ID 恢复独立消息会话、命令与业务产物。 */
export function ConsoleTaskDetailPage() {
  const { taskId: rawTaskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const taskId = rawTaskId ? Number(rawTaskId) : null;
  const [searchParams] = useSearchParams();
  const requestedRun = searchParams.get('runId');
  const requestedRunId = requestedRun === null ? null : Number(requestedRun);
  const invalidRunId = requestedRun !== null && (!Number.isSafeInteger(requestedRunId) || requestedRunId! <= 0);
  const { message: toast, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [selectedAgentId, setSelectedAgentId] = useState<number | 'events' | null>(null);
  const [messageType, setMessageType] = useState<'TEXT' | 'GOAL_UPDATE' | 'REQUIREMENT'>('TEXT');
  const [draft, setDraft] = useState('');
  const taskQuery = useQuery({
    queryKey: ['tasks', taskId],
    queryFn: () => tasksApi.get(taskId!),
    enabled: taskId != null,
    refetchInterval: 5000,
  });
  const runId = invalidRunId ? null : requestedRunId ?? taskQuery.data?.latest_run?.id ?? null;
  const runQuery = useQuery({
    queryKey: ['task-run', runId],
    queryFn: () => tasksApi.getRun(runId!),
    enabled: runId != null && taskQuery.isSuccess,
    refetchInterval: (query) => STOP_POLLING.has(query.state.data?.run.status ?? '') ? false : 3000,
  });
  // 在读取消息等关联数据前核对运行归属，防止链接指向其他任务。
  const runMatchesTask = runQuery.data?.run.task_id === taskId;
  const pollRunDetails = !STOP_POLLING.has(runQuery.data?.run.status ?? '');
  const messagesQuery = useQuery({
    queryKey: ['task-messages', runId],
    queryFn: () => tasksApi.messages(runId!),
    enabled: runId != null && runMatchesTask,
    refetchInterval: pollRunDetails ? 5000 : false,
  });
  const eventsQuery = useQuery({
    queryKey: ['task-events', runId],
    queryFn: async () => {
      // 按缓存尾部游标续读并限制本地历史，避免重复传输完整事件流。
      const previous = queryClient.getQueryData<TaskEvent[]>(['task-events', runId]) ?? [];
      const next = await tasksApi.events(runId!, previous[previous.length - 1]?.event_seq ?? 0);
      return [...previous, ...next].slice(-200);
    },
    enabled: runId != null && runMatchesTask,
    refetchInterval: pollRunDetails ? 3000 : false,
  });
  const resourcesQuery = useQuery({
    queryKey: ['task-resources', runId],
    queryFn: () => tasksApi.resources(runId!),
    enabled: runId != null && runMatchesTask,
    refetchInterval: pollRunDetails ? 5000 : false,
  });
  useEffect(() => {
    if (pollRunDetails || runId == null) return;
    // 停止轮询前补齐终态提交的最后一批消息、事件与产物。
    void Promise.all(['task-messages', 'task-events', 'task-resources'].map((key) =>
      queryClient.invalidateQueries({ queryKey: [key, runId] }),
    ));
  }, [pollRunDetails, queryClient, runId]);
  const detail = runQuery.data;
  const agents = detail?.agents ?? [];
  const workItems = useMemo(() => detail?.work_items ?? [], [detail?.work_items]);
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId) ?? agents.find((agent) => agent.role === 'MAIN') ?? null;
  const selectedId = selectedAgentId === null && selectedAgent ? selectedAgent.id : selectedAgentId;
  const selectedMessages = (messagesQuery.data ?? []).filter((item) => item.agent_instance_id === selectedAgent?.id);

  const refreshTask = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['tasks'] }),
      queryClient.invalidateQueries({ queryKey: ['task-run', runId] }),
      queryClient.invalidateQueries({ queryKey: ['task-messages', runId] }),
      queryClient.invalidateQueries({ queryKey: ['task-events', runId] }),
      queryClient.invalidateQueries({ queryKey: ['task-resources', runId] }),
    ]);
  };
  const commandMutation = useMutation({
    mutationFn: (command: Omit<TaskCommandRequest, 'idempotency_key'>) =>
      tasksApi.command(runId!, { ...command, idempotency_key: `task-ui-${command.command_type}-${command.work_item_id ?? 'run'}-${Date.now()}` }),
    onSuccess: async () => { toast.success('任务命令已记录'); await refreshTask(); },
    onError: (error) => toast.error(getErrorMessage(error, '任务命令失败')),
  });
  const sendMutation = useMutation({
    mutationFn: () => tasksApi.sendMessage(runId!, {
      recipient_instance_id: selectedAgent?.id,
      message_type: selectedAgent?.role === 'MAIN' ? messageType : 'REQUIREMENT',
      content: draft.trim(),
      client_message_id: `task-ui-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    }),
    onSuccess: async (result) => {
      setDraft('');
      if (result.created_run_id) setSelectedAgentId(null);
      await refreshTask();
    },
    onError: (error) => toast.error(getErrorMessage(error, '消息发送失败')),
  });

  const activeWork = useMemo(
    () => workItems.filter((item) => ['PENDING', 'RUNNING', 'WAITING_EXTERNAL'].includes(item.status)).length,
    [workItems],
  );

  if (taskQuery.isLoading) return <PageContainer><LoadingState /></PageContainer>;
  if (taskQuery.isError || !taskQuery.data) return <PageContainer><ErrorState error={taskQuery.error} onRetry={taskQuery.refetch} /></PageContainer>;
  const task = taskQuery.data;
  if (invalidRunId) return <PageContainer><Empty description="运行编号无效" /></PageContainer>;
  if (runQuery.isLoading && runId) return <PageContainer><LoadingState /></PageContainer>;
  if (runQuery.isError) return <PageContainer><ErrorState error={runQuery.error} onRetry={runQuery.refetch} /></PageContainer>;
  if (runQuery.data && !runMatchesTask) return <PageContainer><Empty description="此运行不属于当前任务" /></PageContainer>;
  const run = detail?.run;
  if (!runId || !run) return <PageContainer><Empty description="任务还没有可恢复的运行记录" /></PageContainer>;
  const historicalRun = run.id !== task.latest_run?.id;
  const selectedProfile = run.input_snapshot.agent_definition as { name?: string; version?: number; child_agents?: { id: number; name: string; version: number }[] } | null | undefined;
  const securityAssessmentSelection = run.input_snapshot.security_assessment as { api_id?: number; api_ids?: number[]; web_session_id?: number; strategy_ids?: number[] } | null | undefined;
  const webAuthoringMode = run.input_snapshot.target_type === 'WEB_AUTHORING';
  const latestPlan = detail?.plans.at(-1);
  const securityAssessmentPreview = latestPlan?.plan_json.security_assessment_preview as {
    estimated_count?: number;
    truncated?: boolean;
    api_ids?: number[];
    items?: {
      index: number;
      name: string;
      mutation_type: string;
      method?: string | null;
      location?: string | null;
      field?: string | null;
      severity?: string;
      risk_level?: string | null;
      confirmation_required?: boolean;
      blocked_reason?: string | null;
    }[];
    plans?: {
      api: { id: number; name?: string; method?: string; path?: string };
      strategies?: { id: number; name: string }[];
      plan: {
        estimated_count?: number;
        truncated?: boolean;
        items?: {
          index: number;
          name: string;
          mutation_type: string;
          method?: string | null;
          location?: string | null;
          field?: string | null;
          severity?: string;
          risk_level?: string | null;
          confirmation_required?: boolean;
          blocked_reason?: string | null;
        }[];
      };
    }[];
    web_inspection?: {
      session_id?: number;
      page?: { https?: boolean; response_status?: number | null };
      dom?: Record<string, number | boolean>;
      interpretation?: string;
      signals?: { code: string; title: string; severity: string }[];
    } | null;
  } | null | undefined;
  const securityApiIds = securityAssessmentSelection?.api_ids?.length
    ? securityAssessmentSelection.api_ids
    : securityAssessmentSelection?.api_id ? [securityAssessmentSelection.api_id] : [];
  const securityPreviewItems = securityAssessmentPreview?.plans?.flatMap((item) => item.plan.items ?? [])
    ?? securityAssessmentPreview?.items
    ?? [];
  const canPause = !historicalRun && ['QUEUED', 'RUNNING', 'WAITING_CONFIRMATION'].includes(run.status);
  const canCancel = !historicalRun && !TERMINAL.has(run.status) && run.status !== 'CANCEL_REQUESTED';
  const canResume = !historicalRun && run.status === 'PAUSED';
  const mainSelected = selectedAgent?.role === 'MAIN';
  const canMessageWorker = selectedAgent != null && ['API_WORKER', 'UI_WORKER'].includes(selectedAgent.role) && workItems.some(
    (item) => item.agent_instance_id === selectedAgent.id && ['PENDING', 'FAILED'].includes(item.status),
  );

  const requestCommand = (type: 'APPROVE_PLAN' | 'PAUSE' | 'RESUME' | 'CANCEL') => {
    if (type === 'APPROVE_PLAN' && securityAssessmentSelection) {
      let riskConfirmed = false;
      const highRiskCount = securityPreviewItems.filter((item) => item.confirmation_required && !item.blocked_reason).length;
      modal.confirm({
        title: '确认自研安全评估计划？',
        content: (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text>
              本次评估绑定 {securityApiIds.length} 个 API（{securityApiIds.map((id) => `#${id}`).join('、')}）和 {securityAssessmentSelection.strategy_ids?.length ?? 0} 个安全策略，共预览 {securityAssessmentPreview?.estimated_count ?? securityPreviewItems.length} 条结构化变异{securityAssessmentSelection.web_session_id ? `，并被动检查 Web 会话 #${securityAssessmentSelection.web_session_id} 的当前页面` : ''}。确认后系统将创建安全用例并通过现有安全执行器运行。
            </Typography.Text>
            {highRiskCount > 0 && (
              <Checkbox onChange={(event) => { riskConfirmed = event.target.checked; }}>
                我已审阅 {highRiskCount} 条高风险变异，并明确授权执行
              </Checkbox>
            )}
          </Space>
        ),
        okText: '确认计划并执行',
        onOk: () => commandMutation.mutateAsync({
          command_type: 'APPROVE_PLAN',
          security_risk_confirmed: riskConfirmed,
        }),
      });
      return;
    }
    if (type === 'CANCEL') {
      modal.confirm({
        title: '取消当前运行？',
        content: '系统会在安全边界停止后续调度；已经发出的 HTTP 请求不会被撤销。',
        okButtonProps: { danger: true },
        onOk: () => commandMutation.mutateAsync({ command_type: type }),
      });
      return;
    }
    commandMutation.mutate({ command_type: type });
  };

  const roleItems = [
    ...agents.map((agent) => ({ key: String(agent.id), label: agent.display_name, agent })),
    { key: 'events', label: '系统事件', agent: null },
  ];
  const resources = resourcesQuery.data ?? [];

  return (
    <PageContainer>
      <Flex justify="space-between" align="start" gap={16} wrap="wrap">
        <div>
          <Typography.Title level={4} style={{ marginTop: 0 }}>{task.title}</Typography.Title>
          <Typography.Paragraph type="secondary" style={{ maxWidth: 860, marginBottom: 8 }}>{run.goal_snapshot}</Typography.Paragraph>
          <Space wrap>
            <Tag>{STATUS_LABEL[run.status] ?? run.status}</Tag>
            <Tag color="blue">{STAGE_LABEL[run.stage] ?? run.stage}</Tag>
            <Typography.Text type="secondary">运行 #{run.run_number} · 项目 #{task.project_id}</Typography.Text>
          </Space>
        </div>
        <Space wrap>
          {!historicalRun && webAuthoringMode && run.stage !== 'PLAN_REVIEW' && <Button type="primary" onClick={() => navigate(`/console/web-ui-agent?taskId=${task.id}&runId=${run.id}&projectId=${task.project_id}`)}>打开任务 Web 工作区</Button>}
          {!historicalRun && run.status === 'WAITING_CONFIRMATION' && <Button type="primary" icon={<CheckOutlined />} onClick={() => requestCommand('APPROVE_PLAN')}>{securityAssessmentSelection ? '确认安全计划并执行' : webAuthoringMode ? '批准方案并启动 UI Worker' : '确认方案并执行'}</Button>}
          {canPause && <Button icon={<PauseOutlined />} onClick={() => requestCommand('PAUSE')}>暂停</Button>}
          {canResume && <Button icon={<PlayCircleOutlined />} onClick={() => requestCommand('RESUME')}>继续</Button>}
          {canCancel && <Button danger icon={<StopOutlined />} onClick={() => requestCommand('CANCEL')}>取消运行</Button>}
        </Space>
      </Flex>

      {historicalRun && <Alert style={{ marginTop: 16 }} type="info" showIcon message="当前查看的是历史运行" description={<Link to={`/console/tasks/${task.id}`}>查看最新运行</Link>} />}

      {run.stage === 'WAITING_MODEL' && run.error_message && (
        <Alert
          style={{ marginTop: 16 }}
          type="warning"
          showIcon
          message="任务等待模型恢复"
          description={`${run.error_message}请在模型配置中修复备用路由后点击“继续”。`}
        />
      )}

      {taskQuery.isError && <Alert type="error" message="刷新任务失败" />}
      <Flex gap={12} style={{ margin: '18px 0' }} wrap="wrap">
        <Card size="small"><Statistic title="团队成员" value={agents.length} /></Card>
        <Card size="small"><Statistic title="任务 Agent" value={selectedProfile?.name ? `${selectedProfile.name} v${selectedProfile.version ?? 1}` : '平台默认'} /></Card>
        {selectedProfile?.child_agents?.length ? <Card size="small"><Statistic title="子 Agent 节点" value={selectedProfile.child_agents.length} /></Card> : null}
        <Card size="small"><Statistic title="待处理工作" value={activeWork} /></Card>
        <Card size="small"><Statistic title="方案版本" value={run.current_plan_version} /></Card>
        <Card size="small"><Statistic title="事件序号" value={run.event_seq} /></Card>
      </Flex>

      <div style={{ display: 'grid', gridTemplateColumns: '240px minmax(0, 1fr)', gap: 16, alignItems: 'start' }}>
        <Card title="任务参与者" size="small" styles={{ body: { padding: 8 } }}>
          <List
            size="small"
            dataSource={roleItems}
            renderItem={(item) => {
              const agent = item.agent as TaskAgentInstance | null;
              const selected = String(selectedId ?? agents.find((entry) => entry.role === 'MAIN')?.id) === item.key;
              const state = agent ? agent.status : 'READ_ONLY';
              const stateLabel = agent ? (STATUS_LABEL[state] ?? state) : '只读';
              return (
                <List.Item
                  onClick={() => setSelectedAgentId(item.key === 'events' ? 'events' : Number(item.key))}
                  style={{ cursor: 'pointer', background: selected ? 'rgba(22, 119, 255, .08)' : undefined, paddingInline: 10 }}
                >
                  <List.Item.Meta
                    title={item.label}
                    description={agent ? `#${agent.id} · ${stateLabel}` : '持久化时间线'}
                  />
                </List.Item>
              );
            }}
          />
        </Card>

        <Card
          size="small"
          title={selectedAgent ? `${selectedAgent.display_name} · ${ROLE_LABEL[selectedAgent.role] ?? selectedAgent.role}` : '系统事件'}
          extra={selectedAgent && <Tag>{STATUS_LABEL[selectedAgent.status] ?? selectedAgent.status}</Tag>}
        >
          <Tabs
            items={[
              {
                key: 'conversation', label: '会话',
                children: selectedId === 'events' ? (
                  <EventTimeline events={eventsQuery.data ?? []} />
                ) : (
                  <>
                    <List
                      dataSource={selectedMessages}
                      locale={{ emptyText: <Empty description="该参与者暂无消息" /> }}
                      renderItem={(item) => <MessageRow key={item.id} message={item} projectId={task.project_id} />}
                    />
                    {!historicalRun && selectedAgent && (mainSelected ? !TERMINAL.has(run.status) : canMessageWorker) && (
                      <div style={{ marginTop: 16, borderTop: '1px solid #eee', paddingTop: 16 }}>
                        <Space style={{ marginBottom: 8 }}>
                          {mainSelected ? (
                            <>
                              <Button size="small" type={messageType === 'TEXT' ? 'primary' : 'default'} onClick={() => setMessageType('TEXT')}>发消息</Button>
                              <Button size="small" type={messageType === 'GOAL_UPDATE' ? 'primary' : 'default'} onClick={() => setMessageType('GOAL_UPDATE')}>调整整体目标</Button>
                            </>
                          ) : <Tag color="purple">补充给指定 {selectedAgent.display_name}</Tag>}
                        </Space>
                        <Input.TextArea
                          value={draft}
                          onChange={(event) => setDraft(event.target.value)}
                          rows={3}
                          maxLength={8000}
                          placeholder={mainSelected ? (messageType === 'GOAL_UPDATE' ? '输入新的整体目标，将建立新的运行版本' : '向任务主 Agent 发送消息') : `向当前${selectedAgent?.display_name}提供补充要求`}
                        />
                        <Flex justify="flex-end" style={{ marginTop: 8 }}>
                          <Button
                            type="primary"
                            icon={<SendOutlined />}
                            loading={sendMutation.isPending}
                            disabled={!draft.trim()}
                            onClick={() => {
                              if (!mainSelected) setMessageType('REQUIREMENT');
                              sendMutation.mutate();
                            }}
                          >发送</Button>
                        </Flex>
                      </div>
                    )}
                    {selectedAgent && !mainSelected && !canMessageWorker && <Alert type="info" showIcon message={`${selectedAgent.display_name} 当前没有可接收补充要求的工作项`} />}
                  </>
                ),
              },
              {
                key: 'plan', label: '方案与调度',
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {!latestPlan ? <Empty description="Planner 尚未提交方案" /> : (
                      <Card size="small" title={`方案 v${latestPlan.version} · ${latestPlan.status}`}>
                        <Typography.Paragraph>{String(latestPlan.plan_json.summary ?? '')}</Typography.Paragraph>
                        <Typography.Text strong>验收条件</Typography.Text>
                        <List size="small" dataSource={(latestPlan.plan_json.acceptance_criteria as string[] | undefined) ?? []} renderItem={(item) => <List.Item>{item}</List.Item>} />
                        <Typography.Text type="secondary">用例范围：{((latestPlan.plan_json.case_ids as number[] | undefined) ?? []).map((id) => `#${id}`).join('、')}</Typography.Text>
                      </Card>
                    )}
                    {agents.some((item) => item.role === 'SUB_AGENT') && <Card size="small" title="LangGraph 子 Agent 节点">
                      <List size="small" dataSource={agents.filter((item) => item.role === 'SUB_AGENT')} renderItem={(item) => <List.Item><Space><Typography.Text strong>{item.display_name}</Typography.Text><Tag>v{String(item.config_snapshot.agent_version ?? 1)}</Tag><Tag color={item.status === 'SUCCEEDED' ? 'green' : item.status === 'FAILED' ? 'red' : 'blue'}>{STATUS_LABEL[item.status] ?? item.status}</Tag></Space></List.Item>} />
                    </Card>}
                    <Card size="small" title={`工具调用审计 · ${detail?.tool_invocations.length ?? 0}`}>
                      <Typography.Text type="secondary">仅展示调用身份和状态，不展示工具参数或结果。</Typography.Text>
                      <Table<TaskToolInvocation>
                        size="small"
                        rowKey="id"
                        pagination={false}
                        dataSource={detail?.tool_invocations ?? []}
                        locale={{ emptyText: <Empty description="暂无工具调用记录" /> }}
                        columns={[
                          { title: '工具', dataIndex: 'tool_name' },
                          { title: '状态', dataIndex: 'status', render: (state: string) => <Tag color={state === 'SUCCEEDED' ? 'green' : state === 'FAILED' ? 'red' : 'blue'}>{TOOL_CALL_STATUS[state] ?? state}</Tag> },
                          { title: '时间', dataIndex: 'created_at', render: fmtTime },
                          { title: '错误码', dataIndex: 'error_code', render: (value: string | null) => value || '—' },
                        ]}
                      />
                    </Card>
                    {securityAssessmentSelection && (
                      <Card size="small" title="自研安全评估计划预览">
                        <Space direction="vertical" style={{ width: '100%' }}>
                          <Typography.Text>
                            {securityApiIds.length} 个 API（{securityApiIds.map((id) => `#${id}`).join('、')}）· {securityAssessmentSelection.strategy_ids?.length ?? 0} 个策略 · 共 {securityAssessmentPreview?.estimated_count ?? 0} 条计划项
                          </Typography.Text>
                          {securityAssessmentPreview?.truncated && <Alert type="error" showIcon message="计划预览已截断，当前不能确认执行；请减少策略后重新创建任务。" />}
                          {securityAssessmentPreview?.web_inspection && (
                            <Card size="small" title={`Web 页面被动观察 · 会话 #${securityAssessmentPreview.web_inspection.session_id}`}>
                              <Typography.Text type="secondary">
                                页面 HTTPS：{securityAssessmentPreview.web_inspection.page?.https ? '是' : '否'} · HTTP 状态：{securityAssessmentPreview.web_inspection.page?.response_status ?? '未知'}。{securityAssessmentPreview.web_inspection.interpretation}
                              </Typography.Text>
                              <List
                                size="small"
                                dataSource={securityAssessmentPreview.web_inspection.signals ?? []}
                                locale={{ emptyText: '未观察到候选信号' }}
                                renderItem={(signal) => <List.Item><Space><Tag color={signal.severity === 'LOW' ? 'orange' : 'blue'}>{signal.severity}</Tag>{signal.title}</Space></List.Item>}
                              />
                            </Card>
                          )}
                          <List
                            size="small"
                            dataSource={securityAssessmentPreview?.plans ?? []}
                            locale={{ emptyText: <Empty description="安全计划正在生成" /> }}
                            renderItem={(apiPlan) => (
                              <List.Item>
                                <Space direction="vertical" style={{ width: '100%' }}>
                                  <Typography.Text strong>API #{apiPlan.api.id} · {apiPlan.api.method} {apiPlan.api.path} · {apiPlan.api.name}</Typography.Text>
                                  <Typography.Text type="secondary">策略：{apiPlan.strategies?.map((strategy) => strategy.name).join('、') || '—'}</Typography.Text>
                                  <List
                                    size="small"
                                    dataSource={apiPlan.plan.items ?? []}
                                    locale={{ emptyText: <Empty description="该 API 没有可用变异项" /> }}
                                    renderItem={(item) => (
                                      <List.Item>
                                        <Space direction="vertical" size={0}>
                                          <Space wrap>
                                            <Typography.Text strong>#{item.index + 1} {item.name}</Typography.Text>
                                            <Tag>{item.mutation_type}</Tag>
                                            <Tag color={item.confirmation_required ? 'red' : 'blue'}>{item.confirmation_required ? '需高风险确认' : item.risk_level ?? item.severity ?? '普通风险'}</Tag>
                                          </Space>
                                          <Typography.Text type="secondary">
                                            {[item.method, item.location, item.field].filter(Boolean).join(' · ') || '按策略规则执行'}
                                            {item.blocked_reason ? ` · 暂不可执行：${item.blocked_reason}` : ''}
                                          </Typography.Text>
                                        </Space>
                                      </List.Item>
                                    )}
                                  />
                                </Space>
                              </List.Item>
                            )}
                          />
                          {!securityAssessmentPreview?.plans?.length && securityAssessmentPreview?.items?.length ? (
                            <List size="small" dataSource={securityAssessmentPreview.items} renderItem={(item) => <List.Item>#{item.index + 1} {item.name} · {item.mutation_type}</List.Item>} />
                          ) : null}
                          <Alert type="info" showIcon message="模型只解释预览计划；实际执行目标、策略和变异由服务端固定。高风险项需要在确认窗口显式授权。" />
                        </Space>
                      </Card>
                    )}
                    <Table<TaskWorkItem>
                      size="small"
                      rowKey="id"
                      pagination={false}
                      dataSource={workItems}
                      columns={[
                        { title: '职责', dataIndex: 'kind', render: (kind: string) => ROLE_LABEL[{ PLAN: 'PLANNER', EXECUTE_API: 'API_WORKER', EXECUTE_WEB: 'UI_WORKER', EXECUTE_SECURITY: 'SECURITY_WORKER', SECURITY_SCAN: 'SECURITY_WORKER', REPORT: 'REPORT_AGENT', REVIEW: 'REVIEWER', FINALIZE: 'MAIN' }[kind] ?? kind] ?? kind },
                        { title: '状态', dataIndex: 'status', render: (state: string) => STATUS_LABEL[state] ?? state },
                        { title: '尝试', dataIndex: 'attempt_count', width: 80 },
                        { title: '结果/错误', render: (_, row) => row.error_message ?? JSON.stringify(row.output_json ?? {}) },
                        {
                          title: '操作',
                          width: 110,
                          render: (_, row) => {
                            if (historicalRun || row.status !== 'FAILED') return null;
                            if (!row.retryable) {
                              return (
                                <Tooltip title={row.retry_block_reason ?? '当前工作项不可重试'}>
                                  <Button size="small" disabled>不可重试</Button>
                                </Tooltip>
                              );
                            }
                            return (
                              <Button
                                size="small"
                                icon={<PlayCircleOutlined />}
                                onClick={() => commandMutation.mutate({ command_type: 'RETRY', work_item_id: row.id })}
                              >
                                重试
                              </Button>
                            );
                          },
                        },
                      ]}
                    />
                  </Space>
                ),
              },
              {
                key: 'resources', label: '产物',
                children: <ResourceList resources={resources} projectId={task.project_id} targetType={run.input_snapshot.target_type} />,
              },
              {
                key: 'events', label: '运行记录',
                children: <EventTimeline events={eventsQuery.data ?? []} />,
              },
            ]}
          />
        </Card>
      </div>
    </PageContainer>
  );
}

/** 渲染当前参与者会话消息，不混合其他角色的会话。 */
function MessageRow({ message, projectId }: { message: TaskMessage; projectId: number }) {
  const isUser = message.sender_type === 'USER';
  return (
    <List.Item>
      <Card size="small" style={{ width: '100%', background: isUser ? 'rgba(22, 119, 255, .04)' : undefined }}>
        <Flex justify="space-between" gap={12}>
          <Typography.Text strong>{isUser ? '你' : message.message_type === 'PLAN' ? '方案' : message.message_type === 'REVIEW' ? '审阅结论' : 'Agent'}</Typography.Text>
          <Typography.Text type="secondary">{fmtTime(message.created_at)}</Typography.Text>
        </Flex>
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: '8px 0 0' }}>{message.content}</Typography.Paragraph>
        {message.message_type === 'RESULT' && typeof message.metadata_json.test_run_id === 'number' && (
          <Link to={`/console/execution-history?runId=${message.metadata_json.test_run_id}&projectId=${projectId}`}>打开执行记录 #{message.metadata_json.test_run_id}</Link>
        )}
      </Card>
    </List.Item>
  );
}

/** 展示服务端记录的事件事实，支持刷新后续读。 */
function EventTimeline({ events }: { events: TaskEvent[] }) {
  return (
    <List
      size="small"
      dataSource={events}
      locale={{ emptyText: <Empty description="暂无事件" /> }}
      renderItem={(event) => (
        <List.Item>
          <List.Item.Meta
            title={<Space><Tag color="blue">#{event.event_seq}</Tag><span>{EVENT_LABEL[event.event_type] ?? event.event_type}</span></Space>}
            description={`${fmtTime(event.created_at)} · ${JSON.stringify(event.payload)}`}
          />
        </List.Item>
      )}
    />
  );
}

/** 把任务产物引用还原成已有管理页面地址。 */
function ResourceList({ resources, projectId, targetType }: { resources: TaskResourceRef[]; projectId: number; targetType: unknown }) {
  return (
    <List
      dataSource={resources}
      locale={{ emptyText: <Empty description="暂无产物引用" /> }}
      renderItem={(resource) => {
        const id = Number(resource.resource_id);
        const href = resource.resource_type === 'REPORT'
          ? `/console/test-reports/${id}`
          : resource.resource_type === 'TEST_RUN'
            ? `/console/execution-history?runId=${id}&projectId=${projectId}`
            : resource.resource_type === 'SECURITY_FINDING'
              ? `/console/security-testing?tab=findings&projectId=${projectId}&findingId=${id}`
            : resource.resource_type === 'TEST_CASE'
            ? targetType === 'WEB' || targetType === 'WEB_AUTHORING' ? `/console/web-ui?caseId=${id}&projectId=${projectId}` : targetType === 'API' ? `/console/test-asset?caseId=${id}&projectId=${projectId}` : undefined
              : undefined;
        return (
          <List.Item>
            <List.Item.Meta
              title={href ? <Link to={href}>{resource.display_name ?? `${resource.resource_type} #${resource.resource_id}`}</Link> : (resource.display_name ?? `${resource.resource_type} #${resource.resource_id}`)}
              description={`${resource.direction === 'INPUT' ? '输入引用' : '真实业务产物'} · ${fmtTime(resource.created_at)}`}
            />
          </List.Item>
        );
      }}
    />
  );
}
