// 项目知识库与 Agent 业务组装工作区。
// 当前项目的成员可以维护文档、查看解析依据，并将选中文档异步组装为可编辑业务草稿。
import { useEffect, useMemo, useState } from 'react';
import {
  App,
  Button,
  Card,
  Checkbox,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd';
import type { UploadFile } from 'antd';
import {
  CloudUploadOutlined,
  DeleteOutlined,
  EyeOutlined,
  FileAddOutlined,
  ReloadOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { businessAssemblyApi } from '@/api/businessAssembly';
import { getErrorMessage } from '@/api/client';
import { knowledgeApi } from '@/api/knowledge';
import { tasksApi, type Task } from '@/api/tasks';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import type {
  BusinessAssemblyDraft,
  BusinessAssemblyDraftContent,
  KnowledgeCategory,
  KnowledgeDocument,
} from '@/types';

const CATEGORY_OPTIONS: { value: KnowledgeCategory; label: string }[] = [
  { value: 'REQUIREMENTS', label: '需求说明' },
  { value: 'BUSINESS_PROCESS', label: '业务流程' },
  { value: 'API_SPEC', label: '接口说明' },
  { value: 'FIELD_DICTIONARY', label: '字段字典' },
  { value: 'BUSINESS_RULE', label: '业务规则' },
];
const TERMINAL_TASK_STATUSES = new Set(['SUCCEEDED', 'SUCCEEDED_WITH_ISSUES', 'FAILED', 'CANCELLED']);
const CATEGORY_LABEL: Record<KnowledgeCategory, string> = Object.fromEntries(
  CATEGORY_OPTIONS.map((item) => [item.value, item.label]),
) as Record<KnowledgeCategory, string>;

interface UploadFormValues {
  title: string;
  category: KnowledgeCategory;
}

/** 项目知识库入口：项目切换后重建页面状态，避免带错草稿和文档选择。 */
export function ConsoleKnowledgeBasePage() {
  const { currentProjectId } = useConsoleScope();
  return <KnowledgeBaseWorkspace key={currentProjectId ?? 'none'} />;
}

function KnowledgeBaseWorkspace() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { currentProjectId } = useConsoleScope();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadDocumentId, setUploadDocumentId] = useState<number | undefined>();
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [previewDocument, setPreviewDocument] = useState<KnowledgeDocument | null>(null);
  const [previewPage, setPreviewPage] = useState(1);
  const [previewVersionId, setPreviewVersionId] = useState<number | undefined>();
  const [assemblyOpen, setAssemblyOpen] = useState(false);
  const [assemblyVersionIds, setAssemblyVersionIds] = useState<number[]>([]);
  const [assemblyTask, setAssemblyTask] = useState<Task | null>(null);
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftJson, setDraftJson] = useState('');
  const [selectedFlowIndexes, setSelectedFlowIndexes] = useState<number[]>([]);
  const [applyKey, setApplyKey] = useState('');
  const [uploadForm] = Form.useForm<UploadFormValues>();

  const baseQuery = useQuery({
    queryKey: ['project', currentProjectId, 'knowledge-bases'],
    queryFn: () => knowledgeApi.listBases(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const base = baseQuery.data?.[0] ?? null;
  const documentsQuery = useQuery({
    queryKey: ['project', currentProjectId, 'knowledge-documents', base?.id],
    queryFn: () => knowledgeApi.listDocuments(base!.id),
    enabled: base != null,
    refetchInterval: (query) =>
      query.state.data?.items.some((row) => row.latest_parse_status === 'PENDING' || row.latest_parse_status === 'PROCESSING') ? 1800 : false,
  });
  const documents = documentsQuery.data?.items ?? [];
  const historyQuery = useQuery({
    queryKey: ['business-assembly-history', currentProjectId],
    queryFn: () => tasksApi.list({ page: 1, page_size: 100, project_id: currentProjectId! }),
    enabled: currentProjectId != null,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) =>
        item.task_mode === 'BUSINESS_ASSEMBLY' &&
        item.latest_run != null &&
        !TERMINAL_TASK_STATUSES.has(item.latest_run.status),
      ) ? 1800 : false,
  });
  const historyTasks = (historyQuery.data?.items ?? []).filter((item) => item.task_mode === 'BUSINESS_ASSEMBLY');
  const readyDocuments = useMemo(
    () => documents.filter((row) => row.status === 'ACTIVE' && row.parse_status === 'READY' && row.active_version_id != null),
    [documents],
  );

  const createBaseMutation = useMutation({
    mutationFn: () => knowledgeApi.createBase(currentProjectId!),
    onSuccess: async () => {
      message.success('项目知识库已创建');
      await queryClient.invalidateQueries({ queryKey: ['project', currentProjectId, 'knowledge-bases'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '创建知识库失败')),
  });
  const uploadMutation = useMutation({
    mutationFn: (input: UploadFormValues & { file: File; document_id?: number }) => knowledgeApi.upload(base!.id, input),
    onSuccess: async () => {
      message.success('文档已接收，正在后台解析');
      setUploadOpen(false);
      setUploadFile(null);
      setUploadDocumentId(undefined);
      uploadForm.resetFields();
      await queryClient.invalidateQueries({ queryKey: ['project', currentProjectId, 'knowledge-documents'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '上传文档失败')),
  });
  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => knowledgeApi.setEnabled(id, enabled),
    onSuccess: async () => {
      message.success('文档状态已更新');
      await queryClient.invalidateQueries({ queryKey: ['project', currentProjectId, 'knowledge-documents'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '更新文档状态失败')),
  });
  const deleteMutation = useMutation({
    mutationFn: (documentId: number) => knowledgeApi.remove(documentId),
    onSuccess: async () => {
      message.success('文档及其可检索正文已删除');
      await queryClient.invalidateQueries({ queryKey: ['project', currentProjectId, 'knowledge-documents'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '删除文档失败')),
  });
  const retryMutation = useMutation({
    mutationFn: (versionId: number) => knowledgeApi.retry(versionId),
    onSuccess: async () => {
      message.success('解析任务已重新排队');
      await queryClient.invalidateQueries({ queryKey: ['project', currentProjectId, 'knowledge-documents'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '重试解析失败')),
  });
  const createAssemblyMutation = useMutation({
    mutationFn: (goal: string) => businessAssemblyApi.createTask(currentProjectId!, {
      title: `业务组装：${goal.slice(0, 60)}`,
      goal,
      document_version_ids: assemblyVersionIds,
      request_key: `business-assembly-${currentProjectId}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    }),
    onSuccess: (task) => {
      setAssemblyTask(task);
      setAssemblyOpen(false);
      message.success('组装任务已进入后台队列');
      void queryClient.invalidateQueries({ queryKey: ['business-assembly-history', currentProjectId] });
    },
    onError: (error) => message.error(getErrorMessage(error, '提交业务组装失败')),
  });
  const taskQuery = useQuery({
    queryKey: ['business-assembly-task', assemblyTask?.id],
    queryFn: () => tasksApi.get(assemblyTask!.id),
    enabled: assemblyTask != null,
    refetchInterval: (query) => {
      const status = query.state.data?.latest_run?.status;
      return status && !TERMINAL_TASK_STATUSES.has(status) ? 1500 : false;
    },
  });
  const task = taskQuery.data ?? assemblyTask;
  const run = task?.latest_run ?? null;
  const draftQuery = useQuery({
    queryKey: ['business-assembly-draft', run?.id],
    queryFn: () => businessAssemblyApi.draftForRun(run!.id),
    enabled: run?.status === 'SUCCEEDED' || run?.status === 'SUCCEEDED_WITH_ISSUES',
    retry: false,
  });
  const draft = draftQuery.data;

  useEffect(() => {
    if (draft) {
      setDraftJson(JSON.stringify(draft.content, null, 2));
      setSelectedFlowIndexes(draft.content.flows.map((_, index) => index));
      setApplyKey('');
      setDraftOpen(true);
    }
  }, [draft?.id, draft?.current_revision]);

  const updateDraftMutation = useMutation({
    mutationFn: (content: BusinessAssemblyDraftContent) => businessAssemblyApi.updateDraft(draft!.id, {
      expected_revision: draft!.current_revision,
      content,
    }),
    onSuccess: async (updated) => {
      message.success(`草稿修订 ${updated.current_revision} 已保存`);
      setApplyKey('');
      queryClient.setQueryData(['business-assembly-draft', run?.id], updated);
      setDraftJson(JSON.stringify(updated.content, null, 2));
    },
    onError: (error) => message.error(getErrorMessage(error, '保存草稿失败')),
  });
  const validateDraftMutation = useMutation({
    mutationFn: () => businessAssemblyApi.validateDraft(draft!.id, draft!.current_revision),
    onSuccess: async () => {
      message.success('草稿校验完成');
      await queryClient.invalidateQueries({ queryKey: ['business-assembly-draft', run?.id] });
    },
    onError: (error) => message.error(getErrorMessage(error, '草稿校验失败')),
  });
  const applyDraftMutation = useMutation({
    mutationFn: (idempotencyKey: string) => businessAssemblyApi.applyDraft(draft!.id, {
      revision: draft!.current_revision,
      flow_indexes: selectedFlowIndexes,
      idempotency_key: idempotencyKey,
    }),
    onSuccess: async (result) => {
      setApplyKey('');
      message.success(`已保存 ${result.flow_ids.length} 个业务流程到业务管理`);
      setDraftOpen(false);
      await queryClient.invalidateQueries({ queryKey: ['project', currentProjectId] });
      navigate('/console/business-management');
    },
    onError: (error) => message.error(getErrorMessage(error, '保存业务流程失败')),
  });

  const versionsQuery = useQuery({
    queryKey: ['knowledge-document-versions', previewDocument?.id],
    queryFn: () => knowledgeApi.versions(previewDocument!.id),
    enabled: previewDocument != null,
  });
  const selectedPreviewVersionId = previewVersionId ?? previewDocument?.active_version_id ?? versionsQuery.data?.items[0]?.id;
  const chunksQuery = useQuery({
    queryKey: ['knowledge-document-chunks', selectedPreviewVersionId, previewPage],
    queryFn: () => knowledgeApi.chunks(selectedPreviewVersionId!, previewPage),
    enabled: selectedPreviewVersionId != null,
  });

  if (currentProjectId == null) {
    return <PageContainer><Empty description="请先在顶部选择项目，再维护项目知识文档。" /></PageContainer>;
  }
  if (baseQuery.isPending) return <LoadingState tip="正在读取项目知识库…" />;
  if (baseQuery.isError) return <PageContainer><ErrorState error={baseQuery.error} onRetry={baseQuery.refetch} /></PageContainer>;

  const openUpload = (document?: KnowledgeDocument) => {
    setUploadDocumentId(document?.id);
    setUploadFile(null);
    uploadForm.setFieldsValue({
      title: document?.title ?? '',
      category: document?.category ?? 'REQUIREMENTS',
    });
    setUploadOpen(true);
  };
  const submitUpload = (values: UploadFormValues) => {
    if (!uploadFile) {
      message.warning('请先选择文档文件');
      return;
    }
    uploadMutation.mutate({ ...values, file: uploadFile, document_id: uploadDocumentId });
  };
  const statusTag = (status: string | null) => {
    if (status === 'READY') return <Tag color="success">解析完成</Tag>;
    if (status === 'PENDING' || status === 'PROCESSING') return <Tag color="processing">{status === 'PENDING' ? '等待解析' : '解析中'}</Tag>;
    if (status === 'FAILED') return <Tag color="error">解析失败</Tag>;
    return <Tag>{status ?? '未解析'}</Tag>;
  };
  const saveDraftJson = () => {
    try {
      const parsed = JSON.parse(draftJson) as BusinessAssemblyDraftContent;
      updateDraftMutation.mutate(parsed);
    } catch {
      message.error('草稿 JSON 格式无效，请修正后再保存');
    }
  };
  const openDraft = async () => {
    if (!run?.id) return;
    await draftQuery.refetch();
    setDraftOpen(true);
  };

  return (
    <PageContainer>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, marginBottom: 20 }}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>项目知识库</Typography.Title>
          <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            维护需求、流程、接口和字段资料。Agent 只生成可编辑草稿，保存后仍由业务管理页面继续维护。
          </Typography.Paragraph>
        </div>
        <Space wrap>
          <Button icon={<RobotOutlined />} type="primary" disabled={!readyDocuments.length} onClick={() => {
            setAssemblyVersionIds(readyDocuments.map((doc) => doc.active_version_id!));
            setAssemblyOpen(true);
          }}>组装业务</Button>
          <Button icon={<FileAddOutlined />} disabled={!base} onClick={() => openUpload()}>上传文档</Button>
          {!base && <Button type="primary" loading={createBaseMutation.isPending} onClick={() => createBaseMutation.mutate()}>创建项目知识库</Button>}
        </Space>
      </div>

      {!base ? (
        <Card><Empty description="当前项目还没有知识库。创建后即可上传业务资料。" /></Card>
      ) : (
        <Card title={base.name} extra={<Typography.Text type="secondary">文档内容仅在当前项目成员授权范围内使用</Typography.Text>}>
          {documentsQuery.isPending ? <LoadingState tip="正在读取文档…" /> : null}
          {documentsQuery.isError ? <ErrorState error={documentsQuery.error} onRetry={documentsQuery.refetch} /> : null}
          {!documentsQuery.isPending && !documentsQuery.isError && documents.length === 0 ? (
            <Empty description="还没有上传文档" />
          ) : null}
          {!documentsQuery.isPending && !documentsQuery.isError && documents.length > 0 ? (
            <Table<KnowledgeDocument>
              rowKey="id"
              dataSource={documents}
              pagination={{ pageSize: 10, showSizeChanger: false }}
              columns={[
                { title: '文档', dataIndex: 'title', render: (_: string, row) => <Space direction="vertical" size={0}><Typography.Text strong>{row.title}</Typography.Text><Typography.Text type="secondary">{row.file_name ?? '文件信息不可用'}</Typography.Text></Space> },
                { title: '分类', dataIndex: 'category', render: (value: KnowledgeCategory) => CATEGORY_LABEL[value] ?? value },
                { title: '版本', dataIndex: 'active_version_number', width: 90, render: (value: number | null) => value ? `v${value}` : '—' },
                { title: '状态', dataIndex: 'parse_status', width: 150, render: (_: string, row) => <Space direction="vertical" size={0}>{statusTag(row.parse_status)}{row.latest_version_number != null && row.latest_parse_status !== row.parse_status && <Typography.Text type={row.latest_parse_status === 'FAILED' ? 'danger' : 'secondary'}>最新 v{row.latest_version_number}：{row.latest_parse_status ?? '未解析'}</Typography.Text>}{row.status === 'DISABLED' && <Tag>已停用</Tag>}</Space> },
                { title: '大小', dataIndex: 'file_size', width: 110, render: (value: number | null) => value == null ? '—' : `${(value / 1024).toFixed(0)} KB` },
                { title: '解析提示', dataIndex: 'latest_parse_error', render: (value: string | null) => value ? <Typography.Text type="danger">{value}</Typography.Text> : '—' },
                { title: '操作', key: 'actions', width: 270, render: (_: unknown, row) => (
                  <Space wrap size="small">
                    <Button size="small" icon={<EyeOutlined />} onClick={() => { setPreviewPage(1); setPreviewVersionId(row.active_version_id ?? undefined); setPreviewDocument(row); }}>预览依据</Button>
                    <Button size="small" icon={<CloudUploadOutlined />} onClick={() => openUpload(row)}>新版本</Button>
                    {row.latest_parse_status === 'FAILED' && row.latest_version_id != null && (
                      <Button size="small" icon={<ReloadOutlined />} loading={retryMutation.isPending} onClick={() => retryMutation.mutate(row.latest_version_id!)}>重试最新版本</Button>
                    )}
                    {row.status !== 'DELETED' && <Button size="small" onClick={() => toggleMutation.mutate({ id: row.id, enabled: row.status !== 'ACTIVE' })}>{row.status === 'ACTIVE' ? '停用' : '启用'}</Button>}
                    <Popconfirm title="删除文档？" description="原文件和可检索正文会清理，历史草稿保留依据状态。" onConfirm={() => deleteMutation.mutate(row.id)}>
                      <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                    </Popconfirm>
                  </Space>
                ) },
              ]}
            />
          ) : null}
        </Card>
      )}

      {task && (
        <Card
          style={{ marginTop: 16 }}
          title={<Space><RobotOutlined />业务组装任务：{task.title}</Space>}
          extra={<Button size="small" onClick={() => setAssemblyTask(null)}>收起任务</Button>}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space wrap>
              {statusTag(run?.status === 'SUCCEEDED' ? 'READY' : run?.status ?? 'QUEUED')}
              <Tag>{run?.stage ?? '等待后台 Worker'}</Tag>
              {run?.status === 'FAILED' && <Typography.Text type="danger">{run.error_message ?? '任务失败'}</Typography.Text>}
            </Space>
            {(run?.status === 'SUCCEEDED' || run?.status === 'SUCCEEDED_WITH_ISSUES') && (
              <Button type="primary" onClick={openDraft} loading={draftQuery.isFetching}>打开可编辑草稿</Button>
            )}
            {run?.status && !TERMINAL_TASK_STATUSES.has(run.status) && <Typography.Text type="secondary">任务会在后台继续运行，稍后可重新打开草稿。</Typography.Text>}
          </Space>
        </Card>
      )}

      <Card
        style={{ marginTop: 16 }}
        title="最近的业务组装任务"
        extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => historyQuery.refetch()} loading={historyQuery.isFetching}>刷新</Button>}
      >
        {historyQuery.isError && <ErrorState error={historyQuery.error} onRetry={historyQuery.refetch} />}
        {!historyQuery.isError && historyTasks.length === 0 && <Empty description="当前项目还没有业务组装任务" />}
        {historyTasks.length > 0 && (
          <Table<Task>
            rowKey="id"
            size="small"
            dataSource={historyTasks}
            pagination={{ pageSize: 5, showSizeChanger: false }}
            columns={[
              { title: '任务', dataIndex: 'title', render: (_: string, row) => <Space direction="vertical" size={0}><Typography.Text strong>{row.title}</Typography.Text><Typography.Text type="secondary" ellipsis={{ tooltip: row.goal }}>{row.goal}</Typography.Text></Space> },
              { title: '状态', dataIndex: 'latest_run', width: 150, render: (_: Task['latest_run']) => {
                const status = _?.status;
                return <Tag color={status === 'SUCCEEDED' ? 'success' : status === 'FAILED' || status === 'CANCELLED' ? 'error' : status === 'SUCCEEDED_WITH_ISSUES' ? 'warning' : 'processing'}>{status ?? '尚未启动'}</Tag>;
              } },
              { title: '阶段', dataIndex: 'latest_run', width: 160, render: (_: Task['latest_run']) => _?.stage ?? '—' },
              { title: '更新时间', dataIndex: 'updated_at', width: 180, render: (value: string) => new Date(value).toLocaleString() },
              { title: '操作', key: 'actions', width: 120, render: (_: unknown, row) => <Button size="small" onClick={() => setAssemblyTask(row)}>查看任务</Button> },
            ]}
          />
        )}
      </Card>

      <Modal
        title={uploadDocumentId ? '上传新文档版本' : '上传项目知识文档'}
        open={uploadOpen}
        onCancel={() => { setUploadOpen(false); setUploadFile(null); }}
        onOk={() => uploadForm.submit()}
        confirmLoading={uploadMutation.isPending}
        destroyOnClose
      >
        <Form<UploadFormValues> form={uploadForm} layout="vertical" initialValues={{ category: 'REQUIREMENTS' }} onFinish={submitUpload}>
          <Form.Item name="title" label="文档名称" rules={[{ required: true, whitespace: true, message: '请输入文档名称' }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="category" label="文档分类" rules={[{ required: true }]}><Select options={CATEGORY_OPTIONS} /></Form.Item>
          <Form.Item label="文件" required extra="支持 Markdown、TXT、DOCX、文本型 PDF、JSON、YAML，最大 2 MiB。">
            <Upload
              maxCount={1}
              accept=".md,.markdown,.txt,.docx,.pdf,.json,.yaml,.yml"
              beforeUpload={() => false}
              fileList={uploadFile ? [{ uid: uploadFile.name, name: uploadFile.name, status: 'done' } as UploadFile] : []}
              onChange={(info) => setUploadFile(info.file.originFileObj ?? null)}
              onRemove={() => { setUploadFile(null); return true; }}
            ><Button icon={<CloudUploadOutlined />}>选择文档</Button></Upload>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="基于项目文档组装业务"
        open={assemblyOpen}
        onCancel={() => setAssemblyOpen(false)}
        onOk={() => {
          const goal = (document.getElementById('business-assembly-goal') as HTMLTextAreaElement | null)?.value?.trim() ?? '';
          if (goal.length < 3) {
            message.warning('请描述希望组装的业务目标');
            return;
          }
          if (!assemblyVersionIds.length) {
            message.warning('至少选择一个已解析文档版本');
            return;
          }
          createAssemblyMutation.mutate(goal);
        }}
        confirmLoading={createAssemblyMutation.isPending}
        okText="提交组装任务"
      >
        <Typography.Paragraph type="secondary">文档内容会作为资料输入。Agent 不会创建测试、执行接口或自动绑定未确认的接口。</Typography.Paragraph>
        <Typography.Text strong>选择文档</Typography.Text>
        <Checkbox.Group
          style={{ display: 'flex', flexDirection: 'column', gap: 8, margin: '10px 0 18px' }}
          value={assemblyVersionIds}
          options={readyDocuments.map((row) => ({ value: row.active_version_id!, label: `${row.title} · v${row.active_version_number}` }))}
          onChange={(values) => setAssemblyVersionIds(values.map(Number))}
        />
        <Typography.Text strong>组装目标</Typography.Text>
        <Input.TextArea id="business-assembly-goal" rows={4} placeholder="例如：根据订单需求组装下单及取消流程" maxLength={8000} />
      </Modal>

      <Drawer title={previewDocument ? `文档依据：${previewDocument.title}` : '文档依据'} open={previewDocument != null} width={760} onClose={() => setPreviewDocument(null)}>
        {versionsQuery.isPending ? <Spin /> : null}
        {previewDocument && <Descriptions size="small" column={2} style={{ marginBottom: 16 }} items={[
          { key: 'category', label: '分类', children: CATEGORY_LABEL[previewDocument.category] },
          { key: 'status', label: '状态', children: statusTag(previewDocument.parse_status) },
          { key: 'version', label: '当前版本', children: previewDocument.active_version_number ? `v${previewDocument.active_version_number}` : '无可用版本' },
        ]} />}
        {!!versionsQuery.data?.items.length && (
          <Card size="small" title="版本记录" style={{ marginBottom: 16 }}>
            <Select
              style={{ width: '100%' }}
              value={selectedPreviewVersionId}
              onChange={(value: number) => { setPreviewPage(1); setPreviewVersionId(value); }}
              options={versionsQuery.data.items.map((version) => ({
                value: version.id,
                label: `v${version.version_number} · ${version.file_name} · ${version.parse_status}${version.is_active ? ' · 当前使用' : ''}`,
              }))}
            />
          </Card>
        )}
        {chunksQuery.isPending ? <LoadingState tip="正在读取正文依据…" /> : null}
        {chunksQuery.isError ? <ErrorState error={chunksQuery.error} onRetry={chunksQuery.refetch} /> : null}
        {chunksQuery.data?.items.length === 0 && <Empty description="当前版本尚未生成可预览的正文块" />}
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {chunksQuery.data?.items.map((chunk) => (
            <Card key={chunk.id} size="small" title={<Space><Tag>{chunk.locator}</Tag>{chunk.heading_path && <Typography.Text>{chunk.heading_path}</Typography.Text>}</Space>}>
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{chunk.content}</Typography.Paragraph>
            </Card>
          ))}
        </Space>
        {(chunksQuery.data?.total ?? 0) > 100 && (
          <Pagination
            current={previewPage}
            pageSize={100}
            total={chunksQuery.data?.total ?? 0}
            showSizeChanger={false}
            onChange={setPreviewPage}
            style={{ marginTop: 16, textAlign: 'right' }}
          />
        )}
      </Drawer>

      <Drawer
        title={draft ? `业务草稿 · 修订 ${draft.current_revision}` : '业务草稿'}
        open={draftOpen}
        width="min(1100px, 95vw)"
        onClose={() => setDraftOpen(false)}
        extra={draft && <Space>
          <Button onClick={() => validateDraftMutation.mutate()} loading={validateDraftMutation.isPending}>重新校验</Button>
          <Button onClick={saveDraftJson} loading={updateDraftMutation.isPending}>保存修订</Button>
          <Button type="primary" disabled={!draft.validation.can_save || selectedFlowIndexes.length === 0} loading={applyDraftMutation.isPending} onClick={() => {
            const idempotencyKey = applyKey || `business-assembly-apply-${draft.id}-${draft.current_revision}-${Date.now()}`;
            setApplyKey(idempotencyKey);
            applyDraftMutation.mutate(idempotencyKey);
          }}>保存到业务管理</Button>
        </Space>}
      >
        {draftQuery.isPending && <LoadingState tip="正在加载业务草稿…" />}
        {draftQuery.isError && <ErrorState error={draftQuery.error} onRetry={draftQuery.refetch} />}
        {draft && (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Card size="small" title="草稿状态">
              <Space wrap>
                <Tag color={draft.validation.can_save ? 'success' : 'error'}>{draft.validation.can_save ? '可保存' : '需修正'}</Tag>
                <Tag color={draft.validation.can_execute ? 'success' : 'default'}>{draft.validation.can_execute ? '可执行' : '未达到执行条件'}</Tag>
                <Typography.Text>依据版本：{draft.source_version_ids.join(', ')}</Typography.Text>
              </Space>
              {!!draft.validation.errors.length && <ul>{draft.validation.errors.map((item, index) => <li key={`error-${index}`}><Typography.Text type="danger">{item}</Typography.Text></li>)}</ul>}
              {!!draft.validation.warnings.length && <ul>{draft.validation.warnings.map((item, index) => <li key={`warning-${index}`}><Typography.Text type="warning">{item}</Typography.Text></li>)}</ul>}
              {!!draft.content.issues.length && <div style={{ marginTop: 8 }}>{draft.content.issues.map((item, index) => <Tag key={`issue-${index}`} color="warning">{item}</Tag>)}</div>}
              {!!draft.content.unsupported_elements.length && <div style={{ marginTop: 8 }}><Typography.Text strong>待人工处理：</Typography.Text>{draft.content.unsupported_elements.map((item, index) => <Tag key={`unsupported-${index}`}>{item}</Tag>)}</div>}
              <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0' }}>
                文档覆盖 {String(draft.content.coverage.selected_chunk_count ?? 0)} 个正文块；接口候选不会自动绑定，业务保存默认创建 DRAFT 流程。
              </Typography.Paragraph>
            </Card>
            <Card size="small" title="选择要保存的流程">
                  <Checkbox.Group value={selectedFlowIndexes} onChange={(values) => { setApplyKey(''); setSelectedFlowIndexes(values.map(Number)); }} style={{ width: '100%' }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  {draft.content.flows.map((flow, index) => (
                    <Checkbox key={`${flow.name}-${index}`} value={index}>
                      {flow.name} · {flow.actions.length} 个顺序动作
                    </Checkbox>
                  ))}
                </Space>
              </Checkbox.Group>
            </Card>
            <Card size="small" title="业务预览">
              <Typography.Title level={5}>{draft.content.domain_name}</Typography.Title>
              <Typography.Paragraph type="secondary">{draft.content.domain_description}</Typography.Paragraph>
              {draft.content.flows.map((flow, flowIndex) => (
                <Card key={`${flow.name}-preview-${flowIndex}`} type="inner" title={flow.name} style={{ marginBottom: 12 }}>
                  <Typography.Paragraph>{flow.description}</Typography.Paragraph>
                  <ol>
                    {flow.actions.map((action) => (
                      <li key={`${flowIndex}-${action.action_key}`} style={{ marginBottom: 12 }}>
                        <Typography.Text strong>{action.name}</Typography.Text>
                        <Typography.Text type="secondary"> · {action.action_key} · 顺序动作</Typography.Text>
                        {action.description && <div>{action.description}</div>}
                        {action.api_candidate && <div><Tag color="blue">接口候选 #{action.api_candidate.api_id} · {action.api_candidate.confidence}</Tag>{action.api_candidate.reason}</div>}
                        {action.evidence.map((evidence, evidenceIndex) => (
                          <div key={`${action.action_key}-evidence-${evidenceIndex}`}><Tag>{evidence.locator}</Tag><Typography.Text type="secondary">“{evidence.quote}”</Typography.Text></div>
                        ))}
                      </li>
                    ))}
                  </ol>
                </Card>
              ))}
            </Card>
            <Collapse items={[{
              key: 'json',
              label: '高级编辑：完整草稿 JSON',
              children: <>
                <Typography.Paragraph type="secondary">修改后保存会生成新修订，旧修订仍保留。保存后需要重新校验。</Typography.Paragraph>
                <Input.TextArea value={draftJson} onChange={(event) => setDraftJson(event.target.value)} autoSize={{ minRows: 18, maxRows: 40 }} spellCheck={false} />
              </>,
            }]} />
          </Space>
        )}
      </Drawer>
    </PageContainer>
  );
}
