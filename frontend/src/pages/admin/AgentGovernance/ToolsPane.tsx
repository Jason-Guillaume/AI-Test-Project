// 平台工具白名单、风险信息与授权编辑。
import { App, Alert, Button, Card, Checkbox, Col, Drawer, Form, Input, Row, Space, Switch, Tabs, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import type { AgentDefinition, GovernanceTool, GovernanceToolUpdate } from '@/features/agent-governance/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/PageState';

export function ToolsPane() {
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
                  <Tag color={tool.runtime_details.status === 'active' ? 'green' : 'orange'}>{tool.runtime_details.status_label}</Tag>
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
  const runtime = tool?.runtime_details;
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
    extra={tool ? <Space><Tag color={tool.risk === '高风险' ? 'red' : tool.risk === '执行' ? 'orange' : tool.risk === '写入' ? 'blue' : 'default'}>{tool.risk}</Tag><Tag color={runtime?.status === 'active' ? 'green' : 'orange'}>{runtime?.status_label}</Tag></Space> : null}
    footer={<div className="editor-drawer-footer"><Button onClick={onRestore} loading={restoring}>恢复默认</Button><Space wrap><Button onClick={onClose}>关闭</Button><Button type="primary" loading={loading} onClick={() => form.submit()}>保存配置</Button></Space></div>}
  >
    {tool && <>
      <Alert type={runtime?.status === 'active' ? 'info' : 'warning'} showIcon message={runtime?.status === 'active' ? '平台内置工具' : '工具尚未接入任务执行器'} description={runtime?.status === 'active' ? '可编辑工具说明、运行字段说明和 Agent 授权。字段来源、结构和执行实现由服务端维护；说明覆写只影响治理目录，不会创建新的执行器。保存授权后，相关 Agent 会生成新版本。' : '此项目前仅登记在治理目录，当前任务执行器没有对应调用实现。可以维护目录说明，但绑定 Agent 不会触发工具运行。'} style={{ marginBottom: 16 }} />
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
            {tool.parameters?.length ? <>
              <Typography.Title level={5}>参数定义</Typography.Title>
              <Typography.Paragraph type="secondary">参数名、类型和必填状态来自服务端注册表；可维护管理说明与默认值。</Typography.Paragraph>
              {tool.parameters.map((parameter) => <Card size="small" key={parameter.name} title={<Space><Typography.Text strong>{parameter.name}</Typography.Text><Tag>{parameter.type}</Tag>{parameter.required && <Tag color="red">必填</Tag>}</Space>} style={{ marginBottom: 10 }}>
                <Form.Item name={['parameter_overrides_json', parameter.name, 'description']} label="参数说明" style={{ marginTop: 12 }}>
                  <Input.TextArea rows={2} maxLength={4000} placeholder={parameter.description} />
                </Form.Item>
                <Form.Item name={['parameter_overrides_json', parameter.name, 'default']} label="默认值">
                  <Input maxLength={4000} placeholder={parameter.default ?? '未设置'} />
                </Form.Item>
              </Card>)}
            </> : <Alert type="info" showIcon message="此工具没有可由模型传入的参数 Schema" description="运行时输入由任务和项目上下文自动注入。可在“运行详情”查看每个字段的来源与用途；平台不会接受自定义参数来改变受控执行边界。" />}
          </> },
          { key: 'runtime', label: '运行详情', children: runtime ? <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Row gutter={12}>
              <Col span={12}><Card size="small" title="运行角色"><Typography.Text strong>{runtime.runtime_role}</Typography.Text></Card></Col>
              <Col span={12}><Card size="small" title="执行器映射"><Typography.Text code>{runtime.runtime_name ?? '当前未接入'}</Typography.Text></Card></Col>
            </Row>
            <Card size="small" title="运行时输入 / 上下文" extra={<Tag>字段结构只读 · 说明可编辑</Tag>}>
              {runtime.input_context.length ? <Space direction="vertical" style={{ width: '100%' }} size={8}>
                {runtime.input_context.map((field) => <Card key={field.name} type="inner" size="small" title={<Space><Typography.Text code>{field.name}</Typography.Text><Tag>{field.type ?? 'context'}</Tag>{field.required !== false && <Tag color="red">必需</Tag>}<Tag color="blue">{field.source}</Tag></Space>}>
                  <Form.Item name={['parameter_overrides_json', field.name, 'description']} label="字段说明" style={{ marginBottom: 0 }}>
                    <Input.TextArea rows={2} maxLength={4000} placeholder={field.description} />
                  </Form.Item>
                </Card>)}
              </Space> : <Typography.Text type="secondary">当前没有独立输入字段。</Typography.Text>}
            </Card>
            <Card size="small" title="输出内容"><Typography.Paragraph style={{ marginBottom: 0 }}>{runtime.output}</Typography.Paragraph></Card>
            <Card size="small" title="权限边界与审计">
              <ul style={{ paddingLeft: 20, marginBottom: 12 }}>{runtime.constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}</ul>
              <Typography.Text type="secondary">审计：{runtime.audit}</Typography.Text>
            </Card>
          </Space> : <EmptyState description="没有运行详情" /> },
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
