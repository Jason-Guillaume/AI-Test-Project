// 管理后台的项目知识库。
//
// 资料只挂在项目上，供后续处理该项目的 Agent 直接读取。
// 本页不配置 Agent，也不保存 Agent 绑定。
// 平台管理员通过项目下拉选择目标项目；上传后的解析在后台异步完成。
import { useState } from 'react';
import { App, Button, Card, Input, Select, Space, Table, Upload } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { projectsApi } from '@/features/projects/api/projects';
import { api, getErrorMessage } from '@/shared/api/client';
import { collectPages } from '@/shared/api/pagination';
import { PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';

type Base = { id: number; name: string; enabled: boolean };
type Doc = { id: number; name: string; category: string; enabled: boolean };
type Version = { id: number; version: number; status: string; error: string | null };
type SearchResult = { items: { chunk_id: number; version_id: number; page: number | null; text: string }[] };

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
  const projectsQuery = useQuery({
    queryKey: ['projects', 'knowledge-admin'],
    queryFn: () => collectPages((page) => projectsApi.list({ page, page_size: 200 })),
  });
  const project = selectedProjectId ?? projectsQuery.data?.items[0]?.id;
  const root = `/projects/${project}`;
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

  /** 执行写操作；失败时展示后端文案，成功后由调用方刷新对应列表。 */
  const execute = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      message.success('已保存');
    } catch (error) {
      message.error(getErrorMessage(error, '操作失败，请检查权限或刷新后重试'));
    }
  };

  return (
    <PageContainer>
      <PageHeader title="项目知识库" subtitle="按项目维护项目情况和用例编写规则，处理该项目的 Agent 会直接读取" />
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
              disabled={!name.trim() || project == null}
              onClick={() => execute(async () => {
                await api.post(`${root}/knowledge-bases`, { name });
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
          <Table<Doc>
            rowKey="id"
            dataSource={docs.data?.items || []}
            columns={[
              { title: '名称', dataIndex: 'name' },
              { title: '分类', dataIndex: 'category' },
              { title: '状态', render: (_, row) => (row.enabled ? '启用' : '停用') },
              { title: '版本', render: (_, row) => <Button onClick={() => setDocument(row)}>查看版本 / 更新</Button> },
            ]}
          />
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
        <Card title="当前项目检索">
          <Space>
            <Input placeholder="试查项目资料" value={query} onChange={(event) => setQuery(event.target.value)} />
            <Button
              disabled={project == null}
              onClick={() => execute(async () => {
                setSources(await api.post<SearchResult>(`${root}/knowledge-search`, { query }));
              })}
            >
              检索
            </Button>
          </Space>
          {sources?.items.map((item) => (
            <Card key={item.chunk_id} style={{ marginTop: 12 }} title={`片段 ${item.chunk_id}${item.page ? ` · 第 ${item.page} 页` : ''}`}>
              <div style={{ whiteSpace: 'pre-wrap' }}>{item.text}</div>
            </Card>
          ))}
        </Card>
      </Space>
    </PageContainer>
  );
}
