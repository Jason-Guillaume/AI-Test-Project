// MCP 服务发现、脱敏配置与工具授权。
import { App, Alert, Button, Card, Checkbox, Col, Form, Input, Modal, Row, Select, Space, Switch, Tag, Typography } from 'antd';
import { ApiOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import type { MCPServer } from '@/features/agent-governance/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/PageState';

export function McpPane() {
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

