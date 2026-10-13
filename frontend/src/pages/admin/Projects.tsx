// 项目管理（平台视角）：归属、负责人、成员、项目角色、出站目标。
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
} from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import {
  projectsApi,
  type ProjectCreate,
} from '@/api/projects';
import type {
  Paginated,
  Project,
  ProjectMember,
  ProjectRole,
} from '@/types';
import { organizationsApi } from '@/api/organizations';
import {
  ErrorState,
  LoadingState,
  PageContainer,
} from '@/components/PageState';
import { ProjectRoleTag } from '@/components/RoleTag';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';
import { getErrorMessage } from '@/api/client';

// 项目角色下拉选项：viewer < member < editor 三级
const PROJECT_ROLE_OPTIONS: { label: string; value: ProjectRole }[] = [
  { label: '只读成员', value: 'viewer' },
  { label: '普通成员', value: 'member' },
  { label: '项目管理员', value: 'editor' },
];

/**
 * 项目管理（平台视角）页。
 *
 * 用途：维护全平台的「项目」列表，看每个项目的归属组织、负责人、成员与我的角色。
 * 数据来源：projectsApi.list 分页 + 关键词搜索；详情抽屉内 projectsApi.get 拉单个项目。
 * 是否发请求：是，列表 + 详情两个查询；成员增删走 mutation。
 * 权限：所有写操作仅平台管理员可用；组织负责人不可作为项目成员添加（后端约束）。
 * 失败呈现：mutation 失败 message.error 折叠展示；详情查询失败展示 ErrorState + 重试。
 * 空态：无成员时表格显示「暂无成员」。
 */
export function AdminProjectsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  // 分页初值：第一页，每页 10 条
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 10,
  });
  // 关键词：空串归一为 undefined 后传给后端
  const [keyword, setKeyword] = useState('');
  // 详情抽屉打开时记录 projectId，null 表示关闭
  const [detailId, setDetailId] = useState<number | null>(null);
  // 新建项目弹窗开关
  const [creating, setCreating] = useState(false);

  // 拼装查询参数：keyword 空串归一为 undefined
  const query = useMemo(
    () => ({
      page: pagination.page,
      page_size: pagination.page_size,
      keyword: keyword || undefined,
    }),
    [pagination, keyword],
  );

  const listQuery = useQuery({
    queryKey: ['projects', query],
    queryFn: () => projectsApi.list(query),
  });

  // 表格列：memo 依赖为空数组（columns 内引用闭包外状态），仅首次构建
  const columns = useMemo(
    () => [
      { title: 'ID', dataIndex: 'id', width: 70 },
      { title: '项目名称', dataIndex: 'name' },
      { title: '组织', dataIndex: 'organization_name', render: (v: string | null) => v ?? '-' },
      { title: '负责人', dataIndex: 'owner_username' },
      { title: '成员数', dataIndex: 'member_count', width: 80 },
      {
        title: '我的角色',
        dataIndex: 'my_role',
        render: (v: string | null) => <ProjectRoleTag role={v} />,
      },
      {
        title: '操作',
        key: 'actions',
        width: 160,
        render: (_: unknown, row: Project) => (
          <Space>
            <Button size="small" onClick={() => setDetailId(row.id)}>
              详情
            </Button>
          </Space>
        ),
      },
    ],
    [],
  );

  const createMutation = useMutation({
    mutationFn: projectsApi.create,
    onSuccess: () => {
      message.success('项目已创建');
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setCreating(false);
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });

  // 加载中：整页 LoadingState；失败：整页 ErrorState + 重试
  if (listQuery.isPending) return <LoadingState />;
  if (listQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />
      </PageContainer>
    );

  const data: Paginated<Project> = listQuery.data;

  return (
    <PageContainer>
      <Space
        style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}
      >
        <Input.Search
          placeholder="按项目名搜索"
          allowClear
          enterButton
          style={{ width: 320 }}
          // 搜索触发：更新关键词并把页码重置回第一页
          onSearch={(v) => {
            setKeyword(v);
            setPagination((p) => ({ ...p, page: 1 }));
          }}
        />
        <Button type="primary" onClick={() => setCreating(true)}>
          新建项目
        </Button>
      </Space>

      <ResourceTable<Project>
        rowKey={(r) => r.id}
        columns={columns}
        dataSource={data.items}
        loading={listQuery.isFetching}
        total={data.total}
        pagination={pagination}
        onPaginationChange={setPagination}
      />

      {detailId !== null && (
        <ProjectDetailDrawer
          projectId={detailId}
          onClose={() => setDetailId(null)}
        />
      )}

      <CreateProjectModal
        open={creating}
        loading={createMutation.isPending}
        onCancel={() => setCreating(false)}
        onSubmit={(body) => createMutation.mutate(body)}
      />
    </PageContainer>
  );
}

/**
 * 新建项目弹窗。
 *
 * 用途：收集项目名、描述与所属组织；所属组织可留空。
 * 数据来源：organizationsApi.list 拉组织列表供下拉选择。
 * 是否发请求：本组件不发写请求；父组件的 createMutation 负责提交。
 * 校验：项目名必填 2-100 字符；描述可选。
 */
function CreateProjectModal({
  open,
  loading,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: ProjectCreate) => void;
}) {
  const [form] = Form.useForm<ProjectCreate>();
  const { data: orgsData } = useQuery({
    queryKey: ['organizations'],
    queryFn: () => organizationsApi.list(),
  });
  return (
    <Modal
      title="新建项目"
      open={open}
      confirmLoading={loading}
      onCancel={onCancel}
      destroyOnClose
      onOk={() => form.validateFields().then((v) => onSubmit(v))}
    >
      <Form layout="vertical" form={form} initialValues={{ name: '' }}>
        <Form.Item
          name="name"
          label="项目名称"
          rules={[
            { required: true, message: '请输入项目名称' },
            { min: 2, max: 100 },
          ]}
        >
          <Input />
        </Form.Item>
        <Form.Item name="description" label="项目描述">
          <Input.TextArea rows={2} maxLength={500} />
        </Form.Item>
        <Form.Item name="organization_id" label="所属组织">
          <Select
            allowClear
            placeholder="选择组织（可选）"
            options={(orgsData?.items ?? []).map((o) => ({
              value: o.id,
              label: o.name,
            }))}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/**
 * 项目详情抽屉。
 *
 * 用途：展示单个项目的描述、组织、负责人与成员列表，支持添加/移除成员。
 * 数据来源：projectsApi.get 拉详情；成员增删走 removeMember/upsertMember mutation。
 * 是否发请求：是，详情 + 成员变更。
 * 失败呈现：mutation 失败 message.error 折叠展示；详情失败展示 ErrorState + 重试。
 * 空态：无成员时 DetailBody 内表格显示「暂无成员」。
 */
function ProjectDetailDrawer({
  projectId,
  onClose,
}: {
  projectId: number;
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const detailQuery = useQuery({
    queryKey: ['project', projectId, 'detail'],
    queryFn: () => projectsApi.get(projectId),
  });
  const removeMemberMutation = useMutation({
    mutationFn: ({ memberId }: { memberId: number }) =>
      projectsApi.removeMember(projectId, memberId),
    onSuccess: () => {
      message.success('成员已移除');
      queryClient.invalidateQueries({
        queryKey: ['project', projectId, 'detail'],
      });
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const upsertMemberMutation = useMutation({
    mutationFn: ({
      memberId,
      body,
    }: {
      memberId: number;
      body: { user_id: number; role: ProjectRole };
    }) => projectsApi.upsertMember(projectId, memberId, body),
    onSuccess: () => {
      message.success('成员已保存');
      queryClient.invalidateQueries({
        queryKey: ['project', projectId, 'detail'],
      });
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const [addMember, setAddMember] = useState<{
    user_id: number;
    role: ProjectRole;
  } | null>(null);

  return (
    <Drawer
      title={detailQuery.data?.name ?? `项目 #${projectId}`}
      open
      onClose={onClose}
      width={640}
      destroyOnClose
    >
      {detailQuery.isPending ? (
        <LoadingState />
      ) : detailQuery.isError ? (
        <ErrorState error={detailQuery.error} onRetry={detailQuery.refetch} />
      ) : (
        /* 详情就绪：渲染详情主体；onAddMember 打开添加成员弹窗，onRemoveMember 走 mutation */
        <DetailBody
          project={detailQuery.data}
          onAddMember={() => setAddMember({ user_id: 0, role: 'member' })}
          onRemoveMember={(memberId) =>
            removeMemberMutation.mutate({ memberId })
          }
        />
      )}
      {addMember && (
        <AddMemberModal
          projectId={projectId}
          onCancel={() => setAddMember(null)}
          onOk={(body) => {
            upsertMemberMutation.mutate({ memberId: body.user_id, body });
            setAddMember(null);
          }}
          loading={upsertMemberMutation.isPending}
        />
      )}
    </Drawer>
  );
}

/**
 * 项目详情主体：描述、成员表 + 移除按钮。
 *
 * 用途：只负责渲染，不含查询/请求；成员操作通过 onRemoveMember 回调抛出。
 * 空态：members 为空时表格显示「暂无成员」。
 */
function DetailBody({
  project,
  onAddMember,
  onRemoveMember,
}: {
  project: Project & { members?: ProjectMember[] };
  onAddMember: () => void;
  onRemoveMember: (memberId: number) => void;
}) {
  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <div>
        <strong>项目描述</strong>
        <p style={{ color: '#666' }}>{project.description ?? '（无）'}</p>
        <Space size="small">
          <Tag>组织：{project.organization_name ?? '无'}</Tag>
          <Tag>负责人：{project.owner_username ?? '未知'}</Tag>
          <ProjectRoleTag role={project.my_role} />
        </Space>
      </div>
      <div>
        <Space
          style={{ justifyContent: 'space-between', width: '100%', marginBottom: 8 }}
        >
          <strong>项目成员</strong>
          <Button size="small" onClick={onAddMember}>
            添加/更新成员
          </Button>
        </Space>
        <Table<ProjectMember>
          rowKey={(m) => m.user_id}
          size="small"
          pagination={false}
          dataSource={project.members ?? []}
          locale={{ emptyText: '暂无成员' }}
          columns={[
            { title: '用户ID', dataIndex: 'user_id', width: 80 },
            { title: '用户名', dataIndex: 'username' },
            { title: '角色', dataIndex: 'role', render: (v: string) => <ProjectRoleTag role={v} /> },
            { title: '负责人', dataIndex: 'is_owner', render: (v: boolean) => (v ? <Tag color="gold">是</Tag> : '否') },
            {
              title: '操作',
              key: 'actions',
              render: (_: unknown, m: ProjectMember) => (
                <Button
                  size="small"
                  danger
                  disabled={m.is_owner}
                  onClick={() => onRemoveMember(m.user_id)}
                >
                  移除
                </Button>
              ),
            },
          ]}
        />
      </div>
    </Space>
  );
}

/**
 * 添加项目成员弹窗。
 *
 * 用途：手动输入 user_id + 选择 role，用于把组织成员加入项目。
 * 是否发请求：本组件不发写请求；父组件的 upsertMemberMutation 负责提交。
 * 校验：user_id 必填；role 默认为 member。
 * 提示：底部说明「成员必须是项目所属组织的成员」。
 */
function AddMemberModal({
  projectId,
  loading,
  onCancel,
  onOk,
}: {
  projectId: number;
  loading: boolean;
  onCancel: () => void;
  onOk: (body: { user_id: number; role: ProjectRole }) => void;
}) {
  const [form] = Form.useForm<{ user_id: number; role: ProjectRole }>();
  return (
    <Modal
      title="添加项目成员"
      open
      confirmLoading={loading}
      onCancel={onCancel}
      destroyOnClose
      onOk={() => form.validateFields().then((v) => onOk(v))}
    >
      <Form layout="vertical" form={form} initialValues={{ role: 'member' }}>
        <Form.Item
          name="user_id"
          label="用户 ID"
          rules={[{ required: true, message: '请输入用户 ID' }]}
        >
          <Input type="number" />
        </Form.Item>
        <Form.Item name="role" label="项目角色">
          <Select options={PROJECT_ROLE_OPTIONS} />
        </Form.Item>
      </Form>
      <small style={{ color: '#999' }}>
        成员必须是项目所属组织的成员。项目 ID：{projectId}
      </small>
    </Modal>
  );
}
