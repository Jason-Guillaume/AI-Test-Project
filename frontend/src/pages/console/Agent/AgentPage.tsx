import { collectPages } from '@/shared/api/pagination';
// 接口测试 Agent 页面：三栏布局（会话列表 · 对话流 · 工作区）。
//
// 功能：
//   - 左：当前项目的会话列表，支持新建 / 切换 / 删除；
//   - 中：对话流，支持自然语言消息 + 快捷操作按钮（确认测试点 / 确认用例 / 执行等）；
//   - 右：工作区面板，按 Tabs 展示测试计划 / 测试点 / 测试用例 / 执行结果。
//
// 数据流：
//   - 会话列表 useQuery(['agent','sessions',projectId])；
//   - 会话详情 useQuery(['agent','session',sessionId])；
//   - 工作区 useQuery(['agent','workspace',sessionId])；
//   - 发消息 useMutation → invalidateQueries(['agent'])。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  App,
  Alert,
  Button,
  Checkbox,
  Divider,
  Empty,
  Flex,
  Input,
  List,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  PlusOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { agentApi } from '@/features/agent/api/agent';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import { projectsApi } from '@/features/projects/api/projects';
import { notificationChannelsApi } from '@/features/notifications/api/notificationChannels';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState } from '@/shared/ui/PageState';
import type { AgentAction, AgentWorkspace } from '@/features/agent/contracts';
import { MessageBubble, STAGE_LABELS } from './AgentPanels';
import { AgentWorkspacePanel } from './AgentWorkspacePanel';
import { explicitSelection } from './agentSelection.mjs';


// 项目变更只重置 Agent 工作台本身，不重挂载整个控制台。
export function AgentPage() {
  const { currentProjectId } = useConsoleScope();
  if (currentProjectId == null) {
    return <div style={{ padding: 24 }}><EmptyState description="请先在顶部选择一个项目" /></div>;
  }
  return <AgentProjectPage key={currentProjectId} projectId={currentProjectId} />;
}

interface AgentProjectPageProps {
  projectId: number;
}

function AgentProjectPage({ projectId: currentProjectId }: AgentProjectPageProps) {
  const { message: msg, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [selectedSessionIds, setSelectedSessionIds] = useState<number[]>([]);
  const [activePanel, setActivePanel] = useState<'sessions' | 'chat' | 'workspace'>('chat');
  const [inputValue, setInputValue] = useState('');
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([]);
  const [selectedPointIds, setSelectedPointIds] = useState<number[]>([]);
  const [hasNewMessages, setHasNewMessages] = useState(false);
  const [mediumLayout, setMediumLayout] = useState(false);
  const [sessionsCollapsed, setSessionsCollapsed] = useState(false);
  const [workspaceCollapsed, setWorkspaceCollapsed] = useState(false);
  const workspaceShellRef = useRef<HTMLDivElement>(null);
  const priorMediumLayout = useRef<boolean | null>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);
  const previousMessageCountRef = useRef(0);

  useEffect(() => {
    const element = workspaceShellRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => setMediumLayout(entry.contentRect.width <= 1100));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (priorMediumLayout.current === mediumLayout) return;
    priorMediumLayout.current = mediumLayout;
    setSessionsCollapsed(mediumLayout);
  }, [mediumLayout]);
  const selectedSessionRef = useRef<number | null>(null);
  const inputValueRef = useRef('');
  const selectionInitializedForRef = useRef<number | null>(null);

  useEffect(() => { inputValueRef.current = inputValue; }, [inputValue]);

  const selectSession = useCallback((sessionId: number | null) => {
    selectedSessionRef.current = sessionId;
    selectionInitializedForRef.current = null;
    previousMessageCountRef.current = 0;
    nearBottomRef.current = true;
    setHasNewMessages(false);
    setSelectedSessionId(sessionId);
    setInputValue('');
    setSelectedCaseIds([]);
    setSelectedPointIds([]);
    setActivePanel('chat');
  }, []);

  // ---- 查询 ----
  const sessionsQuery = useQuery({
    queryKey: ['agent', 'sessions', currentProjectId],
    queryFn: () => agentApi.listSessions(currentProjectId!),
    enabled: currentProjectId != null,
  });
  useEffect(() => {
    const visibleIds = new Set((sessionsQuery.data ?? []).map((session) => session.id));
    setSelectedSessionIds((ids) => ids.filter((id) => visibleIds.has(id)));
  }, [sessionsQuery.data]);

  const sessionDetailQuery = useQuery({
    queryKey: ['agent', 'session', currentProjectId, selectedSessionId],
    queryFn: () => agentApi.getSessionDetail(selectedSessionId!),
    enabled: selectedSessionId != null,
  });

  const workspaceQuery = useQuery({
    queryKey: ['agent', 'workspace', currentProjectId, selectedSessionId],
    queryFn: () => agentApi.getWorkspace(selectedSessionId!),
    enabled: selectedSessionId != null,
  });

  const envsQuery = useQuery({
    queryKey: ['agent', 'environments', currentProjectId],
    queryFn: () => projectsApi.listEnvironments(currentProjectId!),
    enabled: currentProjectId != null,
    staleTime: 60_000,
  });

  // 飞书通知渠道候选项：确认报告时选择推送渠道（只显示启用且已配置 webhook 的渠道）。
  const channelsQuery = useQuery({
    queryKey: ['agent', 'notification-channels', currentProjectId],
    queryFn: () => collectPages((page) => notificationChannelsApi.list(currentProjectId!, { page, page_size: 100 })),
    enabled: currentProjectId != null,
    staleTime: 60_000,
  });
  const notifyChannels = (channelsQuery.data?.items ?? []).filter(
    (c) => c.enabled && c.webhook_configured,
  );

  // ---- 自动选中当前项目的第一个会话；切项目时由 key 同步清空整个 Agent 页状态 ----
  useEffect(() => {
    if (!sessionsQuery.data || sessionsQuery.isFetching) return;
    const selectedExists = sessionsQuery.data.some((session) => session.id === selectedSessionId);
    if (selectedSessionId != null && !selectedExists) {
      selectSession(null);
      return;
    }
    if (selectedSessionId == null && sessionsQuery.data.length > 0) {
      selectSession(sessionsQuery.data[0].id);
    }
  }, [sessionsQuery.data, sessionsQuery.isFetching, selectedSessionId, selectSession]);

  const messages = sessionDetailQuery.data?.messages ?? [];
  useEffect(() => {
    if (!sessionDetailQuery.isSuccess) return;
    const scroller = chatScrollRef.current;
    const count = messages.length;
    if (count > previousMessageCountRef.current) {
      if (previousMessageCountRef.current === 0 || nearBottomRef.current) {
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
        nearBottomRef.current = true;
        setHasNewMessages(false);
      } else {
        setHasNewMessages(true);
      }
    }
    previousMessageCountRef.current = count;
  }, [messages.length, sessionDetailQuery.isSuccess]);

  const workspace: AgentWorkspace | null = workspaceQuery.data ?? null;
  const availablePointIds = useMemo(() => (workspace?.test_points ?? [])
    .map((point) => point.id)
    .filter((id): id is number => typeof id === 'number'), [workspace]);
  const availableCaseIds = useMemo(() => (workspace?.stage === 'READY_TO_EXECUTE'
    ? workspace.confirmed_case_ids ?? []
    : (workspace?.test_cases ?? [])
        .map((testCase) => testCase.id)
        .filter((id): id is number => typeof id === 'number')), [workspace]);

  // 首次装载 READY_TO_EXECUTE 会话时恢复服务器记录的确认范围；之后只剔除已失效项。
  useEffect(() => {
    if (selectedSessionId == null || !workspace) return;
    if (selectionInitializedForRef.current !== selectedSessionId) {
      selectionInitializedForRef.current = selectedSessionId;
      setSelectedCaseIds(workspace.stage === 'READY_TO_EXECUTE' ? workspace.confirmed_case_ids ?? [] : []);
      setSelectedPointIds([]);
      return;
    }
    setSelectedCaseIds((ids) => ids.filter((id) => availableCaseIds.includes(id)));
    setSelectedPointIds((ids) => ids.filter((id) => availablePointIds.includes(id)));
  }, [availableCaseIds, availablePointIds, selectedSessionId, workspace]);

  // ---- 变更操作 ----
  const createMutation = useMutation({
    mutationFn: () => agentApi.createSession(currentProjectId!),
    onSuccess: (session) => {
      selectSession(session.id);
      queryClient.invalidateQueries({ queryKey: ['agent', 'sessions', currentProjectId] });
      msg.success('会话已创建');
    },
    onError: (e) => msg.error(getErrorMessage(e, '创建会话失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (sessionId: number) => agentApi.deleteSession(sessionId),
    onSuccess: (_data, deletedId) => {
      if (deletedId === selectedSessionRef.current) selectSession(null);
      queryClient.invalidateQueries({ queryKey: ['agent', 'sessions', currentProjectId] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
      setSelectedSessionIds((ids) => ids.filter((id) => id !== deletedId));
      msg.success('会话已移入回收站');
    },
    onError: (e) => msg.error(getErrorMessage(e, '删除会话失败')),
  });

  const deleteSelectedSessions = () => modal.confirm({
    title: `将选中的 ${selectedSessionIds.length} 个 Agent 会话移入回收站？`,
    content: '会话消息与原有测试追溯关系会保留；任务运行关联的会话属于执行证据，不可删除。',
    okText: '移入回收站', cancelText: '取消', okButtonProps: { danger: true },
    onOk: async () => {
      try {
        const receipt = await dataLifecycleApi.deleteMany('agent_session', currentProjectId, selectedSessionIds);
        setSelectedSessionIds([]);
        if (selectedSessionId != null && selectedSessionIds.includes(selectedSessionId)) selectSession(null);
        queryClient.invalidateQueries({ queryKey: ['agent', 'sessions', currentProjectId] });
        queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
        if (receipt.failed) {
          modal.info({
            title: `成功 ${receipt.succeeded} 个，失败 ${receipt.failed} 个`,
            content: <Space direction="vertical" style={{ width: '100%' }}>
              {receipt.items.filter((item) => !item.succeeded).map((item) => (
                <Alert key={item.id} type="error" showIcon message={`Agent 会话 #${item.id}`} description={item.error ?? '删除失败'} />
              ))}
            </Space>,
          });
        } else msg.success(`已将 ${receipt.succeeded} 个 Agent 会话移入回收站`);
      } catch (error) { msg.error(getErrorMessage(error, '批量删除失败')); }
    },
  });

  const sendMutation = useMutation({
    mutationFn: (variables: {
      projectId: number;
      sessionId: number;
      body: {
      content?: string;
      action?: AgentAction;
      point_ids?: number[];
      case_ids?: number[];
      environment_id?: number | null;
      channel_id?: number | null;
      };
      submittedText?: string;
    }) => agentApi.sendMessage(variables.sessionId, variables.body),
    onSuccess: async (result, variables) => {
      const detailKey = ['agent', 'session', variables.projectId, variables.sessionId];
      const workspaceKey = ['agent', 'workspace', variables.projectId, variables.sessionId];
      queryClient.setQueryData(workspaceKey, result.workspace);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: detailKey }),
        queryClient.invalidateQueries({ queryKey: workspaceKey }),
      ]);
      if (selectedSessionRef.current !== variables.sessionId) return;
      if (variables.body.action === 'confirm_points') setSelectedPointIds([]);
      if (variables.body.action === 'confirm_cases') setSelectedCaseIds(result.workspace.confirmed_case_ids ?? []);
      if (variables.submittedText && inputValueRef.current === variables.submittedText) {
        inputValueRef.current = '';
        setInputValue('');
      }
    },
  });

  // ---- 发送自然语言消息 ----
  const handleSend = useCallback(() => {
    const text = inputValue.trim();
    if (!text || selectedSessionId == null) return;
    sendMutation.mutate({
      projectId: currentProjectId!,
      sessionId: selectedSessionId,
      body: { content: text },
      submittedText: text,
    });
  }, [currentProjectId, inputValue, selectedSessionId, sendMutation]);

  // ---- 发送快捷操作 ----
  const handleAction = useCallback(
    (action: string) => {
      if (selectedSessionId == null) return;
      const submitAction = (body: {
        action: AgentAction;
        point_ids?: number[];
        case_ids?: number[];
        environment_id?: number | null;
        channel_id?: number | null;
      }) => sendMutation.mutate({
        projectId: currentProjectId!,
        sessionId: selectedSessionId,
        body,
      });
      if (action === 'execute') {
        const caseIds = explicitSelection(selectedCaseIds, availableCaseIds);
        if (!caseIds) {
          msg.warning('请先选择至少一条当前会话中已确认的用例');
          return;
        }
        // 执行需要 environment_id
        const envs = envsQuery.data?.items ?? [];
        if (envs.length === 0) {
          msg.warning('请先在环境配置中创建至少一个环境');
          return;
        }
        let envId: number | null = null;
        modal.confirm({
          title: '选择执行环境',
          content: (
            <div>
              <div>本次将执行已选的 {caseIds.length} 条用例。</div>
              <Select
                style={{ width: '100%', marginTop: 8 }}
                options={envs.map((e) => ({ label: e.display_name || e.name, value: e.id }))}
                placeholder="请选择环境"
                onChange={(v) => { envId = v; }}
              />
            </div>
          ),
          onOk: () => {
            if (envId == null) {
              msg.warning('请选择一个环境');
              return Promise.reject();
            }
            submitAction({ action: 'execute', environment_id: envId, case_ids: caseIds });
          },
        });
        return;
      }
      if (action === 'confirm_report') {
        // 报告已生成并暂停在 REPORT_REVIEW，需人工确认后才会推送飞书（不自动发送）。
        if (notifyChannels.length === 0) {
          msg.warning('没有可用的飞书通知渠道，请先到「飞书通知」配置并启用渠道');
          return;
        }
        let channelId: number | null = null;
        modal.confirm({
          title: '确认报告并发送飞书通知',
          content: (
            <div>
              <div style={{ marginBottom: 8 }}>报告已生成，选择要推送的渠道：</div>
              <Select
                style={{ width: '100%' }}
                options={notifyChannels.map((c) => ({
                  label: `${c.name}（${c.notify_condition}）`,
                  value: c.id,
                }))}
                placeholder="请选择通知渠道"
                onChange={(v) => {
                  channelId = v;
                }}
              />
              <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
                Webhook 与签名密钥不会出现在对话或报告中；发送失败不影响报告状态。
              </div>
            </div>
          ),
          onOk: () => {
            if (channelId == null) {
              msg.warning('请选择一个通知渠道');
              return Promise.reject();
            }
            submitAction({ action: 'confirm_report', channel_id: channelId });
          },
        });
        return;
      }
      if (action === 'confirm_points') {
        const pointIds = explicitSelection(selectedPointIds, availablePointIds);
        if (!pointIds) {
          msg.warning('请先选择至少一个当前会话中的测试点');
          return;
        }
        submitAction({ action: 'confirm_points', point_ids: pointIds });
        return;
      }
      if (action === 'confirm_cases') {
        const caseIds = explicitSelection(selectedCaseIds, availableCaseIds);
        if (!caseIds) {
          msg.warning('请先选择至少一条当前会话中的用例');
          return;
        }
        submitAction({ action: 'confirm_cases', case_ids: caseIds });
        return;
      }
      submitAction({ action: action as AgentAction });
    },
    [currentProjectId, selectedSessionId, envsQuery.data, notifyChannels, sendMutation, selectedPointIds, selectedCaseIds, availablePointIds, availableCaseIds, msg, modal],
  );

  // ---- 渲染 ----
  return (
    <div className="agent-workspace-shell" ref={workspaceShellRef}>
      <div className="agent-workspace-toolbar" aria-label="工作区布局">
        <Button aria-controls="agent-workspace-sessions" aria-expanded={!sessionsCollapsed} onClick={() => setSessionsCollapsed((value) => !value)}>
          {sessionsCollapsed ? '显示会话' : '隐藏会话'}
        </Button>
        <Button aria-controls="agent-workspace-panel" aria-expanded={!workspaceCollapsed} onClick={() => setWorkspaceCollapsed((value) => !value)}>
          {workspaceCollapsed ? '展开结果' : '收起结果'}
        </Button>
      </div>
      <div className="agent-workspace-tabs" role="group" aria-label="AI 助手面板">
        <Button type={activePanel === 'sessions' ? 'primary' : 'default'} aria-pressed={activePanel === 'sessions'} onClick={() => setActivePanel('sessions')}>会话</Button>
        <Button type={activePanel === 'chat' ? 'primary' : 'default'} aria-pressed={activePanel === 'chat'} onClick={() => setActivePanel('chat')}>对话</Button>
        <Button type={activePanel === 'workspace' ? 'primary' : 'default'} aria-pressed={activePanel === 'workspace'} onClick={() => setActivePanel('workspace')}>工作区</Button>
      </div>
      <div className="agent-workspace" data-panel={activePanel} data-sessions-collapsed={sessionsCollapsed} data-workspace-collapsed={workspaceCollapsed}>
      {/* 左栏：会话列表 */}
      <div className="agent-workspace-panel agent-workspace-sessions" id="agent-workspace-sessions">
        <Flex justify="space-between" align="center" style={{ marginBottom: 8 }}>
          <Typography.Text strong style={{ fontSize: 14 }}>会话</Typography.Text>
          <Space size={4}>
            <Button danger size="small" disabled={!selectedSessionIds.length} onClick={deleteSelectedSessions}>
              批量删除（{selectedSessionIds.length}）
            </Button>
            <Button size="small" onClick={() => navigate('/console/recycle-bin')}>回收站</Button>
            <Button
              type="primary"
              size="small"
              icon={<PlusOutlined />}
              aria-label="新建 Agent 会话"
              onClick={() => createMutation.mutate()}
              loading={createMutation.isPending}
            />
          </Space>
        </Flex>
        {sessionsQuery.data && sessionsQuery.data.length > 0 && (
          <Checkbox
            checked={selectedSessionIds.length === sessionsQuery.data.length}
            indeterminate={selectedSessionIds.length > 0 && selectedSessionIds.length < sessionsQuery.data.length}
            onChange={(event) => {
              if (event.target.checked && sessionsQuery.data!.length > 100) {
                msg.warning('一次最多选择 100 个 Agent 会话');
                setSelectedSessionIds(sessionsQuery.data!.slice(0, 100).map((session) => session.id));
              } else setSelectedSessionIds(event.target.checked ? sessionsQuery.data!.map((session) => session.id) : []);
            }}
            style={{ marginBottom: 8 }}
          >全选当前项目会话</Checkbox>
        )}
        <Divider style={{ margin: '4px 0 8px' }} />
        <div className="agent-workspace-scroll">
          {sessionsQuery.isPending ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spin size="small" /></div>
          ) : sessionsQuery.isError ? (
            <ErrorState error={sessionsQuery.error} onRetry={() => void sessionsQuery.refetch()} />
          ) : sessionsQuery.data && sessionsQuery.data.length > 0 ? (
            <List
              size="small"
              dataSource={sessionsQuery.data}
              renderItem={(item) => (
                <List.Item
                  onClick={() => selectSession(item.id)}
                  style={{
                    cursor: 'pointer',
                    padding: '6px 8px',
                    borderRadius: 6,
                    background: selectedSessionId === item.id ? '#e6f7ff' : 'transparent',
                    marginBottom: 2,
                  }}
                  actions={[
                    <Popconfirm
                      key="del"
                      title="将会话移入回收站？"
                      description="消息历史与测试追溯关系会保留，可从回收站恢复。"
                      onConfirm={(e) => { e?.stopPropagation(); deleteMutation.mutate(item.id); }}
                    >
                      <Button type="text" size="small" icon={<DeleteOutlined />} danger aria-label={`删除会话 ${item.title || item.id}`}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Popconfirm>,
                  ]}
                >
                  <Checkbox
                    checked={selectedSessionIds.includes(item.id)}
                    aria-label={`选择会话 ${item.title || item.id}`}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => {
                      if (!event.target.checked) setSelectedSessionIds((ids) => ids.filter((id) => id !== item.id));
                      else if (selectedSessionIds.length >= 100) msg.warning('一次最多选择 100 个 Agent 会话');
                      else setSelectedSessionIds((ids) => [...ids, item.id]);
                    }}
                    style={{ marginRight: 8 }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.title || '新会话'}
                    </div>
                    <Tag color={item.current_stage === 'COMPLETED' ? 'green' : item.current_stage === 'FAILED' ? 'red' : 'blue'} style={{ fontSize: 11 }}>
                      {STAGE_LABELS[item.current_stage] ?? item.current_stage}
                    </Tag>
                  </div>
                </List.Item>
              )}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" style={{ padding: 16 }} />
          )}
        </div>
      </div>

      {/* 中栏：对话流 */}
      <div className="agent-workspace-panel agent-workspace-chat" id="agent-workspace-chat">
        <div
          className="agent-workspace-scroll agent-chat-scroll"
          style={{ padding: 8 }}
          ref={chatScrollRef}
          onScroll={(event) => {
            const node = event.currentTarget;
            nearBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight <= 80;
            if (nearBottomRef.current) setHasNewMessages(false);
          }}
        >
          {selectedSessionId == null ? (
            <Empty description="请选择或创建一个会话" style={{ marginTop: 80 }} />
          ) : sessionDetailQuery.isPending ? (
            <div style={{ textAlign: 'center', padding: 48 }}><Spin /></div>
          ) : sessionDetailQuery.isError ? (
            <ErrorState error={sessionDetailQuery.error} onRetry={sessionDetailQuery.refetch} />
          ) : messages.length === 0 ? (
            <Empty description="发送消息开始对话，例如：帮我生成 /api/users 接口的测试点" style={{ marginTop: 80 }} />
          ) : (
            messages.map((m) => <MessageBubble key={m.id} message={m} />)
          )}
          {hasNewMessages && (
            <Button
              className="agent-new-messages"
              size="small"
              onClick={() => {
                const node = chatScrollRef.current;
                if (node) node.scrollTop = node.scrollHeight;
                nearBottomRef.current = true;
                setHasNewMessages(false);
              }}
            >
              有新消息，回到最新
            </Button>
          )}
        </div>

        {sendMutation.isError && sendMutation.variables?.sessionId === selectedSessionId && (
          <Alert
            type="error"
            showIcon
            message="上次操作失败"
            description={getErrorMessage(sendMutation.error, '消息发送失败；输入内容仍保留')}
            action={(
              <Button
                size="small"
                disabled={sendMutation.isPending}
                onClick={() => sendMutation.mutate(sendMutation.variables!)}
              >
                重试上次操作
              </Button>
            )}
            style={{ marginBottom: 8 }}
          />
        )}
        {envsQuery.isError && workspace?.suggested_actions.includes('execute') && (
          <Alert
            type="error"
            showIcon
            message="读取执行环境失败"
            action={<Button size="small" onClick={() => void envsQuery.refetch()}>重试</Button>}
            style={{ marginBottom: 8 }}
          />
        )}
        {channelsQuery.isError && workspace?.suggested_actions.includes('confirm_report') && (
          <Alert
            type="error"
            showIcon
            message="读取通知渠道失败"
            action={<Button size="small" onClick={() => void channelsQuery.refetch()}>重试</Button>}
            style={{ marginBottom: 8 }}
          />
        )}

        {/* 输入框 */}
        <Flex gap="small" className="agent-message-input">
          <Input.TextArea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onPressEnter={(e) => { if (!e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); handleSend(); } }}
            placeholder="输入测试需求，例如：生成 /api/orders 接口的测试点"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={selectedSessionId == null || sendMutation.isPending}
            style={{ flex: 1 }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSend}
            aria-label="发送消息"
            disabled={!inputValue.trim() || selectedSessionId == null || sendMutation.isPending}
          />
        </Flex>
        {sendMutation.isPending && (
          <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
            Agent 正在处理中…
          </Typography.Text>
        )}
      </div>

      {/* 右栏：工作区 */}
      <AgentWorkspacePanel
        selectedSessionId={selectedSessionId}
        workspace={workspace}
        loading={workspaceQuery.isPending}
        error={workspaceQuery.error}
        actionsPending={sendMutation.isPending}
        onRetry={() => void workspaceQuery.refetch()}
        onAction={handleAction}
        selectedCaseIds={selectedCaseIds}
        selectedPointIds={selectedPointIds}
        onSelectedCaseIdsChange={setSelectedCaseIds}
        onSelectedPointIdsChange={setSelectedPointIds}
        onOpenReport={() => {
          if (workspace?.report_id != null) navigate(`/console/test-reports/${workspace.report_id}`);
        }}
      />
      </div>
    </div>
  );
}
