// Skill 列表、文件编辑、版本历史与恢复。
import { App, Alert, Button, Card, Checkbox, Col, Drawer, Form, Input, List, Modal, Row, Pagination, Select, Space, Switch, Table, Tabs, Tag, Tree, Typography, Upload } from 'antd';
import { FileOutlined, FolderOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState, type Key, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { DataNode } from 'antd/es/tree';
import { agentGovernanceApi } from '@/features/agent-governance/api/agentGovernance';
import { useDraftNavigationGuard } from '@/features/asr-evaluation/useDraftNavigationGuard';
import type { AgentDefinition, DefinitionVersion, SkillDefinition, SkillInput } from '@/features/agent-governance/contracts';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/PageState';

function skillCategory(name: string) {
  return name.includes(' · ') ? name.split(' · ')[0] : '通用';
}

function toSkillInput(skill: SkillDefinition): SkillInput {
  const files = skill.files_json?.['SKILL.md'] === undefined
    ? { ...(skill.files_json ?? {}), 'SKILL.md': skill.content ?? '' }
    : skill.files_json;
  return {
    name: skill.name,
    description: skill.description,
    content: files['SKILL.md'],
    files_json: files,
    mcp_tool_keys_json: skill.mcp_tool_keys_json ?? [],
    is_enabled: skill.is_enabled,
  };
}

function buildSkillTreeNode(
  skill: SkillDefinition,
  selectedSkillIds: number[],
  onToggle: (id: number, checked: boolean) => void,
): DataNode {
  const root: DataNode = {
    key: `skill:${skill.id}`,
    title: (
      <div className="skill-workspace__tree-skill" title={skill.name}>
        <Checkbox
          checked={selectedSkillIds.includes(skill.id)}
          disabled={!selectedSkillIds.includes(skill.id) && selectedSkillIds.length >= 100}
          aria-label={`选择 Skill ${skill.name}`}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => onToggle(skill.id, event.target.checked)}
        />
        <span className="skill-workspace__tree-name">{skill.name}</span>
        <Tag color={skill.is_enabled ? 'green' : 'default'}>{skill.is_enabled ? '启用' : '停用'}</Tag>
      </div>
    ),
    children: [],
  };
  const fileNodes = new Map<string, DataNode>();
  const files = skill.files_json?.['SKILL.md'] === undefined
    ? { ...(skill.files_json ?? {}), 'SKILL.md': skill.content ?? '' }
    : skill.files_json;
  for (const path of Object.keys(files).sort()) {
    const parts = path.split('/').filter(Boolean);
    let parent = root;
    const segments: string[] = [];
    parts.forEach((part, index) => {
      segments.push(part);
      const relativePath = segments.join('/');
      let node = fileNodes.get(relativePath);
      if (!node) {
        const isFile = index === parts.length - 1;
        node = {
          key: `${isFile ? 'file' : 'dir'}:${skill.id}:${relativePath}`,
          title: <span className="skill-workspace__tree-file">{isFile ? <FileOutlined /> : <FolderOutlined />}<span>{part}</span></span>,
          isLeaf: isFile,
          ...(isFile ? {} : { children: [] }),
        };
        fileNodes.set(relativePath, node);
        parent.children = parent.children ?? [];
        parent.children.push(node);
      }
      parent = node;
    });
  }
  return root;
}

function MarkdownPreview({ content }: { content: string }) {
  const blocks: ReactNode[] = [];
  const lines = content.split('\n');
  let code: string[] = [];
  let inCode = false;
  lines.forEach((line, index) => {
    if (line.trim().startsWith('```')) {
      if (inCode) {
        blocks.push(<pre className="skill-workspace__markdown-code" key={`code-${index}`}>{code.join('\n')}</pre>);
        code = [];
      }
      inCode = !inCode;
      return;
    }
    if (inCode) { code.push(line); return; }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    const listItem = /^\s*[-*+]\s+(.+)$/.exec(line);
    const orderedItem = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    const quote = /^>\s?(.*)$/.exec(line);
    if (heading) {
      const level = Math.min(5, heading[1].length + 1) as 2 | 3 | 4 | 5;
      blocks.push(<Typography.Title level={level} key={`heading-${index}`}>{heading[2]}</Typography.Title>);
    } else if (listItem || orderedItem) {
      blocks.push(<Typography.Paragraph className="skill-workspace__markdown-list" key={`list-${index}`}>{listItem ? '• ' : `${index + 1}. `}{listItem?.[1] ?? orderedItem?.[1]}</Typography.Paragraph>);
    } else if (quote) {
      blocks.push(<blockquote className="skill-workspace__markdown-quote" key={`quote-${index}`}>{quote[1]}</blockquote>);
    } else if (line.trim()) {
      blocks.push(<Typography.Paragraph key={`paragraph-${index}`}>{line}</Typography.Paragraph>);
    }
  });
  if (code.length) blocks.push(<pre className="skill-workspace__markdown-code" key="code-last">{code.join('\n')}</pre>);
  return <div className="skill-workspace__markdown-preview">{blocks.length ? blocks : <Typography.Text type="secondary">没有可预览的内容。</Typography.Text>}</div>;
}

function isEditableTextFile(path: string) {
  return /\.(md|markdown|txt|rst|json|ya?ml|toml|py|sh|bash|js|jsx|ts|tsx|sql|csv|xml|html|css|go|rs|java|properties|env)$/i.test(path);
}

export function SkillPane() {
  const [creating, setCreating] = useState(false);
  const [creatingDirty, setCreatingDirty] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [categoryFilter, setCategoryFilter] = useState('全部');
  const [selectedSkillIds, setSelectedSkillIds] = useState<number[]>([]);
  const [activeSkillId, setActiveSkillId] = useState<number | null>(null);
  const [draft, setDraft] = useState<SkillInput | null>(null);
  const [selectedNode, setSelectedNode] = useState<{ kind: 'file' | 'folder'; path: string } | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<Key[]>([]);
  const [newFilePath, setNewFilePath] = useState('');
  const [previewMarkdown, setPreviewMarkdown] = useState(false);
  const [history, setHistory] = useState<{ kind: 'agent' | 'skill'; id: number; name: string } | null>(null);
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const skills = useQuery({ queryKey: ['agent-governance', 'skills'], queryFn: agentGovernanceApi.skills });
  const agents = useQuery({ queryKey: ['agent-governance', 'agents'], queryFn: agentGovernanceApi.agents });
  const mcpServers = useQuery({ queryKey: ['agent-governance', 'mcp-servers'], queryFn: agentGovernanceApi.mcpServers });
  const activeSkill = skills.data?.find((skill) => skill.id === activeSkillId) ?? null;
  const activeDirty = Boolean(activeSkill && draft && JSON.stringify(draft) !== JSON.stringify(toSkillInput(activeSkill)));
  useDraftNavigationGuard(activeDirty || creatingDirty);
  const usage = useQuery({
    queryKey: ['agent-governance', 'skill-usage', activeSkillId],
    queryFn: () => agentGovernanceApi.skillUsage(activeSkillId!),
    enabled: activeSkillId !== null,
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['agent-governance'] });
  const setSkillCache = (skill: SkillDefinition) => queryClient.setQueryData<SkillDefinition[]>(['agent-governance', 'skills'], (items) => [...(items ?? []).filter((item) => item.id !== skill.id), skill]);
  const createMutation = useMutation({ mutationFn: agentGovernanceApi.createSkill, onSuccess: (skill) => { message.success('Skill 已创建'); setCreating(false); setSkillCache(skill); setCurrentPage(1); setCategoryFilter('全部'); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const updateMutation = useMutation({ mutationFn: ({ id, body }: { id: number; body: SkillInput }) => agentGovernanceApi.updateSkill(id, body), onSuccess: (skill) => { message.success('Skill 已保存为新版本'); setSkillCache(skill); setDraft(toSkillInput(skill)); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
  const deleteMutation = useMutation({ mutationFn: agentGovernanceApi.deleteSkill, onSuccess: (_, id) => { message.success('Skill 已移入回收站'); if (id === activeSkillId) { setActiveSkillId(null); setDraft(null); setSelectedNode(null); } setCurrentPage(1); invalidate(); queryClient.invalidateQueries({ queryKey: ['recycle-bin'] }); }, onError: (e) => message.error(getErrorMessage(e)) });
  const importMutation = useMutation({ mutationFn: (file: File) => agentGovernanceApi.importSkillZip(file), onSuccess: (skill) => { message.success(`已导入 Skill「${skill.name}」`); setSkillCache(skill); setCurrentPage(1); setCategoryFilter('全部'); invalidate(); }, onError: (e) => message.error(getErrorMessage(e)) });
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
  const displayedActiveSkill = activeSkill && draft ? { ...activeSkill, ...draft } : activeSkill;
  const treeSkills = displayedActiveSkill
    ? pageSkills.some((skill) => skill.id === displayedActiveSkill.id)
      ? pageSkills.map((skill) => skill.id === displayedActiveSkill.id ? displayedActiveSkill : skill)
      : [...pageSkills, displayedActiveSkill]
    : pageSkills;
  const treeData = treeSkills.map((skill) => buildSkillTreeNode(skill, selectedSkillIds, toggleSkillSelection));
  const openSkill = (skillId: number, node: { kind: 'file' | 'folder'; path: string } | null = null) => {
    if (skillId === activeSkillId) { setSelectedNode(node); return; }
    const next = allSkills.find((skill) => skill.id === skillId);
    if (!next) return;
    const open = () => {
      setActiveSkillId(skillId);
      setDraft(toSkillInput(next));
      setSelectedNode(node);
      const parts = node?.path.split('/') ?? [];
      const parentFolders = node?.kind === 'file' ? parts.slice(0, -1) : parts;
      setExpandedKeys([`skill:${skillId}`, ...parentFolders.map((_, index) => `dir:${skillId}:${parts.slice(0, index + 1).join('/')}`)]);
      setPreviewMarkdown(false);
    };
    if (!activeDirty) { open(); return; }
    modal.confirm({ title: '放弃未保存修改？', content: '切换到其他 Skill 会丢弃当前暂存内容。', okText: '放弃并切换', cancelText: '继续编辑', okButtonProps: { danger: true }, onOk: open });
  };
  const onTreeSelect = (keys: Key[]) => {
    const key = String(keys[0] ?? '');
    if (key.startsWith('skill:')) { openSkill(Number(key.slice('skill:'.length))); return; }
    const match = /^(file|dir):(\d+):(.+)$/.exec(key);
    if (match) openSkill(Number(match[2]), { kind: match[1] === 'file' ? 'file' : 'folder', path: match[3] });
  };
  const updateDraft = (patch: Partial<SkillInput>) => setDraft((current) => current ? { ...current, ...patch } : current);
  const updateFile = (path: string, content: string) => setDraft((current) => {
    if (!current) return current;
    const files = { ...current.files_json, [path]: content };
    return { ...current, files_json: files, ...(path === 'SKILL.md' ? { content } : {}) };
  });
  const addFile = () => {
    const path = newFilePath.trim().replace(/\\/g, '/');
    if (!path || path.startsWith('/') || path.split('/').some((part) => !part || part === '.' || part === '..')) { message.error('请输入安全的相对文件路径'); return; }
    if (!draft || draft.files_json[path] !== undefined) { message.error('该文件已存在'); return; }
    updateFile(path, '');
    setSelectedNode({ kind: 'file', path });
    const folders = path.split('/').slice(0, -1);
    setExpandedKeys((current) => [...new Set([...current, `skill:${activeSkillId}`, ...folders.map((_, index) => `dir:${activeSkillId}:${folders.slice(0, index + 1).join('/')}`)])]);
    setNewFilePath('');
  };
  const removeFile = (path: string) => modal.confirm({
    title: `从暂存版本中删除「${path}」？`,
    content: '删除仅影响当前暂存内容，保存后才会创建新版本。SKILL.md 入口文件不能删除。',
    okText: '删除文件', cancelText: '取消', okButtonProps: { danger: true },
    onOk: () => {
      setDraft((current) => current ? { ...current, files_json: Object.fromEntries(Object.entries(current.files_json).filter(([name]) => name !== path)) } : current);
      setSelectedNode(null);
    },
  });
  const discardChanges = () => {
    if (!activeSkill) return;
    setDraft(toSkillInput(activeSkill));
    setSelectedNode(null);
    setPreviewMarkdown(false);
  };
  const saveSkill = () => {
    if (!activeSkill || !draft) return;
    if (!draft.name.trim()) { message.error('请输入 Skill 名称'); return; }
    if (!draft.files_json['SKILL.md']?.trim()) { message.error('必须保留非空的 SKILL.md 入口文件'); return; }
    if (Object.keys(draft.files_json).length > 200) { message.error('单个 Skill 最多包含 200 个文件'); return; }
    updateMutation.mutate({ id: activeSkill.id, body: { ...draft, content: draft.files_json['SKILL.md'] } });
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
          const deletedActiveSkill = receipt.items.some((item) => item.id === activeSkillId && item.succeeded);
          if (deletedActiveSkill) { setActiveSkillId(null); setDraft(null); setSelectedNode(null); }
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
  const linkedAgents = activeSkill ? agentRows.filter((agent) => agent.skill_keys.includes(activeSkill.key)) : [];
  const fileContents = draft?.files_json ?? {};
  const selectedFile = selectedNode?.kind === 'file' ? selectedNode.path : null;
  const markdownFile = Boolean(selectedFile && /\.(md|markdown)$/i.test(selectedFile));
  const visibleTreeData = treeData;
  const setTreeSelection = (keys: Key[]) => onTreeSelect(keys);
  return <>
    <div className="skill-workspace">
      <aside className="skill-workspace__sidebar">
        <div className="skill-workspace__sidebar-actions">
          <Button type="primary" block icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建 Skill</Button>
          <Upload accept=".zip,application/zip" showUploadList={false} beforeUpload={(file) => { importMutation.mutate(file); return false; }}>
            <Button block icon={<UploadOutlined />} loading={importMutation.isPending}>上传 ZIP 包</Button>
          </Upload>
          <Button block onClick={() => navigate('/admin/recycle-bin')}>回收站</Button>
        </div>
        <Input.Search allowClear value={searchText} onChange={(event) => { setSearchText(event.target.value); setCurrentPage(1); }} placeholder="搜索 Skill" />
        <Select value={categoryFilter} onChange={(value) => { setCategoryFilter(value); setCurrentPage(1); }} options={categoryOptions} style={{ width: '100%', marginTop: 8 }} />
        <div className="skill-workspace__bulk-actions">
          <Checkbox checked={pageSkills.length > 0 && selectedOnPage === pageSkills.length} indeterminate={selectedOnPage > 0 && selectedOnPage < pageSkills.length} onChange={(event) => toggleCurrentPage(event.target.checked)}>全选当前页</Checkbox>
          <Button type="link" size="small" disabled={!selectedSkillIds.length} onClick={() => setSelectedSkillIds([])}>清空</Button>
          <Button danger type="link" size="small" disabled={!selectedSkillIds.length} onClick={deleteSelectedSkills}>删除 {selectedSkillIds.length || ''}</Button>
        </div>
        {activeSkill && <div className="skill-workspace__file-add">
          <Typography.Text type="secondary">在 {activeSkill.name} 中新建文件</Typography.Text>
          <Space.Compact block>
            <Input value={newFilePath} onChange={(event) => setNewFilePath(event.target.value)} placeholder="references/guide.md" onPressEnter={addFile} />
            <Button icon={<PlusOutlined />} aria-label="新建 Skill 文件" onClick={addFile} />
          </Space.Compact>
        </div>}
        <div className="skill-workspace__tree-wrap">
          {treeSkills.length ? <Tree
            blockNode
            showIcon={false}
            treeData={visibleTreeData}
            selectedKeys={activeSkillId === null ? [] : [selectedNode ? `${selectedNode.kind === 'file' ? 'file' : 'dir'}:${activeSkillId}:${selectedNode.path}` : `skill:${activeSkillId}`]}
            expandedKeys={expandedKeys}
            onExpand={setExpandedKeys}
            onSelect={setTreeSelection}
          /> : <EmptyState description={normalizedSearch ? '没有匹配的 Skill' : '还没有 Skill'} />}
        </div>
        {visibleSkills.length > pageSize && <Pagination
          size="small" current={currentPage} pageSize={pageSize} total={visibleSkills.length}
          showSizeChanger pageSizeOptions={[20, 40, 80]} showTotal={(total) => `共 ${total} 个`}
          onChange={(page, nextPageSize) => { setCurrentPage(page); setPageSize(nextPageSize); }}
          style={{ marginTop: 12, textAlign: 'center' }}
        />}
        <Typography.Text className="skill-workspace__sidebar-hint" type="secondary">跨页选择最多 100 个 Skill</Typography.Text>
      </aside>
      <main className="skill-workspace__main">
        {!activeSkill || !draft ? <Card className="skill-workspace__welcome">
          <Typography.Title level={4}>Skill 文件工作区</Typography.Title>
          <Typography.Paragraph type="secondary">从左侧选择一个 Skill，查看概览、编辑入口文件和引用资料。所有修改会先暂存，保存后创建新版本。</Typography.Paragraph>
          <Typography.Text type="secondary">共 {allSkills.length} 个 Skill · 已启用 {allSkills.filter((skill) => skill.is_enabled).length} 个</Typography.Text>
        </Card> : <>
          <div className="skill-workspace__resource-header">
            <div className="skill-workspace__resource-title">
              <Space wrap>
                <Typography.Title level={4} style={{ margin: 0 }}>{draft.name || activeSkill.name}</Typography.Title>
                <Tag color={draft.is_enabled ? 'green' : 'default'}>{draft.is_enabled ? '启用' : '停用'}</Tag>
                <Tag>v{activeSkill.version}</Tag>
                {activeDirty && <Tag color="orange">未保存</Tag>}
              </Space>
              <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }}>{draft.description || '暂无描述'}</Typography.Paragraph>
            </div>
            <Space wrap>
              <Button onClick={() => setHistory({ kind: 'skill', id: activeSkill.id, name: activeSkill.name })}>版本历史</Button>
              <Button onClick={discardChanges} disabled={!activeDirty}>放弃修改</Button>
              <Button danger onClick={() => modal.confirm({ title: `将 Skill「${activeSkill.name}」移入回收站？`, content: '仍被引用或处于运行任务中的资源会由服务端拒绝删除。', okText: '移入回收站', cancelText: '取消', okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(activeSkill.id) })} loading={deleteMutation.isPending}>删除</Button>
              <Button type="primary" onClick={saveSkill} disabled={!activeDirty} loading={updateMutation.isPending}>保存新版本</Button>
            </Space>
          </div>
          {!selectedNode ? <>
            <Row gutter={[12, 12]} className="skill-workspace__stats">
              <Col xs={12} md={6}><Card size="small"><Typography.Text type="secondary">文件数量</Typography.Text><Typography.Title level={4}>{Object.keys(draft.files_json).length}</Typography.Title></Card></Col>
              <Col xs={12} md={6}><Card size="small"><Typography.Text type="secondary">版本</Typography.Text><Typography.Title level={4}>v{activeSkill.version}</Typography.Title></Card></Col>
              <Col xs={12} md={6}><Card size="small"><Typography.Text type="secondary">调用次数</Typography.Text><Typography.Title level={4}>{usage.data?.total_loads ?? (usage.isPending ? '…' : usage.isError ? '—' : '0')}</Typography.Title></Card></Col>
              <Col xs={12} md={6}><Card size="small"><Typography.Text type="secondary">最近使用</Typography.Text><Typography.Paragraph>{usage.data?.last_used_at ? new Date(usage.data.last_used_at).toLocaleString('zh-CN') : usage.isPending ? '加载中' : usage.isError ? '加载失败' : '从未使用'}</Typography.Paragraph></Card></Col>
            </Row>
            <Row gutter={[16, 16]}>
              <Col xs={24} xl={14}>
                <Card title="Skill 概览" extra={<Switch checked={draft.is_enabled} checkedChildren="启用" unCheckedChildren="停用" onChange={(checked) => updateDraft({ is_enabled: checked })} />}>
                  <Form layout="vertical">
                    <Form.Item label="Skill 名称" required><Input value={draft.name} maxLength={120} onChange={(event) => updateDraft({ name: event.target.value })} /></Form.Item>
                    <Form.Item label="用途说明"><Input.TextArea value={draft.description} rows={4} maxLength={2000} showCount onChange={(event) => updateDraft({ description: event.target.value })} /></Form.Item>
                    <Form.Item label="关联的 MCP 工具">
                      <Select mode="multiple" value={draft.mcp_tool_keys_json} options={mcpOptions} placeholder="选择已审批、只读且已连接的 MCP 工具" onChange={(value) => updateDraft({ mcp_tool_keys_json: value })} />
                    </Form.Item>
                  </Form>
                  <Alert type="info" showIcon message="SKILL.md 是执行入口" description="关联工具只会进入已绑定该 Skill 的 Agent 任务快照；修改并保存后，已有任务快照不会改变。" />
                </Card>
              </Col>
              <Col xs={24} xl={10}>
                <Card title="关联 Agent 与使用记录">
                  <Typography.Text type="secondary">可见 Agent</Typography.Text>
                  <div className="skill-workspace__agent-list">{linkedAgents.length ? linkedAgents.map((agent) => <Tag key={agent.id}>{agent.name} · v{agent.version}</Tag>) : <Typography.Text type="secondary">尚未绑定 Agent。请在 Agent 配置中添加此 Skill。</Typography.Text>}</div>
                  {usage.isError ? <ErrorState error={usage.error} onRetry={usage.refetch} /> : <>
                    <Typography.Text type="secondary">加载此 Skill 的 Agent</Typography.Text>
                    <div className="skill-workspace__agent-list">{usage.data?.agents.length ? usage.data.agents.map((agent) => <Tag key={agent.id}>{agent.name} · {agent.loads} 次</Tag>) : <Typography.Text type="secondary">暂无加载记录</Typography.Text>}</div>
                    <Typography.Text type="secondary">最近加载任务</Typography.Text>
                    {usage.data?.recent_tasks.length ? <List size="small" dataSource={usage.data.recent_tasks.slice(0, 5)} renderItem={(task) => <List.Item>{task.title} · 第 {task.run_number} 次 · {new Date(task.used_at).toLocaleString('zh-CN')}</List.Item>} /> : <Typography.Paragraph type="secondary">暂无关联任务</Typography.Paragraph>}
                  </>}
                </Card>
              </Col>
            </Row>
          </> : selectedNode.kind === 'folder' ? <Card>
            <Typography.Title level={5}><FolderOutlined /> {selectedNode.path}</Typography.Title>
            <Typography.Text type="secondary">此目录由下方文件路径组成。选择具体文件以查看或编辑内容。</Typography.Text>
            <List size="small" dataSource={Object.keys(fileContents).filter((path) => path.startsWith(`${selectedNode.path}/`)).sort()} renderItem={(path) => <List.Item><Button type="link" onClick={() => setSelectedNode({ kind: 'file', path })}>{path.slice(selectedNode.path.length + 1)}</Button></List.Item>} />
          </Card> : selectedFile && <Card
            className="skill-workspace__file-card"
            title={<Space wrap><FileOutlined /><Typography.Text className="skill-workspace__path">{selectedFile}</Typography.Text><Tag>{selectedFile.split('.').pop()?.toUpperCase() ?? 'TEXT'}</Tag></Space>}
            extra={selectedFile !== 'SKILL.md' && <Button danger type="link" onClick={() => removeFile(selectedFile)}>删除文件</Button>}
          >
            {!isEditableTextFile(selectedFile) ? <Alert type="warning" showIcon message="暂不支持在线预览此文件类型" description="该文件会保留在 Skill 版本中。为避免把二进制内容当作文本破坏，不提供文本编辑。" /> : markdownFile ? <Tabs activeKey={previewMarkdown ? 'preview' : 'edit'} onChange={(key) => setPreviewMarkdown(key === 'preview')} items={[
              { key: 'edit', label: '编辑', children: <Input.TextArea className="skill-workspace__editor-wrap" classNames={{ textarea: 'skill-workspace__editor' }} value={fileContents[selectedFile] ?? ''} onChange={(event) => updateFile(selectedFile, event.target.value)} spellCheck={false} maxLength={100000} showCount /> },
              { key: 'preview', label: '预览', children: <div className="skill-workspace__preview"><MarkdownPreview content={fileContents[selectedFile] ?? ''} /></div> },
            ]} /> : <>
              <Typography.Paragraph type="secondary">纯文本编辑 · {isEditableTextFile(selectedFile) ? 'UTF-8' : '未知格式'}</Typography.Paragraph>
              <Input.TextArea className="skill-workspace__editor-wrap" classNames={{ textarea: 'skill-workspace__editor' }} value={fileContents[selectedFile] ?? ''} onChange={(event) => updateFile(selectedFile, event.target.value)} spellCheck={false} maxLength={100000} showCount />
            </>}
          </Card>}
        </>}
      </main>
    </div>
    <SkillFormModal key={creating ? 'new' : 'closed'} open={creating} loading={createMutation.isPending} agents={agentRows} mcpOptions={mcpOptions} onOpenHistory={() => {}} onDirtyChange={setCreatingDirty} onCancel={() => { setCreating(false); setCreatingDirty(false); }} onSubmit={(body) => createMutation.mutate(body)} />
    <DefinitionHistoryModal
      key={history ? `${history.kind}-${history.id}` : 'closed'}
      target={history}
      onClose={() => setHistory(null)}
      onRestored={(definition) => {
        if ('files_json' in definition) {
          const skill = definition as SkillDefinition;
          setSkillCache(skill);
          setActiveSkillId(skill.id);
          setDraft(toSkillInput(skill));
          setSelectedNode(null);
          invalidate();
        }
      }}
    />
  </>;
}

export function DefinitionHistoryModal({ target, onClose, onRestored }: {
  target: { kind: 'agent' | 'skill'; id: number; name: string } | null;
  onClose: () => void;
  onRestored: (definition: AgentDefinition | SkillDefinition) => void;
}) {
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const { message, modal } = App.useApp();
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
  return <Modal title={target ? `${target.name} · 版本历史` : '版本历史'} open={Boolean(target)} onCancel={onClose} footer={<Space><Button onClick={onClose}>关闭</Button><Button type="primary" disabled={!selected || selected.version === latest?.version} loading={restoreMutation.isPending} onClick={() => modal.confirm({ title: `恢复为 v${selected?.version} 配置？`, content: `历史快照会替换当前${target?.kind === 'skill' ? 'Skill' : 'Agent'}暂存内容，并另存为新的版本号。`, okText: '恢复为新版本', cancelText: '取消', onOk: () => restoreMutation.mutate() })}>恢复为新版本</Button></Space>} width={760}>
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

function SkillFormModal({ open, initial, loading, agents, mcpOptions, onOpenHistory, onDirtyChange, onCancel, onSubmit }: {
  open: boolean;
  initial?: SkillDefinition;
  loading: boolean;
  agents: AgentDefinition[];
  mcpOptions: { label: string; value: string; disabled?: boolean }[];
  onOpenHistory: () => void;
  onDirtyChange: (dirty: boolean) => void;
  onCancel: () => void;
  onSubmit: (body: SkillInput) => void;
}) {
  const [form] = Form.useForm();
  const { message, modal } = App.useApp();
  const [files, setFiles] = useState<Record<string, string>>(initial?.files_json ?? { 'SKILL.md': initial?.content ?? '' });
  const [formChanged, setFormChanged] = useState(false);
  const [filesChanged, setFilesChanged] = useState(false);
  const [selectedPath, setSelectedPath] = useState('SKILL.md');
  const [newPath, setNewPath] = useState('');
  const defaultFiles = useMemo(() => initial?.files_json ?? { 'SKILL.md': initial?.content ?? '' }, [initial]);
  const formInitialValues = useMemo(
    () => initial ? { ...initial, mcp_tool_keys_json: initial.mcp_tool_keys_json ?? [] } : { is_enabled: false, mcp_tool_keys_json: [] },
    [initial],
  );
  const hasUnsavedChanges = formChanged || filesChanged;
  useEffect(() => { onDirtyChange(hasUnsavedChanges); }, [hasUnsavedChanges, onDirtyChange]);
  useEffect(() => {
    if (!open) return;
    setFiles(defaultFiles);
    setFormChanged(false);
    setFilesChanged(false);
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
    setFilesChanged(true);
    setSelectedPath(path);
    setNewPath('');
  };
  const requestClose = () => {
    if (!hasUnsavedChanges) { onCancel(); return; }
    modal.confirm({ title: '放弃未保存的 Skill？', content: '关闭后，新建表单和文件改动会被丢弃。', okText: '放弃修改', cancelText: '继续编辑', okButtonProps: { danger: true }, onOk: onCancel });
  };
  return <Drawer
    title={initial ? `Skill 详情与编辑：${initial.name}` : '新增 Skill'}
    open={open}
    onClose={requestClose}
    width={760}
    destroyOnClose
    extra={initial ? <Space><Tag color={initial.is_enabled ? 'green' : 'default'}>{initial.is_enabled ? '启用' : '停用'}</Tag><Tag>v{initial.version}</Tag></Space> : null}
    footer={<div className="editor-drawer-footer">
      <Space wrap>{initial && <Button onClick={onOpenHistory}>版本历史</Button>}{initial && <Button onClick={() => { setFiles(defaultFiles); form.setFieldsValue({ name: initial.name, description: initial.description, is_enabled: initial.is_enabled, mcp_tool_keys_json: initial.mcp_tool_keys_json }); }}>放弃未保存修改</Button>}</Space>
      <Space wrap><Button onClick={requestClose}>关闭</Button><Button type="primary" loading={loading} onClick={() => form.submit()}>{initial ? '保存为新版本' : '创建 Skill'}</Button></Space>
    </div>}
  >
    <Form form={form} layout="vertical" initialValues={formInitialValues} onValuesChange={() => setFormChanged(true)} onFinish={submit}>
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
                {path !== 'SKILL.md' && <Button size="small" type="link" danger onClick={(event) => { event.stopPropagation(); setFiles((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== path))); setFilesChanged(true); if (selectedPath === path) setSelectedPath('SKILL.md'); }}>删除</Button>}
              </List.Item>} />
            </div>
            <div className="skill-file-editor__content">
              <Typography.Text className="skill-file-editor__path" strong>{selectedPath}</Typography.Text>
              <Input.TextArea
                value={files[selectedPath] ?? ''}
                onChange={(event) => { setFiles((current) => ({ ...current, [selectedPath]: event.target.value })); setFilesChanged(true); }}
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

