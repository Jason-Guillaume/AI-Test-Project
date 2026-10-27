import {
  App,
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
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
} from 'antd';
import { ApiOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { agentGovernanceApi, type AgentDefinition, type AgentDefinitionInput, type DefinitionVersion, type MCPServer, type SkillDefinition } from '@/api/agentGovernance';
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
          <Card size="small" style={{ height: '100%' }} styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', padding: 12 } }}>
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
              <Button size="small" style={{ flex: 1 }} onClick={() => setEditing(agent)}>编辑配置</Button>
              <Button size="small" danger onClick={() => modal.confirm({ title: `删除 Agent「${agent.name}」？`, okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(agent.id) })}>删除</Button>
            </Space>
          </Card>
        </Col>)}
      </Row> : <EmptyState description="还没有 Agent 定义" />}
      <AgentFormModal
        key={editing?.id ?? (creating ? 'new' : 'closed')}
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
      <DefinitionHistoryModal key={history ? `${history.kind}-${history.id}` : 'closed'} target={history} onClose={() => setHistory(null)} />
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
  const [form] = Form.useForm<AgentDefinitionInput>();
  return (
    <Modal title={initial ? `编辑 Agent：${initial.name}` : '新增 Agent'} open={open} onCancel={onCancel} onOk={() => form.submit()} confirmLoading={loading} width={720} destroyOnClose>
      <Form form={form} layout="vertical" initialValues={initial ?? { is_enabled: false, skill_keys: [], tool_keys: [], child_agent_ids: [], instruction: '' }} onFinish={onSubmit}>
        <Row gutter={16}>
          <Col span={12}><Form.Item name="name" label="Agent 名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item></Col>
          <Col span={12}><Form.Item name="workflow_template" label="工作流模板" rules={[{ required: true }]}><Select options={workflows.map((item) => ({ value: item.key, label: item.label }))} /></Form.Item></Col>
        </Row>
        <Form.Item name="description" label="说明"><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
        <Form.Item name="instruction" label="补充指令"><Input.TextArea rows={4} maxLength={12000} placeholder="限定该 Agent 的任务范围和输出要求" /></Form.Item>
        <Form.Item name="model_config_id" label="默认模型"><Select allowClear placeholder="沿用工作流默认模型" options={modelOptions} /></Form.Item>
        <Form.Item name="child_agent_ids" label="子 Agent 节点"><Select mode="multiple" maxCount={8} disabled={!allowChildNodes} options={childAgentOptions} placeholder="可选：按顺序加入最多 8 个已启用叶子 Agent" /></Form.Item>
        <Typography.Paragraph type="secondary" style={{ marginTop: -16 }}>{allowChildNodes ? '子 Agent 需是无工具授权的叶子配置，作为分析节点依次运行；父 Agent 会在任务创建时冻结它们的版本与 Skill。' : '该配置已作为其他 Agent 的子节点使用，因此只能保持叶子节点。'}</Typography.Paragraph>
        <Form.Item name="skill_keys" label="关联 Skill"><Select mode="multiple" options={skillOptions} placeholder="先创建并启用 Skill" /></Form.Item>
        <Form.Item name="tool_keys" label="允许使用的工具"><Select mode="multiple" disabled={!allowChildNodes && Boolean(initial)} options={toolOptions} placeholder="内置工具或已审批的 MCP 只读工具" /></Form.Item>
        <Form.Item name="is_enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Modal>
  );
}

function SkillPane() {
  const [editing, setEditing] = useState<SkillDefinition | null>(null);
  const [creating, setCreating] = useState(false);
  const [detail, setDetail] = useState<SkillDefinition | null>(null);
  const [searchText, setSearchText] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [categoryFilter, setCategoryFilter] = useState('全部');
  const [history, setHistory] = useState<{ kind: 'agent' | 'skill'; id: number; name: string } | null>(null);
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const skills = useQuery({ queryKey: ['agent-governance', 'skills'], queryFn: agentGovernanceApi.skills });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['agent-governance'] });
  const createMutation = useMutation({ mutationFn: agentGovernanceApi.createSkill, onSuccess: () => { message.success('Skill 已创建'); setCreating(false); setCurrentPage(1); setCategoryFilter('全部'); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const updateMutation = useMutation({ mutationFn: ({ id, body }: { id: number; body: Partial<SkillDefinition> }) => agentGovernanceApi.updateSkill(id, body), onSuccess: () => { message.success('Skill 已更新，版本已递增'); setEditing(null); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const deleteMutation = useMutation({ mutationFn: agentGovernanceApi.deleteSkill, onSuccess: () => { message.success('Skill 已删除'); setCurrentPage(1); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  if (skills.isPending) return <LoadingState />;
  if (skills.isError) return <ErrorState error={skills.error} onRetry={skills.refetch} />;
  const allSkills = skills.data ?? [];
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
  const onSubmit = (body: { name: string; description: string; content: string; is_enabled: boolean }) => editing ? updateMutation.mutate({ id: editing.id, body }) : createMutation.mutate(body);
  return <>
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
      <Space wrap size={8}>
        <Input.Search allowClear value={searchText} onChange={(event) => { setSearchText(event.target.value); setCurrentPage(1); }} placeholder="按 Skill 名称或说明搜索" style={{ width: 320, maxWidth: '100%' }} />
        <Select value={categoryFilter} onChange={(value) => { setCategoryFilter(value); setCurrentPage(1); }} options={categoryOptions} style={{ width: 180 }} />
      </Space>
      <Button type="primary" onClick={() => setCreating(true)}>新增 Skill</Button>
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
              <Button key="detail" type="link" size="small" onClick={() => setDetail(skill)}>查看详情</Button>,
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
              <Button key="edit" type="link" size="small" onClick={() => setEditing(skill)}>编辑</Button>,
              <Button key="delete" type="link" size="small" danger onClick={() => modal.confirm({ title: `删除 Skill「${skill.name}」？`, okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(skill.id) })}>删除</Button>,
            ]}
          >
            <List.Item.Meta
              title={<Space wrap size={6}><Typography.Text strong>{skill.name}</Typography.Text><Tag color={category === '安全' ? 'red' : category === '平台' ? 'blue' : 'default'}>{category}</Tag></Space>}
              description={skill.description || '暂无说明'}
            />
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
    <SkillFormModal key={editing?.id ?? (creating ? 'new' : 'closed')} open={creating || Boolean(editing)} initial={editing ?? undefined} loading={createMutation.isPending || updateMutation.isPending} onCancel={() => { setCreating(false); setEditing(null); }} onSubmit={onSubmit} />
    <SkillDetailModal skill={detail} onClose={() => setDetail(null)} />
    <DefinitionHistoryModal key={history ? `${history.kind}-${history.id}` : 'closed'} target={history} onClose={() => setHistory(null)} />
  </>;
}

function SkillDetailModal({ skill, onClose }: { skill: SkillDefinition | null; onClose: () => void }) {
  const category = skill ? skillCategory(skill.name) : '';
  return <Modal
    title={skill ? `Skill 详情：${skill.name}` : 'Skill 详情'}
    open={Boolean(skill)}
    onCancel={onClose}
    footer={<Button onClick={onClose}>关闭</Button>}
    width={840}
  >
    {skill && <>
      <Space wrap size={[8, 8]} style={{ marginBottom: 12 }}>
        <Tag color={category === '安全' ? 'red' : category === '平台' ? 'blue' : 'default'}>{category}</Tag>
        <Tag color={skill.is_enabled ? 'green' : 'default'}>{skill.is_enabled ? '启用' : '停用'}</Tag>
        <Tag>v{skill.version}</Tag>
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        {skill.description || '暂无说明'}
      </Typography.Paragraph>
      <Typography.Text strong>Skill 内容</Typography.Text>
      <pre style={{ marginTop: 8, padding: 16, maxHeight: '55vh', overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,.03)', border: '1px solid #f0f0f0', borderRadius: 8 }}>{skill.content || '暂无内容'}</pre>
    </>}
  </Modal>;
}

function DefinitionHistoryModal({ target, onClose }: {
  target: { kind: 'agent' | 'skill'; id: number; name: string } | null;
  onClose: () => void;
}) {
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const versions = useQuery({
    queryKey: ['agent-governance', 'versions', target?.kind, target?.id],
    queryFn: () => target?.kind === 'agent'
      ? agentGovernanceApi.agentVersions(target.id)
      : agentGovernanceApi.skillVersions(target!.id),
    enabled: Boolean(target),
  });
  const selected = versions.data?.find((item) => item.version === selectedVersion) ?? versions.data?.[0];
  return <Modal title={target ? `${target.name} · 版本历史` : '版本历史'} open={Boolean(target)} onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>} width={760}>
    {versions.isPending ? <LoadingState /> : versions.isError ? <ErrorState error={versions.error} onRetry={versions.refetch} /> : versions.data?.length ? <>
      <Table<DefinitionVersion>
        size="small"
        rowKey="version"
        dataSource={versions.data}
        pagination={false}
        onRow={(row) => ({ onClick: () => setSelectedVersion(row.version), style: { cursor: 'pointer', background: selected?.version === row.version ? 'rgba(82, 112, 255, 0.08)' : undefined } })}
        columns={[{ title: '版本', dataIndex: 'version', render: (value: number) => `v${value}` }, { title: '保存时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString() }]}
      />
      <Typography.Text type="secondary">版本快照只读保存，可用于审计和后续回滚能力。</Typography.Text>
      <pre style={{ marginTop: 12, padding: 12, maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'rgba(0,0,0,.03)', borderRadius: 8 }}>{JSON.stringify(selected?.snapshot_json ?? {}, null, 2)}</pre>
    </> : <EmptyState description="暂无历史版本" />}
  </Modal>;
}

function SkillFormModal({ open, initial, loading, onCancel, onSubmit }: {
  open: boolean;
  initial?: SkillDefinition;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: { name: string; description: string; content: string; is_enabled: boolean }) => void;
}) {
  const [form] = Form.useForm();
  return <Modal title={initial ? `编辑 Skill：${initial.name}` : '新增 Skill'} open={open} onCancel={onCancel} onOk={() => form.submit()} confirmLoading={loading} width={760} destroyOnClose>
    <Form form={form} layout="vertical" initialValues={initial ?? { is_enabled: false }} onFinish={onSubmit}>
      <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item>
      <Form.Item name="description" label="说明"><Input maxLength={2000} /></Form.Item>
      <Form.Item name="content" label="Skill 内容（Markdown）" rules={[{ required: true }]}><Input.TextArea rows={12} maxLength={50000} /></Form.Item>
      <Form.Item name="is_enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
    </Form>
  </Modal>;
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
  const tools = useQuery({ queryKey: ['agent-governance', 'tools'], queryFn: agentGovernanceApi.tools });
  const agents = useQuery({ queryKey: ['agent-governance', 'agents'], queryFn: agentGovernanceApi.agents });
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
        <Typography.Text type="secondary">共 {visibleTools.length} 个工具</Typography.Text>
      </div>
    </div>
    {visibleTools.length ? <Row gutter={[12, 12]}>
      {visibleTools.map((tool) => {
        const linkedAgents = agentRows.filter((agent) => agent.tool_keys.includes(tool.key));
        return <Col xs={24} md={12} xl={8} xxl={6} key={tool.key}>
          <Card size="small" style={{ height: '100%' }} styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', padding: 12 } }}>
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
            <Typography.Text type="secondary" ellipsis={{ tooltip: tool.key }} style={{ display: 'block', fontSize: 12 }}>{tool.key}</Typography.Text>
            <div style={{ marginTop: 'auto', paddingTop: 8 }}>
              <Typography.Text type="secondary">Agent 绑定</Typography.Text>
              <div style={{ minHeight: 28, marginTop: 4 }}>
                {linkedAgents.length ? <Space wrap size={[4, 4]}>{linkedAgents.map((agent) => <Tag key={agent.id}>{agent.name}</Tag>)}</Space> : <Typography.Text type="secondary">尚未绑定</Typography.Text>}
              </div>
            </div>
          </Card>
        </Col>;
      })}
    </Row> : <EmptyState description={normalizedSearch ? '没有匹配的工具' : '还没有系统工具'} />}
  </>;
}
