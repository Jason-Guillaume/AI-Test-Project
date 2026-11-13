// Agent 配置列表、版本化编辑与受控工作流表单。
import { collectPages } from '@/shared/api/pagination';
import { App, Alert, Button, Card, Col, Form, Input, Pagination, Row, Select, Space, Switch, Table, Tabs, Tag, Tree, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import type { AgentDefinition, AgentDefinitionInput, AgentTrigger } from '@/features/agent-governance/contracts';
import { modelConfigsApi } from '@/features/model-configuration/api/modelConfigs';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/PageState';
import { DetailDrawer } from '@/shared/ui/DetailDrawer';
import { DefinitionHistoryModal } from './SkillPane';

import { CaseGenerationModal } from './CaseGenerationModal';
import { agentTestTypes, fixedModel, filterAgentHierarchy, matchesAgent, TEST_TYPE_LABELS } from './agentHierarchy.mjs';

import { EvaluationToolModal } from './EvaluationToolModal';

const WORKFLOW_LABELS: Record<string, string> = {
  case_generation: '用例生成 · 主子协作',
  api_test: '接口测试',
  asr_evaluation: '语音识别评测',
  ai_evaluation: 'AI 质量评测',
  web_ui: 'Web UI 测试',
  security: '安全测试',
  reporting: '测试报告',
};

export function AgentPane() {
  const [moduleFilter, setModuleFilter] = useState<string>();
  const [modelFilter, setModelFilter] = useState<string>();
  const [agentSearch, setAgentSearch] = useState('');
  const [agentPage, setAgentPage] = useState(1);
  const [view, setView] = useState('cards');
  const [generating, setGenerating] = useState<AgentDefinition | null>(null);
  const [evaluating, setEvaluating] = useState<AgentDefinition | null>(null);
  const [editing, setEditing] = useState<AgentDefinition | null>(null);
  const [creating, setCreating] = useState(false);
  const [history, setHistory] = useState<{ kind: 'agent' | 'skill'; id: number; name: string } | null>(null);
  const [selectedAgentIds, setSelectedAgentIds] = useState<number[]>([]);
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['agent-governance'] });
  const agents = useQuery({ queryKey: ['agent-governance', 'agents'], queryFn: agentGovernanceApi.agents });
  const workflows = useQuery({ queryKey: ['agent-governance', 'workflows'], queryFn: agentGovernanceApi.workflows });
  const skills = useQuery({ queryKey: ['agent-governance', 'skills'], queryFn: agentGovernanceApi.skills });
  const tools = useQuery({ queryKey: ['agent-governance', 'tools'], queryFn: agentGovernanceApi.tools });
  const mcpServers = useQuery({ queryKey: ['agent-governance', 'mcp-servers'], queryFn: agentGovernanceApi.mcpServers });
  const models = useQuery({ queryKey: ['agent-governance', 'models'], queryFn: () => collectPages((page) => modelConfigsApi.list({ page, page_size: 100, is_enabled: true })) });
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
    onSuccess: () => { message.success('Agent 配置已移入回收站'); invalidate(); queryClient.invalidateQueries({ queryKey: ['recycle-bin'] }); },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  if (agents.isPending || workflows.isPending || skills.isPending || tools.isPending || models.isPending || mcpServers.isPending) return <LoadingState />;
  const failed = [agents, workflows, skills, tools, models, mcpServers].find((query) => query.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  const allAgents = agents.data ?? [];
  const normalizedSearch = agentSearch.trim().toLocaleLowerCase();
  const searchedAgents = allAgents.filter((agent) => `${agent.name} ${agent.key} ${agent.description} ${agent.workflow_template} ${agent.purpose}`.toLocaleLowerCase().includes(normalizedSearch));
  const groups = filterAgentHierarchy(searchedAgents, moduleFilter, modelFilter);
  const agentRows = searchedAgents.filter((agent) => matchesAgent(agent, moduleFilter, modelFilter));
  const agentPageSize = 12;
  const cardRows = agentRows.slice((agentPage - 1) * agentPageSize, agentPage * agentPageSize);
  const modelLabel = (agent: AgentDefinition, child = false) => {
    const id = fixedModel(agent);
    return id == null ? (child ? '模型：继承主 Agent' : '模型：本次选择 / 全局默认') : `模型：${models.data?.items.find((item) => item.id === id)?.label ?? `#${id}`}`;
  };
  const treeTitle = (agent: AgentDefinition, child = false) => <Space wrap>
    <Typography.Text strong>{agent.name}</Typography.Text>
    <Tag color={child ? 'cyan' : agent.child_agent_ids.length ? 'purple' : 'default'}>{child ? '子 Agent' : agent.child_agent_ids.length ? '主 Agent' : '独立 Agent'}</Tag>
    <Tag>{agentTestTypes(agent).map((type) => TEST_TYPE_LABELS[type] ?? TEST_TYPE_LABELS.general).join("、")}</Tag><Tag>{modelLabel(agent, child)}</Tag>
    <Tag>{agent.is_enabled ? '启用' : '停用'}</Tag>
    <Button size="small" onClick={() => setEditing(agent)}>配置</Button>
    {agent.tool_keys.some((key) => key.startsWith('asr.') || key === 'ai.check_output') && <Button size="small" disabled={!agent.is_enabled} onClick={() => setEvaluating(agent)}>运行评测工具</Button>}
    {agent.workflow_template === 'case_generation' && agent.child_agent_ids.length > 0 && <Button size="small" type="primary" disabled={!agent.is_enabled} onClick={() => setGenerating(agent)}>生成用例</Button>}
  </Space>;
  const treeData = groups.map(({ agent, children, matches }) => ({ key: `root-${agent.id}`, title: <>{treeTitle(agent)}{!matches && <Tag>包含匹配子 Agent</Tag>}</>, children: children.map((child) => ({ key: `${agent.id}-${child.id}`, title: treeTitle(child, true) })) }));

  const submit = (body: AgentDefinitionInput) => {
    const normalized = { ...body, skill_keys: body.skill_keys ?? [], tool_keys: body.tool_keys ?? [], child_agent_ids: body.child_agent_ids ?? [], instruction: body.instruction ?? '' };
    if (editing) updateMutation.mutate({ id: editing.id, body: normalized });
    else createMutation.mutate(normalized);
  };

  const deleteSelected = () => {
    if (!selectedAgentIds.length) return;
    modal.confirm({
      title: `将 ${selectedAgentIds.length} 个 Agent 移入回收站？`,
      content: '平台内置 Agent、仍被其他 Agent 或执行中任务引用的项会逐条拒绝；成功项保留原始 ID 和修订历史，可在回收站恢复。',
      okText: '移入回收站', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const receipt = await dataLifecycleApi.deleteMany('agent_definition', null, selectedAgentIds);
          setSelectedAgentIds([]);
          invalidate();
          queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
          if (receipt.failed) {
            modal.info({
              title: `成功 ${receipt.succeeded} 个，失败 ${receipt.failed} 个`,
              content: <Space direction="vertical" style={{ width: '100%' }}>{receipt.items.filter((item) => !item.succeeded).map((item) => <Alert key={item.id} type="error" showIcon message={`Agent #${item.id}`} description={item.error ?? '删除失败'} />)}</Space>,
            });
          } else message.success(`已将 ${receipt.succeeded} 个 Agent 移入回收站`);
        } catch (error) { message.error(getErrorMessage(error, '批量删除失败')); }
      },
    });
  };

  const agentTableColumns = [
    { title: 'Agent', dataIndex: 'name', render: (_: string, row: AgentDefinition) => <Button type="link" onClick={() => setEditing(row)}>{row.name}</Button> },
    { title: '工作流', dataIndex: 'workflow_template', render: (value: string) => WORKFLOW_LABELS[value] ?? value },
    { title: '用途', dataIndex: 'purpose' },
    { title: '状态', dataIndex: 'is_enabled', render: (enabled: boolean) => <Tag color={enabled ? 'green' : 'default'}>{enabled ? '启用' : '停用'}</Tag> },
    { title: '模型', key: 'model', render: (_: unknown, row: AgentDefinition) => modelLabel(row) },
    { title: '操作', key: 'actions', render: (_: unknown, row: AgentDefinition) => <Space><Button size="small" onClick={() => setEditing(row)}>配置</Button><Button size="small" onClick={() => setHistory({ kind: 'agent', id: row.id, name: row.name })}>变更记录</Button><Button size="small" danger onClick={() => modal.confirm({ title: `将 Agent「${row.name}」移入回收站？`, okText: '移入回收站', okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(row.id) })}>删除</Button></Space> },
  ];

  return (
    <>
      <Space wrap className="resource-list-toolbar">
        <Input.Search allowClear value={agentSearch} onChange={(event) => { setAgentSearch(event.target.value); setAgentPage(1); }} placeholder="搜索 Agent 名称、说明或工作流" aria-label="搜索 Agent" />
        <Select allowClear placeholder="测试类型" aria-label="测试类型" value={moduleFilter} onChange={(value) => { setModuleFilter(value); setAgentPage(1); }} style={{ width: 180 }} options={Object.entries(TEST_TYPE_LABELS).map(([value, label]) => ({ value, label }))} />
        <Select allowClear showSearch optionFilterProp="label" placeholder="按绑定模型筛选" aria-label="按绑定模型筛选" value={modelFilter} onChange={(value) => { setModelFilter(value); setAgentPage(1); }} style={{ width: 260 }} options={[{ value: 'inherit', label: '继承 / 本次选择 / 全局默认' }, ...(models.data?.items ?? []).map((item) => ({ value: String(item.id), label: `${item.label} (${item.model_name})` }))]} />
        <Select value={view} onChange={setView} options={[{ value: 'tree', label: '主子关系' }, { value: 'cards', label: '全部卡片' }, { value: 'table', label: '表格与批量删除' }]} />
        <Button danger disabled={!selectedAgentIds.length} onClick={deleteSelected}>批量删除（{selectedAgentIds.length}）</Button>
        <Button onClick={() => navigate('/admin/recycle-bin')}>回收站</Button>
        <Button type="primary" onClick={() => setCreating(true)}>新增 Agent</Button>
      </Space>
      {view === 'tree' && (treeData.length ? <Card><Tree key={`${moduleFilter}-${modelFilter}-${allAgents.length}`} defaultExpandAll selectable={false} blockNode treeData={treeData} /></Card> : <EmptyState description="没有匹配的 Agent" />)}
      {view === 'table' && <Table<AgentDefinition>
        rowKey="id" size="small" scroll={{ x: 'max-content' }} columns={agentTableColumns}
        dataSource={agentRows} pagination={false}
        rowSelection={{ selectedRowKeys: selectedAgentIds, onChange: (keys) => setSelectedAgentIds(keys.map(Number)) }}
        locale={{ emptyText: '没有匹配的 Agent' }}
      />}
      {view === 'cards' && (agentRows.length ? <>
        <Row gutter={[12, 12]}>
        {cardRows.map((agent) => <Col xs={24} md={12} xl={8} xxl={6} key={agent.id}>
          <Card
            size="small"
            hoverable
            role="button"
            tabIndex={0}
            aria-label={`查看 Agent ${agent.name}`}
            onClick={(event) => {
              if ((event.target as HTMLElement).closest('button')) return;
              setEditing(agent);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setEditing(agent); }
            }}
            style={{ height: '100%' }}
            styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', padding: 12 } }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <Typography.Text strong ellipsis={{ tooltip: agent.name }} style={{ display: 'block' }}>{agent.name}</Typography.Text>
                <Space size={4} style={{ marginTop: 4 }}>
                  <Tag color="blue">{WORKFLOW_LABELS[agent.workflow_template] ?? agent.workflow_template}</Tag>

                </Space>
              </div>
              <Tag color={agent.is_enabled ? 'green' : 'default'}>{agent.is_enabled ? '启用' : '停用'}</Tag>
            </div>
            {agent.tool_keys.some((key) => key.startsWith('asr.') || key === 'ai.check_output') && <Button type="link" disabled={!agent.is_enabled} onClick={() => setEvaluating(agent)}>运行评测工具</Button>}
            <Typography.Paragraph type="secondary" ellipsis={{ rows: 2, tooltip: agent.description || '暂无说明' }} style={{ minHeight: 40, marginTop: 6, marginBottom: 8 }}>
              {agent.description || '暂无说明'}
            </Typography.Paragraph>
            <Tag>{modelLabel(agent, allAgents.some((parent) => parent.child_agent_ids.includes(agent.id)))}</Tag>
            <Tag>{allAgents.some((parent) => parent.child_agent_ids.includes(agent.id)) ? `子 Agent · 主 Agent：${allAgents.filter((parent) => parent.child_agent_ids.includes(agent.id)).map((parent) => parent.name).join('、')}` : agent.child_agent_ids.length ? '主 Agent' : '独立 Agent'}</Tag>
            {agent.workflow_template === 'case_generation' && agent.child_agent_ids.length > 0 && <Button onClick={() => setGenerating(agent)} disabled={!agent.is_enabled}>生成用例</Button>}
            <Space wrap size={[4, 4]} style={{ marginTop: 'auto', marginBottom: 8 }}>
              <Tag>子 Agent {agent.child_agent_ids.length}</Tag>
              <Tag>Skill {agent.skill_keys.length}</Tag>
              <Tag>系统工具 {agent.tool_keys.filter((key) => !key.startsWith('mcp:')).length}</Tag>
              <Tag>MCP 工具 {agent.tool_keys.filter((key) => key.startsWith('mcp:')).length}</Tag>
            </Space>
            <div className="agent-card-actions">
              <Button size="small" style={{ flex: 1 }} onClick={() => setEditing(agent)}>查看详情 / 编辑配置</Button>
              <Button size="small" onClick={() => setHistory({ kind: 'agent', id: agent.id, name: agent.name })}>变更记录</Button>
              <Button size="small" danger onClick={() => modal.confirm({ title: `将 Agent「${agent.name}」移入回收站？`, okText: '移入回收站', okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(agent.id) })}>删除</Button>
            </div>
          </Card>
        </Col>)}
        </Row>
        {agentRows.length > agentPageSize && <Pagination current={agentPage} pageSize={agentPageSize} total={agentRows.length} showSizeChanger={false} onChange={setAgentPage} style={{ marginTop: 16, textAlign: 'right' }} />}
      </> : <EmptyState description="没有匹配的 Agent" />)}
      <CaseGenerationModal key={generating?.id ?? 'closed'} agent={generating} agents={allAgents} models={(models.data?.items ?? []).map((item) => ({ value: item.id, label: `${item.label} (${item.model_name})` }))} onClose={() => setGenerating(null)} />
      <EvaluationToolModal agent={evaluating} onClose={() => setEvaluating(null)} />
      <AgentFormModal
        key={editing ? `${editing.id}-${editing.version}` : (creating ? 'new' : 'closed')}
        open={creating || Boolean(editing)}
        initial={editing ?? undefined}
        workflows={workflows.data ?? []}
        skillOptions={(skills.data ?? []).map((item) => ({ label: `${item.name}${item.is_enabled ? '' : ' · 已停用'}`, value: item.key, disabled: !item.is_enabled }))}
        toolOptions={[
          ...(tools.data ?? []).map((item) => ({
            label: `${item.name} · ${item.risk}${item.runtime_details.status === 'catalog_only' ? ' · 未接入' : ''}${item.is_enabled ? '' : ' · 已停用'}`,
            value: item.key,
            disabled: !item.is_enabled || item.runtime_details.status !== 'active',
          })),
          ...(mcpServers.data ?? []).flatMap((server) => server.discovered_tools_json
            .filter((tool) => server.approved_tools_json.includes(tool.name))
            .map((tool) => ({
              label: `${server.name} / ${tool.name} · ${tool.annotations?.readOnlyHint ? '只读已审批' : '仅审批，不自动执行'}`,
              value: `mcp:${server.id}:${tool.name}`,
              disabled: !server.is_enabled || server.connection_status !== 'connected' || tool.annotations?.readOnlyHint !== true,
            }))),
        ]}
        childAgentOptions={(agents.data ?? []).filter((item) => item.id !== editing?.id && item.child_agent_ids.length === 0 && (item.tool_keys.length === 0 || (item.workflow_template === 'case_generation' && item.tool_keys.length === 1 && /^case_generation\.generate_(api|web|security|asr|ai)$/.test(item.tool_keys[0])))).map((item) => ({
          label: `${item.name} · ${item.tool_keys.length ? '用例生成节点' : '分析节点'}${item.is_enabled ? '' : ' · 已停用'}`,
          value: item.id,
          generationOnly: item.tool_keys.length > 0,
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
  toolOptions: { label: string; value: string; disabled?: boolean }[];
  childAgentOptions: { label: string; value: number; disabled?: boolean; generationOnly?: boolean }[];
  allowChildNodes: boolean;
  modelOptions: { label: string; value: number }[];
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: AgentDefinitionInput) => void;
}) {
  type AgentFormState = AgentDefinitionInput & { mcp_tool_keys: string[] };
  const [form] = Form.useForm<AgentFormState>();
  const [dirty, setDirty] = useState(false);
  const { modal } = App.useApp();
  const selectedWorkflow = Form.useWatch('workflow_template', form);
  const instruction = Form.useWatch('instruction', form) ?? '';
  const runtimeVariables = Form.useWatch(['settings_json', 'runtime_variables'], form) ?? [];
  const preview = runtimeVariables.reduce((text: string, variable: { name?: string; value?: string }) => {
    const name = variable.name?.trim();
    if (!name) return text;
    const value = name === 'Now' ? new Date().toLocaleString() : name === 'DataDir' ? '（任务运行时目录）' : variable.value ?? '';
    return text.split(`{{.${name}}}`).join(value);
  }, instruction);
  const defaultWorkflow = workflows[0]?.key ?? 'api_test';
  const initialValues = useMemo<AgentFormState>(() => initial
    ? {
      ...initial,
      tool_keys: initial.tool_keys.filter((key) => !key.startsWith('mcp:')),
      mcp_tool_keys: initial.tool_keys.filter((key) => key.startsWith('mcp:')),
      settings_json: initial.settings_json ?? defaultAgentSettings(),
      triggers_json: initial.triggers_json ?? [],
    }
    : {
      name: '', description: '', workflow_template: defaultWorkflow, test_types: ['general'], purpose: 'test_execution', instruction: '', model_config_id: null,
      skill_keys: [], tool_keys: [], mcp_tool_keys: [], child_agent_ids: [], is_enabled: false,
      settings_json: defaultAgentSettings(), triggers_json: [],
    }, [initial, defaultWorkflow]);
  useEffect(() => {
    if (!open) return;
    form.resetFields();
    form.setFieldsValue(initialValues);
    setDirty(false);
  }, [form, initialValues, open]);
  const requestClose = () => {
    if (!dirty) { onCancel(); return; }
    modal.confirm({
      title: '放弃未保存修改？',
      content: '关闭会丢弃当前 Agent 表单中的修改。',
      okText: '放弃修改', cancelText: '继续编辑', okButtonProps: { danger: true },
      onOk: onCancel,
    });
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
    <DetailDrawer
      title={initial ? `Agent 详情与配置：${initial.name}` : '新增 Agent'}
      open={open}
      onClose={requestClose}
      width={720}
      destroyOnClose
      dirty={false}
      footer={<div className="editor-drawer-footer">
        <Space wrap>
          {initial && <Button onClick={() => { form.setFieldsValue({ instruction: '', settings_json: defaultAgentSettings(), triggers_json: [] }); setDirty(true); }}>恢复默认</Button>}
          {initial && <Button onClick={() => { form.setFieldsValue(initialValues); setDirty(false); }}>放弃未保存修改</Button>}
        </Space>
        <Space wrap><Button onClick={requestClose}>关闭</Button><Button type="primary" loading={loading} onClick={() => form.submit()}>{initial ? '保存为新版本' : '创建 Agent'}</Button></Space>
      </div>}
    >
      <Form form={form} layout="vertical" initialValues={initialValues} onFinish={submit} onValuesChange={() => setDirty(true)}>
        <Tabs items={[
          { key: 'config', label: '配置与提示词', children: <>
            <Row gutter={16}>
              <Col span={12}><Form.Item name="name" label="Agent 名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item></Col>
              <Col span={12}><Form.Item name="workflow_template" label="工作流模板" rules={[{ required: true }]}><Select options={workflows.map((item) => ({ value: item.key, label: item.label }))} /></Form.Item></Col>
            </Row>
            <Row gutter={16}><Col span={12}><Form.Item name="test_types" label="测试类型" rules={[{ required: true }]}><Select mode="multiple" options={Object.entries(TEST_TYPE_LABELS).map(([value, label]) => ({ value, label }))} /></Form.Item></Col><Col span={12}><Form.Item name="purpose" label="用途" rules={[{ required: true }]}><Select options={[{value:'case_generation',label:'用例生成'},{value:'test_execution',label:'测试执行'},{value:'quality_evaluation',label:'质量评测'},{value:'test_report',label:'测试报告'}]} /></Form.Item></Col></Row>
            <Form.Item name="description" label="说明"><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
            <Row gutter={16}>
              <Col span={12}><Form.Item name={['settings_json', 'max_loop_count']} label="最大循环次数（0 = 不限）"><Input type="number" min={0} max={1000} /></Form.Item></Col>
              <Col span={12}><Form.Item name={['settings_json', 'timeout_seconds']} label="运行时长（秒，0 = 不限）"><Input type="number" min={0} max={86400} /></Form.Item></Col>
            </Row>
            <Form.Item name={['settings_json', 'model_binding']} label="默认模型绑定策略"><Select options={[{ value: 'task_or_global', label: '跟随任务选择 / 全局默认' }, { value: 'agent', label: '固定绑定 Agent 模型' }]} /></Form.Item>
            <Alert type="info" showIcon style={{ marginBottom: 16 }} message="模型选择优先级" description="固定绑定到本 Agent 的模型优先；未固定时使用任务会话选定模型，再回退到平台全局默认。执行记录会保留实际使用的模型快照。" />
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
            <Form.Item name="child_agent_ids" label="子 Agent 节点"><Select mode="multiple" maxCount={8} disabled={!allowChildNodes} options={childAgentOptions.filter((item) => selectedWorkflow === 'case_generation' ? item.generationOnly : !item.generationOnly)} placeholder="按顺序加入最多 8 个已启用叶子 Agent" /></Form.Item>
            <Typography.Paragraph type="secondary">{allowChildNodes ? '普通子 Agent 承担分析；用例生成子 Agent 需绑定一个对应模块生成工具。子 Agent 可固定模型，也可继承主 Agent 模型。' : '该配置已作为其他 Agent 的子节点使用，因此只能保持叶子节点。'}</Typography.Paragraph>
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
    </DetailDrawer>
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

