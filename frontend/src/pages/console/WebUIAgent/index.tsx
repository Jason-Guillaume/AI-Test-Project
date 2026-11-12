// Web UI 智能体交互式编写页。
//
// 形态：受控浏览器会话（沙箱）+ 自然语言目标 + 人工步骤 review。
// 安全边界与后端一致：观测面板只显示脱敏语义树与遮罩截图，凭据永不回显；
// 提升只产出未确认草稿，正式执行仍须在 Web UI 自动化页人工确认后 debug。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, App, Card, Col, Row, Space, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { PageContainer, EmptyState, LoadingState, ErrorState } from '@/shared/ui/PageState';
import { getErrorMessage } from '@/shared/api/client';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { webUIApi } from '@/features/web-testing/api/webUI';
import { webAgentApi } from '@/features/browser-authoring/api';
import type { WebAgentPromoteBody, WebAgentStartBody } from '@/features/browser-authoring/contracts';
import { agentApi } from '@/features/agent/api/agent';
import { tasksApi } from '@/features/tasks/api/tasks';
import type { TaskWebAuthoringWorkspace } from '@/features/tasks/contracts';
import type { SendMessageRequest } from '@/features/agent/contracts';

import type { Paginated } from '@/shared/api/contracts';
import type { WebAgentSession } from '@/features/browser-authoring/contracts';
import type { WebCaseInput } from '@/features/web-testing/contracts';
import { ChatPanel, ConversationCard, ObservationPanel, ProposalPanel, agentSessionStorageKey, readRememberedAgentSession, SessionPanel, SetupCard, type WebWorkspace } from './webAgentPanels';


function Workspace({ projectId }: { projectId: number }) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedTaskId = Number(searchParams.get('taskId'));
  const taskId = Number.isSafeInteger(requestedTaskId) && requestedTaskId > 0 ? requestedTaskId : null;
  const requestedRunId = Number(searchParams.get('runId'));
  const taskRunId = Number.isSafeInteger(requestedRunId) && requestedRunId > 0 ? requestedRunId : null;
  const taskBound = taskId != null && taskRunId != null;
  const taskContextRequested = searchParams.has('taskId') || searchParams.has('runId');

  const envs = useQuery({ queryKey: ['project', projectId, 'web', 'environments', ''], queryFn: () => webUIApi.environments(projectId, ''), enabled: !taskContextRequested });
  const auth = useQuery({ queryKey: ['project', projectId, 'web', 'auth'], queryFn: () => webUIApi.auth(projectId), enabled: !taskContextRequested });
  const sessions = useQuery({ queryKey: ['project', projectId, 'web-agent', 'sessions'], queryFn: () => webAgentApi.sessions(projectId), enabled: !taskContextRequested });
  const agentSessions = useQuery({
    queryKey: ['agent', 'sessions', projectId],
    queryFn: () => agentApi.listSessions(projectId),
    enabled: !taskContextRequested,
  });
  const taskWorkspace = useQuery({
    queryKey: ['task-web-authoring', taskRunId],
    queryFn: () => tasksApi.webAuthoring(taskRunId!),
    enabled: taskBound,
    refetchInterval: taskBound ? 3000 : false,
  });
  const [agentSessionId, setAgentSessionId] = useState<number | null>(null);
  const [webSessionId, setWebSessionId] = useState<number | null>(null);
  const restoredAgentSession = useRef(false);
  const turnBusy = useRef(false);

  const envRows = envs.data?.items.filter((e) => e.is_active) ?? [];
  const authRows = auth.data?.items ?? [];
  // 只按显式选中的会话 ID 解析，不回退到列表首项——历史遗留的 CLOSED 会话会让
  // 用户永远停在「关闭会话」按钮上，再也无法启动新会话。
  const session = taskBound
    ? taskWorkspace.data?.web_session ?? null
    : webSessionId != null ? sessions.data?.items.find((s) => s.id === webSessionId) ?? null : null;
  const taskAgentSessionId = taskWorkspace.data?.agent_session.id;
  const taskWebSessionId = taskWorkspace.data?.web_session.id;

  const detail = useQuery({ queryKey: ['agent', 'session', agentSessionId], queryFn: () => agentApi.getSessionDetail(agentSessionId!), enabled: !taskBound && agentSessionId != null });
  const workspace = useQuery({ queryKey: ['agent', 'workspace', agentSessionId], queryFn: () => agentApi.getWorkspace(agentSessionId!), enabled: !taskBound && agentSessionId != null });

  useEffect(() => {
    if (!taskBound || taskAgentSessionId == null || taskWebSessionId == null) return;
    setAgentSessionId(taskAgentSessionId);
    setWebSessionId(taskWebSessionId);
  }, [taskBound, taskAgentSessionId, taskWebSessionId]);

  useEffect(() => {
    if (taskBound || agentSessionId == null) return;
    try {
      window.localStorage.setItem(agentSessionStorageKey(projectId), String(agentSessionId));
    } catch {
      /* localStorage 不可用时静默降级：仅失去刷新恢复能力 */
    }
  }, [agentSessionId, projectId, taskBound]);

  // 会话列表加载后恢复上次的 Web 智能体对话；没有记忆时选择最近一条。
  // 只初始化一次，避免创建新对话后的列表刷新把当前选择跳回旧会话。
  useEffect(() => {
    if (taskBound || agentSessions.data == null || restoredAgentSession.current) return;
    restoredAgentSession.current = true;
    const remembered = readRememberedAgentSession(projectId);
    const webChats = agentSessions.data.filter((s) =>
      s.title === 'Web 智能体会话' || s.title?.startsWith('Web UI 智能体'),
    );
    if (remembered != null && webChats.some((s) => s.id === remembered)) {
      setAgentSessionId(remembered);
    } else if (remembered != null) {
      try {
        window.localStorage.removeItem(agentSessionStorageKey(projectId));
      } catch {
        /* 忽略 */
      }
      setAgentSessionId(webChats[0]?.id ?? null);
    } else {
      setAgentSessionId(webChats[0]?.id ?? null);
    }
  }, [agentSessions.data, projectId, taskBound]);

  const turn = useMutation({
    mutationFn: ({ sessionId, body }: { sessionId: number; body: SendMessageRequest }) =>
      taskBound && taskRunId != null
        ? tasksApi.webAuthoringTurn(taskRunId, {
          request_key: `web-turn-${Date.now()}-${Math.random().toString(16).slice(2)}`,
          content: body.content ?? undefined,
          action: body.action === 'confirm_web_step' || body.action === 'reject_web_step' ? body.action : undefined,
          web_session_id: webSessionId ?? undefined,
        })
        : agentApi.sendMessage(sessionId, body),
  });
  const createAgentSession = useMutation({
    mutationFn: () => agentApi.createSession(projectId, { title: 'Web UI 智能体会话' }),
  });
  const startSession = useMutation<TaskWebAuthoringWorkspace | WebAgentSession, Error, WebAgentStartBody>({
    mutationFn: (body) => taskBound && taskRunId != null ? tasksApi.restartWebAuthoring(taskRunId) : webAgentApi.start(projectId, body),
  });
  const closeSession = useMutation<TaskWebAuthoringWorkspace | WebAgentSession, Error, number>({
    mutationFn: (sessionId) => taskBound && taskRunId != null ? tasksApi.closeWebAuthoring(taskRunId) : webAgentApi.close(sessionId),
  });
  const promote = useMutation({
    mutationFn: ({ sessionId, body }: { sessionId: number; body: WebAgentPromoteBody }) =>
      taskBound && taskRunId != null ? tasksApi.promoteWebAuthoring(taskRunId, body) : webAgentApi.promote(sessionId, body),
  });

  /** 切换对话时关闭当前浏览器上下文，避免把一个会话的页面状态借给另一个对话。 */
  const selectAgentSession = useCallback((nextId: number) => {
    if (nextId === agentSessionId) return;
    turn.reset();
    setAgentSessionId(nextId);
    if (agentSessionId != null && webSessionId != null) {
      setWebSessionId(null);
      closeSession.mutate(webSessionId, {
        onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['project', projectId, 'web-agent'] }),
        onError: (e) => void message.error(getErrorMessage(e, '关闭旧浏览器会话失败')),
      });
    }
  }, [agentSessionId, turn, webSessionId, closeSession, queryClient, projectId, message]);

  const invalidate = useCallback((sessionId: number | null = agentSessionId) => {
    if (sessionId != null) {
      void queryClient.invalidateQueries({ queryKey: ['agent', 'session', sessionId] });
      void queryClient.invalidateQueries({ queryKey: ['agent', 'workspace', sessionId] });
    }
    void queryClient.invalidateQueries({ queryKey: ['agent', 'sessions', projectId] });
    void queryClient.invalidateQueries({ queryKey: ['project', projectId, 'web-agent'] });
    if (taskRunId != null) void queryClient.invalidateQueries({ queryKey: ['task-web-authoring', taskRunId] });
  }, [queryClient, agentSessionId, projectId, taskRunId]);

  /** 发消息或动作前确保存在对话会话；智能体会话按 Agent 会话创建。
   *  失败必须显式提示——否则按钮永久卡在 loading，用户以为智能体在思考。 */
  const withAgentSession = useCallback(async (body: SendMessageRequest) => {
    if (webSessionId == null || session?.status !== 'ACTIVE' || turnBusy.current) return;
    // mutation 状态完成 React 重绘前也拦住快速双击，避免并发创建两个 Agent turn。
    turnBusy.current = true;
    try {
      let targetAgentSessionId = agentSessionId;
      if (taskBound) {
        await turn.mutateAsync({ sessionId: targetAgentSessionId ?? 0, body: { ...body, web_session_id: webSessionId } });
        invalidate(targetAgentSessionId);
        return;
      }
      if (targetAgentSessionId == null) {
        const created = await createAgentSession.mutateAsync();
        setAgentSessionId(created.id);
        targetAgentSessionId = created.id;
        void queryClient.invalidateQueries({ queryKey: ['agent', 'sessions', projectId] });
      }
      if (targetAgentSessionId == null) return;
      await turn.mutateAsync({
        sessionId: targetAgentSessionId,
        body: { ...body, web_session_id: webSessionId },
      });
      invalidate(targetAgentSessionId);
    } catch (e) {
      void message.error(getErrorMessage(e, '智能体处理失败，请重试'));
    } finally {
      turnBusy.current = false;
    }
  }, [taskBound, webSessionId, session?.status, agentSessionId, projectId, turn, createAgentSession, invalidate, queryClient, message]);

  const doCreateAgentSession = useCallback(() => {
    if (turnBusy.current) return;
    turnBusy.current = true;
    createAgentSession.mutate(undefined, {
      onSuccess: (created) => {
        selectAgentSession(created.id);
        void queryClient.invalidateQueries({ queryKey: ['agent', 'sessions', projectId] });
        void message.success('Web 智能体对话已创建');
      },
      onError: (e) => void message.error(getErrorMessage(e, '创建对话失败')),
      onSettled: () => { turnBusy.current = false; },
    });
  }, [createAgentSession, selectAgentSession, queryClient, projectId, message]);

  const doStart = useCallback((body: WebAgentStartBody) => {
    startSession.mutate(body, {
      onSuccess: (created) => {
        if (taskBound) {
          if (!('agent_session' in created)) return;
          const updated = created;
          setAgentSessionId(updated.agent_session.id);
          setWebSessionId(updated.web_session.id);
          void queryClient.invalidateQueries({ queryKey: ['task-web-authoring', taskRunId] });
          void message.success('任务受控浏览器工作区已启动');
          return;
        }
        if ('agent_session' in created) return;
        const webSession = created;
        setWebSessionId(webSession.id);
        queryClient.setQueryData<Paginated<WebAgentSession>>(
          ['project', projectId, 'web-agent', 'sessions'],
          (current) => current
            ? { ...current, items: [webSession, ...current.items.filter((item) => item.id !== webSession.id)].slice(0, 20) }
            : current,
        );
        void message.success('受控会话已启动');
        void queryClient.invalidateQueries({ queryKey: ['project', projectId, 'web-agent'] });
      },
      onError: (e) => void message.error(getErrorMessage(e, '启动会话失败')),
    });
  }, [startSession, message, queryClient, projectId, taskBound, taskRunId]);

  const doClose = useCallback(() => {
    if (webSessionId == null) return;
    closeSession.mutate(webSessionId, {
      onSuccess: (closed) => {
        if (taskBound) {
          if (!('agent_session' in closed)) return;
          const updated = closed;
          setWebSessionId(updated.web_session.id);
          void queryClient.invalidateQueries({ queryKey: ['task-web-authoring', taskRunId] });
          void message.success('任务浏览器会话已关闭');
          return;
        }
        if ('agent_session' in closed) return;
        const webSession = closed;
        queryClient.setQueryData<Paginated<WebAgentSession>>(
          ['project', projectId, 'web-agent', 'sessions'],
          (current) => current
            ? { ...current, items: current.items.map((item) => item.id === webSession.id ? webSession : item) }
            : current,
        );
        void message.success('会话已关闭');
        void queryClient.invalidateQueries({ queryKey: ['project', projectId, 'web-agent'] });
      },
      onError: (e) => void message.error(getErrorMessage(e, '关闭会话失败')),
    });
  }, [webSessionId, closeSession, message, queryClient, projectId, taskBound, taskRunId]);

  /** 恢复本项目中仍活跃的浏览器会话；切换时先关闭当前句柄，避免占满并发槽。 */
  const selectWebSession = useCallback((nextId: number) => {
    if (taskBound) return;
    if (nextId === webSessionId) return;
    if (webSessionId == null) {
      setWebSessionId(nextId);
      return;
    }
    closeSession.mutate(webSessionId, {
      onSuccess: () => {
        setWebSessionId(nextId);
        void queryClient.invalidateQueries({ queryKey: ['project', projectId, 'web-agent'] });
      },
      onError: (e) => void message.error(getErrorMessage(e, '切换会话时关闭旧浏览器失败')),
    });
  }, [taskBound, webSessionId, closeSession, queryClient, projectId, message]);

  /** 提升：后端只取会话内已确认的步骤生成未确认草稿，随后跳转用例管理页人工确认。 */
  const onPromote = useCallback((name: string, steps: WebCaseInput['steps']) => {
    if (webSessionId == null || !steps.length) {
      void message.warning('尚无可提升的步骤');
      return;
    }
    const sessionId = webSessionId;
    modal.confirm({
      title: '提升为正式 Web 用例？',
      content: '后端只取本会话中已确认执行的步骤；将生成一个未确认草稿，需在 Web UI 自动化页人工确认后才能执行。',
      onOk: async () => {
        try {
          const created = await promote.mutateAsync({ sessionId, body: { name: name || undefined } });
          void message.success(`已生成用例「${created.name}」（未确认）`);
          navigate(taskBound ? `/console/web-ui?caseId=${created.id}&projectId=${projectId}` : '/console/web-ui');
        } catch (e) {
          void message.error(getErrorMessage(e, '提升失败'));
        }
      },
    });
  }, [webSessionId, modal, promote, message, navigate, taskBound, projectId]);

  const workspaceData = (
    turn.data?.session.id === agentSessionId
      ? turn.data.workspace
      : taskBound ? taskWorkspace.data?.workspace ?? null : workspace.data ?? null
  ) as WebWorkspace | null;
  // 刷新后原浏览器句柄已失效；切换到新浏览器时，在发出新目标前隐藏旧会话的提案、
  // 观测和快捷动作，避免把旧步骤提升到新会话或误以为它描述当前页面。
  const visibleWorkspace = workspaceData && workspaceData.web_agent_session_id === webSessionId
    ? workspaceData
    : null;
  // 本轮新增消息与历史消息按 id 去重：invalidate 后 refetch 会把同一条消息带回两次，
  // React key 冲突会导致列表错乱。
  const messages = useMemo(() => {
    const seen = new Set<number>();
    const currentTurnMessages = turn.data?.session.id === agentSessionId ? turn.data.messages : [];
    const history = taskBound ? taskWorkspace.data?.messages ?? [] : detail.data?.messages ?? [];
    return [...history, ...currentTurnMessages].filter((m) => {
      if (seen.has(m.id)) return false;
      seen.add(m.id);
      return true;
    });
  }, [detail.data, taskBound, taskWorkspace.data?.messages, turn.data, agentSessionId]);

  if (taskContextRequested && !taskBound) return <Alert type="error" showIcon message="任务工作区链接缺少有效的任务或运行编号" />;
  if (taskBound ? taskWorkspace.isPending : envs.isPending || auth.isPending || sessions.isPending || agentSessions.isPending) return <LoadingState tip="加载 Web 智能体配置…" />;
  const failed = taskBound ? taskWorkspace.error : envs.error || auth.error || sessions.error || agentSessions.error;
  if (failed) return <ErrorState error={failed} onRetry={() => { if (taskBound) void taskWorkspace.refetch(); else { void envs.refetch(); void auth.refetch(); void sessions.refetch(); void agentSessions.refetch(); } }} />;
  if (taskBound && taskWorkspace.data && (
    taskWorkspace.data.task_id !== taskId
    || taskWorkspace.data.run.id !== taskRunId
    || taskWorkspace.data.run.task_id !== taskId
  )) return <Alert type="error" showIcon message="任务与运行编号不匹配" description={<Link to={`/console/tasks/${taskWorkspace.data.task_id}?runId=${taskWorkspace.data.run.id}`}>打开服务端确认的任务运行</Link>} />;

  const webChats = (agentSessions.data ?? []).filter((s) =>
    s.title === 'Web 智能体会话' || s.title?.startsWith('Web UI 智能体'),
  );

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {taskBound && taskWorkspace.data && (
        <Card size="small" title="任务 Web 工作区">
          <Space direction="vertical">
            <Typography.Text>项目 #{taskWorkspace.data.project_id} · 任务 #{taskWorkspace.data.task_id} · 运行 #{taskWorkspace.data.run.run_number} · UI Worker #{taskWorkspace.data.agent.id}</Typography.Text>
            <Link to={`/console/tasks/${taskWorkspace.data.task_id}?runId=${taskWorkspace.data.run.id}`}>返回任务运行详情</Link>
          </Space>
        </Card>
      )}
      {!taskBound && <ConversationCard
        sessions={webChats}
        value={agentSessionId}
        loading={createAgentSession.isPending}
        pending={turn.isPending || closeSession.isPending || createAgentSession.isPending}
        onChange={selectAgentSession}
        onCreate={doCreateAgentSession}
      />}
      <SetupCard
        environments={envRows}
        auth={authRows}
        sessions={taskBound ? (session ? [session] : []) : sessions.data?.items ?? []}
        session={session}
        taskBound={taskBound}
        busy={startSession.isPending || closeSession.isPending || turn.isPending || createAgentSession.isPending}
        closing={closeSession.isPending}
        onStart={doStart}
        onSelectSession={selectWebSession}
        onClose={doClose}
      />
      <Row gutter={16} align="stretch">
        <Col xs={24} lg={12}>
          <ChatPanel
            webSessionId={webSessionId}
            webSessionActive={session?.status === 'ACTIVE'}
            messages={messages}
            workspace={visibleWorkspace}
        pending={turn.isPending || closeSession.isPending || createAgentSession.isPending}
            onSend={(content) => void withAgentSession({ content })}
            onAction={(action) => void withAgentSession({ action })}
          />
        </Col>
        <Col xs={24} lg={12}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <SessionPanel session={session} workspace={visibleWorkspace} />
            <ObservationPanel observation={visibleWorkspace?.web_observation ?? null} />
            <ProposalPanel workspace={visibleWorkspace} promoting={promote.isPending} onPromote={onPromote} />
          </Space>
        </Col>
      </Row>
    </Space>
  );
}

/** 页面入口：未选项目时提示，其余交给工作区处理。 */
export function ConsoleWebUIAgentPage() {
  const { currentProjectId } = useConsoleScope();
  const [searchParams] = useSearchParams();
  const taskContext = searchParams.has('taskId') && searchParams.has('runId');
  const requestedProjectId = Number(searchParams.get('projectId'));
  const projectMismatch = taskContext && Number.isSafeInteger(requestedProjectId) && requestedProjectId > 0 && currentProjectId !== requestedProjectId;
  return (
    <PageContainer>
      {projectMismatch
        ? <EmptyState description={`请先切换到项目 #${requestedProjectId}，再打开该任务的 Web 工作区`} />
        : currentProjectId != null
        ? <Workspace key={currentProjectId} projectId={currentProjectId} />
        : <EmptyState description="请先在顶部选择一个项目" />
      }
    </PageContainer>
  );
}
