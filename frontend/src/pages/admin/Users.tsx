// 用户管理：列表、搜索、分页、状态管理、角色调整。
import {
  App,
  Avatar,
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { PlusOutlined, ReloadOutlined, TeamOutlined, UserSwitchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { usersApi } from '@/features/users/api/users';
import type { UserListQuery, UserUpdate } from '@/features/users/contracts';
import type { Paginated } from '@/shared/api/contracts';
import type { PlatformRole, User } from '@/features/identity/contracts';

import { ResourceTable, type PaginationState } from '@/shared/ui/ResourceTable';
import { PlatformRoleTag } from '@/features/identity/components/RoleTag';
import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { getErrorMessage } from '@/shared/api/client';
import { PageHeader } from '@/shared/ui/PageHeader';

// 平台角色下拉选项：admin > test > dev 三级
const ROLE_OPTIONS: { label: string; value: PlatformRole }[] = [
  { label: '平台管理员', value: 'admin' },
  { label: '测试工程师', value: 'test' },
  { label: '开发工程师', value: 'dev' },
];
type UserStatusFilter = 'all' | 'active' | 'inactive';

/**
 * 用户管理页。
 *
 * 用途：管理全平台用户列表，支持搜索、分页、编辑与新建。
 * 数据来源：usersApi.list 分页 + 关键词搜索；编辑/新建走 mutation。
 * 是否发请求：是，列表查询 + 各 mutation。
 * 权限：所有写操作仅平台管理员可用。
 * 失败呈现：mutation 失败 message.error 折叠展示；列表失败整页 ErrorState。
 * 空态：无搜索结果时表格空态由 antd 默认展示。
 */
export function AdminUsersPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  // 分页初值：第一页，每页 10 条
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 10,
  });
  // 关键词：空串归一为 undefined 后传给后端
  const [keyword, setKeyword] = useState('');
  // 账号状态筛选直接传给后端，切换时回到第一页。
  const [statusFilter, setStatusFilter] = useState<UserStatusFilter>('all');
  // 编辑目标：null 表示不编辑
  const [editing, setEditing] = useState<User | null>(null);
  // 新建弹窗开关
  const [creating, setCreating] = useState(false);

  // 拼装查询参数：keyword 空串归一为 undefined，避免后端把它当作「空字符串过滤」
  const query: UserListQuery = useMemo(
    () => ({
      page: pagination.page,
      page_size: pagination.page_size,
      keyword: keyword || undefined,
      is_active:
        statusFilter === 'all' ? undefined : statusFilter === 'active',
    }),
    [pagination, keyword, statusFilter],
  );

  const listQuery = useQuery({
    queryKey: ['users', query],
    queryFn: () => usersApi.list(query),
  });

  const updateMutation = useMutation({
    // 更新走 (id, body) 二元参数；body 中只包含实际变更的字段
    mutationFn: ({ id, body }: { id: number; body: UserUpdate }) =>
      usersApi.update(id, body),
    onSuccess: () => {
      message.success('已更新');
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setEditing(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const createMutation = useMutation({
    mutationFn: usersApi.create,
    onSuccess: () => {
      message.success('已创建');
      queryClient.invalidateQueries({ queryKey: ['users'] });
      setCreating(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  // 表格列：memo 依赖为空数组（columns 内不引用闭包外状态），仅首次构建
  const columns = useMemo(
    () => [
      {
        title: '用户账号',
        dataIndex: 'username',
        render: (username: string, row: User) => (
          <Space className="admin-user-identity" size="middle">
            <Avatar className="admin-user-avatar">
              {username.slice(0, 1).toUpperCase()}
            </Avatar>
            <span className="admin-user-copy">
              <Typography.Text strong>{username}</Typography.Text>
              <Typography.Text className="admin-user-id" type="secondary">
                用户 ID · {row.id}
              </Typography.Text>
            </span>
          </Space>
        ),
      },
      {
        title: '平台角色',
        dataIndex: 'role',
        render: (role: PlatformRole) => <PlatformRoleTag role={role} />,
      },
      {
        title: '账号状态',
        dataIndex: 'is_active',
        render: (active: boolean) => (
          <Tag color={active ? 'success' : 'default'}>
            {active ? '正常使用' : '已停用'}
          </Tag>
        ),
      },
      {
        title: '创建时间',
        dataIndex: 'created_at',
        render: (value: string) => {
          const createdAt = dayjs(value);
          return createdAt.isValid() ? createdAt.format('YYYY-MM-DD HH:mm') : '—';
        },
      },
      {
        title: '操作',
        key: 'actions',
        width: 100,
        render: (_: unknown, row: User) => (
          <Button type="link" size="small" onClick={() => setEditing(row)}>
            编辑
          </Button>
        ),
      },
    ],
    [],
  );

  // 加载中：整页 LoadingState；失败：整页 ErrorState + 重试
  if (listQuery.isPending) return <LoadingState />;
  if (listQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />
      </PageContainer>
    );

  const data: Paginated<User> = listQuery.data;
  const activeOnPage = data.items.filter((user) => user.is_active).length;
  const adminsOnPage = data.items.filter((user) => user.role === 'admin').length;

  return (
    <PageContainer>
      <PageHeader
        title="用户管理"
        titleExtra={<Tag color="blue">账号治理</Tag>}
        subtitle="统一管理平台账号、角色权限与访问状态"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreating(true)}
          >
            新建用户
          </Button>
        }
      />

      <Row gutter={[14, 14]} className="admin-users-summary">
        <Col xs={24} sm={8}>
          <Card className="admin-users-summary-card">
            <span className="admin-users-summary-icon admin-users-summary-icon--blue">
              <TeamOutlined />
            </span>
            <span className="admin-users-summary-copy">
              <Typography.Text type="secondary">筛选结果</Typography.Text>
              <Typography.Title level={3}>{data.total}</Typography.Title>
              <Typography.Text type="secondary">符合当前条件的账号</Typography.Text>
            </span>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card className="admin-users-summary-card">
            <span className="admin-users-summary-icon admin-users-summary-icon--green">
              <UserSwitchOutlined />
            </span>
            <span className="admin-users-summary-copy">
              <Typography.Text type="secondary">当前页启用</Typography.Text>
              <Typography.Title level={3}>{activeOnPage}</Typography.Title>
              <Typography.Text type="secondary">本页账号可正常登录</Typography.Text>
            </span>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card className="admin-users-summary-card">
            <span className="admin-users-summary-icon admin-users-summary-icon--violet">
              <UserSwitchOutlined />
            </span>
            <span className="admin-users-summary-copy">
              <Typography.Text type="secondary">当前页管理员</Typography.Text>
              <Typography.Title level={3}>{adminsOnPage}</Typography.Title>
              <Typography.Text type="secondary">本页拥有平台管理权限</Typography.Text>
            </span>
          </Card>
        </Col>
      </Row>

      <Card
        className="admin-users-directory"
        title={
          <span className="admin-users-directory-title">
            <Typography.Text strong>账号目录</Typography.Text>
            <Typography.Text type="secondary">搜索并维护平台用户</Typography.Text>
          </span>
        }
        extra={<Tag bordered={false} color="processing">共 {data.total} 个账号</Tag>}
      >
        <div className="admin-users-toolbar">
          <Input.Search
            className="admin-users-search"
            placeholder="搜索用户名、角色或用户 ID"
            allowClear
            onSearch={(value) => {
              setKeyword(value);
              setPagination((current) => ({ ...current, page: 1 }));
            }}
          />
          <Space className="admin-users-filters" wrap>
            <Select<UserStatusFilter>
              aria-label="账号状态筛选"
              value={statusFilter}
              onChange={(value) => {
                setStatusFilter(value);
                setPagination((current) => ({ ...current, page: 1 }));
              }}
              options={[
                { label: '全部状态', value: 'all' },
                { label: '正常使用', value: 'active' },
                { label: '已停用', value: 'inactive' },
              ]}
              style={{ width: 132 }}
            />
            <Button
              icon={<ReloadOutlined />}
              loading={listQuery.isFetching}
              onClick={() => void listQuery.refetch()}
            >
              刷新
            </Button>
          </Space>
        </div>

        <ResourceTable<User>
          rowKey={(row) => row.id}
          columns={columns}
          dataSource={data.items}
          loading={listQuery.isFetching}
          total={data.total}
          pagination={pagination}
          onPaginationChange={setPagination}
        />
      </Card>

      {editing && (
        <EditUserModal
          user={editing}
          loading={updateMutation.isPending}
          onCancel={() => setEditing(null)}
          onSubmit={(body) =>
            updateMutation.mutate({ id: editing.id, body })
          }
        />
      )}
      <CreateUserModal
        open={creating}
        loading={createMutation.isPending}
        onCancel={() => setCreating(false)}
        onSubmit={(body) => createMutation.mutate(body)}
      />
    </PageContainer>
  );
}

/**
 * 编辑用户弹窗。
 *
 * 用途：修改用户信息，采用「只提交变更字段」策略——表单值与原值比对，
 *       没有差异则直接取消弹窗，不发任何请求。
 * 是否发请求：本组件不发写请求；父组件的 updateMutation 负责提交。
 * 校验：username 3-50 字符。
 * 失败呈现：Form 就地展示 rules 提示。
 */
function EditUserModal({
  user,
  loading,
  onCancel,
  onSubmit,
}: {
  user: User;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: UserUpdate) => void;
}) {
  const [form] = Form.useForm<UserUpdate>();
  return (
    <Modal
      title={`编辑用户：${user.username}`}
      open
      confirmLoading={loading}
      onCancel={onCancel}
      onOk={() =>
        form.validateFields().then((v) => {
          // 构造 body：只保留「已变更」的字段，避免覆盖其他字段为 undefined
          const body: UserUpdate = {};
          if (v.username && v.username !== user.username) body.username = v.username;
          if (v.role && v.role !== user.role) body.role = v.role;
          if (v.is_active !== undefined && v.is_active !== user.is_active)
            body.is_active = v.is_active;
          // 完全无变化：直接取消弹窗，不发请求
          if (Object.keys(body).length === 0) {
            onCancel();
            return;
          }
          onSubmit(body);
        })
      }
    >
      <Form<UserUpdate>
        layout="vertical"
        initialValues={{
          username: user.username,
          role: user.role,
          is_active: user.is_active,
        }}
        form={form}
      >
        <Form.Item name="username" label="用户名" rules={[{ min: 3, max: 50 }]}>
          <Input />
        </Form.Item>
        <Form.Item name="role" label="平台角色">
          <Select options={ROLE_OPTIONS} />
        </Form.Item>
        <Form.Item name="is_active" label="是否启用" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/**
 * 新建用户弹窗。
 *
 * 用途：收集用户名、初始密码、平台角色与是否启用；提交后由后端创建账号。
 * 是否发请求：本组件不发写请求；父组件的 createMutation 负责提交。
 * 校验：username 必填 3-50 字符；password 必填 6-100 字符；默认角色 test，默认启用。
 */
function CreateUserModal({
  open,
  loading,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: {
    username: string;
    password: string;
    role: PlatformRole;
    is_active: boolean;
  }) => void;
}) {
  const [form] = Form.useForm();
  return (
    <Modal
      title="新建用户"
      open={open}
      confirmLoading={loading}
      onCancel={onCancel}
      destroyOnClose
      onOk={() =>
        form.validateFields().then((v) => onSubmit(v))
      }
    >
      <Form
        layout="vertical"
        form={form}
        initialValues={{ role: 'test', is_active: true }}
      >
        <Form.Item
          name="username"
          label="用户名"
          rules={[
            { required: true, message: '请输入用户名' },
            { min: 3, max: 50 },
          ]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="password"
          label="初始密码"
          rules={[
            { required: true, message: '请输入初始密码' },
            { min: 6, max: 100 },
          ]}
        >
          <Input.Password />
        </Form.Item>
        <Form.Item name="role" label="平台角色">
          <Select options={ROLE_OPTIONS} />
        </Form.Item>
        <Form.Item name="is_active" label="是否启用" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  );
}
