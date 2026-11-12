// Skill 列表、文件编辑、版本历史与恢复。
import { App, Alert, Button, Card, Checkbox, Col, Drawer, Form, Input, List, Modal, Row, Pagination, Select, Space, Switch, Table, Tabs, Tag, Typography, Upload } from 'antd';
import { PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import type { AgentDefinition, DefinitionVersion, SkillDefinition, SkillInput } from '@/features/agent-governance/contracts';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/PageState';

function skillCategory(name: string) {
  return name.includes(' · ') ? name.split(' · ')[0] : '通用';
}

export function SkillPane() {
  const [editing, setEditing] = useState<SkillDefinition | null>(null);
  const [creating, setCreating] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [categoryFilter, setCategoryFilter] = useState('全部');
  const [selectedSkillIds, setSelectedSkillIds] = useState<number[]>([]);
  const [history, setHistory] = useState<{ kind: 'agent' | 'skill'; id: number; name: string } | null>(null);
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const skills = useQuery({ queryKey: ['agent-governance', 'skills'], queryFn: agentGovernanceApi.skills });
  const agents = useQuery({ queryKey: ['agent-governance', 'agents'], queryFn: agentGovernanceApi.agents });
  const mcpServers = useQuery({ queryKey: ['agent-governance', 'mcp-servers'], queryFn: agentGovernanceApi.mcpServers });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['agent-governance'] });
  const createMutation = useMutation({ mutationFn: agentGovernanceApi.createSkill, onSuccess: () => { message.success('Skill 已创建'); setCreating(false); setCurrentPage(1); setCategoryFilter('全部'); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const updateMutation = useMutation({ mutationFn: ({ id, body }: { id: number; body: Partial<SkillDefinition> }) => agentGovernanceApi.updateSkill(id, body), onSuccess: () => { message.success('Skill 已更新，版本已递增'); setEditing(null); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const deleteMutation = useMutation({ mutationFn: agentGovernanceApi.deleteSkill, onSuccess: () => { message.success('Skill 已移入回收站'); setCurrentPage(1); invalidate(); queryClient.invalidateQueries({ queryKey: ['recycle-bin'] }); }, onError: (e) => message.error(getErrorMessage(e)) });
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
  const selectedOnPage = pageSkills.filter((skill) => selectedSkillIds.includes(skill.id)).length;
  const toggleSkillSelection = (skillId: number, checked: boolean) => {
    setSelectedSkillIds((current) => checked
      ? (current.includes(skillId) || current.length >= 100 ? current : [...current, skillId])
      : current.filter((id) => id !== skillId));
  };
  const toggleCurrentPage = (checked: boolean) => {
    const pageIds = pageSkills.map((skill) => skill.id);
    setSelectedSkillIds((current) => {
      if (!checked) return current.filter((id) => !pageIds.includes(id));
      const next = [...new Set([...current, ...pageIds])];
      if (next.length > 100) {
        message.warning('一次最多选择 100 个 Skill');
        return current;
      }
      return next;
    });
  };
  const deleteSelectedSkills = () => {
    if (!selectedSkillIds.length) return;
    modal.confirm({
      title: `将 ${selectedSkillIds.length} 个 Skill 移入回收站？`,
      content: '平台内置 Skill、仍被 Agent 配置或执行中任务引用的项会逐条拒绝；成功项保留原始 ID 和修订历史，可在回收站恢复。',
      okText: '移入回收站', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const receipt = await dataLifecycleApi.deleteMany('skill_definition', null, selectedSkillIds);
          setSelectedSkillIds([]);
          invalidate();
          queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
          if (receipt.failed) {
            modal.info({
              title: `成功 ${receipt.succeeded} 个，失败 ${receipt.failed} 个`,
              content: <Space direction="vertical" style={{ width: '100%' }}>{receipt.items.filter((item) => !item.succeeded).map((item) => <Alert key={item.id} type="error" showIcon message={`Skill #${item.id}`} description={item.error ?? '删除失败'} />)}</Space>,
            });
          } else message.success(`已将 ${receipt.succeeded} 个 Skill 移入回收站`);
        } catch (error) { message.error(getErrorMessage(error, '批量删除失败')); }
      },
    });
  };
  const onSubmit = (body: SkillInput) => editing ? updateMutation.mutate({ id: editing.id, body }) : createMutation.mutate(body);
  return <>
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
      <Space wrap size={8}>
        <Input.Search allowClear value={searchText} onChange={(event) => { setSearchText(event.target.value); setCurrentPage(1); }} placeholder="按 Skill 名称或说明搜索" style={{ width: 320, maxWidth: '100%' }} />
        <Select value={categoryFilter} onChange={(value) => { setCategoryFilter(value); setCurrentPage(1); }} options={categoryOptions} style={{ width: 180 }} />
      </Space>
      <Space>
        <Button danger disabled={!selectedSkillIds.length} onClick={deleteSelectedSkills}>批量删除（{selectedSkillIds.length}）</Button>
        <Button onClick={() => navigate('/admin/recycle-bin')}>回收站</Button>
        <Upload accept=".zip,application/zip" showUploadList={false} beforeUpload={(file) => { importMutation.mutate(file); return false; }}>
          <Button icon={<UploadOutlined />} loading={importMutation.isPending}>导入 Skill ZIP</Button>
        </Upload>
        <Button type="primary" onClick={() => setCreating(true)}>新增 Skill</Button>
      </Space>
    </div>
    <Space style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
      <Typography.Text type="secondary">共 {visibleSkills.length} 个 Skill；跨页选择已保留，最多 100 个</Typography.Text>
      <Space size={8}>
        <Checkbox checked={pageSkills.length > 0 && selectedOnPage === pageSkills.length} indeterminate={selectedOnPage > 0 && selectedOnPage < pageSkills.length} onChange={(event) => toggleCurrentPage(event.target.checked)}>全选当前页</Checkbox>
        <Button type="link" size="small" disabled={!selectedSkillIds.length} onClick={() => setSelectedSkillIds([])}>清空选择</Button>
      </Space>
    </Space>
    {visibleSkills.length ? <>
      <List
        size="small"
        bordered
        dataSource={pageSkills}
        renderItem={(skill) => {
          const category = skillCategory(skill.name);
          return <List.Item
            actions={[
              <Checkbox key="select" checked={selectedSkillIds.includes(skill.id)} disabled={!selectedSkillIds.includes(skill.id) && selectedSkillIds.length >= 100} onChange={(event) => toggleSkillSelection(skill.id, event.target.checked)} aria-label={`选择 Skill ${skill.name}`} />,
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
              <Button key="delete" type="link" size="small" danger onClick={() => modal.confirm({ title: `将 Skill「${skill.name}」移入回收站？`, okText: '移入回收站', okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(skill.id) })}>删除</Button>,
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

export function DefinitionHistoryModal({ target, onClose, onRestored }: {
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
  const defaultFiles = useMemo(() => initial?.files_json ?? { 'SKILL.md': initial?.content ?? '' }, [initial]);
  const formInitialValues = useMemo(
    () => initial ? { ...initial, mcp_tool_keys_json: initial.mcp_tool_keys_json ?? [] } : { is_enabled: false, mcp_tool_keys_json: [] },
    [initial],
  );
  useEffect(() => {
    if (!open) return;
    setFiles(defaultFiles);
    setSelectedPath('SKILL.md');
    setNewPath('');
    form.resetFields();
    form.setFieldsValue(formInitialValues);
  }, [defaultFiles, form, formInitialValues, open]);
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
  return <Drawer
    title={initial ? `Skill 详情与编辑：${initial.name}` : '新增 Skill'}
    open={open}
    onClose={onCancel}
    width={760}
    destroyOnClose
    extra={initial ? <Space><Tag color={initial.is_enabled ? 'green' : 'default'}>{initial.is_enabled ? '启用' : '停用'}</Tag><Tag>v{initial.version}</Tag></Space> : null}
    footer={<div className="editor-drawer-footer">
      <Space wrap>{initial && <Button onClick={onOpenHistory}>版本历史</Button>}{initial && <Button onClick={() => { setFiles(defaultFiles); form.setFieldsValue({ name: initial.name, description: initial.description, is_enabled: initial.is_enabled, mcp_tool_keys_json: initial.mcp_tool_keys_json }); }}>放弃未保存修改</Button>}</Space>
      <Space wrap><Button onClick={onCancel}>关闭</Button><Button type="primary" loading={loading} onClick={() => form.submit()}>{initial ? '保存为新版本' : '创建 Skill'}</Button></Space>
    </div>}
  >
    <Form form={form} layout="vertical" initialValues={formInitialValues} onFinish={submit}>
      <Tabs items={[
        { key: 'overview', label: '概览与内容', children: <>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="name" label="Skill 名称" rules={[{ required: true }]}><Input maxLength={120} /></Form.Item></Col>
            <Col span={12}><Form.Item name="is_enabled" label="启用 Skill" valuePropName="checked"><Switch /></Form.Item></Col>
          </Row>
          <Form.Item name="description" label="Skill 描述"><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
          <Alert type="info" showIcon message="AgentSkills 文件库" description="Skill 使用 SKILL.md 作为入口文件。任务创建时，已绑定 Agent 的任务快照会保留所有相关文件内容和版本。" style={{ marginBottom: 16 }} />
          <div className="skill-file-editor">
            <div className="skill-file-editor__tree">
              <Space.Compact style={{ width: '100%', marginBottom: 10 }}>
                <Input value={newPath} onChange={(event) => setNewPath(event.target.value)} placeholder="文件路径，如 references/api.md" onPressEnter={addFile} />
                <Button icon={<PlusOutlined />} onClick={addFile} />
              </Space.Compact>
              <List className="skill-file-editor__files" size="small" bordered dataSource={Object.keys(files).sort()} renderItem={(path) => <List.Item style={{ cursor: 'pointer', background: path === selectedPath ? 'rgba(82,112,255,.08)' : undefined }} onClick={() => setSelectedPath(path)}>
                <Typography.Text ellipsis={{ tooltip: path }} style={{ minWidth: 0, flex: 1 }}>{path}</Typography.Text>
                {path !== 'SKILL.md' && <Button size="small" type="link" danger onClick={(event) => { event.stopPropagation(); setFiles((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== path))); if (selectedPath === path) setSelectedPath('SKILL.md'); }}>删除</Button>}
              </List.Item>} />
            </div>
            <div className="skill-file-editor__content">
              <Typography.Text className="skill-file-editor__path" strong>{selectedPath}</Typography.Text>
              <Input.TextArea
                value={files[selectedPath] ?? ''}
                onChange={(event) => setFiles((current) => ({ ...current, [selectedPath]: event.target.value }))}
                rows={12}
                classNames={{ textarea: 'skill-file-editor__textarea' }}
                maxLength={100000}
                showCount
                style={{ marginTop: 8, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}
              />
            </div>
          </div>
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

