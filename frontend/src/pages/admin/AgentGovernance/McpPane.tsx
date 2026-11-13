// MCP 服务发现、脱敏配置与工具授权。
import { App, Alert, Button, Card, Checkbox, Col, Form, Input, Row, Select, Space, Switch, Tabs, Tag, Typography } from 'antd';
import { ApiOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import type { MCPServer } from '@/features/agent-governance/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/PageState';
import { DetailDrawer } from '@/shared/ui/DetailDrawer';

export function McpPane() {
  const [searchText, setSearchText] = useState('');
  const [editing, setEditing] = useState<MCPServer | null>(null);
  const [creating, setCreating] = useState(false);
  const [inspecting, setInspecting] = useState<MCPServer | null>(null);
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const servers = useQuery({ queryKey: ['agent-governance', 'mcp'], queryFn: agentGovernanceApi.mcpServers });
  const agents = useQuery({ queryKey: ['agent-governance', 'agents'], queryFn: agentGovernanceApi.agents });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['agent-governance', 'mcp'] });
    queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
  };
  const createMutation = useMutation({ mutationFn: agentGovernanceApi.createMcpServer, onSuccess: () => { message.success('MCP 服务已登记'); setCreating(false); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const updateMutation = useMutation({ mutationFn: ({ id, body }: { id: number; body: { name?: string; endpoint?: string; auth_type?: 'none' | 'bearer'; auth_token?: string; is_enabled?: boolean } }) => agentGovernanceApi.updateMcpServer(id, body), onSuccess: () => { message.success('MCP 配置已更新'); setEditing(null); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const discoverMutation = useMutation({ mutationFn: agentGovernanceApi.discoverMcpTools, onSuccess: (server) => { message.success(`已发现 ${server.discovered_tools_json.length} 个工具`); setInspecting(server); invalidate(); }, onError: (e) => { message.error(getErrorMessage(e)); invalidate(); } });
  const approveMutation = useMutation({ mutationFn: ({ id, names }: { id: number; names: string[] }) => agentGovernanceApi.approveMcpTools(id, names), onSuccess: (server) => { message.success('工具审批清单已保存'); setInspecting(server); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const deleteMutation = useMutation({ mutationFn: agentGovernanceApi.deleteMcpServer, onSuccess: () => { message.success('MCP 服务已移入回收站'); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const deleteMany = () => modal.confirm({
    title: `将 ${selectedIds.length} 个 MCP 服务移入回收站？`,
    content: '被 Agent、Skill 或运行任务引用的服务会逐项拒绝；凭据与配置保留且不会级联删除历史记录。',
    okText: '移入回收站', cancelText: '取消', okButtonProps: { danger: true },
    onOk: async () => {
      try {
        const receipt = await dataLifecycleApi.deleteMany('mcp_server', null, selectedIds);
        setSelectedIds([]);
        invalidate();
        if (receipt.failed) modal.info({
          title: `成功 ${receipt.succeeded} 个，失败 ${receipt.failed} 个`,
          content: <Space direction="vertical" style={{ width: '100%' }}>{receipt.items.filter((item) => !item.succeeded).map((item) => <Alert key={item.id} type="error" showIcon message={`MCP 服务 #${item.id}`} description={item.error ?? '删除失败'} />)}</Space>,
        });
        else message.success(`已将 ${receipt.succeeded} 个 MCP 服务移入回收站`);
      } catch (error) { message.error(getErrorMessage(error, '批量删除失败')); }
    },
  });
  if (servers.isPending || agents.isPending) return <LoadingState />;
  const failed = [servers, agents].find((query) => query.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => void failed.refetch()} />;
  const serverRows = servers.data ?? [];
  const agentRows = agents.data ?? [];
  const normalizedSearch = searchText.trim().toLocaleLowerCase();
  const visibleServers = serverRows.filter((server) => `${server.name} ${server.endpoint} ${server.connection_status} ${server.auth_type}`.toLocaleLowerCase().includes(normalizedSearch));
  const onSubmit = (body: { name: string; endpoint: string; auth_type: 'none' | 'bearer'; auth_token?: string; is_enabled: boolean }) => editing ? updateMutation.mutate({ id: editing.id, body }) : createMutation.mutate(body);
  return <>
    <Alert type="warning" showIcon message="MCP 调用限定为管理员审批的只读工具" description="配置 Agent 时可关联已审批工具，任务 Planner 可能在制定方案时调用只读工具并写入任务审计回执。写入、高风险或未标注 readOnlyHint 的工具不会自动执行；Bearer 凭据加密保存且接口不回传明文。" style={{ marginBottom: 12 }} />
    <div className="resource-list-toolbar">
      <Input.Search allowClear value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="搜索服务名称、地址或连接状态" aria-label="搜索 MCP 服务" />
      <Typography.Text type="secondary">显示 {visibleServers.length} / {serverRows.length} 个服务</Typography.Text>
      <Space wrap style={{ marginLeft: 'auto' }}>
      <Button danger disabled={!selectedIds.length} onClick={deleteMany}>批量删除（{selectedIds.length}）</Button>
      <Button onClick={() => navigate('/admin/recycle-bin')}>回收站</Button>
      <Button type="primary" icon={<ApiOutlined />} onClick={() => setCreating(true)}>新增 MCP 服务</Button>
      </Space>
    </div>
    {visibleServers.length ? <Row gutter={[12, 12]}>
      {visibleServers.map((server) => {
        const linkedAgents = agentRows.filter((agent) => agent.tool_keys.some((key) => key.startsWith(`mcp:${server.id}:`)));
        const connectionLabel = server.connection_status === 'connected' ? '已连接' : server.connection_status === 'error' ? '连接失败' : '未检查';
        const connectionColor = server.connection_status === 'connected' ? 'green' : server.connection_status === 'error' ? 'red' : 'default';
        return <Col xs={24} md={12} xl={8} xxl={6} key={server.id}>
          <Card size="small" style={{ height: '100%' }} styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', padding: 12 } }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <Checkbox
                  checked={selectedIds.includes(server.id)}
                  onChange={(event) => setSelectedIds((current) => event.target.checked
                    ? current.length < 100 ? [...current, server.id] : (message.warning('一次最多选择 100 个 MCP 服务'), current)
                    : current.filter((id) => id !== server.id))}
                  aria-label={`选择 MCP 服务 ${server.name}`}
                />
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
                <Button size="small" danger onClick={() => modal.confirm({ title: `将 MCP 服务「${server.name}」移入回收站？`, content: '若 Agent、Skill 或运行任务仍引用该服务，删除会被拒绝。', okText: '移入回收站', cancelText: '取消', okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(server.id) })}>删除</Button>
              </Space>
            </div>
          </Card>
        </Col>;
      })}
    </Row> : <EmptyState description={normalizedSearch ? '没有匹配的 MCP 服务' : '还没有登记 MCP 服务'} />}
    <McpFormModal key={editing?.id ?? (creating ? 'new' : 'closed')} open={creating || Boolean(editing)} initial={editing ?? undefined} loading={createMutation.isPending || updateMutation.isPending} onCancel={() => { setCreating(false); setEditing(null); }} onSubmit={onSubmit} />
    <McpToolsModal
      key={inspecting ? `${inspecting.id}-${inspecting.last_checked_at ?? 'initial'}` : 'closed'}
      server={inspecting}
      agents={agentRows}
      loading={approveMutation.isPending}
      onCancel={() => setInspecting(null)}
      onSave={(names) => inspecting && approveMutation.mutate({ id: inspecting.id, names })}
    />
  </>;
}

function McpToolsModal({ server, agents, loading, onCancel, onSave }: {
  server: MCPServer | null;
  agents: Array<{ id: number; name: string; tool_keys: string[] }>;
  loading: boolean;
  onCancel: () => void;
  onSave: (names: string[]) => void;
}) {
  const [selected, setSelected] = useState(server?.approved_tools_json ?? []);
  const [dirty, setDirty] = useState(false);
  const { modal } = App.useApp();
  useEffect(() => {
    setSelected(server?.approved_tools_json ?? []);
    setDirty(false);
  }, [server]);
  const linkedAgents = server ? agents.filter((agent) => agent.tool_keys.some((key) => key.startsWith(`mcp:${server.id}:`))) : [];
  const requestClose = () => {
    if (!dirty) { onCancel(); return; }
    modal.confirm({
      title: '放弃未保存审批？',
      content: '关闭会丢弃本次修改的 MCP 工具审批清单。',
      okText: '放弃修改', cancelText: '继续编辑', okButtonProps: { danger: true }, onOk: onCancel,
    });
  };
  return <DetailDrawer title={server ? `${server.name} · MCP 详情` : 'MCP 详情'} open={Boolean(server)} onClose={requestClose} width={820} dirty={false}
    extra={server ? <Space><Tag color={server.connection_status === 'connected' ? 'green' : server.connection_status === 'error' ? 'red' : 'default'}>{server.connection_status === 'connected' ? '已连接' : server.connection_status === 'error' ? '连接失败' : '未检查'}</Tag><Tag>{server.is_enabled ? '启用' : '停用'}</Tag></Space> : null}
    footer={<div className="editor-drawer-footer"><Typography.Text type="secondary">审批通过 ≠ 已授权给 Agent ≠ 可执行</Typography.Text><Space wrap><Button onClick={requestClose}>关闭</Button><Button type="primary" loading={loading} disabled={!server?.is_enabled || server?.connection_status !== 'connected'} onClick={() => onSave(selected)}>保存审批清单</Button></Space></div>}>
    {server && <>
      <Tabs items={[
        { key: 'tools', label: `发现与审批（${server.discovered_tools_json.length}）`, children: <>
          <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="审批仅将工具加入管理员白名单" description="被 Agent 选用还需要连接状态、只读标记和 Agent 侧绑定同时满足。写入或高风险工具即使审批，也不会自动调用。" />
          {server.discovered_tools_json.length ? <Checkbox.Group value={selected} onChange={(values) => { setSelected(values as string[]); setDirty(true); }} style={{ display: 'block' }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              {server.discovered_tools_json.map((tool) => <Card key={tool.name} size="small" title={<Space wrap><Checkbox value={tool.name}><Typography.Text strong>{tool.name}</Typography.Text></Checkbox><Tag color={tool.annotations?.readOnlyHint ? 'green' : 'orange'}>{tool.annotations?.readOnlyHint ? '标记为只读' : '未声明只读'}</Tag>{tool.annotations?.destructiveHint && <Tag color="red">可能产生破坏性影响</Tag>}{tool.annotations?.idempotentHint && <Tag>幂等</Tag>}{tool.annotations?.openWorldHint && <Tag>开放世界</Tag>}</Space>}>
                <Typography.Paragraph type="secondary">{tool.description || '无描述'}</Typography.Paragraph>
                <Typography.Text strong>输入 Schema</Typography.Text>
                <pre className="mcp-schema-preview">{JSON.stringify(tool.inputSchema ?? {}, null, 2)}</pre>
              </Card>)}
            </Space>
          </Checkbox.Group> : <EmptyState description="尚未发现工具，请先执行连接并发现" />}
        </> },
        { key: 'agents', label: `Agent 关联（${linkedAgents.length}）`, children: linkedAgents.length
          ? <Space direction="vertical" style={{ width: '100%' }}>{linkedAgents.map((agent) => <Card size="small" key={agent.id} title={agent.name}>
            <Space wrap>{agent.tool_keys.filter((key) => key.startsWith(`mcp:${server.id}:`)).map((key) => <Tag key={key}>{key.slice(`mcp:${server.id}:`.length)}</Tag>)}</Space>
          </Card>)}</Space>
          : <EmptyState description="尚无 Agent 绑定此服务的工具" /> },
      ]} />
    </>}
  </DetailDrawer>;
}

function McpFormModal({ open, initial, loading, onCancel, onSubmit }: {
  open: boolean;
  initial?: MCPServer;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: { name: string; endpoint: string; auth_type: 'none' | 'bearer'; auth_token?: string; is_enabled: boolean }) => void;
}) {
  const [form] = Form.useForm();
  const [dirty, setDirty] = useState(false);
  const { modal } = App.useApp();
  const requestClose = () => {
    if (!dirty) { onCancel(); return; }
    modal.confirm({ title: '放弃未保存配置？', content: '关闭会丢弃 MCP 服务连接配置修改。', okText: '放弃修改', cancelText: '继续编辑', okButtonProps: { danger: true }, onOk: onCancel });
  };
  return <DetailDrawer title={initial ? `编辑 MCP 服务：${initial.name}` : '新增 MCP 服务'} open={open} onClose={requestClose} width={720} dirty={false}
    footer={<div className="editor-drawer-footer"><Typography.Text type="secondary">Bearer Token 只写入，服务端不会回传明文。</Typography.Text><Space wrap><Button onClick={requestClose}>取消</Button><Button type="primary" loading={loading} onClick={() => form.submit()}>{initial ? '保存配置' : '登记服务'}</Button></Space></div>}>
    <Form form={form} layout="vertical" initialValues={initial ? { name: initial.name, endpoint: initial.endpoint, auth_type: initial.auth_type, is_enabled: initial.is_enabled } : { auth_type: 'none', is_enabled: false }} onFinish={onSubmit} onValuesChange={() => setDirty(true)}>
      <Tabs items={[
        { key: 'connection', label: '连接配置', children: <>
          <Form.Item name="name" label="服务名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item>
          <Form.Item name="endpoint" label="MCP Streamable HTTP 地址" rules={[{ required: true, type: 'url' }]} extra="仅支持当前服务端实现的 Streamable HTTP 连接。"><Input placeholder="https://mcp.example.com/mcp" /></Form.Item>
          <Form.Item name="auth_type" label="认证方式"><Select options={[{ value: 'none', label: '无认证' }, { value: 'bearer', label: 'Bearer Token' }]} /></Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, next) => prev.auth_type !== next.auth_type}>{({ getFieldValue }) => getFieldValue('auth_type') === 'bearer' ? <Form.Item name="auth_token" label="Bearer Token" rules={initial ? [] : [{ required: true }]} extra={initial?.has_auth ? '留空保留已保存凭据；重新填写会覆盖。' : undefined}><Input.Password autoComplete="new-password" placeholder={initial?.has_auth ? '已配置，留空表示保留' : '粘贴访问令牌'} /></Form.Item> : null}</Form.Item>
          <Form.Item name="is_enabled" label="启用登记" valuePropName="checked"><Switch /></Form.Item>
        </> },
        { key: 'status', label: '连接状态', children: <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert type={initial?.connection_status === 'error' ? 'error' : initial?.connection_status === 'connected' ? 'success' : 'info'} showIcon message={initial ? (initial.connection_status === 'connected' ? '最近连接成功' : initial.connection_status === 'error' ? '最近连接失败' : '尚未执行连接检查') : '保存服务后可执行连接与工具发现'} description={initial?.last_error || (initial?.last_checked_at ? `最近检查：${new Date(initial.last_checked_at).toLocaleString()}` : '新增服务尚未连接。')} />
          <Typography.Text type="secondary">已发现 {initial?.discovered_tools_json.length ?? 0} 个工具，已审批 {initial?.approved_tools_json.length ?? 0} 个。发现和审批清单可在服务详情页管理。</Typography.Text>
        </Space> },
      ]} />
    </Form>
  </DetailDrawer>;
}

