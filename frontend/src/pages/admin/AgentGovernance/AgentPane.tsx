// Agent 配置列表、版本化编辑与受控工作流表单。
import { collectPages } from '@/shared/api/pagination';
import { App, Alert, Button, Card, Col, Drawer, Form, Input, Row, Select, Space, Switch, Tabs, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import type { AgentDefinition, AgentDefinitionInput, AgentTrigger } from '@/features/agent-governance/contracts';
import { modelConfigsApi } from '@/features/model-configuration/api/modelConfigs';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/PageState';
import { DefinitionHistoryModal } from './SkillPane';

const WORKFLOW_LABELS: Record<string, string> = {
  api_test: '接口测试',
  web_ui: 'Web UI 测试',
  security: '安全测试',
  reporting: '测试报告',
};

export function AgentPane() {
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
            <div className="agent-card-actions">
              <Button size="small" style={{ flex: 1 }} onClick={() => setEditing(agent)}>查看详情 / 编辑配置</Button>
              <Button size="small" danger onClick={() => modal.confirm({ title: `删除 Agent「${agent.name}」？`, okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(agent.id) })}>删除</Button>
            </div>
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
  toolOptions: { label: string; value: string; disabled?: boolean }[];
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
      name: '', description: '', workflow_template: defaultWorkflow, instruction: '', model_config_id: null,
      skill_keys: [], tool_keys: [], mcp_tool_keys: [], child_agent_ids: [], is_enabled: false,
      settings_json: defaultAgentSettings(), triggers_json: [],
    }, [initial, defaultWorkflow]);
  useEffect(() => {
    if (!open) return;
    form.resetFields();
    form.setFieldsValue(initialValues);
  }, [form, initialValues, open]);
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
      footer={<div className="editor-drawer-footer">
        <Space wrap>
          {initial && <Button onClick={() => form.setFieldsValue({ instruction: '', settings_json: defaultAgentSettings(), triggers_json: [] })}>恢复默认</Button>}
          {initial && <Button onClick={() => form.setFieldsValue(initialValues)}>放弃未保存修改</Button>}
        </Space>
        <Space wrap><Button onClick={onCancel}>关闭</Button><Button type="primary" loading={loading} onClick={() => form.submit()}>{initial ? '保存为新版本' : '创建 Agent'}</Button></Space>
      </div>}
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

