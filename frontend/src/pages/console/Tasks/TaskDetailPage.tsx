/**
 * 统一任务运行详情页。
 * 导出 ConsoleTaskDetailPage，由任务路由加载；编排任务/运行查询与命令，将消息、事件、资源展示交给同目录组件。
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Empty,
  Flex,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import {
  CheckOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { getErrorMessage } from '@/shared/api/client';
import { tasksApi } from '@/features/tasks/api/tasks';
import type { TaskEvent, TaskCommandRequest } from '@/features/tasks/contracts';
import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { TaskRunPanels } from './TaskRunPanels';
import type { TaskAgentDefinitionSnapshot, TaskSecurityAssessmentPreview, TaskSecurityAssessmentSelection } from './taskTypes';
import { STATUS_LABEL, STAGE_LABEL, TERMINAL, STOP_POLLING } from './taskLabels';

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
  const selectedProfile = run.input_snapshot.agent_definition as TaskAgentDefinitionSnapshot | null | undefined;
  const webAuthoringMode = run.input_snapshot.target_type === 'WEB_AUTHORING';
  const latestPlan = detail?.plans.at(-1);
  const securityAssessmentSelection = run.input_snapshot.security_assessment as TaskSecurityAssessmentSelection | null | undefined;
  const securityAssessmentPreview = latestPlan?.plan_json.security_assessment_preview as TaskSecurityAssessmentPreview | null | undefined;
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

      <TaskRunPanels
        task={task}
        run={run}
        detail={detail}
        agents={agents}
        workItems={workItems}
        selectedId={selectedId}
        selectedAgent={selectedAgent}
        selectedMessages={selectedMessages}
        events={eventsQuery.data ?? []}
        resources={resources}
        historicalRun={historicalRun}
        latestPlan={latestPlan}
        securityAssessmentSelection={securityAssessmentSelection}
        securityAssessmentPreview={securityAssessmentPreview}
        securityApiIds={securityApiIds}
        mainSelected={mainSelected}
        canMessageWorker={canMessageWorker}
        draft={draft}
        onDraftChange={setDraft}
        messageType={messageType}
        onMessageTypeChange={setMessageType}
        onSelectAgent={setSelectedAgentId}
        sendPending={sendMutation.isPending}
        onSend={() => {
          if (!mainSelected) setMessageType('REQUIREMENT');
          sendMutation.mutate();
        }}
        onRetryWorkItem={(workItemId) => commandMutation.mutate({ command_type: 'RETRY', work_item_id: workItemId })}
      />

    </PageContainer>
  );
}

