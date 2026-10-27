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
  Button,
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
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  bugsApi,
  type BugCreate,
  type BugUpdate,
} from '@/api/defects';
import { projectsApi } from '@/api/projects';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';
import { getErrorMessage } from '@/api/client';
import { DefectOrigins } from '@/components/exec/DefectOrigins';
import type { Bug, BugSeverity, BugStatus, Paginated, Project } from '@/types';

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
  const projectsQuery = useQuery<Paginated<Project>>({
    queryKey: ['projects', { page: 1, page_size: 100 }],
    queryFn: () =>
      projectsApi.list({
        page: 1,
        page_size: 100,
      }),
  });

  // 弹窗内需要展示「某项目的成员列表」作为「处理人」下拉；
  // 只在弹窗打开并选定 project_id 时才请求，避免无谓流量。
  const modalProjectId =
    modalState?.mode === 'edit'
      ? modalState.bug.project_id
      : projectId;
  const membersQuery = useQuery<Paginated<unknown>>({
    queryKey: ['project', modalProjectId, 'members'],
    queryFn: () =>
      projectsApi.listMembers(modalProjectId!, { page: 1, page_size: 200 }),
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
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const confirmDelete = (bug: Bug) => {
    modal.confirm({
      title: '确认删除该缺陷？',
      icon: <ExclamationCircleOutlined />,
      content: `「${bug.title}」将被永久删除，无法恢复。`,
      okText: '删除',
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
      />

      <Modal title={bugDetail.data ? `缺陷 #${bugDetail.data.id}：${bugDetail.data.title}` : '缺陷详情'} open={Number.isSafeInteger(requestedBugId) && requestedBugId > 0} onCancel={() => setSearchParams({})} footer={null} destroyOnClose>
        {bugDetail.isLoading ? <LoadingState /> : bugDetail.isError || !bugDetail.data ? <ErrorState error={bugDetail.error} onRetry={bugDetail.refetch} /> : <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text>{bugDetail.data.description || '暂无描述'}</Typography.Text>
          <Typography.Text strong>关联来源</Typography.Text>
          <DefectOrigins bugId={bugDetail.data.id} />
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
          <Space size="middle" style={{ display: 'flex', gap: 12 }}>
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
          </Space>
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

