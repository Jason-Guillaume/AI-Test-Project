import {
  App,
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Drawer,
  Form,
  Input,
  List,
  Modal,
  Row,
  Pagination,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
} from 'antd';
import { ApiOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { agentGovernanceApi, type AgentDefinition, type AgentDefinitionInput, type AgentTrigger, type DefinitionVersion, type GovernanceTool, type GovernanceToolUpdate, type MCPServer, type SkillDefinition, type SkillInput } from '@/api/agentGovernance';
import { modelConfigsApi } from '@/api/modelConfigs';
import { getErrorMessage } from '@/api/client';
import { EmptyState, ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { PageHeader } from '@/components/PageHeader';

const ROUTES = {
  agents: '/admin/agents',
  mcp: '/admin/mcp',
  skills: '/admin/skills',
  tools: '/admin/tools',
} as const;

const WORKFLOW_LABELS: Record<string, string> = {
  api_test: '接口测试',
  web_ui: 'Web UI 测试',
  security: '安全测试',
  reporting: '测试报告',
};

function skillCategory(name: string) {
  return name.includes(' · ') ? name.split(' · ')[0] : '通用';
}

export function AdminAgentGovernancePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeKey = location.pathname.startsWith(ROUTES.mcp)
    ? 'mcp'
    : location.pathname.startsWith(ROUTES.skills)
      ? 'skills'
      : location.pathname.startsWith(ROUTES.tools)
        ? 'tools'
        : 'agents';

  return (
    <PageContainer>
      <PageHeader title="Agent 治理中心" subtitle="管理受控工作流、知识技能、MCP 接入与平台工具白名单" />
      <Tabs
        activeKey={activeKey}
        onChange={(key) => navigate(ROUTES[key as keyof typeof ROUTES])}
        items={[
          { key: 'agents', label: 'Agent', children: <AgentPane /> },
          { key: 'mcp', label: 'MCP', children: <McpPane /> },
          { key: 'skills', label: 'Skill', children: <SkillPane /> },
          { key: 'tools', label: '工具', children: <ToolsPane /> },
        ]}
      />
    </PageContainer>
  );
}

function AgentPane() {
  const [editing, setEditing] = useState<AgentDefinition | null>(null);
  const [creating, setCreating] = useState(false);
  const [history, setHistory] = useState<{ kind: 'agent' | 'skill'; id: number; name: string } | null>(null);
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['agent-governance'] });
  const agents = useQuery({ queryKey: ['agent-governance', 'agents'], queryFn: agentGovernanceApi.agents });
  const workflows = useQuery({ queryKey: ['agent-governance', 'workflows'], queryFn: agentGovernanceApi.workflows });
  const skills = useQuery({ queryKey: ['agent-governance', 'skills'], queryFn: agentGovernanceApi.skills });
  const tools = useQuery({ queryKey: ['agent-governance', 'tools'], queryFn: agentGovernanceApi.tools });
  const mcpServers = useQuery({ queryKey: ['agent-governance', 'mcp-servers'], queryFn: agentGovernanceApi.mcpServers });
  const models = useQuery({ queryKey: ['agent-governance', 'models'], queryFn: () => modelConfigsApi.list({ page: 1, page_size: 100, is_enabled: true }) });
  const createMutation = useMutation({
    mutationFn: agentGovernanceApi.createAgent,
    onSuccess: () => { message.success('Agent 配置已创建'); setCreating(false); invalidate(); },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<AgentDefinitionInput> }) => agentGovernanceApi.updateAgent(id, body),
    onSuccess: () => { message.success('Agent 配置已更新'); setEditing(null); invalidate(); },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  const deleteMutation = useMutation({
    mutationFn: agentGovernanceApi.deleteAgent,
    onSuccess: () => { message.success('Agent 配置已删除'); invalidate(); },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  if (agents.isPending || workflows.isPending || skills.isPending || tools.isPending || models.isPending || mcpServers.isPending) return <LoadingState />;
  const failed = [agents, workflows, skills, tools, models, mcpServers].find((query) => query.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  const agentRows = agents.data ?? [];

  const submit = (body: AgentDefinitionInput) => {
    const normalized = { ...body, skill_keys: body.skill_keys ?? [], tool_keys: body.tool_keys ?? [], child_agent_ids: body.child_agent_ids ?? [], instruction: body.instruction ?? '' };
    if (editing) updateMutation.mutate({ id: editing.id, body: normalized });
    else createMutation.mutate(normalized);
  };

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}><Button type="primary" onClick={() => setCreating(true)}>新增 Agent</Button></div>
      {agentRows.length ? <Row gutter={[12, 12]}>
        {agentRows.map((agent) => <Col xs={24} md={12} xl={8} xxl={6} key={agent.id}>
          <Card
            size="small"
            hoverable
            onClick={(event) => {
              if ((event.target as HTMLElement).closest('button')) return;
              setEditing(agent);
            }}
            style={{ height: '100%' }}
            styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', padding: 12 } }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <Typography.Text strong ellipsis={{ tooltip: agent.name }} style={{ display: 'block' }}>{agent.name}</Typography.Text>
                <Space size={4} style={{ marginTop: 4 }}>
                  <Tag color="blue">{WORKFLOW_LABELS[agent.workflow_template] ?? agent.workflow_template}</Tag>
                  <Button type="link" size="small" style={{ paddingInline: 4 }} onClick={() => setHistory({ kind: 'agent', id: agent.id, name: agent.name })}>v{agent.version}</Button>
                </Space>
              </div>
              <Tag color={agent.is_enabled ? 'green' : 'default'}>{agent.is_enabled ? '启用' : '停用'}</Tag>
            </div>
            <Typography.Paragraph type="secondary" ellipsis={{ rows: 2, tooltip: agent.description || '暂无说明' }} style={{ minHeight: 40, marginTop: 6, marginBottom: 8 }}>
              {agent.description || '暂无说明'}
            </Typography.Paragraph>
            <Space wrap size={[4, 4]} style={{ marginTop: 'auto', marginBottom: 8 }}>
              <Tag>子 Agent {agent.child_agent_ids.length}</Tag>
              <Tag>Skill {agent.skill_keys.length}</Tag>
              <Tag>工具 {agent.tool_keys.length}</Tag>
            </Space>
            <Space style={{ width: '100%' }}>
              <Button size="small" style={{ flex: 1 }} onClick={() => setEditing(agent)}>查看详情 / 编辑配置</Button>
              <Button size="small" danger onClick={() => modal.confirm({ title: `删除 Agent「${agent.name}」？`, okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(agent.id) })}>删除</Button>
            </Space>
          </Card>
        </Col>)}
      </Row> : <EmptyState description="还没有 Agent 定义" />}
      <AgentFormModal
        key={editing ? `${editing.id}-${editing.version}` : (creating ? 'new' : 'closed')}
        open={creating || Boolean(editing)}
        initial={editing ?? undefined}
        workflows={workflows.data ?? []}
        skillOptions={(skills.data ?? []).map((item) => ({ label: `${item.name}${item.is_enabled ? '' : ' · 已停用'}`, value: item.key, disabled: !item.is_enabled }))}
        toolOptions={[
          ...(tools.data ?? []).map((item) => ({ label: `${item.name} · ${item.risk}`, value: item.key })),
          ...(mcpServers.data ?? []).flatMap((server) => server.discovered_tools_json
            .filter((tool) => server.approved_tools_json.includes(tool.name))
            .map((tool) => ({
              label: `${server.name} / ${tool.name} · ${tool.annotations?.readOnlyHint ? '只读已审批' : '仅审批，不自动执行'}`,
              value: `mcp:${server.id}:${tool.name}`,
              disabled: !server.is_enabled || server.connection_status !== 'connected' || tool.annotations?.readOnlyHint !== true,
            }))),
        ]}
        childAgentOptions={(agents.data ?? []).filter((item) => item.id !== editing?.id && item.child_agent_ids.length === 0 && item.tool_keys.length === 0).map((item) => ({
          label: `${item.name} · v${item.version} · 分析节点${item.is_enabled ? '' : ' · 已停用'}`,
          value: item.id,
          disabled: !item.is_enabled,
        }))}
        allowChildNodes={!editing || !(agents.data ?? []).some((item) => item.id !== editing.id && item.is_enabled && item.child_agent_ids.includes(editing.id))}
        modelOptions={(models.data?.items ?? []).map((item) => ({ label: `${item.label} (${item.model_name})`, value: item.id }))}
        loading={createMutation.isPending || updateMutation.isPending}
        onCancel={() => { setCreating(false); setEditing(null); }}
        onSubmit={submit}
      />
      <DefinitionHistoryModal
        key={history ? `${history.kind}-${history.id}` : 'closed'}
        target={history}
        onClose={() => setHistory(null)}
        onRestored={(definition) => { if ('instruction' in definition) setEditing(definition); }}
      />
    </>
  );
}

function AgentFormModal({ open, initial, workflows, skillOptions, toolOptions, childAgentOptions, allowChildNodes, modelOptions, loading, onCancel, onSubmit }: {
  open: boolean;
  initial?: AgentDefinition;
  workflows: { key: string; label: string; description: string }[];
  skillOptions: { label: string; value: string; disabled?: boolean }[];
  toolOptions: { label: string; value: string }[];
  childAgentOptions: { label: string; value: number; disabled?: boolean }[];
  allowChildNodes: boolean;
  modelOptions: { label: string; value: number }[];
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: AgentDefinitionInput) => void;
}) {
  type AgentFormState = AgentDefinitionInput & { mcp_tool_keys: string[] };
  const [form] = Form.useForm<AgentFormState>();
  const instruction = Form.useWatch('instruction', form) ?? '';
  const runtimeVariables = Form.useWatch(['settings_json', 'runtime_variables'], form) ?? [];
  const preview = runtimeVariables.reduce((text: string, variable: { name?: string; value?: string }) => {
    const name = variable.name?.trim();
    if (!name) return text;
    const value = name === 'Now' ? new Date().toLocaleString() : name === 'DataDir' ? '（任务运行时目录）' : variable.value ?? '';
    return text.split(`{{.${name}}}`).join(value);
  }, instruction);
  const initialValues: AgentFormState = initial
    ? {
      ...initial,
      tool_keys: initial.tool_keys.filter((key) => !key.startsWith('mcp:')),
      mcp_tool_keys: initial.tool_keys.filter((key) => key.startsWith('mcp:')),
      settings_json: initial.settings_json ?? defaultAgentSettings(),
      triggers_json: initial.triggers_json ?? [],
    }
    : {
      name: '', description: '', workflow_template: workflows[0]?.key ?? 'api_test', instruction: '', model_config_id: null,
      skill_keys: [], tool_keys: [], mcp_tool_keys: [], child_agent_ids: [], is_enabled: false,
      settings_json: defaultAgentSettings(), triggers_json: [],
    };
  const submit = (values: AgentFormState) => {
    const { mcp_tool_keys, ...body } = values;
    onSubmit({
      ...body,
      model_config_id: body.settings_json.model_binding === 'agent' ? body.model_config_id : null,
      tool_keys: [...new Set([...(body.tool_keys ?? []), ...(mcp_tool_keys ?? [])])],
    });
  };
  return (
    <Drawer
      title={initial ? `Agent 详情与配置：${initial.name}` : '新增 Agent'}
      open={open}
      onClose={onCancel}
      width={720}
      destroyOnClose
      extra={initial ? <Tag>v{initial.version}</Tag> : null}
      footer={<Space style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
        <Space>
          {initial && <Button onClick={() => form.setFieldsValue({ instruction: '', settings_json: defaultAgentSettings(), triggers_json: [] })}>恢复默认</Button>}
          {initial && <Button onClick={() => form.setFieldsValue(initialValues)}>放弃未保存修改</Button>}
        </Space>
        <Space><Button onClick={onCancel}>关闭</Button><Button type="primary" loading={loading} onClick={() => form.submit()}>{initial ? '保存为新版本' : '创建 Agent'}</Button></Space>
      </Space>}
    >
      <Form form={form} layout="vertical" initialValues={initialValues} onFinish={submit}>
        <Tabs items={[
          { key: 'config', label: '配置与提示词', children: <>
            <Row gutter={16}>
              <Col span={12}><Form.Item name="name" label="Agent 名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item></Col>
              <Col span={12}><Form.Item name="workflow_template" label="工作流模板" rules={[{ required: true }]}><Select options={workflows.map((item) => ({ value: item.key, label: item.label }))} /></Form.Item></Col>
            </Row>
            <Form.Item name="description" label="说明"><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
            <Row gutter={16}>
              <Col span={12}><Form.Item name={['settings_json', 'max_loop_count']} label="最大循环次数（0 = 不限）"><Input type="number" min={0} max={1000} /></Form.Item></Col>
              <Col span={12}><Form.Item name={['settings_json', 'timeout_seconds']} label="运行时长（秒，0 = 不限）"><Input type="number" min={0} max={86400} /></Form.Item></Col>
            </Row>
            <Form.Item name={['settings_json', 'model_binding']} label="默认模型绑定策略"><Select options={[{ value: 'task_or_global', label: '跟随任务 / 全局激活配置' }, { value: 'agent', label: '固定绑定 Agent 模型' }]} /></Form.Item>
            <Form.Item noStyle shouldUpdate={(previous, current) => previous.settings_json?.model_binding !== current.settings_json?.model_binding}>
              {({ getFieldValue }) => getFieldValue(['settings_json', 'model_binding']) === 'agent'
                ? <Form.Item name="model_config_id" label="绑定模型配置" rules={[{ required: true, message: '固定绑定时必须选择模型配置' }]}><Select options={modelOptions} placeholder="选择已启用并获授权的模型" /></Form.Item>
                : <>
                  <Form.Item name="model_config_id" hidden><Input /></Form.Item>
                  <Typography.Paragraph type="secondary">任务创建时由平台按任务授权选择模型；Agent 固定模型优先于任务会话配置。</Typography.Paragraph>
                </>}
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}><Form.Item name={['settings_json', 'network_search_enabled']} label="网络搜索" valuePropName="checked"><Switch disabled /></Form.Item></Col>
              <Col span={12}><Form.Item name={['settings_json', 'interactive_shell_enabled']} label="交互式 Shell" valuePropName="checked"><Switch disabled /></Form.Item></Col>
            </Row>
            <Alert type="warning" showIcon message="当前任务执行器尚未接入网络搜索与交互式 Shell" description="这两个能力暂时锁定，避免保存后给人已可运行的错觉。最大循环、运行时长和收尾提示词会版本化保存；任务 Worker 的执行边界仍由平台固定工作流控制。" style={{ marginBottom: 16 }} />
            <Form.Item name="is_enabled" label="启用 Agent" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item name="instruction" label="系统提示词 / Agent 指令"><Input.TextArea rows={15} maxLength={12000} showCount placeholder="描述角色、任务边界、操作步骤、证据要求与输出格式。此内容会随任务版本快照一并冻结。" /></Form.Item>
            <Space wrap style={{ marginTop: -10, marginBottom: 12 }}>
              <Typography.Text type="secondary">可插入变量：</Typography.Text>
              <Tag style={{ cursor: 'copy' }} onClick={() => void navigator.clipboard?.writeText('{{.Now}}')}>{'{{.Now}}'} · runtime</Tag>
              <Tag style={{ cursor: 'copy' }} onClick={() => void navigator.clipboard?.writeText('{{.DataDir}}')}>{'{{.DataDir}}'} · runtime</Tag>
            </Space>
            <Form.List name={['settings_json', 'runtime_variables']}>
              {(fields, { add, remove }) => <Card size="small" title="运行变量占位符" extra={<Button size="small" icon={<PlusOutlined />} onClick={() => add({ name: '', value: '' })}>新增变量</Button>} style={{ marginBottom: 16 }}>
                {fields.map((field) => <Row gutter={8} key={field.key} align="middle">
                  <Col span={7}><Form.Item name={[field.name, 'name']} label="变量名"><Input maxLength={80} placeholder="例如 Now" /></Form.Item></Col>
                  <Col span={14}><Form.Item name={[field.name, 'value']} label="占位符"><Input maxLength={200} placeholder="例如 {{.Now}}" /></Form.Item></Col>
                  <Col span={3}><Button danger type="link" onClick={() => remove(field.name)}>删除</Button></Col>
                </Row>)}
                {!fields.length && <Typography.Text type="secondary">暂无自定义变量</Typography.Text>}
              </Card>}
            </Form.List>
            <Card size="small" title="预览渲染" extra={<Tag>示例变量替换</Tag>}>
              <pre style={{ maxHeight: 220, overflow: 'auto', whiteSpace: 'pre-wrap', margin: 0 }}>{preview || '填写提示词后可预览渲染结果'}</pre>
            </Card>
          </> },
          { key: 'close', label: '收尾提示词', children: <>
            <Alert type="info" showIcon message="任务执行完成边界的提示词" description="当前任务工作流在固定状态机内收尾；这些提示词会保存在版本快照中，供收尾阶段配置使用。" style={{ marginBottom: 16 }} />
            <Form.Item name={['settings_json', 'close_step_prompt']} label="单次执行超时 / 步数耗尽时"><Input.TextArea rows={9} maxLength={12000} showCount placeholder="告诉 Agent 如何整理已取得的证据、标注未完成事项并结束本轮执行。" /></Form.Item>
            <Form.Item name={['settings_json', 'close_step_max_loops']} label="收尾阶段最大循环次数（0 = 不限）"><Input type="number" min={0} max={20} /></Form.Item>
            <Form.Item name={['settings_json', 'close_task_timeout_prompt']} label="整个任务超时时"><Input.TextArea rows={9} maxLength={12000} showCount placeholder="描述整个任务达到时限后如何给出最终状态与结论。" /></Form.Item>
            <Form.Item name={['settings_json', 'close_task_timeout_max_loops']} label="任务超时收尾最大循环次数"><Input type="number" min={0} max={20} /></Form.Item>
          </> },
          { key: 'mcp', label: 'MCP', children: <>
            <Alert type="warning" showIcon message="只允许绑定已审批的只读工具" description="MCP 服务必须处于连接状态，且工具已通过管理员审批。MCP 调用通过任务 Planner 执行并保留审计记录。" style={{ marginBottom: 16 }} />
            <Form.Item name="mcp_tool_keys" label="授权的 MCP 工具"><Select mode="multiple" options={toolOptions.filter((item) => item.value.startsWith('mcp:'))} placeholder="选择已连接且审批通过的只读工具" /></Form.Item>
            <Typography.Text type="secondary">MCP 工具的完整输入结构与发现结果可在 MCP 标签页查看。</Typography.Text>
          </> },
          { key: 'skill', label: 'Skill', children: <>
            <Form.Item name="skill_keys" label="加载的 Skill"><Select mode="multiple" options={skillOptions} placeholder="选择已启用 Skill；任务启动时会冻结所选版本和文件内容" /></Form.Item>
            <Form.Item name="child_agent_ids" label="子 Agent 节点"><Select mode="multiple" maxCount={8} disabled={!allowChildNodes} options={childAgentOptions} placeholder="按顺序加入最多 8 个已启用叶子 Agent" /></Form.Item>
            <Typography.Paragraph type="secondary">{allowChildNodes ? '子 Agent 需是无工具授权的叶子配置；父 Agent 会在任务创建时冻结它们的版本与 Skill。' : '该配置已作为其他 Agent 的子节点使用，因此只能保持叶子节点。'}</Typography.Paragraph>
          </> },
          { key: 'tools', label: 'Tools', children: <>
            <Form.Item name="tool_keys" label="绑定的系统工具"><Select mode="multiple" disabled={!allowChildNodes && Boolean(initial)} options={toolOptions.filter((item) => !item.value.startsWith('mcp:'))} placeholder="选择由平台注册并实现的工具" /></Form.Item>
            <Alert type="info" showIcon message="平台工具使用受控实现" description="执行代码、参数结构和安全校验由服务端维护。Shell、Python、任意命令与 HTTP 自定义工具尚未开放执行器，不会在这里伪装成可调用工具。" />
          </> },
          { key: 'triggers', label: '触发', children: <Form.List name="triggers_json">
            {(fields, { add, remove }) => <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Alert type="info" showIcon message="触发器配置会随 Agent 版本保存" description="任务平台当前按人工发起和已实现的任务事件运行；定时与事件触发定义先纳入治理配置，待调度器消费后才会自动创建会话。" />
              {fields.map((field) => <Card key={field.key} size="small" title={`触发器 ${field.name + 1}`} extra={<Button danger type="link" onClick={() => remove(field.name)}>删除</Button>}>
                <Row gutter={12}>
                  <Col span={14}><Form.Item name={[field.name, 'event']} label="事件"><Select options={[
                    ['schedule', '定时'], ['finding.discovered', '发现漏洞'], ['objective.achieved', '目标达成'], ['task.timeout', '任务超时'], ['tool.call', '工具调用'], ['task.created', '任务创建'],
                  ].map(([value, label]) => ({ value, label }))} /></Form.Item></Col>
                  <Col span={10}><Form.Item name={[field.name, 'enabled']} label="启用" valuePropName="checked"><Switch /></Form.Item></Col>
                </Row>
                <Form.Item name={[field.name, 'message']} label="触发消息"><Input.TextArea rows={3} maxLength={4000} /></Form.Item>
                <Form.Item noStyle shouldUpdate={(previous, current) => previous.triggers_json?.[field.name]?.event !== current.triggers_json?.[field.name]?.event}>{() => form.getFieldValue(['triggers_json', field.name, 'event']) === 'schedule' ? <Form.Item name={[field.name, 'schedule']} label="定时表达式"><Input placeholder="例如：0 9 * * 1-5" /></Form.Item> : null}</Form.Item>
                <Form.Item noStyle shouldUpdate={(previous, current) => previous.triggers_json?.[field.name]?.event !== current.triggers_json?.[field.name]?.event}>{() => form.getFieldValue(['triggers_json', field.name, 'event']) === 'tool.call' ? <Form.Item name={[field.name, 'tool_keys']} label="工具范围"><Select mode="multiple" options={toolOptions} /></Form.Item> : null}</Form.Item>
                <Row gutter={12}>
                  <Col span={8}><Form.Item name={[field.name, 'queue_policy']} label="队列策略"><Select options={[{ value: 'serial', label: '串行' }, { value: 'parallel', label: '并行' }]} /></Form.Item></Col>
                  <Col span={8}><Form.Item name={[field.name, 'coalesce_by']} label="合并范围"><Select options={[{ value: 'task', label: '同一任务' }, { value: 'all', label: '全部事件' }, { value: 'none', label: '不合并' }]} /></Form.Item></Col>
                  <Col span={8}><Form.Item name={[field.name, 'max_concurrency']} label="最大并发"><Input type="number" min={1} max={50} /></Form.Item></Col>
                </Row>
              </Card>)}
              <Button icon={<PlusOutlined />} onClick={() => add(defaultTrigger(fields.length))}>新增触发器</Button>
            </Space>}
          </Form.List> },
        ]} />
      </Form>
    </Drawer>
  );
}

function defaultAgentSettings() {
  return {
    model_binding: 'task_or_global' as const,
    max_loop_count: 0,
    timeout_seconds: 1200,
    network_search_enabled: false,
    interactive_shell_enabled: false,
    close_step_prompt: '',
    close_step_max_loops: 0,
    close_task_timeout_prompt: '',
    close_task_timeout_max_loops: 0,
    runtime_variables: [{ name: 'Now', value: '{{.Now}}' }, { name: 'DataDir', value: '{{.DataDir}}' }],
  };
}

function defaultTrigger(index: number): AgentTrigger {
  return {
    id: `trigger-${Date.now()}-${index}`, event: 'task.created', enabled: false, message: '', schedule: '',
    tool_keys: [], queue_policy: 'serial', coalesce_by: 'task', max_concurrency: 1,
  };
}

function SkillPane() {
  const [editing, setEditing] = useState<SkillDefinition | null>(null);
  const [creating, setCreating] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [categoryFilter, setCategoryFilter] = useState('全部');
  const [history, setHistory] = useState<{ kind: 'agent' | 'skill'; id: number; name: string } | null>(null);
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const skills = useQuery({ queryKey: ['agent-governance', 'skills'], queryFn: agentGovernanceApi.skills });
  const agents = useQuery({ queryKey: ['agent-governance', 'agents'], queryFn: agentGovernanceApi.agents });
  const mcpServers = useQuery({ queryKey: ['agent-governance', 'mcp-servers'], queryFn: agentGovernanceApi.mcpServers });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['agent-governance'] });
  const createMutation = useMutation({ mutationFn: agentGovernanceApi.createSkill, onSuccess: () => { message.success('Skill 已创建'); setCreating(false); setCurrentPage(1); setCategoryFilter('全部'); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const updateMutation = useMutation({ mutationFn: ({ id, body }: { id: number; body: Partial<SkillDefinition> }) => agentGovernanceApi.updateSkill(id, body), onSuccess: () => { message.success('Skill 已更新，版本已递增'); setEditing(null); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const deleteMutation = useMutation({ mutationFn: agentGovernanceApi.deleteSkill, onSuccess: () => { message.success('Skill 已删除'); setCurrentPage(1); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const importMutation = useMutation({ mutationFn: (file: File) => agentGovernanceApi.importSkillZip(file), onSuccess: (skill) => { message.success(`已导入 Skill「${skill.name}」`); setEditing(skill); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  if (skills.isPending || agents.isPending || mcpServers.isPending) return <LoadingState />;
  const failed = [skills, agents, mcpServers].find((query) => query.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  const allSkills = skills.data ?? [];
  const agentRows = agents.data ?? [];
  const mcpOptions = (mcpServers.data ?? []).flatMap((server) => server.discovered_tools_json
    .filter((tool) => server.approved_tools_json.includes(tool.name) && tool.annotations?.readOnlyHint === true)
    .map((tool) => ({
      label: `${server.name} / ${tool.name}`,
      value: `mcp:${server.id}:${tool.name}`,
      disabled: !server.is_enabled || server.connection_status !== 'connected',
    })));
  const categoryCounts = allSkills.reduce<Record<string, number>>((counts, skill) => {
    const category = skillCategory(skill.name);
    counts[category] = (counts[category] ?? 0) + 1;
    return counts;
  }, {});
  const categoryOptions = [
    { value: '全部', label: `全部分类 (${allSkills.length})` },
    ...Object.entries(categoryCounts).sort(([left], [right]) => left.localeCompare(right, 'zh-CN')).map(([category, count]) => ({ value: category, label: `${category} (${count})` })),
  ];
  const normalizedSearch = searchText.trim().toLocaleLowerCase();
  const visibleSkills = allSkills.filter((skill) =>
    (categoryFilter === '全部' || skillCategory(skill.name) === categoryFilter)
    && `${skill.name} ${skill.description}`.toLocaleLowerCase().includes(normalizedSearch),
  );
  const pageSkills = visibleSkills.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const onSubmit = (body: SkillInput) => editing ? updateMutation.mutate({ id: editing.id, body }) : createMutation.mutate(body);
  return <>
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
      <Space wrap size={8}>
        <Input.Search allowClear value={searchText} onChange={(event) => { setSearchText(event.target.value); setCurrentPage(1); }} placeholder="按 Skill 名称或说明搜索" style={{ width: 320, maxWidth: '100%' }} />
        <Select value={categoryFilter} onChange={(value) => { setCategoryFilter(value); setCurrentPage(1); }} options={categoryOptions} style={{ width: 180 }} />
      </Space>
      <Space>
        <Upload accept=".zip,application/zip" showUploadList={false} beforeUpload={(file) => { importMutation.mutate(file); return false; }}>
          <Button icon={<UploadOutlined />} loading={importMutation.isPending}>导入 Skill ZIP</Button>
        </Upload>
        <Button type="primary" onClick={() => setCreating(true)}>新增 Skill</Button>
      </Space>
    </div>
    <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>共 {visibleSkills.length} 个 Skill</Typography.Text>
    {visibleSkills.length ? <>
      <List
        size="small"
        bordered
        dataSource={pageSkills}
        renderItem={(skill) => {
          const category = skillCategory(skill.name);
          return <List.Item
            actions={[
              <Button key="detail" type="link" size="small" onClick={() => setEditing(skill)}>详情 / 编辑</Button>,
              <Button key="version" type="link" size="small" onClick={() => setHistory({ kind: 'skill', id: skill.id, name: skill.name })}>v{skill.version}</Button>,
              <Tag key="status" color={skill.is_enabled ? 'green' : 'default'}>{skill.is_enabled ? '启用' : '停用'}</Tag>,
              <Switch
                key="enabled"
                size="small"
                checked={skill.is_enabled}
                loading={updateMutation.isPending && updateMutation.variables?.id === skill.id}
                onChange={(checked) => updateMutation.mutate({ id: skill.id, body: { is_enabled: checked } })}
                aria-label={`${skill.is_enabled ? '停用' : '启用'} ${skill.name}`}
              />,
              <Button key="delete" type="link" size="small" danger onClick={() => modal.confirm({ title: `删除 Skill「${skill.name}」？`, okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(skill.id) })}>删除</Button>,
            ]}
          >
            <div
              role="button"
              tabIndex={0}
              aria-label={`编辑 Skill ${skill.name}`}
              onClick={() => setEditing(skill)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setEditing(skill); }
              }}
              style={{ flex: 1, minWidth: 0, cursor: 'pointer' }}
            >
              <List.Item.Meta
                title={<Space wrap size={6}><Typography.Text strong>{skill.name}</Typography.Text><Tag color={category === '安全' ? 'red' : category === '平台' ? 'blue' : 'default'}>{category}</Tag><Typography.Text type="secondary" style={{ fontSize: 12 }}>点击查看并编辑内容</Typography.Text></Space>}
                description={skill.description || '暂无说明'}
              />
            </div>
          </List.Item>;
        }}
      />
      {visibleSkills.length > pageSize && <Pagination
        current={currentPage}
        pageSize={pageSize}
        total={visibleSkills.length}
        showSizeChanger
        pageSizeOptions={[20, 40, 80]}
        showTotal={(total, range) => `${range[0]}-${range[1]} / 共 ${total} 个`}
        onChange={(page, nextPageSize) => { setCurrentPage(page); setPageSize(nextPageSize); }}
        style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 20 }}
      />}
    </> : <EmptyState description={normalizedSearch ? '没有匹配的 Skill' : '还没有 Skill'} />}
    <SkillFormModal key={editing ? `${editing.id}-${editing.version}` : (creating ? 'new' : 'closed')} open={creating || Boolean(editing)} initial={editing ?? undefined} loading={createMutation.isPending || updateMutation.isPending} agents={agentRows} mcpOptions={mcpOptions} onOpenHistory={() => editing && setHistory({ kind: 'skill', id: editing.id, name: editing.name })} onCancel={() => { setCreating(false); setEditing(null); }} onSubmit={onSubmit} />
    <DefinitionHistoryModal
      key={history ? `${history.kind}-${history.id}` : 'closed'}
      target={history}
      onClose={() => setHistory(null)}
      onRestored={(definition) => { if ('files_json' in definition) setEditing(definition); }}
    />
  </>;
}

function DefinitionHistoryModal({ target, onClose, onRestored }: {
  target: { kind: 'agent' | 'skill'; id: number; name: string } | null;
  onClose: () => void;
  onRestored: (definition: AgentDefinition | SkillDefinition) => void;
}) {
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const versions = useQuery({
    queryKey: ['agent-governance', 'versions', target?.kind, target?.id],
    queryFn: () => target?.kind === 'agent'
      ? agentGovernanceApi.agentVersions(target.id)
      : agentGovernanceApi.skillVersions(target!.id),
    enabled: Boolean(target),
  });
  const selected = versions.data?.find((item) => item.version === selectedVersion) ?? versions.data?.[0];
  const latest = versions.data?.[0];
  const restoreMutation = useMutation<AgentDefinition | SkillDefinition, Error>({
    mutationFn: () => target?.kind === 'agent'
      ? agentGovernanceApi.restoreAgentVersion(target.id, selected!.version)
      : agentGovernanceApi.restoreSkillVersion(target!.id, selected!.version),
    onSuccess: (definition) => {
      message.success('历史配置已恢复为新的版本');
      void queryClient.invalidateQueries({ queryKey: ['agent-governance'] });
      onRestored(definition);
      onClose();
    },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  const changedFields = selected && latest
    ? [...new Set([...Object.keys(selected.snapshot_json), ...Object.keys(latest.snapshot_json)])].filter((key) => JSON.stringify(selected.snapshot_json[key]) !== JSON.stringify(latest.snapshot_json[key]))
    : [];
  return <Modal title={target ? `${target.name} · 版本历史` : '版本历史'} open={Boolean(target)} onCancel={onClose} footer={<Space><Button onClick={onClose}>关闭</Button><Button type="primary" disabled={!selected || selected.version === latest?.version} loading={restoreMutation.isPending} onClick={() => restoreMutation.mutate()}>恢复为新版本</Button></Space>} width={760}>
    {versions.isPending ? <LoadingState /> : versions.isError ? <ErrorState error={versions.error} onRetry={versions.refetch} /> : versions.data?.length ? <>
      <Table<DefinitionVersion>
        size="small"
        rowKey="version"
        dataSource={versions.data}
        pagination={false}
        onRow={(row) => ({ onClick: () => setSelectedVersion(row.version), style: { cursor: 'pointer', background: selected?.version === row.version ? 'rgba(82, 112, 255, 0.08)' : undefined } })}
        columns={[{ title: '版本', dataIndex: 'version', render: (value: number) => `v${value}` }, { title: '保存时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString() }]}
      />
      <Typography.Text type="secondary">恢复会保留此历史快照，并将当前配置另存为新的版本号。</Typography.Text>
      <Card size="small" title={`与当前版本 v${latest?.version ?? '-' } 的差异`} style={{ marginTop: 12 }}>
        {changedFields.length ? <Space wrap>{changedFields.map((field) => <Tag key={field} color="orange">{field}</Tag>)}</Space> : <Typography.Text type="secondary">此版本与当前版本相同</Typography.Text>}
      </Card>
      <pre style={{ marginTop: 12, padding: 12, maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,.03)', borderRadius: 8 }}>{JSON.stringify(selected?.snapshot_json ?? {}, null, 2)}</pre>
    </> : <EmptyState description="暂无历史版本" />}
  </Modal>;
}

function SkillFormModal({ open, initial, loading, agents, mcpOptions, onOpenHistory, onCancel, onSubmit }: {
  open: boolean;
  initial?: SkillDefinition;
  loading: boolean;
  agents: AgentDefinition[];
  mcpOptions: { label: string; value: string; disabled?: boolean }[];
  onOpenHistory: () => void;
  onCancel: () => void;
  onSubmit: (body: SkillInput) => void;
}) {
  const [form] = Form.useForm();
  const { message } = App.useApp();
  const [files, setFiles] = useState<Record<string, string>>(initial?.files_json ?? { 'SKILL.md': initial?.content ?? '' });
  const [selectedPath, setSelectedPath] = useState('SKILL.md');
  const [newPath, setNewPath] = useState('');
  const usage = useQuery({
    queryKey: ['agent-governance', 'skill-usage', initial?.id],
    queryFn: () => agentGovernanceApi.skillUsage(initial!.id),
    enabled: Boolean(initial),
  });
  const linkedAgents = agents.filter((agent) => agent.skill_keys.includes(initial?.key ?? ''));
  const submit = (values: Omit<SkillInput, 'content' | 'files_json'>) => {
    if (!files['SKILL.md']?.trim()) {
      message.error('Skill 文件树必须包含非空的 SKILL.md');
      return;
    }
    onSubmit({ ...values, content: files['SKILL.md'], files_json: files });
  };
  const addFile = () => {
    const path = newPath.trim().replace(/\\/g, '/');
    if (!path || path.startsWith('/') || path.split('/').some((part: string) => !part || part === '.' || part === '..')) {
      message.error('请输入安全的相对文件路径');
      return;
    }
    if (files[path] !== undefined) {
      message.error('该文件已存在');
      return;
    }
    setFiles((current) => ({ ...current, [path]: '' }));
    setSelectedPath(path);
    setNewPath('');
  };
  const defaultFiles = initial?.files_json ?? { 'SKILL.md': initial?.content ?? '' };
  return <Drawer
    title={initial ? `Skill 详情与编辑：${initial.name}` : '新增 Skill'}
    open={open}
    onClose={onCancel}
    width={760}
    destroyOnClose
    extra={initial ? <Space><Tag color={initial.is_enabled ? 'green' : 'default'}>{initial.is_enabled ? '启用' : '停用'}</Tag><Tag>v{initial.version}</Tag></Space> : null}
    footer={<Space style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
      <Space>{initial && <Button onClick={onOpenHistory}>版本历史</Button>}{initial && <Button onClick={() => { setFiles(defaultFiles); form.setFieldsValue({ name: initial.name, description: initial.description, is_enabled: initial.is_enabled, mcp_tool_keys_json: initial.mcp_tool_keys_json }); }}>放弃未保存修改</Button>}</Space>
      <Space><Button onClick={onCancel}>关闭</Button><Button type="primary" loading={loading} onClick={() => form.submit()}>{initial ? '保存为新版本' : '创建 Skill'}</Button></Space>
    </Space>}
  >
    <Form form={form} layout="vertical" initialValues={initial ? { ...initial, mcp_tool_keys_json: initial.mcp_tool_keys_json ?? [] } : { is_enabled: false, mcp_tool_keys_json: [] }} onFinish={submit}>
      <Tabs items={[
        { key: 'overview', label: '概览与内容', children: <>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="name" label="Skill 名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item></Col>
            <Col span={12}><Form.Item name="is_enabled" label="启用 Skill" valuePropName="checked"><Switch /></Form.Item></Col>
          </Row>
          <Form.Item name="description" label="Skill 描述"><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
          <Alert type="info" showIcon message="AgentSkills 文件库" description="Skill 使用 SKILL.md 作为入口文件。任务创建时，已绑定 Agent 的任务快照会保留所有相关文件内容和版本。" style={{ marginBottom: 16 }} />
          <Space align="start" style={{ display: 'flex' }}>
            <div style={{ width: 220, flexShrink: 0 }}>
              <Space.Compact style={{ width: '100%', marginBottom: 10 }}>
                <Input value={newPath} onChange={(event) => setNewPath(event.target.value)} placeholder="文件路径，如 references/api.md" onPressEnter={addFile} />
                <Button icon={<PlusOutlined />} onClick={addFile} />
              </Space.Compact>
              <List size="small" bordered dataSource={Object.keys(files).sort()} renderItem={(path) => <List.Item style={{ cursor: 'pointer', background: path === selectedPath ? 'rgba(82,112,255,.08)' : undefined }} onClick={() => setSelectedPath(path)}>
                <Typography.Text ellipsis={{ tooltip: path }} style={{ maxWidth: 170 }}>{path}</Typography.Text>
                {path !== 'SKILL.md' && <Button size="small" type="link" danger onClick={(event) => { event.stopPropagation(); setFiles((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== path))); if (selectedPath === path) setSelectedPath('SKILL.md'); }}>删除</Button>}
              </List.Item>} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Typography.Text strong>{selectedPath}</Typography.Text>
              <Input.TextArea
                value={files[selectedPath] ?? ''}
                onChange={(event) => setFiles((current) => ({ ...current, [selectedPath]: event.target.value }))}
                rows={22}
                maxLength={100000}
                showCount
                style={{ marginTop: 8, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}
              />
            </div>
          </Space>
        </> },
        { key: 'mcp', label: 'MCP 与 Agent', children: <>
          <Form.Item name="mcp_tool_keys_json" label="Skill 加载时关联的 MCP 工具"><Select mode="multiple" options={mcpOptions} placeholder="选择已审批、只读的 MCP 工具" /></Form.Item>
          <Typography.Text type="secondary">仅当绑定本 Skill 的 Agent 加载该 Skill 时，关联工具才会进入任务快照。</Typography.Text>
          {initial && <>
            <Typography.Title level={5} style={{ marginTop: 24 }}>Agent 可见范围</Typography.Title>
            {linkedAgents.length ? <Space wrap>{linkedAgents.map((agent) => <Tag key={agent.id}>{agent.name} · v{agent.version}</Tag>)}</Space> : <Typography.Text type="secondary">尚未绑定 Agent。可在 Agent 详情的 Skill 标签中绑定。</Typography.Text>}
            <Typography.Title level={5} style={{ marginTop: 24 }}>使用统计</Typography.Title>
            {usage.isPending ? <LoadingState /> : usage.isError ? <ErrorState error={usage.error} onRetry={usage.refetch} /> : <>
              <Row gutter={12}>
                <Col span={8}><Card size="small"><Typography.Text type="secondary">任务加载次数</Typography.Text><Typography.Title level={4}>{usage.data?.total_loads ?? 0}</Typography.Title></Card></Col>
                <Col span={8}><Card size="small"><Typography.Text type="secondary">关联任务</Typography.Text><Typography.Title level={4}>{usage.data?.task_count ?? 0}</Typography.Title></Card></Col>
                <Col span={8}><Card size="small"><Typography.Text type="secondary">最近使用</Typography.Text><Typography.Paragraph>{usage.data?.last_used_at ? new Date(usage.data.last_used_at).toLocaleString() : '从未使用'}</Typography.Paragraph></Card></Col>
              </Row>
              <Typography.Title level={5}>加载此 Skill 的 Agent</Typography.Title>
              {usage.data?.agents.length ? <Space wrap>{usage.data.agents.map((agent) => <Tag key={agent.id}>{agent.name} · {agent.loads} 次</Tag>)}</Space> : <Typography.Text type="secondary">暂无加载记录</Typography.Text>}
              <Typography.Title level={5}>最近加载任务</Typography.Title>
              {usage.data?.recent_tasks.length ? <List size="small" dataSource={usage.data.recent_tasks} renderItem={(task) => <List.Item>{task.title} · 第 {task.run_number} 次运行 · {new Date(task.used_at).toLocaleString()}</List.Item>} /> : <Typography.Text type="secondary">暂无关联任务</Typography.Text>}
            </>}
          </>}
        </> },
      ]} />
    </Form>
  </Drawer>;
}

function McpPane() {
  const [editing, setEditing] = useState<MCPServer | null>(null);
  const [creating, setCreating] = useState(false);
  const [inspecting, setInspecting] = useState<MCPServer | null>(null);
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const servers = useQuery({ queryKey: ['agent-governance', 'mcp'], queryFn: agentGovernanceApi.mcpServers });
  const agents = useQuery({ queryKey: ['agent-governance', 'agents'], queryFn: agentGovernanceApi.agents });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['agent-governance', 'mcp'] });
  const createMutation = useMutation({ mutationFn: agentGovernanceApi.createMcpServer, onSuccess: () => { message.success('MCP 服务已登记'); setCreating(false); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const updateMutation = useMutation({ mutationFn: ({ id, body }: { id: number; body: { name?: string; endpoint?: string; auth_type?: 'none' | 'bearer'; auth_token?: string; is_enabled?: boolean } }) => agentGovernanceApi.updateMcpServer(id, body), onSuccess: () => { message.success('MCP 配置已更新'); setEditing(null); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const discoverMutation = useMutation({ mutationFn: agentGovernanceApi.discoverMcpTools, onSuccess: (server) => { message.success(`已发现 ${server.discovered_tools_json.length} 个工具`); setInspecting(server); invalidate(); }, onError: (e) => { message.error(getErrorMessage(e)); invalidate(); } });
  const approveMutation = useMutation({ mutationFn: ({ id, names }: { id: number; names: string[] }) => agentGovernanceApi.approveMcpTools(id, names), onSuccess: (server) => { message.success('工具审批清单已保存'); setInspecting(server); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const deleteMutation = useMutation({ mutationFn: agentGovernanceApi.deleteMcpServer, onSuccess: () => { message.success('MCP 服务已删除'); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  if (servers.isPending || agents.isPending) return <LoadingState />;
  const failed = [servers, agents].find((query) => query.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  const serverRows = servers.data ?? [];
  const agentRows = agents.data ?? [];
  const onSubmit = (body: { name: string; endpoint: string; auth_type: 'none' | 'bearer'; auth_token?: string; is_enabled: boolean }) => editing ? updateMutation.mutate({ id: editing.id, body }) : createMutation.mutate(body);
  return <>
    <Alert type="warning" showIcon message="MCP 调用限定为管理员审批的只读工具" description="配置 Agent 时可关联已审批工具，任务 Planner 可能在制定方案时调用只读工具并写入任务审计回执。写入、高风险或未标注 readOnlyHint 的工具不会自动执行；Bearer 凭据加密保存且接口不回传明文。" style={{ marginBottom: 12 }} />
    <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}><Button type="primary" icon={<ApiOutlined />} onClick={() => setCreating(true)}>新增 MCP 服务</Button></div>
    {serverRows.length ? <Row gutter={[12, 12]}>
      {serverRows.map((server) => {
        const linkedAgents = agentRows.filter((agent) => agent.tool_keys.some((key) => key.startsWith(`mcp:${server.id}:`)));
        const connectionLabel = server.connection_status === 'connected' ? '已连接' : server.connection_status === 'error' ? '连接失败' : '未检查';
        const connectionColor = server.connection_status === 'connected' ? 'green' : server.connection_status === 'error' ? 'red' : 'default';
        return <Col xs={24} md={12} xl={8} xxl={6} key={server.id}>
          <Card size="small" style={{ height: '100%' }} styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', padding: 12 } }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <Typography.Text strong ellipsis={{ tooltip: server.name }}>{server.name}</Typography.Text>
                <div style={{ marginTop: 4 }}><Tag>{server.auth_type === 'bearer' ? 'Bearer' : '无认证'}</Tag><Tag color={connectionColor}>{connectionLabel}</Tag></div>
              </div>
              <Switch
                checked={server.is_enabled}
                loading={updateMutation.isPending && updateMutation.variables?.id === server.id}
                size="small"
                onChange={(checked) => updateMutation.mutate({ id: server.id, body: { is_enabled: checked } })}
                aria-label={`${server.is_enabled ? '停用' : '启用'} ${server.name}`}
              />
            </div>
            <Typography.Text type="secondary" ellipsis={{ tooltip: server.endpoint }} style={{ display: 'block', marginTop: 8 }}>{server.endpoint}</Typography.Text>
            {server.last_error && <Typography.Text type="danger" ellipsis={{ tooltip: server.last_error }} style={{ display: 'block', marginTop: 4 }}>{server.last_error}</Typography.Text>}
            <Space wrap size={[4, 4]} style={{ marginTop: 8 }}>
              <Tag>{server.discovered_tools_json.length} 个工具</Tag>
              <Tag color="blue">已审批 {server.approved_tools_json.length}</Tag>
            </Space>
            <div style={{ marginTop: 'auto', paddingTop: 12 }}>
              <Typography.Text type="secondary">Agent 授权</Typography.Text>
              <div style={{ minHeight: 28, marginTop: 4 }}>
                {linkedAgents.length ? <Space wrap size={[4, 4]}>{linkedAgents.map((agent) => <Tag key={agent.id}>{agent.name}</Tag>)}</Space> : <Typography.Text type="secondary">尚未关联 Agent</Typography.Text>}
              </div>
              <Space wrap size={4} style={{ width: '100%', marginTop: 8 }}>
                <Button size="small" loading={discoverMutation.isPending && discoverMutation.variables === server.id} onClick={() => discoverMutation.mutate(server.id)}>连接并发现</Button>
                <Button size="small" onClick={() => setInspecting(server)}>工具清单</Button>
                <Button size="small" onClick={() => setEditing(server)}>编辑</Button>
                <Button size="small" danger onClick={() => modal.confirm({ title: `删除 MCP 服务「${server.name}」？`, okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(server.id) })}>删除</Button>
              </Space>
            </div>
          </Card>
        </Col>;
      })}
    </Row> : <EmptyState description="还没有登记 MCP 服务" />}
    <McpFormModal key={editing?.id ?? (creating ? 'new' : 'closed')} open={creating || Boolean(editing)} initial={editing ?? undefined} loading={createMutation.isPending || updateMutation.isPending} onCancel={() => { setCreating(false); setEditing(null); }} onSubmit={onSubmit} />
    <McpToolsModal
      key={inspecting ? `${inspecting.id}-${inspecting.last_checked_at ?? 'initial'}` : 'closed'}
      server={inspecting}
      loading={approveMutation.isPending}
      onCancel={() => setInspecting(null)}
      onSave={(names) => inspecting && approveMutation.mutate({ id: inspecting.id, names })}
    />
  </>;
}

function McpToolsModal({ server, loading, onCancel, onSave }: {
  server: MCPServer | null;
  loading: boolean;
  onCancel: () => void;
  onSave: (names: string[]) => void;
}) {
  const [selected, setSelected] = useState(server?.approved_tools_json ?? []);
  return <Modal title={server ? `${server.name} · 发现工具` : '发现工具'} open={Boolean(server)} onCancel={onCancel} onOk={() => onSave(selected)} confirmLoading={loading} okText="保存审批清单" width={680}>
    {server && <>
      {server.discovered_tools_json.length ? <Checkbox.Group value={selected} onChange={(values) => setSelected(values as string[])} style={{ display: 'block' }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          {server.discovered_tools_json.map((tool) => <Card key={tool.name} size="small"><Checkbox value={tool.name}><Typography.Text strong>{tool.name}</Typography.Text></Checkbox><Tag color={tool.annotations?.readOnlyHint ? 'green' : 'orange'}>{tool.annotations?.readOnlyHint ? '只读，可用于规划' : '审批后也不会自动执行'}</Tag><div><Typography.Text type="secondary">{tool.description || '无描述'}</Typography.Text></div></Card>)}
        </Space>
      </Checkbox.Group> : <EmptyState description="尚未发现工具，请先执行连接并发现" />}
    </>}
  </Modal>;
}

function McpFormModal({ open, initial, loading, onCancel, onSubmit }: {
  open: boolean;
  initial?: MCPServer;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: { name: string; endpoint: string; auth_type: 'none' | 'bearer'; auth_token?: string; is_enabled: boolean }) => void;
}) {
  const [form] = Form.useForm();
  return <Modal title={initial ? `编辑 MCP 服务：${initial.name}` : '新增 MCP 服务'} open={open} onCancel={onCancel} onOk={() => form.submit()} confirmLoading={loading} width={640} destroyOnClose>
    <Form form={form} layout="vertical" initialValues={initial ? { name: initial.name, endpoint: initial.endpoint, auth_type: initial.auth_type, is_enabled: initial.is_enabled } : { auth_type: 'none', is_enabled: false }} onFinish={onSubmit}>
      <Form.Item name="name" label="服务名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item>
      <Form.Item name="endpoint" label="MCP Streamable HTTP 地址" rules={[{ required: true, type: 'url' }]}><Input placeholder="https://mcp.example.com/mcp" /></Form.Item>
      <Form.Item name="auth_type" label="认证方式"><Select options={[{ value: 'none', label: '无认证' }, { value: 'bearer', label: 'Bearer Token' }]} /></Form.Item>
      <Form.Item noStyle shouldUpdate={(prev, next) => prev.auth_type !== next.auth_type}>{({ getFieldValue }) => getFieldValue('auth_type') === 'bearer' ? <Form.Item name="auth_token" label="Bearer Token" rules={initial ? [] : [{ required: true }]} extra={initial?.has_auth ? '留空保留已保存凭据；重新填写会覆盖。' : undefined}><Input.Password placeholder={initial?.has_auth ? '已配置，留空表示保留' : '粘贴访问令牌'} /></Form.Item> : null}</Form.Item>
      <Form.Item name="is_enabled" label="启用登记" valuePropName="checked"><Switch /></Form.Item>
    </Form>
  </Modal>;
}

function ToolsPane() {
  const [searchText, setSearchText] = useState('');
  const [detail, setDetail] = useState<GovernanceTool | null>(null);
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const tools = useQuery({ queryKey: ['agent-governance', 'tools'], queryFn: agentGovernanceApi.tools });
  const agents = useQuery({ queryKey: ['agent-governance', 'agents'], queryFn: agentGovernanceApi.agents });
  const updateMutation = useMutation({
    mutationFn: ({ key, body }: { key: string; body: GovernanceToolUpdate }) => agentGovernanceApi.updateTool(key, body),
    onSuccess: () => {
      message.success('工具说明和 Agent 授权已保存');
      setDetail(null);
      void queryClient.invalidateQueries({ queryKey: ['agent-governance'] });
    },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  const restoreMutation = useMutation({
    mutationFn: agentGovernanceApi.restoreToolDefaults,
    onSuccess: (tool) => {
      message.success('已恢复工具默认配置');
      setDetail(tool);
      void queryClient.invalidateQueries({ queryKey: ['agent-governance'] });
    },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  if (tools.isPending || agents.isPending) return <LoadingState />;
  const failed = [tools, agents].find((query) => query.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  const toolRows = tools.data ?? [];
  const agentRows = agents.data ?? [];
  const normalizedSearch = searchText.trim().toLocaleLowerCase();
  const visibleTools = toolRows.filter((tool) => {
    const linkedAgentNames = agentRows.filter((agent) => agent.tool_keys.includes(tool.key)).map((agent) => agent.name).join(' ');
    return `${tool.name} ${tool.description} ${tool.key} ${tool.category} ${tool.risk} ${linkedAgentNames}`.toLocaleLowerCase().includes(normalizedSearch);
  });
  const riskColor = (risk: string) => risk === '高风险' ? 'red' : risk === '执行' ? 'orange' : risk === '写入' ? 'blue' : 'default';
  return <>
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <Input.Search allowClear value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="搜索工具名、描述、Agent..." style={{ maxWidth: 420 }} />
        <Typography.Text type="secondary">共 {visibleTools.length} 个工具 · 点击卡片查看详情</Typography.Text>
      </div>
    </div>
    {visibleTools.length ? <Row gutter={[12, 12]}>
      {visibleTools.map((tool) => {
        const linkedAgents = agentRows.filter((agent) => agent.tool_keys.includes(tool.key));
        return <Col xs={24} md={12} xl={8} xxl={6} key={tool.key}>
          <Card
            size="small"
            hoverable
            role="button"
            tabIndex={0}
            onClick={() => setDetail(tool)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setDetail(tool); }
            }}
            style={{ height: '100%' }}
            styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', padding: 12 } }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <Typography.Text strong ellipsis={{ tooltip: tool.name }} style={{ display: 'block' }}>{tool.name}</Typography.Text>
                <Space size={4} style={{ marginTop: 4 }}>
                  <Tag>{tool.category}</Tag>
                  <Tag color={riskColor(tool.risk)}>{tool.risk}</Tag>
                </Space>
              </div>
              <Tag>系统</Tag>
            </div>
            <Typography.Paragraph type="secondary" ellipsis={{ rows: 2, tooltip: tool.description || '无描述' }} style={{ marginTop: 8, marginBottom: 6, minHeight: 40 }}>
              {tool.description || '无描述'}
            </Typography.Paragraph>
            <div style={{ marginTop: 'auto', paddingTop: 8 }}>
              <Tag color={tool.is_enabled ? 'green' : 'default'}>{tool.is_enabled ? '启用' : '停用'}</Tag>
              <Typography.Text type="secondary">Agent 绑定</Typography.Text>
              <div style={{ minHeight: 28, marginTop: 4 }}>
                {linkedAgents.length ? <Space wrap size={[4, 4]}>{linkedAgents.map((agent) => <Tag key={agent.id}>{agent.name}</Tag>)}</Space> : <Typography.Text type="secondary">尚未绑定</Typography.Text>}
              </div>
            </div>
          </Card>
        </Col>;
      })}
    </Row> : <EmptyState description={normalizedSearch ? '没有匹配的工具' : '还没有系统工具'} />}
    <ToolDetailModal
      tool={detail}
      agents={agentRows}
      loading={updateMutation.isPending}
      restoring={restoreMutation.isPending}
      onClose={() => setDetail(null)}
      onRestore={() => detail && restoreMutation.mutate(detail.key)}
      onSubmit={(body) => detail && updateMutation.mutate({ key: detail.key, body })}
    />
  </>;
}

function ToolDetailModal({ tool, agents, loading, restoring, onClose, onRestore, onSubmit }: {
  tool: GovernanceTool | null;
  agents: AgentDefinition[];
  loading: boolean;
  restoring: boolean;
  onClose: () => void;
  onRestore: () => void;
  onSubmit: (body: GovernanceToolUpdate) => void;
}) {
  const [form] = Form.useForm<GovernanceToolUpdate>();
  useEffect(() => {
    if (!tool) return;
    form.setFieldsValue({
      description: tool.description,
      agent_ids: tool.agent_ids?.length ? tool.agent_ids : agents.filter((agent) => agent.tool_keys.includes(tool.key)).map((agent) => agent.id),
      parameter_overrides_json: tool.parameter_overrides_json ?? {},
      is_enabled: tool.is_enabled ?? true,
    });
  }, [agents, form, tool]);
  return <Drawer
    title={tool ? `工具详情与配置：${tool.name}` : '工具详情与配置'}
    open={Boolean(tool)}
    onClose={onClose}
    width={720}
    destroyOnClose
    extra={tool ? <Tag color={tool.risk === '高风险' ? 'red' : tool.risk === '执行' ? 'orange' : tool.risk === '写入' ? 'blue' : 'default'}>{tool.risk}</Tag> : null}
    footer={<Space style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}><Button onClick={onRestore} loading={restoring}>恢复默认</Button><Space><Button onClick={onClose}>关闭</Button><Button type="primary" loading={loading} onClick={() => form.submit()}>保存配置</Button></Space></Space>}
  >
    {tool && <>
      <Alert type="info" showIcon message="平台内置工具" description="工具实现、分类和风险级别由平台代码维护；此处可编辑治理目录说明及 Agent 授权。固定任务工作流仍只执行平台已有实现，修改说明不会创建新的执行器。保存授权后，相关 Agent 会生成新版本。" style={{ marginBottom: 16 }} />
      <Space wrap size={[8, 8]} style={{ marginBottom: 16 }}>
        <Tag>{tool.category}</Tag>
        <Tag>系统工具</Tag>
      </Space>
      <Form
        key={tool.key}
        form={form}
        layout="vertical"
        initialValues={{
          description: tool.description,
        agent_ids: tool.agent_ids?.length ? tool.agent_ids : agents.filter((agent) => agent.tool_keys.includes(tool.key)).map((agent) => agent.id),
        parameter_overrides_json: tool.parameter_overrides_json ?? {},
        is_enabled: tool.is_enabled ?? true,
        }}
        onFinish={onSubmit}
      >
        <Tabs items={[
          { key: 'details', label: '配置与说明', children: <>
            <Form.Item name="is_enabled" label="启用工具" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item name="description" label="治理目录说明" rules={[{ required: true, message: '请填写工具用途说明' }]}>
              <Input.TextArea rows={6} maxLength={2000} showCount />
            </Form.Item>
            <Typography.Title level={5}>参数定义</Typography.Title>
            {tool.parameters?.length ? tool.parameters.map((parameter) => <Card size="small" key={parameter.name} title={<Space><Typography.Text strong>{parameter.name}</Typography.Text><Tag>{parameter.type}</Tag>{parameter.required && <Tag color="red">必填</Tag>}</Space>} style={{ marginBottom: 10 }}>
              <Typography.Text type="secondary">由服务端注册表定义；参数名、类型与必填状态保持只读。</Typography.Text>
              <Form.Item name={['parameter_overrides_json', parameter.name, 'description']} label="参数说明" style={{ marginTop: 12 }}>
                <Input.TextArea rows={2} maxLength={4000} placeholder={parameter.description} />
              </Form.Item>
              <Form.Item name={['parameter_overrides_json', parameter.name, 'default']} label="默认值">
                <Input maxLength={4000} placeholder={parameter.default ?? '未设置'} />
              </Form.Item>
            </Card>) : <Alert type="info" showIcon message="固定任务上下文工具" description="此工具由任务执行服务按固定输入结构调用，不接受自定义参数 Schema。平台会校验任务上下文和项目权限。" />}
          </> },
          { key: 'agents', label: '绑定 Agent', children: <>
        <Form.Item name="agent_ids" label="绑定 Agent">
          <Checkbox.Group style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
            {agents.length ? agents.map((agent) => <Checkbox key={agent.id} value={agent.id} style={{ alignItems: 'flex-start' }}>
              <Space direction="vertical" size={0}>
                <Typography.Text>{agent.name}</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {agent.workflow_template} · v{agent.version} · {agent.is_enabled ? '启用' : '停用'}
                </Typography.Text>
              </Space>
            </Checkbox>) : <Typography.Text type="secondary">暂无可绑定的 Agent</Typography.Text>}
          </Checkbox.Group>
        </Form.Item>
          </> },
        ]} />
      </Form>
    </>}
  </Drawer>;
}
