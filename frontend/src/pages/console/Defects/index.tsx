import { collectPages } from '@/shared/api/pagination';
// 缺陷管理（用户视角）。
// 本模块导出 ConsoleDefectsPage，由路由 /console/defects 挂载。
//
// 功能：
//   - 列表：分页展示当前用户可见项目下的缺陷，支持项目/状态/严重度/关键字过滤；
//   - 新建：弹窗收集标题、严重度、状态、复现步骤、环境、处理人；
//   - 编辑：与新建共用同一弹窗，处理人可为空表示「未分配」；
//   - 删除：Modal.confirm 二次确认。
//
// 权限（服务端为准，前端隐藏只是辅助）：
//   - 读 = 项目可见（viewer+）；
//   - 写 = 项目成员（member+），viewer 无法新建/编辑/删除；
//   - 跨项目越权按 404 返回，前端不会展示；
//   - 处理人必须是项目成员。
//
// 未接入（明确标记，不虚报）：回归关联、趋势看板、修复时长统计。
import {
  App,
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { ExclamationCircleOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { bugsApi } from '@/features/defects/api/defects';
import type { BugCreate, BugUpdate } from '@/features/defects/contracts';
import { projectsApi } from '@/features/projects/api/projects';
import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { ResourceTable, type PaginationState } from '@/shared/ui/ResourceTable';
import { getErrorMessage } from '@/shared/api/client';
import { DefectOrigins } from '@/widgets/execution-detail/DefectOrigins';
import { tasksApi } from '@/features/tasks/api/tasks';
import { clearTaskCreateUncertainty, readTaskCreateUncertainty, rememberTaskCreateUncertainty, type TaskCreateUncertainty } from '@/features/tasks/createUncertainty';
import { isAxiosError } from 'axios';
import type { Bug, BugSeverity, BugStatus } from '@/features/defects/contracts';
import type { BatchLifecycleReceipt } from '@/features/data-lifecycle/api';
import type { Paginated } from '@/shared/api/contracts';


// 后端约定的状态与严重度常量；与 BugStatus/BugSeverity 类型保持同步。
const BUG_STATUSES: BugStatus[] = ['待确认', '处理中', '已修复', '已关闭', '已拒绝'];
const SEVERITY_OPTIONS: { label: string; value: BugSeverity }[] = [
  { label: '1 低', value: 1 },
  { label: '2 中', value: 2 },
  { label: '3 高', value: 3 },
  { label: '4 严重', value: 4 },
];
const STATUS_COLOR: Record<BugStatus, string> = {
  待确认: 'orange',
  处理中: 'blue',
  已修复: 'cyan',
  已关闭: 'default',
  已拒绝: 'red',
};
const SEVERITY_COLOR: Record<BugSeverity, string> = {
  1: 'gold',
  2: 'orange',
  3: 'volcano',
  4: 'red',
};

// 新建/编辑弹窗的表单值。severity 与 status 都有默认值，减少空态。
interface BugFormValues {
  title: string;
  description?: string;
  severity: BugSeverity;
  status: BugStatus;
  steps_to_reproduce?: string;
  environment?: string;
  assignee_id?: number | null;
}

/**
 * 控制台缺陷列表页。
 *
 * 会发请求：
 *   - useQuery ['bugs', query] 拉缺陷列表；
 *   - useQuery ['projects', { page: 1, page_size: 100 }] 拉可见项目列表（供过滤与新建弹窗下拉）；
 *   - useQuery ['bugs/projects', projectId] 拉某项目的成员列表（供新建/编辑弹窗「处理人」下拉）。
 * mutation：create / update / remove，成功后统一 invalidate ['bugs']。
 * 失败呈现：列表失败整页 ErrorState；mutation 失败 message.error 折叠展示。
 */
export function ConsoleDefectsPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedBugId = Number(searchParams.get('bugId'));
  const bugDetail = useQuery({ queryKey: ['bug-detail', requestedBugId], queryFn: () => bugsApi.get(requestedBugId), enabled: Number.isSafeInteger(requestedBugId) && requestedBugId > 0 });
  // antd Form 实例：必须在使用 useForm 的组件内创建；
  // 每次弹窗打开用 key 强制重建以重置值，无需手工 resetFields。
  const [bugForm] = Form.useForm<BugFormValues>();

  // 分页：默认第一页、每页 10 条
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 10,
  });
  // 过滤：project_id / status / severity / keyword；空串归一为 undefined
  const [projectId, setProjectId] = useState<number | undefined>(undefined);
  const [status, setStatus] = useState<BugStatus | undefined>(undefined);
  const [severity, setSeverity] = useState<BugSeverity | undefined>(undefined);
  const [keyword, setKeyword] = useState('');
  const [selectedBugIds, setSelectedBugIds] = useState<number[]>([]);

  // 弹窗状态：null 表示关闭；mode='create' 新建，mode='edit' 编辑已有 bug
  const [modalState, setModalState] = useState<
    { mode: 'create' } | { mode: 'edit'; bug: Bug } | null
  >(null);
  // 编辑时把 bug 值回填进 form；用 key 触发 antd Form 的 resetFields
  const [formKey, setFormKey] = useState(0);

  // 拼装查询参数
  const query = useMemo(
    () => ({
      page: pagination.page,
      page_size: pagination.page_size,
      project_id: projectId,
      status,
      severity,
      keyword: keyword || undefined,
    }),
    [pagination, projectId, status, severity, keyword],
  );

  const listQuery = useQuery<Paginated<Bug>>({
    queryKey: ['bugs', query],
    queryFn: () => bugsApi.list(query),
  });

  // 项目下拉数据源：拉当前用户全部可见项目（page_size=100 兜底）
  const projectsQuery = useQuery({
    queryKey: ['projects', { page: 1, page_size: 100 }],
    queryFn: () =>
      collectPages((page) => projectsApi.list({ page, page_size: 100 })),
  });

  // 弹窗内需要展示「某项目的成员列表」作为「处理人」下拉；
  // 只在弹窗打开并选定 project_id 时才请求，避免无谓流量。
  const modalProjectId =
    modalState?.mode === 'edit'
      ? modalState.bug.project_id
      : projectId;
  const membersQuery = useQuery({
    queryKey: ['project', modalProjectId, 'members'],
    queryFn: () =>
      collectPages((page) => projectsApi.listMembers(modalProjectId!, { page, page_size: 200 })),
    enabled: modalState != null && modalProjectId != null,
  });

  // 建缺陷
  const createMutation = useMutation({
    mutationFn: (body: BugCreate) => bugsApi.create(body),
    onSuccess: () => {
      message.success('缺陷已创建');
      queryClient.invalidateQueries({ queryKey: ['bugs'] });
      setModalState(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  // 改缺陷
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: BugUpdate }) =>
      bugsApi.update(id, body),
    onSuccess: () => {
      message.success('缺陷已更新');
      queryClient.invalidateQueries({ queryKey: ['bugs'] });
      setModalState(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  // 删缺陷
  const removeMutation = useMutation({
    mutationFn: (id: number) => bugsApi.remove(id),
    onSuccess: () => {
      message.success('缺陷已删除');
      queryClient.invalidateQueries({ queryKey: ['bugs'] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const batchRemoveMutation = useMutation({
    mutationFn: (ids: number[]) => bugsApi.removeMany(projectId!, ids),
    onSuccess: (receipt: BatchLifecycleReceipt) => {
      setSelectedBugIds([]);
      queryClient.invalidateQueries({ queryKey: ['bugs'] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
      if (receipt.failed === 0) message.success(`已删除 ${receipt.succeeded} 个缺陷，记录已移入回收站`);
      else {
        message.warning(`已删除 ${receipt.succeeded} 个缺陷，${receipt.failed} 个未删除`);
        modal.info({
          title: '批量删除结果',
          width: 620,
          content: <Space direction="vertical" style={{ width: '100%' }}>
            {receipt.items.filter((item) => !item.succeeded).map((item) => (
              <Alert key={item.id} type="error" showIcon message={`缺陷 #${item.id}`} description={item.error ?? '删除失败'} />
            ))}
          </Space>,
        });
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '批量删除失败')),
  });

  const confirmDelete = (bug: Bug) => {
    modal.confirm({
      title: '确认删除该缺陷？',
      icon: <ExclamationCircleOutlined />,
      content: `「${bug.title}」将移入项目回收站，可由授权成员恢复。`,
      okText: '删除并移入回收站',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => removeMutation.mutateAsync(bug.id),
    });
  };

  const openCreate = () => {
    setFormKey((k) => k + 1);
    setModalState({ mode: 'create' });
  };
  const openEdit = (bug: Bug) => {
    setFormKey((k) => k + 1);
    setModalState({ mode: 'edit', bug });
  };

  const projectOptions = (projectsQuery.data?.items ?? []).map((p) => ({
    label: p.name,
    value: p.id,
  }));
  const memberOptions = (membersQuery.data?.items ?? []).map((m) => {
    const item = m as { user_id: number; username?: string };
    return { label: item.username ?? `用户 ${item.user_id}`, value: item.user_id };
  });

  // 加载中 / 失败：整页占位，不渲染空表格
  if (listQuery.isPending) return <LoadingState />;
  if (listQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />
      </PageContainer>
    );

  const data = listQuery.data;

  return (
    <PageContainer>
      <Space wrap style={{ marginBottom: 16 }} align="center">
        <Input.Search
          placeholder="按标题或描述搜索"
          allowClear
          enterButton
          style={{ maxWidth: 260 }}
          onSearch={(v) => {
            setKeyword(v);
            setPagination((p) => ({ ...p, page: 1 }));
          }}
        />
        <Select
          placeholder="全部项目"
          allowClear
          showSearch
          optionFilterProp="label"
          options={projectOptions}
          value={projectId}
          onChange={(v) => {
            setProjectId(v);
            setSelectedBugIds([]);
            setPagination((p) => ({ ...p, page: 1 }));
          }}
          style={{ minWidth: 180 }}
        />
        <Select
          placeholder="全部状态"
          allowClear
          options={BUG_STATUSES.map((s) => ({ label: s, value: s }))}
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPagination((p) => ({ ...p, page: 1 }));
          }}
          style={{ minWidth: 140 }}
        />
        <Select
          placeholder="全部严重度"
          allowClear
          options={SEVERITY_OPTIONS}
          value={severity}
          onChange={(v) => {
            setSeverity(v);
            setPagination((p) => ({ ...p, page: 1 }));
          }}
          style={{ minWidth: 140 }}
        />
        <Button type="primary" onClick={openCreate} loading={createMutation.isPending}>
          新建缺陷
        </Button>
      </Space>

      <Space style={{ marginBottom: 12 }} wrap>
        <Checkbox
          checked={data.items.length > 0 && data.items.every((bug) => selectedBugIds.includes(bug.id))}
          indeterminate={data.items.some((bug) => selectedBugIds.includes(bug.id)) && !data.items.every((bug) => selectedBugIds.includes(bug.id))}
          disabled={projectId == null}
          onChange={(event) => setSelectedBugIds(event.target.checked ? data.items.map((bug) => bug.id) : [])}
        >
          全选当前页（{data.items.length}）
        </Checkbox>
        <Button danger disabled={projectId == null || selectedBugIds.length === 0 || batchRemoveMutation.isPending}
          loading={batchRemoveMutation.isPending}
          onClick={() => modal.confirm({
            title: `删除选中的 ${selectedBugIds.length} 个缺陷？`,
            content: '删除会保留来源追溯关系并移入项目回收站；每个缺陷独立校验并返回处理结果。',
            okText: '删除并移入回收站', cancelText: '取消', okButtonProps: { danger: true },
            onOk: () => batchRemoveMutation.mutateAsync(selectedBugIds),
          })}>
          批量删除（{selectedBugIds.length}）
        </Button>
        {projectId == null && <Typography.Text type="secondary">请先选择项目，再批量删除缺陷。</Typography.Text>}
      </Space>

      <ResourceTable
        rowKey={(r) => r.id}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 70 },
          {
            title: '项目',
            dataIndex: 'project_name',
            render: (v: string | null) => v ?? '-',
          },
          { title: '标题', dataIndex: 'title' },
          {
            title: '严重度',
            dataIndex: 'severity',
            width: 90,
            render: (v: BugSeverity) => (
              <Tag color={SEVERITY_COLOR[v]}>{v}</Tag>
            ),
          },
          {
            title: '状态',
            dataIndex: 'status',
            width: 90,
            render: (v: BugStatus) => (
              <Tag color={STATUS_COLOR[v]}>{v}</Tag>
            ),
          },
          {
            title: '报告人',
            dataIndex: 'reporter_username',
            width: 120,
            render: (v: string | null) => v ?? '-',
          },
          {
            title: '处理人',
            dataIndex: 'assignee_username',
            width: 120,
            render: (v: string | null) =>
              v ? <Typography.Text>{v}</Typography.Text> : <Typography.Text type="secondary">未分配</Typography.Text>,
          },
          {
            title: '创建时间',
            dataIndex: 'created_at',
            width: 180,
            render: (v: string) => new Date(v).toLocaleString(),
          },
          {
            title: '操作',
            key: 'actions',
            width: 140,
            render: (_: unknown, row: Bug) => (
              <Space>
                <Button size="small" onClick={() => setSearchParams({ bugId: String(row.id) })}>详情</Button>
                <Button size="small" onClick={() => openEdit(row)}>
                  编辑
                </Button>
                <Button
                  size="small"
                  danger
                  disabled={removeMutation.isPending}
                  onClick={() => confirmDelete(row)}
                >
                  删除
                </Button>
              </Space>
            ),
          },
        ]}
        dataSource={data.items}
        loading={listQuery.isFetching}
        total={data.total}
        pagination={pagination}
        onPaginationChange={setPagination}
        rowSelection={{
          selectedRowKeys: selectedBugIds,
          preserveSelectedRowKeys: true,
          onChange: (keys) => setSelectedBugIds(keys.map(Number)),
          getCheckboxProps: (row) => ({ disabled: projectId == null || row.project_id !== projectId }),
        }}
      />

      <Modal title={bugDetail.data ? `缺陷 #${bugDetail.data.id}：${bugDetail.data.title}` : '缺陷详情'} open={Number.isSafeInteger(requestedBugId) && requestedBugId > 0} onCancel={() => setSearchParams({})} footer={null} destroyOnClose>
        {bugDetail.isLoading ? <LoadingState /> : bugDetail.isError || !bugDetail.data ? <ErrorState error={bugDetail.error} onRetry={bugDetail.refetch} /> : <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text>{bugDetail.data.description || '暂无描述'}</Typography.Text>
          <Typography.Text strong>关联来源</Typography.Text>
          <DefectOrigins bugId={bugDetail.data.id} />
          <BugVerificationPanel bug={bugDetail.data} />
        </Space>}
      </Modal>

      {/* 新建 / 编辑弹窗 */}
      <Modal
        title={
          modalState?.mode === 'edit'
            ? `编辑缺陷 #${modalState.bug.id}`
            : '新建缺陷'
        }
        open={modalState != null}
        onCancel={() => setModalState(null)}
        onOk={async () => {
          if (modalState == null) return;
          const values = await bugForm.validateFields();
          if (modalState.mode === 'create') {
            // 新建：project_id 从顶部过滤器取；若用户未选，用第一条可见项目。
            const projectIdForCreate = projectId ?? projectOptions[0]?.value;
            if (projectIdForCreate == null) {
              message.error('请先选择一个项目，或先创建项目');
              return;
            }
            await createMutation.mutateAsync({
              ...values,
              project_id: projectIdForCreate,
            });
          } else {
            await updateMutation.mutateAsync({
              id: modalState.bug.id,
              body: values,
            });
          }
        }}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={620}
      >
        <Form<BugFormValues>
          key={formKey}
          form={bugForm}
          layout="vertical"
          initialValues={
            modalState?.mode === 'edit'
              ? {
                  title: modalState.bug.title,
                  description: modalState.bug.description ?? undefined,
                  severity: modalState.bug.severity,
                  status: modalState.bug.status,
                  steps_to_reproduce: modalState.bug.steps_to_reproduce ?? undefined,
                  environment: modalState.bug.environment ?? undefined,
                  assignee_id: modalState.bug.assignee_id ?? undefined,
                }
              : { severity: 2, status: '待确认' }
          }
        >
          <Form.Item
            name="title"
            label="标题"
            rules={[{ required: true, message: '请输入缺陷标题' }]}
          >
            <Input placeholder="一句话描述问题" maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="详细描述问题现象" rows={3} maxLength={1000} />
          </Form.Item>
          <div className="form-field-row">
            <Form.Item
              name="severity"
              label="严重度"
              style={{ flex: 1, margin: 0 }}
              rules={[{ required: true, message: '请选择严重度' }]}
            >
              <Select options={SEVERITY_OPTIONS} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="status"
              label="状态"
              style={{ flex: 1, margin: 0 }}
              rules={[{ required: true, message: '请选择状态' }]}
            >
              <Select
                options={BUG_STATUSES.map((s) => ({ label: s, value: s }))}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </div>
          <Form.Item name="environment" label="环境">
            <Input placeholder="如 dev / test / prod" maxLength={200} />
          </Form.Item>
          <Form.Item
            name="steps_to_reproduce"
            label="复现步骤"
            tooltip="多行文本，编号或换行均可"
          >
            <Input.TextArea rows={4} placeholder={'1. 打开登录页\n2. 输入错误密码\n3. 点击登录'} />
          </Form.Item>
          <Form.Item
            name="assignee_id"
            label="处理人"
            tooltip="必须是项目成员；留空表示未分配"
          >
            <Select
              placeholder="未分配"
              allowClear
              showSearch
              optionFilterProp="label"
              options={memberOptions}
              loading={membersQuery.isPending}
              notFoundContent={
                membersQuery.isPending
                  ? '加载中...'
                  : projectId == null
                    ? '请先在项目选择框中选择一个项目'
                    : '该项目下暂无其他成员'
              }
            />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}

function BugVerificationPanel({ bug }: { bug: Bug }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [environmentId, setEnvironmentId] = useState<number>();
  const [sourceExecutionId, setSourceExecutionId] = useState<number>();
  const intent = useRef<{ fingerprint: string; requestKey: string } | null>(null);
  const currentBugId = useRef(bug.id);
  const currentFingerprint = JSON.stringify({ bug_id: bug.id, sourceExecutionId, environmentId });
  currentBugId.current = bug.id;
  const currentFingerprintRef = useRef(currentFingerprint);
  currentFingerprintRef.current = currentFingerprint;
  const [unknownCreate, setUnknownCreate] = useState<TaskCreateUncertainty | null>(null);
  useEffect(() => {
    intent.current = null;
    setSourceExecutionId(undefined);
    setEnvironmentId(undefined);
    setUnknownCreate(null);
  }, [bug.id]);
  const sourcesQuery = useQuery({
    queryKey: ['bug-sources', bug.id],
    queryFn: () => bugsApi.bugSources(bug.id),
  });
  const environmentsQuery = useQuery({
    queryKey: ['project-environments', bug.project_id],
    queryFn: () => projectsApi.listEnvironments(bug.project_id),
  });
  const taskRefsQuery = useQuery({
    queryKey: ['task-resource-sources', 'BUG', bug.id, bug.project_id],
    queryFn: () => tasksApi.sources('BUG', String(bug.id), bug.project_id),
  });
  const verifyMutation = useMutation({
    mutationFn: (submission: { bugId: number; sourceExecutionId: number; environmentId: number; requestKey: string; fingerprint: string }) => tasksApi.verifyBug(submission.bugId, {
      source_case_execution_id: submission.sourceExecutionId,
      environment_id: submission.environmentId,
      request_key: submission.requestKey,
    }),
    onSuccess: async (task, submission) => {
      clearTaskCreateUncertainty(submission.requestKey);
      if (intent.current?.requestKey === submission.requestKey) intent.current = null;
      setUnknownCreate((previous) => previous?.request_key === submission.requestKey ? null : previous);
      message.success('验证任务已创建；任务结果不会自动关闭缺陷');
      await queryClient.invalidateQueries({ queryKey: ['task-resource-sources', 'BUG', submission.bugId] });
      if (currentBugId.current === submission.bugId && currentFingerprintRef.current === submission.fingerprint) {
        navigate(`/console/tasks/${task.id}`);
      }
    },
    onError: (error, submission) => {
      message.error(getErrorMessage(error, '验证任务创建失败'));
      if (!isAxiosError(error) || !error.response || error.response.status >= 500) {
        const marker = { kind: 'verification' as const, project_id: bug.project_id, request_key: submission.requestKey, recorded_at: Date.now() };
        rememberTaskCreateUncertainty(marker);
        setUnknownCreate(marker);
      } else clearTaskCreateUncertainty(submission.requestKey);
    },
  });
  const failedSources = (sourcesQuery.data ?? []).filter((source) => source.case_execution_id != null);
  const environments = (environmentsQuery.data?.items ?? []).filter((environment) => environment.is_active && environment.id != null);

  return (
    <div>
      <Typography.Text strong>修复验证</Typography.Text>
      {bug.status !== '已修复' ? <Typography.Paragraph type="secondary">将缺陷状态改为“已修复”后，可以选择原失败用例创建新的验证任务。</Typography.Paragraph> : (
        <Space direction="vertical" style={{ width: '100%', marginTop: 8 }}>
          {sourcesQuery.isError || environmentsQuery.isError ? <Typography.Text type="danger">来源或执行环境读取失败，无法创建验证任务。</Typography.Text> : null}
          <Select
            aria-label="原失败执行"
            value={sourceExecutionId}
            onChange={(value) => { setSourceExecutionId(value); setUnknownCreate(null); }}
            loading={sourcesQuery.isLoading}
            options={failedSources.map((source) => ({ value: source.case_execution_id!, label: `原失败用例执行 #${source.case_execution_id}` }))}
            placeholder={failedSources.length ? '选择关联的原失败执行' : '缺陷没有可用的用例失败来源'}
          />
          <Select
            aria-label="验证环境"
            value={environmentId}
            onChange={(value) => { setEnvironmentId(value); setUnknownCreate(null); }}
            loading={environmentsQuery.isLoading}
            options={environments.map((environment) => ({ value: environment.id!, label: environment.display_name || environment.name }))}
            placeholder={environments.length ? '重新确认验证环境' : '当前项目没有可用环境'}
          />
          <Button
            type="primary"
            loading={verifyMutation.isPending}
            disabled={sourceExecutionId == null || environmentId == null || sourcesQuery.isError || environmentsQuery.isError}
            onClick={() => {
              if (verifyMutation.isPending) return;
              if (sourceExecutionId == null || environmentId == null) return;
              const fingerprint = JSON.stringify({ bug_id: bug.id, sourceExecutionId, environmentId });
              const retryingIntent = intent.current?.fingerprint === fingerprint ? intent.current : null;
              const previousUnknown = readTaskCreateUncertainty();
              if (previousUnknown && retryingIntent?.requestKey !== previousUnknown.request_key) {
                message.warning('请先到任务列表核对上一条结果未知的请求，再提交新的验证配置');
                return;
              }
              const submissionIntent = retryingIntent ?? { fingerprint, requestKey: `bug-verify-${crypto.randomUUID()}` };
              intent.current = submissionIntent;
              rememberTaskCreateUncertainty({ kind: 'verification', project_id: bug.project_id, request_key: submissionIntent.requestKey, recorded_at: Date.now() });
              verifyMutation.mutate({ bugId: bug.id, sourceExecutionId, environmentId, ...submissionIntent });
            }}
          >创建新的验证任务</Button>
          {unknownCreate && <Alert type="warning" showIcon message="验证任务创建结果未知" description="请检查关联任务记录后再决定是否重试；切换环境或来源会建立新的提交意图。" action={<Button size="small" onClick={() => navigate('/console/tasks')}>查看任务列表</Button>} />}
          {taskRefsQuery.isError ? <Typography.Text type="secondary">无法读取相关任务结果。</Typography.Text> : taskRefsQuery.data?.map((ref) => (
            <Typography.Link key={`${ref.task_run_id}-${ref.id}`} onClick={() => navigate(`/console/tasks/${ref.task_id}?runId=${ref.task_run_id}`)}>
              {ref.task_title ?? `验证任务 #${ref.task_id}`} · 运行 #{ref.run_number}
            </Typography.Link>
          ))}
        </Space>
      )}
    </div>
  );
}

