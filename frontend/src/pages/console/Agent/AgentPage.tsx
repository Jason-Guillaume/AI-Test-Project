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
  Button,
  Divider,
  Empty,
  Flex,
  Input,
  List,
  Popconfirm,
  Select,
  Spin,
  Tag,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  PlusOutlined,
  RobotOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { agentApi } from '@/features/agent/api/agent';
import { projectsApi } from '@/features/projects/api/projects';
import { notificationChannelsApi } from '@/features/notifications/api/notificationChannels';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState } from '@/shared/ui/PageState';
import type { AgentAction, AgentWorkspace } from '@/features/agent/contracts';
import { MessageBubble, STAGE_ACTION_LABELS, STAGE_LABELS } from './AgentPanels';
import { AgentWorkspacePanel } from './AgentWorkspacePanel';


// ---- 主页面 ----
export function AgentPage() {
  const { message: msg, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const navigate = useNavigate();

  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [activePanel, setActivePanel] = useState<'sessions' | 'chat' | 'workspace'>('chat');
  const [inputValue, setInputValue] = useState('');
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([]);
  const [selectedPointIds, setSelectedPointIds] = useState<number[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // ---- 查询 ----
  const sessionsQuery = useQuery({
    queryKey: ['agent', 'sessions', currentProjectId],
    queryFn: () => agentApi.listSessions(currentProjectId!),
    enabled: currentProjectId != null,
  });

  const sessionDetailQuery = useQuery({
    queryKey: ['agent', 'session', selectedSessionId],
    queryFn: () => agentApi.getSessionDetail(selectedSessionId!),
    enabled: selectedSessionId != null,
  });

  const workspaceQuery = useQuery({
    queryKey: ['agent', 'workspace', selectedSessionId],
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

  // ---- 自动选中第一个会话 ----
  useEffect(() => {
    if (sessionsQuery.data && sessionsQuery.data.length > 0 && selectedSessionId == null) {
      setSelectedSessionId(sessionsQuery.data[0].id);
    }
  }, [sessionsQuery.data, selectedSessionId]);

  // ---- 消息列表自动滚动到底部 ----
  const messages = sessionDetailQuery.data?.messages ?? [];
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  // ---- 变更操作 ----
  const createMutation = useMutation({
    mutationFn: () => agentApi.createSession(currentProjectId!),
    onSuccess: (session) => {
      setSelectedSessionId(session.id);
      setActivePanel('chat');
      queryClient.invalidateQueries({ queryKey: ['agent', 'sessions', currentProjectId] });
      msg.success('会话已创建');
    },
    onError: (e) => msg.error(getErrorMessage(e, '创建会话失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (sessionId: number) => agentApi.deleteSession(sessionId),
    onSuccess: (_data, deletedId) => {
      if (deletedId === selectedSessionId) setSelectedSessionId(null);
      queryClient.invalidateQueries({ queryKey: ['agent', 'sessions', currentProjectId] });
      msg.success('会话已删除');
    },
    onError: (e) => msg.error(getErrorMessage(e, '删除会话失败')),
  });

  const sendMutation = useMutation({
    mutationFn: (body: {
      content?: string;
      action?: AgentAction;
      point_ids?: number[];
      case_ids?: number[];
      environment_id?: number | null;
      channel_id?: number | null;
    }) => agentApi.sendMessage(selectedSessionId!, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent', 'session', selectedSessionId] });
      queryClient.invalidateQueries({ queryKey: ['agent', 'workspace', selectedSessionId] });
      setSelectedPointIds([]);
      setSelectedCaseIds([]);
    },
    onError: (e) => msg.error(getErrorMessage(e, '消息发送失败')),
  });

  // ---- 工作区快照（发消息后优先用 response.workspace，否则用 query）----
  // 仅当 sendMutation 的结果属于当前选中的会话时才使用，否则回退到 query 数据。
  const workspace: AgentWorkspace | null = useMemo(() => {
    const sendData = sendMutation.data;
    if (sendData?.session?.id === selectedSessionId) {
      return sendData.workspace ?? null;
    }
    return workspaceQuery.data ?? null;
  }, [sendMutation.data, workspaceQuery.data, selectedSessionId]);

  // ---- 发送自然语言消息 ----
  const handleSend = useCallback(() => {
    const text = inputValue.trim();
    if (!text || selectedSessionId == null) return;
    setInputValue('');
    sendMutation.mutate({ content: text });
  }, [inputValue, selectedSessionId, sendMutation]);

  // ---- 发送快捷操作 ----
  const handleAction = useCallback(
    (action: string) => {
      if (selectedSessionId == null) return;
      if (action === 'execute') {
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
            <Select
              style={{ width: '100%', marginTop: 8 }}
              options={envs.map((e) => ({ label: e.display_name || e.name, value: e.id }))}
              placeholder="请选择环境"
              onChange={(v) => { envId = v; }}
            />
          ),
          onOk: () => {
            if (envId == null) {
              msg.warning('请选择一个环境');
              return Promise.reject();
            }
            sendMutation.mutate({ action: 'execute' as AgentAction, environment_id: envId, case_ids: selectedCaseIds.length > 0 ? selectedCaseIds : undefined });
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
            sendMutation.mutate({ action: 'confirm_report' as AgentAction, channel_id: channelId });
          },
        });
        return;
      }
      if (action === 'confirm_points') {
        sendMutation.mutate({ action: 'confirm_points' as AgentAction, point_ids: selectedPointIds.length > 0 ? selectedPointIds : undefined });
        return;
      }
      if (action === 'confirm_cases') {
        sendMutation.mutate({ action: 'confirm_cases' as AgentAction, case_ids: selectedCaseIds.length > 0 ? selectedCaseIds : undefined });
        return;
      }
      sendMutation.mutate({ action: action as AgentAction });
    },
    [selectedSessionId, envsQuery.data, notifyChannels, sendMutation, selectedPointIds, selectedCaseIds, msg, modal],
  );

  // ---- 无项目提示 ----
  if (currentProjectId == null) {
    return (
      <div style={{ padding: 24 }}>
        <EmptyState description="请先在顶部选择一个项目" />
      </div>
    );
  }

  // ---- 渲染 ----
  return (
    <div className="agent-workspace-shell">
      <div className="agent-workspace-tabs" role="group" aria-label="AI 助手面板">
        <Button type={activePanel === 'sessions' ? 'primary' : 'default'} aria-pressed={activePanel === 'sessions'} onClick={() => setActivePanel('sessions')}>会话</Button>
        <Button type={activePanel === 'chat' ? 'primary' : 'default'} aria-pressed={activePanel === 'chat'} onClick={() => setActivePanel('chat')}>对话</Button>
        <Button type={activePanel === 'workspace' ? 'primary' : 'default'} aria-pressed={activePanel === 'workspace'} onClick={() => setActivePanel('workspace')}>工作区</Button>
      </div>
      <div className="agent-workspace" data-panel={activePanel}>
      {/* 左栏：会话列表 */}
      <div className="agent-workspace-panel agent-workspace-sessions">
        <Flex justify="space-between" align="center" style={{ marginBottom: 8 }}>
          <Typography.Text strong style={{ fontSize: 14 }}>会话</Typography.Text>
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => createMutation.mutate()}
            loading={createMutation.isPending}
          />
        </Flex>
        <Divider style={{ margin: '4px 0 8px' }} />
        <div className="agent-workspace-scroll">
          {sessionsQuery.isPending ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spin size="small" /></div>
          ) : sessionsQuery.data && sessionsQuery.data.length > 0 ? (
            <List
              size="small"
              dataSource={sessionsQuery.data}
              renderItem={(item) => (
                <List.Item
                  onClick={() => { setSelectedSessionId(item.id); setActivePanel('chat'); }}
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
                      title="确认删除？"
                      onConfirm={(e) => { e?.stopPropagation(); deleteMutation.mutate(item.id); }}
                    >
                      <Button type="text" size="small" icon={<DeleteOutlined />} danger
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Popconfirm>,
                  ]}
                >
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
      <div className="agent-workspace-panel agent-workspace-chat">
        <div className="agent-workspace-scroll" style={{ padding: 8 }} ref={chatEndRef}>
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
        </div>

        {/* 快捷操作按钮 */}
        {workspace && workspace.suggested_actions.length > 0 && (
          <Flex gap="small" wrap style={{ marginBottom: 8 }}>
            {workspace.suggested_actions.map((action) => (
              <Button
                key={action}
                size="small"
                icon={<RobotOutlined />}
                onClick={() => handleAction(action)}
                loading={sendMutation.isPending}
              >
                {STAGE_ACTION_LABELS[action] ?? action}
              </Button>
            ))}
          </Flex>
        )}

        {/* 多选确认提示 */}
        {workspace && workspace.test_cases.length > 0 && workspace.stage === 'TEST_CASE_REVIEW' && (
          <div style={{ marginBottom: 8, fontSize: 12, color: '#999' }}>
            已选 {selectedCaseIds.length}/{workspace.test_cases.length} 条用例
            （可全选 / 勾选后再点击「确认测试用例」）
          </div>
        )}

        {/* 输入框 */}
        <Flex gap="small" className="agent-message-input">
          <Input.TextArea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onPressEnter={(e) => { if (!e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); handleSend(); } }}
            placeholder="输入测试需求，例如：生成 /api/orders 接口的测试点"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={sendMutation.isPending}
            style={{ flex: 1 }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={!inputValue.trim() || sendMutation.isPending}
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
