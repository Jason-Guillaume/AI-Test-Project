// 统一任务列表与任务执行台；会话、方案和产物均从后端持久化状态恢复。
import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Flex,
  Input,
  List,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
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
  type TaskWorkItem,
} from '@/api/tasks';
import { TaskCreateModal } from '@/components/tasks/TaskCreateModal';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { fmtTime } from '@/shared/format';
import { useConsoleScope } from '@/hooks/useConsoleScope';

const STATUS_LABEL: Record<string, string> = {
  QUEUED: '排队中', RUNNING: '运行中', WAITING_CONFIRMATION: '待确认',
  PAUSE_REQUESTED: '暂停中', PAUSED: '已暂停', CANCEL_REQUESTED: '取消中',
  WAITING_EXTERNAL: '等待外部扫描',
  SUCCEEDED: '已完成', SUCCEEDED_WITH_ISSUES: '完成但有问题', FAILED: '失败',
  CANCELLED: '已取消', SUPERSEDED: '已被新目标替代', RECONCILIATION_REQUIRED: '待核对',
};
const STAGE_LABEL: Record<string, string> = {
  MODEL_RETRY: '模型重试中', WAITING_MODEL: '等待修复模型配置',
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
  REPORT_AGENT: '报告 Agent',
};
const TERMINAL = new Set(['SUCCEEDED', 'SUCCEEDED_WITH_ISSUES', 'FAILED', 'CANCELLED', 'SUPERSEDED']);
const STOP_POLLING = new Set([...TERMINAL, 'RECONCILIATION_REQUIRED', 'PAUSED']);

/** 展示用户有权查看的任务与最近一次持久化运行。 */
export function ConsoleTasksPage() {
  const { currentProjectId } = useConsoleScope();
  const [createOpen, setCreateOpen] = useState(false);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialProjectId = Number(searchParams.get('projectId')) || undefined;
  const initialCaseId = Number(searchParams.get('caseId')) || undefined;
  useEffect(() => {
    if (searchParams.get('create') === '1') setCreateOpen(true);
  }, [searchParams]);
  const tasksQuery = useQuery({
    queryKey: ['tasks', 'list', currentProjectId],
    queryFn: () => tasksApi.list({ page: 1, page_size: 100, project_id: currentProjectId ?? undefined }),
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
          <Typography.Text type="secondary">任务在后台持久运行，关闭页面不会中断；输入范围来自已确认的 API 或 Web 测试资产，可选关联 ZAP 扫描。</Typography.Text>
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
          pagination={{ pageSize: 20, showSizeChanger: true }}
          onRow={(task) => ({ onClick: () => navigate(`/console/tasks/${task.id}`), style: { cursor: 'pointer' } })}
        />
      )}
      <TaskCreateModal
        open={createOpen}
        onClose={() => { setCreateOpen(false); setSearchParams({}); }}
        onCreated={(task) => navigate(`/console/tasks/${task.id}`)}
        initialProjectId={initialProjectId}
        initialCaseIds={initialCaseId ? [initialCaseId] : []}
      />
    </PageContainer>
  );
}

/** 按运行和参与者 ID 恢复独立消息会话、命令与业务产物。 */
export function ConsoleTaskDetailPage() {
  const { taskId: rawTaskId } = useParams<{ taskId: string }>();
  const taskId = rawTaskId ? Number(rawTaskId) : null;
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
  const runId = taskQuery.data?.latest_run?.id ?? null;
  const runQuery = useQuery({
    queryKey: ['task-run', runId],
    queryFn: () => tasksApi.getRun(runId!),
    enabled: runId != null,
    refetchInterval: (query) => STOP_POLLING.has(query.state.data?.run.status ?? '') ? false : 3000,
  });
  const pollRunDetails = !STOP_POLLING.has(runQuery.data?.run.status ?? taskQuery.data?.latest_run?.status ?? '');
  const messagesQuery = useQuery({
    queryKey: ['task-messages', runId],
    queryFn: () => tasksApi.messages(runId!),
    enabled: runId != null,
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
    enabled: runId != null,
    refetchInterval: pollRunDetails ? 3000 : false,
  });
  const resourcesQuery = useQuery({
    queryKey: ['task-resources', runId],
    queryFn: () => tasksApi.resources(runId!),
    enabled: runId != null,
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
  const workItems = detail?.work_items ?? [];
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
  const run = detail?.run;
  if (!runId || !run) return <PageContainer><Empty description="任务还没有可恢复的运行记录" /></PageContainer>;
  const securityScanSelection = run.input_snapshot.security_scan as { target_id?: number; scan_profile_id?: number } | null | undefined;
  const latestPlan = detail?.plans.at(-1);
  const scanPreview = latestPlan?.plan_json.security_scan_preview as {
    target?: { name?: string; base_url?: string };
    profile?: { name?: string; scan_mode?: string };
    is_active_scan?: boolean;
    zap_available?: boolean;
    estimated_requests?: number | null;
    max_duration_minutes?: number;
    exclude_paths?: string[];
    limitations?: string[];
  } | null | undefined;
  const canPause = ['QUEUED', 'RUNNING', 'WAITING_CONFIRMATION'].includes(run.status);
  const canCancel = !TERMINAL.has(run.status) && run.status !== 'CANCEL_REQUESTED';
  const canResume = run.status === 'PAUSED';
  const mainSelected = selectedAgent?.role === 'MAIN';
  const canMessageWorker = selectedAgent != null && ['API_WORKER', 'UI_WORKER'].includes(selectedAgent.role) && workItems.some(
    (item) => item.agent_instance_id === selectedAgent.id && ['PENDING', 'FAILED'].includes(item.status),
  );

  const requestCommand = (type: 'APPROVE_PLAN' | 'PAUSE' | 'RESUME' | 'CANCEL') => {
    if (type === 'APPROVE_PLAN' && securityScanSelection) {
      let approvalNote = '';
      modal.confirm({
        title: '确认测试方案并附加 ZAP 扫描？',
        content: (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text>
              已选择扫描目标 #{securityScanSelection.target_id} 和策略 #{securityScanSelection.scan_profile_id}。确认后安全 Worker 会在 TestRun 创建后调用现有 ZAP 队列；主动扫描仍会由后端再次校验项目角色、目标授权和执行环境。
            </Typography.Text>
            <Input.TextArea
              rows={3}
              maxLength={500}
              placeholder="主动扫描必填批准说明；被动扫描可留空"
              onChange={(event) => { approvalNote = event.target.value; }}
            />
          </Space>
        ),
        okText: '确认方案并请求扫描',
        onOk: () => commandMutation.mutateAsync({
          command_type: 'APPROVE_PLAN',
          security_scan_confirmed: true,
          security_scan_approval_note: approvalNote,
        }),
      });
      return;
    }
    if (type === 'CANCEL') {
      modal.confirm({
        title: '取消当前运行？',
        content: '系统会在安全边界停止后续调度；已发出的 HTTP 请求不会被撤销，关联 ZAP 扫描会收到取消请求。',
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
          <Typography.Paragraph type="secondary" style={{ maxWidth: 860, marginBottom: 8 }}>{task.goal}</Typography.Paragraph>
          <Space wrap>
            <Tag>{STATUS_LABEL[run.status] ?? run.status}</Tag>
            <Tag color="blue">{STAGE_LABEL[run.stage] ?? run.stage}</Tag>
            <Typography.Text type="secondary">运行 #{run.run_number} · 项目 #{task.project_id}</Typography.Text>
          </Space>
        </div>
        <Space wrap>
          {run.status === 'WAITING_CONFIRMATION' && <Button type="primary" icon={<CheckOutlined />} onClick={() => requestCommand('APPROVE_PLAN')}>{securityScanSelection ? '确认方案并请求 ZAP 扫描' : '确认方案并执行'}</Button>}
          {canPause && <Button icon={<PauseOutlined />} onClick={() => requestCommand('PAUSE')}>暂停</Button>}
          {canResume && <Button icon={<PlayCircleOutlined />} onClick={() => requestCommand('RESUME')}>继续</Button>}
          {canCancel && <Button danger icon={<StopOutlined />} onClick={() => requestCommand('CANCEL')}>取消运行</Button>}
        </Space>
      </Flex>

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
                      renderItem={(item) => <MessageRow key={item.id} message={item} />}
                    />
                    {selectedAgent && (mainSelected ? !TERMINAL.has(run.status) : canMessageWorker) && (
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
                    {securityScanSelection && (
                      <Alert
                        type={scanPreview?.zap_available ? 'warning' : 'error'}
                        showIcon
                        message={`ZAP 扫描计划预览 · ${scanPreview?.is_active_scan ? '主动扫描' : '被动扫描'}`}
                        description={scanPreview ? (
                          <Space direction="vertical">
                            <span>目标：{scanPreview.target?.name ?? `#${securityScanSelection.target_id}`} · {scanPreview.target?.base_url ?? '地址未知'}</span>
                            <span>策略：{scanPreview.profile?.name ?? `#${securityScanSelection.scan_profile_id}`} · {scanPreview.profile?.scan_mode ?? '模式未知'}</span>
                            <span>请求预算：{scanPreview.estimated_requests ?? '未知'} · 最长时长：{scanPreview.max_duration_minutes ?? '未知'} 分钟</span>
                            {scanPreview.exclude_paths?.length ? <span>排除路径：{scanPreview.exclude_paths.join('、')}</span> : null}
                            {scanPreview.limitations?.map((item) => <span key={item}>限制：{item}</span>)}
                            {!scanPreview.zap_available && <span>当前部署未配置可用 ZAP；确认后安全扫描无法启动。</span>}
                          </Space>
                        ) : '正在读取扫描目标与策略的最新范围；确认前请核对完整预览。'}
                      />
                    )}
                    <Table<TaskWorkItem>
                      size="small"
                      rowKey="id"
                      pagination={false}
                      dataSource={workItems}
                      columns={[
                        { title: '职责', dataIndex: 'kind', render: (kind: string) => ROLE_LABEL[{ PLAN: 'PLANNER', EXECUTE_API: 'API_WORKER', EXECUTE_WEB: 'UI_WORKER', SECURITY_SCAN: 'SECURITY_WORKER', REPORT: 'REPORT_AGENT', REVIEW: 'REVIEWER', FINALIZE: 'MAIN' }[kind] ?? kind] ?? kind },
                        { title: '状态', dataIndex: 'status', render: (state: string) => STATUS_LABEL[state] ?? state },
                        { title: '尝试', dataIndex: 'attempt_count', width: 80 },
                        { title: '结果/错误', render: (_, row) => row.error_message ?? JSON.stringify(row.output_json ?? {}) },
                        { title: '操作', width: 90, render: (_, row) => row.status === 'FAILED' ? <Button size="small" icon={<PlayCircleOutlined />} onClick={() => commandMutation.mutate({ command_type: 'RETRY', work_item_id: row.id })}>重试</Button> : null },
                      ]}
                    />
                  </Space>
                ),
              },
              {
                key: 'resources', label: '产物',
                children: <ResourceList resources={resources} />,
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
function MessageRow({ message }: { message: TaskMessage }) {
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
          <Link to={`/console/execution-history?runId=${message.metadata_json.test_run_id}`}>打开执行记录 #{message.metadata_json.test_run_id}</Link>
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
function ResourceList({ resources }: { resources: TaskResourceRef[] }) {
  return (
    <List
      dataSource={resources}
      locale={{ emptyText: <Empty description="暂无产物引用" /> }}
      renderItem={(resource) => {
        const id = Number(resource.resource_id);
        const href = resource.resource_type === 'REPORT'
          ? `/console/test-reports/${id}`
          : resource.resource_type === 'TEST_RUN'
            ? `/console/execution-history?runId=${id}`
            : resource.resource_type === 'TEST_CASE'
              ? `/console/test-asset?caseId=${id}`
              : resource.resource_type === 'SECURITY_SCAN_JOB'
                ? `/console/security-testing?tab=zap&jobId=${id}`
              : undefined;
        return (
          <List.Item>
            <List.Item.Meta
              title={href ? <Link to={href}>{resource.resource_type} #{resource.resource_id}</Link> : `${resource.resource_type} #${resource.resource_id}`}
              description={`${resource.direction === 'INPUT' ? '输入引用' : '真实业务产物'} · ${fmtTime(resource.created_at)}`}
            />
          </List.Item>
        );
      }}
    />
  );
}
