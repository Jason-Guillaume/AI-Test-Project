// 管理后台的项目知识库。
//
// 资料只挂在项目上；默认项目共享，也可在本页为 Agent 显式限定文档范围。
// 平台管理员通过项目下拉选择目标项目；上传后的解析在后台异步完成。
import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Checkbox, Input, InputNumber, Radio, Select, Space, Table, Upload } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { projectsApi } from '@/features/projects/api/projects';
import { api, getErrorMessage } from '@/shared/api/client';
import { collectPages } from '@/shared/api/pagination';
import { PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';

type Base = { id: number; name: string; enabled: boolean };
type Doc = { id: number; name: string; category: string; enabled: boolean };
type Version = { id: number; version: number; status: string; error: string | null };
type AgentOption = { id: number; name: string };
type KnowledgeScope = { base_id: number; mode: string; document_ids: number[]; categories: string[] };
type KnowledgeBinding = { revision: number; enabled: boolean; required: boolean; access_mode: 'PROJECT_SHARED' | 'AGENT_SCOPED'; scopes: KnowledgeScope[] };
type SearchResult = { items: { chunk_id: number; version_id: number; version: number; document_id: number; document_name: string; score: number; score_type: string; page: number | null; text: string }[] };

const CATEGORIES = [
  { value: '项目情况', label: '项目情况' },
  { value: '用例编写规则', label: '用例编写规则' },
  { value: '其他', label: '其他' },
];

/**
 * 管理端项目知识库页。
 *
 * 先选择项目，再维护该项目的知识库和文档。切换项目会清空已选库和文档，避免把上一个项目的上传目标带过来。
 */
export function AdminKnowledgePage() {
  const { message } = App.useApp();
  const [selectedProjectId, setSelectedProjectId] = useState<number>();
  const [base, setBase] = useState<number>();
  const [name, setName] = useState('项目资料');
  const [category, setCategory] = useState('项目情况');
  const [document, setDocument] = useState<Doc>();
  const [query, setQuery] = useState('');
  const [sources, setSources] = useState<SearchResult>();
  const [agentId, setAgentId] = useState<number>();
  const [accessMode, setAccessMode] = useState<'PROJECT_SHARED' | 'AGENT_SCOPED'>('PROJECT_SHARED');
  const [scopeMode, setScopeMode] = useState<'ALL' | 'DOCUMENTS' | 'CATEGORIES'>('DOCUMENTS');
  const [scopedDocumentIds, setScopedDocumentIds] = useState<number[]>([]);
  const [scopedCategories, setScopedCategories] = useState<string[]>([]);
  const [topK, setTopK] = useState(8);
  const [minimumScore, setMinimumScore] = useState(0);
  const [saving, setSaving] = useState(false);
  const projectsQuery = useQuery({
    queryKey: ['projects', 'knowledge-admin'],
    queryFn: () => collectPages((page) => projectsApi.list({ page, page_size: 200 })),
  });
  const project = selectedProjectId ?? projectsQuery.data?.items[0]?.id;
  const root = `/projects/${project}`;
  const agents = useQuery({
    queryKey: ['knowledge-agents', project],
    enabled: project != null,
    queryFn: () => api.get<AgentOption[]>(`${root}/knowledge-agent-options`),
  });
  const binding = useQuery({
    queryKey: ['knowledge-binding', project, agentId],
    enabled: project != null && agentId != null,
    queryFn: () => api.get<KnowledgeBinding>(`${root}/agents/${agentId}/knowledge-binding`),
  });
  const bases = useQuery({
    queryKey: ['knowledge', project],
    enabled: project != null,
    queryFn: () => api.get<{ items: Base[] }>(`${root}/knowledge-bases`),
  });
  const docs = useQuery({
    queryKey: ['knowledge', project, base],
    enabled: project != null && base != null,
    queryFn: () => api.get<{ items: Doc[] }>(`${root}/knowledge-bases/${base}/documents`),
  });
  const versions = useQuery({
    queryKey: ['knowledge-versions', project, document?.id],
    enabled: project != null && document != null,
    refetchInterval: 3000,
    queryFn: () => api.get<{ items: Version[] }>(`${root}/knowledge-documents/${document!.id}/versions`),
  });

  useEffect(() => {
    setAccessMode(binding.data?.access_mode ?? 'PROJECT_SHARED');
    const selectedScope = (binding.data?.scopes ?? []).find((scope) => scope.base_id === base);
    setScopeMode(selectedScope?.mode === 'ALL' || selectedScope?.mode === 'CATEGORIES'
      ? selectedScope.mode
      : 'DOCUMENTS');
    setScopedDocumentIds(selectedScope?.mode === 'DOCUMENTS' ? selectedScope.document_ids : []);
    setScopedCategories(selectedScope?.mode === 'CATEGORIES' ? selectedScope.categories : []);
  }, [binding.data, base]);

  /** 执行写操作。保存中禁止再次点击，避免同一名称连续入库却看不到结果。 */
  const execute = async (fn: () => Promise<unknown>) => {
    if (saving) return;
    setSaving(true);
    try {
      await fn();
      message.success('已保存');
    } catch (error) {
      message.error(getErrorMessage(error, '操作失败，请检查权限或刷新后重试'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <PageContainer>
      <PageHeader title="项目知识库" subtitle="按项目管理资料，并为 Agent 配置共享或限定文档范围" />
      <Space direction="vertical" style={{ width: '100%' }}>
        <Select
          placeholder="选择项目"
          style={{ width: 320 }}
          value={project}
          options={projectsQuery.data?.items.map((item) => ({ value: item.id, label: item.name }))}
          onChange={(value) => {
            setSelectedProjectId(value);
            setBase(undefined);
            setDocument(undefined);
            setSources(undefined);
            setAgentId(undefined);
            setAccessMode('PROJECT_SHARED');
            setScopeMode('DOCUMENTS');
            setScopedDocumentIds([]);
            setScopedCategories([]);
          }}
        />
        <Card title="资料">
          <Space wrap>
            <Select
              placeholder="选择知识库"
              style={{ width: 220 }}
              value={base}
              options={bases.data?.items.map((item) => ({ value: item.id, label: item.name }))}
              onChange={(value) => {
                setBase(value);
                setDocument(undefined);
              }}
            />
            {base != null && ['enable', 'disable'].map((action, index) => (
              <Button
                key={action}
                onClick={() => execute(async () => {
                  await api.post(`${root}/knowledge-bases/${base}/commands`, { action });
                  await bases.refetch();
                })}
              >
                {['启用库', '停用库'][index]}
              </Button>
            ))}
            <Input placeholder="新知识库名称" value={name} onChange={(event) => setName(event.target.value)} />
            <Button
              disabled={!name.trim() || project == null || saving}
              onClick={() => execute(async () => {
                const created = await api.post<Base>(`${root}/knowledge-bases`, { name });
                setBase(created.id);
                setDocument(undefined);
                await bases.refetch();
              })}
            >
              创建知识库
            </Button>
            <Select style={{ width: 180 }} value={category} options={CATEGORIES} onChange={setCategory} />
            <Upload
              accept=".txt,.md,.markdown,.docx,.pdf"
              showUploadList={false}
              beforeUpload={(file) => {
                if (base == null) return false;
                const form = new FormData();
                form.append('file', file);
                form.append('category', category);
                if (document) form.append('document_id', String(document.id));
                void execute(async () => {
                  await api.post(`${root}/knowledge-bases/${base}/documents`, form);
                  await docs.refetch();
                  await versions.refetch();
                });
                return false;
              }}
            >
              <Button disabled={base == null}>{document ? `上传「${document.name}」新版本` : '上传文档'}</Button>
            </Upload>
            {document && <Button onClick={() => setDocument(undefined)}>返回新文档上传</Button>}
          </Space>
          <Table<Base>
            rowKey="id"
            dataSource={bases.data?.items || []}
            locale={{ emptyText: '当前项目还没有知识库' }}
            rowClassName={(row) => (row.id === base ? 'ant-table-row-selected' : '')}
            onRow={(row) => ({
              onClick: () => {
                setBase(row.id);
                setDocument(undefined);
              },
            })}
            columns={[
              { title: '知识库', dataIndex: 'name' },
              { title: '状态', render: (_, row) => (row.enabled ? '启用' : '停用') },
              { title: '操作', render: (_, row) => <Button onClick={() => { setBase(row.id); setDocument(undefined); }}>查看文档</Button> },
            ]}
          />
          {base != null && <Table<Doc>
            rowKey="id"
            dataSource={docs.data?.items || []}
            locale={{ emptyText: '这个知识库还没有文档' }}
            columns={[
              { title: '名称', dataIndex: 'name' },
              { title: '分类', dataIndex: 'category' },
              { title: '状态', render: (_, row) => (row.enabled ? '启用' : '停用') },
              { title: '版本', render: (_, row) => <Button onClick={() => setDocument(row)}>查看版本 / 更新</Button> },
            ]}
          />}
          {document && (
            <Table<Version>
              rowKey="id"
              dataSource={versions.data?.items || []}
              columns={[
                { title: '版本', dataIndex: 'version' },
                { title: '解析状态', dataIndex: 'status' },
                { title: '错误', dataIndex: 'error' },
                {
                  title: '操作',
                  render: (_, row) => (
                    <Space>
                      {['retry', 'enable', 'disable'].map((action, index) => (
                        <Button
                          key={action}
                          disabled={action === 'retry' && row.status === 'READY'}
                          onClick={() => execute(async () => {
                            await api.post(`${root}/knowledge-document-versions/${row.id}/commands`, { action });
                            await versions.refetch();
                            await docs.refetch();
                          })}
                        >
                          {['重试解析', '启用文档', '停用文档'][index]}
                        </Button>
                      ))}
                    </Space>
                  ),
                },
              ]}
            />
          )}
        </Card>
        <Card title="Agent 知识范围">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space wrap>
              <Select
                placeholder="选择 Agent"
                style={{ width: 280 }}
                value={agentId}
                options={agents.data?.map((item) => ({ value: item.id, label: item.name }))}
                onChange={(value) => setAgentId(value)}
              />
              <Radio.Group
                value={accessMode}
                disabled={agentId == null}
                onChange={(event) => setAccessMode(event.target.value)}
                options={[
                  { value: 'PROJECT_SHARED', label: '共享项目知识' },
                  { value: 'AGENT_SCOPED', label: '限定 Agent 范围' },
                ]}
              />
              <Button
                disabled={agentId == null || saving || (accessMode === 'AGENT_SCOPED' && base == null)}
                onClick={() => execute(async () => {
                  const scopes = (binding.data?.scopes ?? []).filter((scope) => scope.base_id !== base);
                  if (accessMode === 'AGENT_SCOPED' && base != null) {
                    scopes.push({
                      base_id: base,
                      mode: scopeMode,
                      document_ids: scopeMode === 'DOCUMENTS' ? scopedDocumentIds : [],
                      categories: scopeMode === 'CATEGORIES' ? scopedCategories : [],
                    });
                  }
                  await api.put(`${root}/agents/${agentId}/knowledge-binding`, {
                    revision: binding.data?.revision ?? 0,
                    enabled: true,
                    required: binding.data?.required ?? false,
                    access_mode: accessMode,
                    scopes,
                  });
                  await binding.refetch();
                })}
              >
                保存 Agent 范围
              </Button>
            </Space>
            {accessMode === 'PROJECT_SHARED' ? (
              <Alert type="info" showIcon message="该 Agent 可读取当前项目内所有启用资料；这是旧配置的兼容默认值。" />
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Select
                  placeholder="选择要授权的知识库"
                  style={{ width: 280 }}
                  value={base}
                  options={bases.data?.items.map((item) => ({ value: item.id, label: item.name }))}
                  onChange={(value) => setBase(value)}
                />
                {base == null ? <Alert type="warning" message="选择知识库后，再勾选该 Agent 可以读取的文档。" /> : (
                  <Space direction="vertical">
                    <Radio.Group
                      value={scopeMode}
                      onChange={(event) => setScopeMode(event.target.value)}
                      options={[
                        { value: 'ALL', label: '该库内所有启用文档' },
                        { value: 'DOCUMENTS', label: '仅选择的文档' },
                        { value: 'CATEGORIES', label: '按资料分类授权' },
                      ]}
                    />
                    {scopeMode === 'DOCUMENTS' && (
                      <Checkbox.Group
                        value={scopedDocumentIds}
                        options={(docs.data?.items ?? []).map((item) => ({ label: `${item.name}${item.enabled ? '' : '（已停用）'}`, value: item.id, disabled: !item.enabled }))}
                        onChange={(values) => setScopedDocumentIds(values as number[])}
                      />
                    )}
                    {scopeMode === 'CATEGORIES' && (
                      <Checkbox.Group
                        value={scopedCategories}
                        options={CATEGORIES}
                        onChange={(values) => setScopedCategories(values as string[])}
                      />
                    )}
                  </Space>
                )}
                <Alert type="warning" showIcon message="保存会替换所选知识库的范围；未选文档或分类时，该库不会向此 Agent 提供内容。" />
              </Space>
            )}
          </Space>
        </Card>
        <Card title="当前项目检索">
          <Space>
            <Input placeholder="试查项目资料" value={query} onChange={(event) => setQuery(event.target.value)} />
            <InputNumber min={1} max={50} value={topK} onChange={(value) => setTopK(value ?? 8)} addonBefore="Top‑K" />
            <InputNumber min={0} max={100} step={0.1} value={minimumScore} onChange={(value) => setMinimumScore(value ?? 0)} addonBefore="最低分" />
            <Button
              disabled={project == null}
              onClick={() => execute(async () => {
                setSources(await api.post<SearchResult>(`${root}/knowledge-search`, {
                  query, top_k: topK, minimum_score: minimumScore,
                }));
              })}
            >
              检索
            </Button>
          </Space>
          {sources?.items.map((item) => (
            <Card key={item.chunk_id} style={{ marginTop: 12 }} title={`${item.document_name} · v${item.version} · 片段 ${item.chunk_id}${item.page ? ` · 第 ${item.page} 页` : ''} · BM25 ${item.score}`}>
              <div style={{ whiteSpace: 'pre-wrap' }}>{item.text}</div>
            </Card>
          ))}
        </Card>
      </Space>
    </PageContainer>
  );
}
