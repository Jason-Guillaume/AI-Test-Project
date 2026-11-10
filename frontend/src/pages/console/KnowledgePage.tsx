import { useEffect, useState } from 'react';
import { Alert, Button, Card, Checkbox, Input, Modal, Select, Space, Table, Upload, message } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { api } from '@/shared/api/client';

type Base = { id: number; name: string };
type Doc = { id: number; name: string; category: string; enabled: boolean };
type Version = { id: number; version: number; status: string; error: string | null };
type Scope = { base_id: number; mode: string; document_ids: number[]; categories: string[] };
type SearchResult = { items: { chunk_id: number; version_id: number; page: number | null; text: string }[] };
type Binding = { revision: number; enabled: boolean; required: boolean; scopes: Scope[] };

export function KnowledgePage() {
  const { currentProjectId: project } = useConsoleScope();
  const root = `/projects/${project}`;
  const [base, setBase] = useState<number>();
  const [name, setName] = useState('默认知识库');
  const [category, setCategory] = useState('');
  const [document, setDocument] = useState<Doc>();
  const [agent, setAgent] = useState<number>();
  const [binding, setBinding] = useState<Binding>({ revision: 0, enabled: true, required: false, scopes: [] });
  const [mode, setMode] = useState('DOCUMENTS');
  const [selected, setSelected] = useState<number[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [sources, setSources] = useState<SearchResult>();
  useEffect(() => { setBase(undefined); setDocument(undefined); setAgent(undefined); setSources(undefined); }, [project]);
  const bases = useQuery({ queryKey: ['knowledge', project], enabled: !!project, queryFn: () => api.get<{ items: Base[] }>(`${root}/knowledge-bases`) });
  const docs = useQuery({ queryKey: ['knowledge', project, base], enabled: !!project && !!base, queryFn: () => api.get<{ items: Doc[] }>(`${root}/knowledge-bases/${base}/documents`) });
  const versions = useQuery({ queryKey: ['knowledge-versions', project, document?.id], enabled: !!project && !!document, refetchInterval: 3000, queryFn: () => api.get<{ items: Version[] }>(`${root}/knowledge-documents/${document!.id}/versions`) });
  const agents = useQuery({ queryKey: ['knowledge-agents', project], enabled: !!project, queryFn: () => api.get<{ id: number; name: string }[]>(`${root}/knowledge-agent-options`) });
  useEffect(() => {
    if (!project || !agent) return;
    let active = true;
    api.get<Binding>(`${root}/agents/${agent}/knowledge-binding`).then(value => { if (active) setBinding(value); }).catch(() => message.error('读取绑定失败'));
    return () => { active = false; };
  }, [project, agent, root]);
  const execute = async (fn: () => Promise<unknown>) => { try { await fn(); message.success('已保存'); } catch { message.error('操作失败，请检查权限或刷新后重试'); } };
  if (!project) return <Alert message="请先选择项目" />;
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Card title="项目知识库">
      <Space wrap>
        <Select placeholder="选择知识库" style={{ width: 220 }} value={base} options={bases.data?.items.map(b => ({ value: b.id, label: b.name }))} onChange={v => { setBase(v); setDocument(undefined); }} />
        {base && ['enable', 'disable'].map((action, i) => <Button key={action} onClick={() => execute(async () => { await api.post(`${root}/knowledge-bases/${base}/commands`, { action }); await bases.refetch(); })}>{['启用库', '停用库'][i]}</Button>)}
        <Input placeholder="新知识库名称" value={name} onChange={e => setName(e.target.value)} />
        <Button disabled={!name.trim()} onClick={() => execute(async () => { await api.post(`${root}/knowledge-bases`, { name }); await bases.refetch(); })}>创建知识库</Button>
        <Input placeholder="文档分类" value={category} onChange={e => setCategory(e.target.value)} />
        <Upload accept=".txt,.md,.markdown,.docx,.pdf" showUploadList={false} beforeUpload={file => {
          if (!base) return false;
          const form = new FormData(); form.append('file', file); form.append('category', category);
          if (document) form.append('document_id', String(document.id));
          void execute(async () => { await api.post(`${root}/knowledge-bases/${base}/documents`, form); await docs.refetch(); await versions.refetch(); });
          return false;
        }}><Button disabled={!base}>{document ? `上传「${document.name}」新版本` : '上传文档'}</Button></Upload>
        {document && <Button onClick={() => setDocument(undefined)}>返回新文档上传</Button>}
      </Space>
      <Table<Doc> rowKey="id" dataSource={docs.data?.items || []} columns={[
        { title: '名称', dataIndex: 'name' }, { title: '分类', dataIndex: 'category' },
        { title: '状态', render: (_, d) => d.enabled ? '启用' : '停用' },
        { title: '版本', render: (_, d) => <Button onClick={() => setDocument(d)}>查看版本 / 更新</Button> },
      ]} />
      {document && <Table<Version> rowKey="id" dataSource={versions.data?.items || []} columns={[
        { title: '版本', dataIndex: 'version' }, { title: '解析状态', dataIndex: 'status' }, { title: '错误', dataIndex: 'error' },
        { title: '操作', render: (_, v) => <Space>{['retry', 'enable', 'disable'].map((action, i) => <Button key={action} disabled={action === 'retry' && v.status === 'READY'} onClick={() => execute(async () => { await api.post(`${root}/knowledge-document-versions/${v.id}/commands`, { action }); await versions.refetch(); await docs.refetch(); })}>{['重试解析', '启用文档', '停用文档'][i]}</Button>)}</Space> },
      ]} />}
    </Card>
    <Card title="当前项目的 Agent 知识配置">
      <Alert message="未绑定默认无知识访问。范围只属于当前项目和所选 Agent；子 Agent 需要单独绑定。检索结果仅代表命中片段，不代表全文覆盖。" />
      <Space wrap style={{ marginTop: 16 }}>
        <Select placeholder="选择 Agent" style={{ width: 240 }} value={agent} onChange={setAgent} options={agents.data?.map(a => ({ value: a.id, label: a.name }))} />
        <Checkbox checked={binding.required} onChange={e => setBinding({ ...binding, required: e.target.checked })}>必须有有效知识</Checkbox>
        <Checkbox checked={binding.enabled} onChange={e => setBinding({ ...binding, enabled: e.target.checked })}>启用绑定</Checkbox>
        <Select value={mode} onChange={setMode} options={[{ value: 'ALL', label: '整个所选库' }, { value: 'DOCUMENTS', label: '指定文档' }, { value: 'CATEGORIES', label: '指定分类' }]} />
        {mode === 'DOCUMENTS' && <Select mode="multiple" placeholder="选择文档" style={{ minWidth: 220 }} value={selected} onChange={setSelected} options={docs.data?.items.map(d => ({ value: d.id, label: d.name }))} />}
        {mode === 'CATEGORIES' && <Select mode="tags" placeholder="分类" style={{ minWidth: 220 }} value={categories} onChange={setCategories} />}
        <Button disabled={!base} onClick={() => setBinding({ ...binding, scopes: [...binding.scopes.filter(s => s.base_id !== base), { base_id: base!, mode, document_ids: selected, categories }] })}>设置所选库范围</Button>
        <Button disabled={!agent} onClick={() => execute(async () => { setBinding(await api.put<Binding>(`${root}/agents/${agent}/knowledge-binding`, binding)); })}>保存绑定</Button>
        <Button onClick={() => setBinding({ ...binding, scopes: [] })}>清空范围</Button>
      </Space>
      <Table<Scope> rowKey="base_id" pagination={false} dataSource={binding.scopes} columns={[
        { title: '知识库', render: (_, s) => bases.data?.items.find(b => b.id === s.base_id)?.name || `知识库 ${s.base_id}` },
        { title: '范围', render: (_, s) => s.mode === 'ALL' ? '整个库' : s.mode === 'CATEGORIES' ? `分类：${s.categories.join('、') || '未选择'}` : `指定 ${s.document_ids.length} 份文档` },
        { title: '操作', render: (_, s) => <Button onClick={() => setBinding({ ...binding, scopes: binding.scopes.filter(item => item.base_id !== s.base_id) })}>移除</Button> },
      ]} />
      <Space><Input placeholder="检索试用" value={query} onChange={e => setQuery(e.target.value)} /><Button disabled={!agent} onClick={() => execute(async () => { setSources(await api.post<SearchResult>(`${root}/agents/${agent}/knowledge-search`, { query })); })}>检索与来源预览</Button></Space>
    </Card>
    <Modal title="知识来源片段" width={900} open={!!sources} footer={null} onCancel={() => setSources(undefined)}>{sources?.items.length ? sources.items.map(s => <Card key={s.chunk_id} title={`来源片段 ${s.chunk_id} · 文档版本 ${s.version_id}${s.page ? ` · 第 ${s.page} 页` : ''}`}><div style={{ whiteSpace: 'pre-wrap' }}>{s.text}</div></Card>) : <Alert message="当前范围没有可用片段，请检查绑定和解析状态" />}</Modal>
  </Space>;
}
