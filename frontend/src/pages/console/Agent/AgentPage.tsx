import { collectPages } from '@/api/pagination';
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
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Divider,
  Empty,
  Flex,
  Input,
  List,
  Popconfirm,
  Select,
  Spin,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  EyeOutlined,
  PlusOutlined,
  RobotOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { agentApi } from '@/api/agent';
import { projectsApi } from '@/api/projects';
import { notificationChannelsApi } from '@/api/notificationChannels';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { getErrorMessage } from '@/api/client';
import { EmptyState, ErrorState } from '@/components/PageState';
import type { AgentAction, AgentMessage, AgentWorkspace } from '@/types';

// ---- 阶段 → 快捷操作按钮映射（与后端 _STAGE_ACTIONS 对齐）----
const STAGE_ACTION_LABELS: Record<string, string> = {
  confirm_points: '确认测试点',
  confirm_cases: '确认测试用例',
  execute: '执行测试',
  analyze: '分析结果',
  regenerate_points: '重新生成测试点',
  regenerate_cases: '重新生成测试用例',
  confirm_report: '确认报告并发送飞书通知',
  skip_notification: '跳过飞书通知',
};

const STAGE_LABELS: Record<string, string> = {
  UNDERSTANDING: '理解中',
  CONTEXT_LOADING: '加载上下文',
  PLANNING: '规划中',
  TEST_POINT_REVIEW: '测试点待确认',
  TEST_POINT_GENERATED: '测试点已生成',
  TEST_CASE_REVIEW: '用例待确认',
  READY_TO_EXECUTE: '准备执行',
  EXECUTING: '执行中',
  ANALYZING: '分析中',
  REPORT_GENERATING: '报告生成中',
  REPORT_REVIEW: '报告待确认',
  NOTIFYING: '通知发送中',
  COMPLETED: '已完成',
  FAILED: '失败',
  CLARIFY: '等待澄清',
};

/** 报告风险等级 Tag 颜色（与报告页保持一致）。 */
const RISK_TAG_COLOR: Record<string, string> = {
  LOW: 'green',
  MEDIUM: 'gold',
  HIGH: 'orange',
  CRITICAL: 'red',
};
const RISK_LABEL: Record<string, string> = {
  LOW: '低',
  MEDIUM: '中',
  HIGH: '高',
  CRITICAL: '严重',
};

// ---- 消息类型 → 渲染器 ----
function MessageBubble({ message }: { message: AgentMessage }) {
  const navigate = useNavigate();
  const roleIcon = message.role === 'USER' ? '👤' : message.role === 'SYSTEM' ? '⚙️' : '🤖';
  const bgColor =
    message.role === 'USER'
      ? 'background: #e6f7ff;'
      : message.role === 'SYSTEM'
        ? 'background: #fff7e6;'
        : 'background: #f0f0f0;';

  // 结构化消息：从 metadata_json 提取内容渲染
  if (message.message_type !== 'TEXT' && message.metadata_json) {
    const meta = message.metadata_json as Record<string, unknown>;
    let body: React.ReactNode = null;
    switch (message.message_type) {
      case 'TEST_PLAN':
        body = (
          <div style={{ fontSize: 13, lineHeight: 1.6 }}>
            <b>测试计划</b>
            {meta.plan != null && (
              <pre style={{ margin: '4px 0 0', padding: 8, background: '#fafafa', borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(meta.plan, null, 2)}
              </pre>
            )}
          </div>
        );
        break;
      case 'TEST_POINTS':
        body = (
          <div style={{ fontSize: 13 }}>
            <b>测试点</b>
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {(meta.points as Array<Record<string, unknown>> | undefined)?.map((p, i) => (
                <li key={i}>
                  {p.name as string}
                  {p.priority != null && <Tag style={{ marginLeft: 6 }} color="blue">{p.priority as string}</Tag>}
                </li>
              ))}
            </ul>
          </div>
        );
        break;
      case 'TEST_CASES':
        body = (
          <div style={{ fontSize: 13 }}>
            <b>测试用例</b>
            <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
              {(meta.cases as Array<Record<string, unknown>> | undefined)?.map((c, i) => (
                <li key={i}>
                  {c.name as string}
                  {c.priority != null && <Tag style={{ marginLeft: 6 }}>{c.priority as string}</Tag>}
                </li>
              ))}
            </ul>
          </div>
        );
        break;
      case 'EXECUTION':
        body = (
          <div style={{ fontSize: 13 }}>
            <b>执行结果</b>
            <pre style={{ margin: '4px 0 0', padding: 8, background: '#fafafa', borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(meta.run ?? meta, null, 2)}
            </pre>
          </div>
        );
        break;
      case 'RESULT':
        body = (
          <div style={{ fontSize: 13 }}>
            <b>分析结果</b>
            <pre style={{ margin: '4px 0 0', padding: 8, background: '#fafafa', borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(meta.analysis ?? meta, null, 2)}
            </pre>
          </div>
        );
        break;
      case 'REPORT': {
        const brief = (meta.report ?? meta) as Record<string, unknown>;
        const totals = (brief.totals as Record<string, unknown> | undefined) ?? {};
        const ai = (brief.ai_summary as Record<string, unknown> | undefined) ?? null;
        const risk = String(brief.risk_level ?? '');
        return (
          <div style={{ fontSize: 13 }}>
            <b>测试报告</b>
            <div style={{ margin: '4px 0' }}>
              <Tag color={RISK_TAG_COLOR[risk] ?? 'default'}>
                风险 {(RISK_LABEL[risk] ?? risk) || '-'}
              </Tag>
              <Tag color="blue">通过率 {String(brief.pass_rate ?? '-')}%</Tag>
              <Tag>共 {String(totals.total ?? brief.total_cases ?? '-')} 条</Tag>
              <Tag color="green">{String(totals.passed ?? '-')} 通过</Tag>
              <Tag color="red">{String(totals.failed ?? '-')} 失败</Tag>
              {Number(totals.error ?? 0) > 0 && <Tag color="orange">{String(totals.error)} 错误</Tag>}
            </div>
            {brief.report_no != null && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {String(brief.report_no)}
                {brief.title ? ` · ${String(brief.title)}` : ''}
              </Typography.Text>
            )}
            {typeof ai?.overview === 'string' && ai.overview ? (
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#555', whiteSpace: 'pre-wrap' }}>
                {ai.overview}
              </p>
            ) : null}
            {brief.report_id != null && (
              <Button
                size="small"
                type="link"
                style={{ padding: 0, marginTop: 2 }}
                icon={<EyeOutlined />}
                onClick={() => navigate(`/console/test-reports/${String(brief.report_id)}`)}
              >
                查看完整报告
              </Button>
            )}
          </div>
        );
      }
      case 'NOTIFICATION': {
        const brief = (meta.notification ?? meta) as Record<string, unknown>;
        const ok = brief.skipped === false && brief.status === 'SUCCESS';
        const skipped = brief.skipped === true;
        return (
          <div style={{ fontSize: 13 }}>
            <b>飞书通知</b>
            <div style={{ margin: '4px 0' }}>
              <Tag color={skipped ? 'default' : ok ? 'green' : 'red'}>
                {skipped ? '已跳过' : ok ? '发送成功' : `发送失败：${String(brief.error_message ?? '未知错误')}`}
              </Tag>
              {brief.channel_name != null && <Tag>{String(brief.channel_name)}</Tag>}
            </div>
            {brief.message != null && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {String(brief.message)}
              </Typography.Text>
            )}
            {!ok && !skipped && (
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 2 }}>
                通知发送失败不影响报告与执行记录状态，可在报告详情页重试。
              </Typography.Text>
            )}
          </div>
        );
      }
      case 'CLARIFY':
        body = <div style={{ fontSize: 13 }}><b>需要澄清</b><p style={{ margin: '4px 0 0' }}>{message.content}</p></div>;
        break;
      default:
        body = <pre style={{ fontSize: 12 }}>{JSON.stringify(meta, null, 2)}</pre>;
    }
    return (
      <div style={{ marginBottom: 12 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{roleIcon} {message.role}</Typography.Text>
        <div style={{ marginTop: 4, padding: '8px 12px', borderRadius: 8, ...bgColor.split(';').reduce((acc, prop) => { const [k, v] = prop.split(':').map(s => s.trim()); return { ...acc, [k]: v }; }, {} as React.CSSProperties) }}>
          {body}
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{roleIcon} {message.role}</Typography.Text>
      <div style={{ marginTop: 4, padding: '8px 12px', borderRadius: 8, ...bgColor.split(';').reduce((acc, prop) => { const [k, v] = prop.split(':').map(s => s.trim()); return { ...acc, [k]: v }; }, {} as React.CSSProperties) }}>
        <span style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{message.content}</span>
      </div>
    </div>
  );
}

// ---- 工作区「报告」面板：Agent 侧脱敏摘要（由代码统计，不含 webhook / secret）----
function ReportBriefPanel({
  brief,
  onOpen,
}: {
  brief: Record<string, unknown> | null;
  onOpen: () => void;
}) {
  if (!brief) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无报告数据" />;
  const totals = (brief.totals as Record<string, unknown> | undefined) ?? {};
  const ai = (brief.ai_summary as Record<string, unknown> | undefined) ?? null;
  const risk = String(brief.risk_level ?? '');
  const potentialIssues = ((ai?.potential_issues as string[] | undefined) ?? []);
  const recommendations = ((ai?.recommendations as string[] | undefined) ?? []);

  return (
    <div style={{ fontSize: 13 }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 6 }}>
        <Typography.Text strong>{String(brief.title ?? brief.report_no ?? '测试报告')}</Typography.Text>
        {brief.report_id != null && (
          <Button size="small" type="link" style={{ padding: 0 }} icon={<EyeOutlined />} onClick={onOpen}>
            查看详情
          </Button>
        )}
      </Flex>
      <div style={{ marginBottom: 6 }}>
        <Tag color={RISK_TAG_COLOR[risk] ?? 'default'}>风险 {(RISK_LABEL[risk] ?? risk) || '-'}</Tag>
        <Tag color="blue">通过率 {String(brief.pass_rate ?? '-')}%</Tag>
      </div>
      <div style={{ color: '#666', fontSize: 12, marginBottom: 8 }}>
        共 {String(totals.total ?? '-')} 条 · 通过 {String(totals.passed ?? '-')} · 失败 {String(totals.failed ?? '-')} ·
        错误 {String(totals.error ?? '-')} · 跳过 {String(totals.skipped ?? '-')}
        {brief.duration_ms != null && ` · 耗时 ${(Number(brief.duration_ms) / 1000).toFixed(2)}s`}
      </div>
      {typeof ai?.overview === 'string' && ai.overview && (
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 8, fontSize: 12 }}
          message="总体结论"
          description={<span style={{ whiteSpace: 'pre-wrap' }}>{ai.overview}</span>}
        />
      )}
      {potentialIssues.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 8, fontSize: 12 }}
          message="疑似产品问题（需人工确认，不是已确认缺陷）"
          description={
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {potentialIssues.map((t, i) => (
                <li key={i} style={{ lineHeight: 1.6 }}>
                  {t}
                </li>
              ))}
            </ul>
          }
        />
      )}
      {recommendations.length > 0 && (
        <div style={{ fontSize: 12, color: '#666' }}>
          <b>建议</b>
          <ul style={{ margin: '2px 0 0', paddingLeft: 16 }}>
            {recommendations.map((t, i) => (
              <li key={i} style={{ lineHeight: 1.6 }}>
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---- 工作区「通知」面板：飞书发送结果留痕 ----
function NotificationBriefPanel({ brief }: { brief: Record<string, unknown> | null }) {
  if (!brief) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知记录" />;
  const skipped = brief.skipped === true;
  const ok = !skipped && brief.status === 'SUCCESS';
  return (
    <div style={{ fontSize: 13 }}>
      <Tag color={skipped ? 'default' : ok ? 'green' : 'red'}>
        {skipped ? '已跳过' : ok ? '发送成功' : '发送失败'}
      </Tag>
      {brief.channel_name != null && <Tag>{String(brief.channel_name)}</Tag>}
      {brief.message != null && (
        <div style={{ marginTop: 6, fontSize: 12, color: '#666' }}>{String(brief.message)}</div>
      )}
      {!ok && !skipped && (
        <Alert
          type="error"
          showIcon
          style={{ marginTop: 8, fontSize: 12 }}
          message="通知发送失败"
          description={String(brief.error_message ?? '未知错误')}
        />
      )}
      <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
        通知失败不会把报告或执行记录标记为失败，可在报告详情页重试。
      </Typography.Text>
    </div>
  );
}

// ---- 主页面 ----
export function AgentPage() {
  const { message: msg, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const navigate = useNavigate();

  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
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
    <div style={{ padding: 16, height: 'calc(100vh - 56px)', display: 'flex', gap: 12 }}>
      {/* 左栏：会话列表 */}
      <div style={{ width: 240, flexShrink: 0, display: 'flex', flexDirection: 'column', background: '#fff', borderRadius: 8, padding: 12 }}>
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
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {sessionsQuery.isPending ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spin size="small" /></div>
          ) : sessionsQuery.data && sessionsQuery.data.length > 0 ? (
            <List
              size="small"
              dataSource={sessionsQuery.data}
              renderItem={(item) => (
                <List.Item
                  onClick={() => setSelectedSessionId(item.id)}
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
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#fff', borderRadius: 8, padding: 12, minWidth: 0 }}>
        <div style={{ flex: 1, overflowY: 'auto', padding: 8 }} ref={chatEndRef}>
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
        <Flex gap="small">
          <Input.TextArea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onPressEnter={(e) => { e.preventDefault(); handleSend(); }}
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
      <div style={{ width: 360, flexShrink: 0, display: 'flex', flexDirection: 'column', background: '#fff', borderRadius: 8, padding: 12 }}>
        <Typography.Text strong style={{ fontSize: 14 }}>工作区</Typography.Text>
        <Divider style={{ margin: '4px 0 8px' }} />
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {selectedSessionId == null ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择会话" style={{ marginTop: 80 }} />
          ) : !workspace ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spin size="small" /></div>
          ) : workspace.test_plan || workspace.test_points.length > 0 || workspace.test_cases.length > 0 || workspace.analysis || workspace.report_brief || workspace.notification_brief ? (
            <Tabs
              size="small"
              items={[
                ...(workspace.test_plan
                  ? [{
                      key: 'plan',
                      label: '测试计划',
                      children: (
                        <pre style={{ fontSize: 12, background: '#fafafa', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap' }}>
                          {JSON.stringify(workspace.test_plan, null, 2)}
                        </pre>
                      ),
                    }]
                  : []),
                ...(workspace.test_points.length > 0
                  ? [{
                      key: 'points',
                      label: `测试点(${workspace.test_points.length})`,
                      children: (
                        <div style={{ fontSize: 13 }}>
                          {workspace.stage === 'TEST_POINT_REVIEW' && (
                            <Checkbox.Group
                              style={{ marginBottom: 8 }}
                              value={selectedPointIds}
                              onChange={(vals) => setSelectedPointIds(vals.map((v) => Number(v)))}
                            >
                              {workspace.test_points.map((p) => (
                                <Checkbox key={String(p.id)} value={p.id as number} style={{ display: 'block', marginBottom: 4 }}>
                                  {p.name as string} <Tag color="blue">{p.priority as string}</Tag>
                                </Checkbox>
                              ))}
                            </Checkbox.Group>
                          )}
                          {workspace.test_points.map((p, i) => (
                            <Card key={i} size="small" style={{ marginBottom: 4 }}>
                              <Typography.Text strong>{p.name as string}</Typography.Text>
                              <Tag color="blue" style={{ marginLeft: 8 }}>{p.priority as string}</Tag>
                              {p.description != null && <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>{p.description as string}</Typography.Text>}
                            </Card>
                          ))}
                        </div>
                      ),
                    }]
                  : []),
                ...(workspace.test_cases.length > 0
                  ? [{
                      key: 'cases',
                      label: `用例(${workspace.test_cases.length})`,
                      children: (
                        <div style={{ fontSize: 13 }}>
                          {workspace.stage === 'TEST_CASE_REVIEW' && (
                            <Checkbox.Group
                              style={{ marginBottom: 8 }}
                              value={selectedCaseIds}
                              onChange={(vals) => setSelectedCaseIds(vals.map((v) => Number(v)))}
                            >
                              {workspace.test_cases.map((c) => (
                                <Checkbox key={String(c.id)} value={c.id as number} style={{ display: 'block', marginBottom: 4 }}>
                                  {c.name as string} <Tag>{c.priority as string}</Tag>
                                </Checkbox>
                              ))}
                            </Checkbox.Group>
                          )}
                          {workspace.test_cases.map((c, i) => (
                            <Card key={i} size="small" style={{ marginBottom: 4 }}>
                              <Typography.Text strong>{c.name as string}</Typography.Text>
                              <Tag style={{ marginLeft: 8 }}>{c.priority as string}</Tag>
                              {c.case_type != null && <Tag color="green">{c.case_type as string}</Tag>}
                            </Card>
                          ))}
                        </div>
                      ),
                    }]
                  : []),
                ...(workspace.analysis
                  ? [{
                      key: 'analysis',
                      label: '分析',
                      children: (
                        <pre style={{ fontSize: 12, background: '#fafafa', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap' }}>
                          {JSON.stringify(workspace.analysis, null, 2)}
                        </pre>
                      ),
                    }]
                  : []),
                ...(workspace.execution_result
                  ? [{
                      key: 'execution',
                      label: '执行',
                      children: (
                        <pre style={{ fontSize: 12, background: '#fafafa', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap' }}>
                          {JSON.stringify(workspace.execution_result, null, 2)}
                        </pre>
                      ),
                    }]
                  : []),
                ...(workspace.report_brief
                  ? [{
                      key: 'report',
                      label: '报告',
                      children: (
                        <ReportBriefPanel
                          brief={workspace.report_brief}
                          onOpen={() =>
                            workspace.report_id != null
                              ? navigate(`/console/test-reports/${workspace.report_id}`)
                              : undefined
                          }
                        />
                      ),
                    }]
                  : []),
                ...(workspace.notification_brief
                  ? [{
                      key: 'notification',
                      label: '通知',
                      children: <NotificationBriefPanel brief={workspace.notification_brief} />,
                    }]
                  : []),
              ]}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无工作区数据" style={{ marginTop: 48 }} />
          )}
        </div>

        {workspace?.error && (
          <Alert
            type="error"
            showIcon
            message="Agent 报错"
            description={workspace.error.message as string}
            style={{ marginTop: 8, fontSize: 12 }}
          />
        )}
      </div>
    </div>
  );
}
