// Web UI 智能体交互式编写页。
//
// 形态：受控浏览器会话（沙箱）+ 自然语言目标 + 人工步骤 review。
// 安全边界与后端一致：观测面板只显示脱敏语义树与遮罩截图，凭据永不回显；
// 提升只产出未确认草稿，正式执行仍须在 Web UI 自动化页人工确认后 debug。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  App, Button, Card, Col, Descriptions, Empty, Flex, Form, Image, Input,
  InputNumber, Row, Select, Space, Table, Tag, Typography,
} from 'antd';
import { InboxOutlined, PlayCircleOutlined, PlusOutlined, RobotOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { PageContainer, EmptyState, LoadingState, ErrorState } from '@/components/PageState';
import { getErrorMessage } from '@/api/client';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { webAgentApi, webUIApi, type WebAgentPromoteBody, type WebAgentStartBody } from '@/api/webUI';
import { agentApi } from '@/api/agent';
import type {
  AgentAction, AgentMessage, AgentSession, AgentWorkspace, Paginated, SendMessageRequest,
  WebAgentSession, WebAuthProfile, WebCaseInput, WebEnvironment, WebLocator, WebOperation,
} from '@/types';

/** 步骤 review 暂停点提供的两个快捷动作。
 *  不提供「提升为正式用例」：提升是服务层 HTTP 调用，图内只作终态，
 *  在对话里点了没有可见效果；提升入口在右侧提案面板上。 */
const WEB_ACTION_LABELS: Record<string, string> = {
  confirm_web_step: '确认执行这一步',
  reject_web_step: '驳回并重试',
};

/** 会话状态到中文标签与颜色的映射。 */
const SESSION_STATUS: Record<WebAgentSession['status'], { text: string; color: string }> = {
  ACTIVE: { text: '活跃', color: 'green' },
  CLOSED: { text: '已关闭', color: 'default' },
  FAILED: { text: '失败', color: 'red' },
};

/** 智能体在 state 里暴露的步骤（与后端 WebStep 对齐，字段可缺失）。
 *  WAIT / ASSERT 的专用字段必须完整透传，否则提升为正式用例后会丢掉等待状态与断言。 */
type WebDecision = {
  name?: string;
  operation?: WebOperation;
  locator?: { strategy: WebLocator['strategy']; value: string } | null;
  page_object_id?: number | null;
  element_key?: string | null;
  value?: string | null;
  timeout_ms?: number | null;
  wait_state?: 'visible' | 'hidden' | 'attached' | 'detached';
  assertion?: 'TEXT' | 'VALUE' | 'VISIBLE' | 'COUNT' | 'URL' | 'TITLE';
  operator?: 'EQ' | 'NE' | 'CONTAINS' | 'GT' | 'GE' | 'LT' | 'LE';
  expected?: string | null;
  sensitive?: boolean;
  output_variable?: string | null;
  /** 沙箱执行结果：ACCEPTED=已确认且通过，FAILED=执行未通过 */
  status?: string;
};

interface WebWorkspace extends AgentWorkspace {
  web_agent_session_id: number | null;
  web_goal: string | null;
  web_step_budget: number;
  web_proposed_steps: WebDecision[];
  web_current_step: WebDecision | null;
  web_observation: { url: string; title: string; accessibility_tree: string; screenshot_b64: string } | null;
}

/** 把智能体步骤转成可保存的用例步骤：原样透传 WebStep 字段，只去掉运行期标记。
 *  不补 upload——智能体不会产出内存上传，避免把大段 base64 塞进提升请求体。 */
function toCaseSteps(steps: WebDecision[]): WebCaseInput['steps'] {
  return steps.map((s) => ({
    name: s.name ?? '智能体会话步骤',
    operation: s.operation ?? 'CLICK',
    locator: s.locator ?? null,
    page_object_id: s.page_object_id ?? null,
    element_key: s.element_key ?? null,
    value: s.value ?? null,
    timeout_ms: s.timeout_ms ?? null,
    wait_state: s.wait_state ?? undefined,
    assertion: s.assertion ?? undefined,
    operator: s.operator ?? undefined,
    expected: s.expected ?? null,
    sensitive: s.sensitive,
    output_variable: s.output_variable ?? null,
  }));
}

/** 描述定位器：策略 + 定位值。 */
function describeLocator(row: WebDecision): string {
  if (!row.locator) return '—';
  return [row.locator.strategy, row.locator.value].filter(Boolean).join(' ');
}

/** 智能体会话面板：会话元信息、步数预算与用户目标。 */
function SessionPanel({ session, workspace }: { session: WebAgentSession | null; workspace: WebWorkspace | null }) {
  const state = session ? SESSION_STATUS[session.status] : null;
  return (
    <Card size="small" title="智能体会话">
      {!session ? (
        <Empty description="尚未启动受控浏览器会话" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Descriptions size="small" column={2} bordered>
          <Descriptions.Item label="会话 ID">{session.id}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={state?.color ?? 'default'}>{state?.text ?? session.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="环境">{session.environment_id}</Descriptions.Item>
          <Descriptions.Item label="目标页">{session.target_page_path || '（根路径）'}</Descriptions.Item>
          <Descriptions.Item label="步数预算">{session.step_budget}</Descriptions.Item>
          <Descriptions.Item label="已执行">{session.step_count}</Descriptions.Item>
        </Descriptions>
      )}
      {workspace?.web_goal ? (
        <div style={{ marginTop: 12 }}>
          <Typography.Text type="secondary">用户目标</Typography.Text>
          <div>{workspace.web_goal}</div>
        </div>
      ) : null}
    </Card>
  );
}

/** 页面观测面板：只显示脱敏语义树与遮罩截图，绝不显示原始 DOM 或凭据。 */
function ObservationPanel({ observation }: { observation: WebWorkspace['web_observation'] }) {
  if (!observation) {
    return (
      <Card size="small" title="页面观测">
        <Empty description="观测尚未产生，请先发送目标" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </Card>
    );
  }
  const shot = observation.screenshot_b64 ? `data:image/png;base64,${observation.screenshot_b64}` : '';
  return (
    <Card size="small" title="页面观测（已脱敏）">
      <Descriptions size="small" column={1}>
        <Descriptions.Item label="URL">{observation.url || '（未加载）'}</Descriptions.Item>
        <Descriptions.Item label="标题">{observation.title || '（未加载）'}</Descriptions.Item>
      </Descriptions>
      <div style={{ margin: '12px 0 8px' }}>
        <Typography.Text type="secondary">页面语义树</Typography.Text>
        <pre style={{ maxHeight: 220, overflow: 'auto', padding: 12, background: 'rgba(0,0,0,0.04)', borderRadius: 6, whiteSpace: 'pre-wrap', fontSize: 12 }}>
          {observation.accessibility_tree || '（空）'}
        </pre>
      </div>
      {shot ? (
        <div>
          <Typography.Text type="secondary">遮罩截图</Typography.Text>
          <div><Image src={shot} alt="遮罩截图" style={{ maxWidth: '100%' }} /></div>
        </div>
      ) : null}
    </Card>
  );
}

/** 步骤提案面板：当前待确认提案 + 已执行步骤，并提供提升入口。 */
function ProposalPanel({ workspace, promoting, onPromote }: {
  workspace: WebWorkspace | null;
  promoting: boolean;
  onPromote: (name: string, steps: WebCaseInput['steps']) => void;
}) {
  const [name, setName] = useState('');
  const pending = workspace?.web_current_step ?? null;
  const executed = workspace?.web_proposed_steps ?? [];
  // 后端提升只认 status=ACCEPTED 且 source=AI 的步骤；待确认提案与执行失败的步骤
  // 都不会进入正式用例，前端不能把它们算进可提升集合。
  const promotable = executed.filter((s) => s.status === 'ACCEPTED');
  const steps = toCaseSteps(promotable);

  return (
    <Card size="small" title="步骤提案" extra={
      <Button size="small" disabled={!steps.length} loading={promoting} onClick={() => onPromote(name.trim(), steps)}>
        提升为正式用例{promotable.length ? `（${promotable.length} 步）` : ''}
      </Button>
    }>
      {pending ? (
        <Card size="small" type="inner" title="待确认提案" style={{ marginBottom: 12 }}>
          <Descriptions size="small" column={2}>
            <Descriptions.Item label="名称">{pending.name ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="操作"><Tag color="blue">{pending.operation ?? '—'}</Tag></Descriptions.Item>
            <Descriptions.Item label="定位">{describeLocator(pending)}</Descriptions.Item>
            <Descriptions.Item label="值 / 期望">{pending.value ?? pending.expected ?? '（无）'}</Descriptions.Item>
          </Descriptions>
        </Card>
      ) : null}
      <Table
        size="small"
        rowKey={(_, index) => String(index)}
        pagination={false}
        columns={[
          { title: '名称', dataIndex: 'name', key: 'name', render: (v: string | undefined) => v ?? '—' },
          { title: '操作', dataIndex: 'operation', key: 'operation', width: 90, render: (v: string) => <Tag>{v}</Tag> },
          { title: '定位', key: 'locator', width: 180, render: (_: unknown, row: WebDecision) => describeLocator(row) },
          {
            title: '结果', key: 'status', width: 80,
            render: (_: unknown, row: WebDecision) => (
              <Tag color={row.status === 'ACCEPTED' ? 'green' : 'red'}>
                {row.status === 'ACCEPTED' ? '通过' : '未通过'}
              </Tag>
            ),
          },
        ]}
        dataSource={executed}
        locale={{ emptyText: <Empty description="尚无已执行的步骤" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
      <div style={{ marginTop: 8 }}>
        <Input size="small" placeholder="提升后的用例名称（留空自动生成）" value={name} onChange={(e) => setName(e.target.value)} allowClear />
      </div>
    </Card>
  );
}

/** 对话面板：发送自然语言目标、执行建议动作、展示智能体回复。 */
function ChatPanel({ webSessionId, webSessionActive, messages, workspace, pending, onSend, onAction }: {
  webSessionId: number | null;
  webSessionActive: boolean;
  messages: AgentMessage[];
  workspace: WebWorkspace | null;
  pending: boolean;
  onSend: (content: string) => void;
  onAction: (action: AgentAction) => void;
}) {
  const { message } = App.useApp();
  const [value, setValue] = useState('');
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages.length]);

  const disabled = webSessionId == null || !webSessionActive || pending;
  const actions = workspace && workspace.web_agent_session_id === webSessionId
    ? (workspace.suggested_actions ?? []).filter((a) => WEB_ACTION_LABELS[a])
    : [];

  const send = useCallback(() => {
    const text = value.trim();
    if (!text || disabled) return;
    if (webSessionId == null) {
      void message.warning('请先启动受控浏览器会话');
      return;
    }
    setValue('');
    onSend(text);
  }, [value, disabled, webSessionId, message, onSend]);

  const renderMeta = (msg: AgentMessage): React.ReactNode => {
    const meta = (msg.metadata_json ?? {}) as Record<string, unknown>;
    if (msg.message_type === 'WEB_OBSERVATION') {
      return <Typography.Text type="secondary">{msg.content ?? '（页面观测）'}</Typography.Text>;
    }
    if (msg.message_type === 'WEB_AGENT_STEP') {
      const count = Array.isArray(meta.steps) ? (meta.steps as unknown[]).length : 0;
      return (
        <div>
          <Tag color="cyan">步骤留痕</Tag>
          <span>{msg.content}</span>
          {count ? <Typography.Text type="secondary"> 已执行 {count} 步</Typography.Text> : null}
        </div>
      );
    }
    if (msg.content) return <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>;
    return <Typography.Text type="secondary">{msg.message_type}</Typography.Text>;
  };

  return (
    <Card size="small" title="对话" extra={<Tag color="geekblue">{workspace?.stage ?? '未开始'}</Tag>}>
      <div style={{ height: 360, overflow: 'auto', padding: '4px 2px 12px', marginBottom: 12 }}>
        {messages.length === 0 ? (
          <Empty description="输入目标，例如「登录后点击提交按钮」" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Flex vertical gap="middle">
            {messages.map((msg) => (
              <div key={msg.id}>
                <Typography.Text type="secondary">
                  <RobotOutlined /> {msg.role === 'USER' ? '你' : '智能体'}
                </Typography.Text>
                {renderMeta(msg)}
              </div>
            ))}
            <div ref={endRef} />
          </Flex>
        )}
      </div>
      {actions.length > 0 ? (
        <Flex wrap gap="small" style={{ marginBottom: 8 }}>
          {actions.map((action) => (
            <Button key={action} size="small" icon={<PlayCircleOutlined />} loading={pending} disabled={disabled} onClick={() => onAction(action as AgentAction)}>
              {WEB_ACTION_LABELS[action]}
            </Button>
          ))}
        </Flex>
      ) : null}
      <Flex gap="small">
        <Input.TextArea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="输入目标；智能体只观察脱敏后的页面语义树"
          autoSize={{ minRows: 1, maxRows: 3 }}
          disabled={disabled}
          onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send(); } }}
        />
        <Button type="primary" icon={<RobotOutlined />} loading={pending} disabled={disabled} onClick={send}>发送</Button>
      </Flex>
      {workspace?.error ? (
        <Typography.Text type="danger">
          错误 {String((workspace.error as Record<string, unknown>).code ?? '')}：
          {String((workspace.error as Record<string, unknown>).message ?? '')}
        </Typography.Text>
      ) : null}
    </Card>
  );
}

/** 会话配置卡片：选环境、登录态、目标页与步数预算后启动或关闭受控会话。 */
function SetupCard({ environments, auth, sessions, session, busy, closing, onStart, onSelectSession, onClose }: {
  environments: WebEnvironment[];
  auth: WebAuthProfile[];
  sessions: WebAgentSession[];
  session: WebAgentSession | null;
  busy: boolean;
  closing: boolean;
  onStart: (body: WebAgentStartBody) => void;
  onSelectSession: (sessionId: number) => void;
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const [environmentId, setEnvironmentId] = useState<number>();
  const [authId, setAuthId] = useState<number | undefined>();
  const [path, setPath] = useState('');
  const [budget, setBudget] = useState(20);

  const start = useCallback(() => {
    if (environmentId == null) {
      void message.warning('请选择执行环境');
      return;
    }
    if (budget < 1 || budget > 100) {
      void message.warning('步数预算需在 1 到 100 之间');
      return;
    }
    onStart({ environment_id: environmentId, auth_profile_id: authId ?? null, target_page_path: path.trim(), step_budget: budget });
  }, [environmentId, authId, path, budget, onStart, message]);

  return (
    <Card size="small" title="受控浏览器会话" extra={
      session ? <Typography.Text type="secondary">已执行 {session.step_count} / {session.step_budget} 步</Typography.Text> : null
    }>
      <Form layout="inline" style={{ rowGap: 8 }}>
        <Form.Item label="已有会话">
          <Select
            style={{ width: 220 }}
            value={session?.id}
            onChange={onSelectSession}
            placeholder="选择已有会话"
            disabled={busy}
            options={sessions.map((item) => ({
              value: item.id,
              label: `会话 ${item.id} · ${SESSION_STATUS[item.status].text} · ${item.step_count}/${item.step_budget} 步`,
            }))}
          />
        </Form.Item>
        <Form.Item label="环境">
          <Select
            showSearch
            optionFilterProp="label"
            style={{ width: 220 }}
            value={environmentId}
            onChange={setEnvironmentId}
            placeholder="选择执行环境"
            disabled={busy}
            options={environments.map((e) => ({ value: e.id, label: e.display_name || e.name }))}
          />
        </Form.Item>
        <Form.Item label="登录态">
          <Select
            allowClear
            style={{ width: 220 }}
            value={authId}
            onChange={(v) => setAuthId(v)}
            placeholder="不使用登录态"
            disabled={busy}
            options={auth.map((a) => ({ value: a.id, label: a.name }))}
          />
        </Form.Item>
        <Form.Item label="目标页">
          <Input style={{ width: 180 }} value={path} onChange={(e) => setPath(e.target.value)} placeholder="/orders" disabled={busy} />
        </Form.Item>
        <Form.Item label="步数预算">
          <InputNumber min={1} max={100} value={budget} onChange={(v) => setBudget(typeof v === 'number' ? v : 20)} disabled={busy} />
        </Form.Item>
        <Form.Item>
          {session?.status === 'ACTIVE' ? (
            <Button danger icon={<InboxOutlined />} loading={closing} onClick={onClose}>关闭会话</Button>
          ) : (
            <Button type="primary" icon={<PlayCircleOutlined />} loading={busy} onClick={start}>启动会话</Button>
          )}
        </Form.Item>
      </Form>
    </Card>
  );
}

/** 本项目的智能体对话会话 ID 在浏览器里的键名。
 *  对话会话（agent_session）是后端持久化的，只存内存会导致刷新后整段探索历史
 *  与已提出的步骤全部丢失；这里按项目隔离落 localStorage，刷新后自动恢复。
 *  受控浏览器会话不落——它是进程内资源，重启后端后一定失效。 */
const agentSessionStorageKey = (projectId: number): string =>
  `webui-agent-session-${projectId}`;

/** 读回上一次记住的对话会话 ID；不可用时静默返回 null。 */
function readRememberedAgentSession(projectId: number): number | null {
  try {
    const raw = window.localStorage.getItem(agentSessionStorageKey(projectId));
    const value = raw ? Number(raw) : NaN;
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

/** 项目内 Web 智能体对话列表与新建入口。 */
function ConversationCard({ sessions, value, loading, pending, onChange, onCreate }: {
  sessions: AgentSession[];
  value: number | null;
  loading: boolean;
  pending: boolean;
  onChange: (sessionId: number) => void;
  onCreate: () => void;
}) {
  return (
    <Card size="small" title="对话会话" extra={
      <Button size="small" icon={<PlusOutlined />} loading={loading} disabled={pending} onClick={onCreate}>
        新建对话
      </Button>
    }>
      <Select
        showSearch
        optionFilterProp="label"
        style={{ width: '100%' }}
        value={value ?? undefined}
        loading={loading}
        disabled={pending}
        placeholder="选择 Web 智能体对话"
        onChange={onChange}
        options={sessions.map((session) => ({
          value: session.id,
          label: `${session.title || `Web 智能体会话 ${session.id}`} · ${session.current_stage}`,
        }))}
        notFoundContent={<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 Web 智能体对话" />}
      />
    </Card>
  );
}

function Workspace({ projectId }: { projectId: number }) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const envs = useQuery({ queryKey: ['project', projectId, 'web', 'environments', ''], queryFn: () => webUIApi.environments(projectId, '') });
  const auth = useQuery({ queryKey: ['project', projectId, 'web', 'auth'], queryFn: () => webUIApi.auth(projectId) });
  const sessions = useQuery({ queryKey: ['project', projectId, 'web-agent', 'sessions'], queryFn: () => webAgentApi.sessions(projectId) });
  const agentSessions = useQuery({
    queryKey: ['agent', 'sessions', projectId],
    queryFn: () => agentApi.listSessions(projectId),
  });
  const [agentSessionId, setAgentSessionId] = useState<number | null>(null);
  const [webSessionId, setWebSessionId] = useState<number | null>(null);
  const restoredAgentSession = useRef(false);
  const turnBusy = useRef(false);

  const envRows = envs.data?.items.filter((e) => e.is_active) ?? [];
  const authRows = auth.data?.items ?? [];
  // 只按显式选中的会话 ID 解析，不回退到列表首项——历史遗留的 CLOSED 会话会让
  // 用户永远停在「关闭会话」按钮上，再也无法启动新会话。
  const session = webSessionId != null ? sessions.data?.items.find((s) => s.id === webSessionId) ?? null : null;

  const detail = useQuery({ queryKey: ['agent', 'session', agentSessionId], queryFn: () => agentApi.getSessionDetail(agentSessionId!), enabled: agentSessionId != null });
  const workspace = useQuery({ queryKey: ['agent', 'workspace', agentSessionId], queryFn: () => agentApi.getWorkspace(agentSessionId!), enabled: agentSessionId != null });

  useEffect(() => {
    if (agentSessionId == null) return;
    try {
      window.localStorage.setItem(agentSessionStorageKey(projectId), String(agentSessionId));
    } catch {
      /* localStorage 不可用时静默降级：仅失去刷新恢复能力 */
    }
  }, [agentSessionId, projectId]);

  // 会话列表加载后恢复上次的 Web 智能体对话；没有记忆时选择最近一条。
  // 只初始化一次，避免创建新对话后的列表刷新把当前选择跳回旧会话。
  useEffect(() => {
    if (agentSessions.data == null || restoredAgentSession.current) return;
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
  }, [agentSessions.data, projectId]);

  const turn = useMutation({
    mutationFn: ({ sessionId, body }: { sessionId: number; body: SendMessageRequest }) =>
      agentApi.sendMessage(sessionId, body),
  });
  const createAgentSession = useMutation({
    mutationFn: () => agentApi.createSession(projectId, { title: 'Web UI 智能体会话' }),
  });
  const startSession = useMutation({ mutationFn: (body: WebAgentStartBody) => webAgentApi.start(projectId, body) });
  const closeSession = useMutation({ mutationFn: (sessionId: number) => webAgentApi.close(sessionId) });
  const promote = useMutation({
    mutationFn: ({ sessionId, body }: { sessionId: number; body: WebAgentPromoteBody }) =>
      webAgentApi.promote(sessionId, body),
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
  }, [queryClient, agentSessionId, projectId]);

  /** 发消息或动作前确保存在对话会话；智能体会话按 Agent 会话创建。
   *  失败必须显式提示——否则按钮永久卡在 loading，用户以为智能体在思考。 */
  const withAgentSession = useCallback(async (body: SendMessageRequest) => {
    if (webSessionId == null || session?.status !== 'ACTIVE' || turnBusy.current) return;
    // mutation 状态完成 React 重绘前也拦住快速双击，避免并发创建两个 Agent turn。
    turnBusy.current = true;
    try {
      let targetAgentSessionId = agentSessionId;
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
  }, [webSessionId, session?.status, agentSessionId, projectId, turn, createAgentSession, invalidate, queryClient, message]);

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
        setWebSessionId(created.id);
        queryClient.setQueryData<Paginated<WebAgentSession>>(
          ['project', projectId, 'web-agent', 'sessions'],
          (current) => current
            ? { ...current, items: [created, ...current.items.filter((item) => item.id !== created.id)].slice(0, 20) }
            : current,
        );
        void message.success('受控会话已启动');
        void queryClient.invalidateQueries({ queryKey: ['project', projectId, 'web-agent'] });
      },
      onError: (e) => void message.error(getErrorMessage(e, '启动会话失败')),
    });
  }, [startSession, message, queryClient, projectId]);

  const doClose = useCallback(() => {
    if (webSessionId == null) return;
    closeSession.mutate(webSessionId, {
      onSuccess: (closed) => {
        queryClient.setQueryData<Paginated<WebAgentSession>>(
          ['project', projectId, 'web-agent', 'sessions'],
          (current) => current
            ? { ...current, items: current.items.map((item) => item.id === closed.id ? closed : item) }
            : current,
        );
        void message.success('会话已关闭');
        void queryClient.invalidateQueries({ queryKey: ['project', projectId, 'web-agent'] });
      },
      onError: (e) => void message.error(getErrorMessage(e, '关闭会话失败')),
    });
  }, [webSessionId, closeSession, message, queryClient, projectId]);

  /** 恢复本项目中仍活跃的浏览器会话；切换时先关闭当前句柄，避免占满并发槽。 */
  const selectWebSession = useCallback((nextId: number) => {
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
  }, [webSessionId, closeSession, queryClient, projectId, message]);

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
          const created = await promote.mutateAsync({
            sessionId,
            body: { name: name || undefined },
          });
          void message.success(`已生成用例「${created.name}」（未确认）`);
          navigate('/console/web-ui');
        } catch (e) {
          void message.error(getErrorMessage(e, '提升失败'));
        }
      },
    });
  }, [webSessionId, modal, promote, message, navigate]);

  const workspaceData = (
    turn.data?.session.id === agentSessionId ? turn.data.workspace : workspace.data ?? null
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
    return [...(detail.data?.messages ?? []), ...currentTurnMessages].filter((m) => {
      if (seen.has(m.id)) return false;
      seen.add(m.id);
      return true;
    });
  }, [detail.data, turn.data, agentSessionId]);

  if (envs.isPending || auth.isPending || sessions.isPending || agentSessions.isPending) return <LoadingState tip="加载 Web 智能体配置…" />;
  const failed = envs.error || auth.error || sessions.error || agentSessions.error;
  if (failed) return <ErrorState error={failed} onRetry={() => { void envs.refetch(); void auth.refetch(); void sessions.refetch(); void agentSessions.refetch(); }} />;

  const webChats = (agentSessions.data ?? []).filter((s) =>
    s.title === 'Web 智能体会话' || s.title?.startsWith('Web UI 智能体'),
  );

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <ConversationCard
        sessions={webChats}
        value={agentSessionId}
        loading={createAgentSession.isPending}
        pending={turn.isPending || closeSession.isPending || createAgentSession.isPending}
        onChange={selectAgentSession}
        onCreate={doCreateAgentSession}
      />
      <SetupCard
        environments={envRows}
        auth={authRows}
        sessions={sessions.data?.items ?? []}
        session={session}
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
  return (
    <PageContainer>
      {currentProjectId != null
        ? <Workspace key={currentProjectId} projectId={currentProjectId} />
        : <EmptyState description="请先在顶部选择一个项目" />
      }
    </PageContainer>
  );
}
