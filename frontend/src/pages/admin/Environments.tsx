// 环境与目标服务配置：保留项目作用域与目标授权规则（写操作仅平台管理员）。
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Tag,
} from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  environmentsApi,
  type EnvironmentCreate,
  type EnvironmentUpdate,
} from '@/api/environments';
import type { Environment, Paginated } from '@/types';
import {
  ErrorState,
  LoadingState,
  PageContainer,
} from '@/components/PageState';
import { ResourceTable, type PaginationState } from '@/components/ResourceTable';
import { getErrorMessage } from '@/api/client';

/**
 * 环境与目标服务配置页。
 *
 * 用途：维护全局「环境」列表，每个环境对应一个被测服务的 base_url 与网关前缀。
 * 数据来源：environmentsApi.list 分页查询（include_inactive=true 展示停用项）；
 *       写操作（create/update/setDefault/remove）成功后 invalidate 整个 ['environments'] 缓存。
 * 权限：写操作仅平台管理员可用；后端对停用/默认环境有保护，前端 disabled 位与之一致。
 * 失败呈现：任一 mutation 失败通过 message.error 折叠展示 getErrorMessage(e)。
 * 空态：表格 emptyText 提示「系统会在表为空时回退到内置环境」；内置环境（无 id）不可编辑/删除。
 */
export function AdminEnvironmentsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  // 分页初值：第一页，每页 20 条
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 20,
  });
  // 新建弹窗开关
  const [creating, setCreating] = useState(false);
  // 编辑目标：null 表示不编辑，非 null 表示正在编辑该环境
  const [editing, setEditing] = useState<Environment | null>(null);

  // 列表查询：queryKey 同时带上分页与 include_inactive，翻页/搜索都能命中不同缓存槽
  const listQuery = useQuery({
    queryKey: ['environments', { ...pagination, include_inactive: true }],
    queryFn: () =>
      environmentsApi.list({ ...pagination, include_inactive: true }),
  });

  // 写操作成功后的统一缓存失效入口
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['environments'] });

  const createMutation = useMutation({
    mutationFn: environmentsApi.create,
    // 成功后 toast + 失效列表 + 关闭弹窗
    onSuccess: () => {
      message.success('已创建');
      invalidate();
      setCreating(false);
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const updateMutation = useMutation({
    // 更新需要同时带环境 name 与 body；body 内字段部分更新即可
    mutationFn: ({ name, body }: { name: string; body: EnvironmentUpdate }) =>
      environmentsApi.update(name, body),
    onSuccess: () => {
      message.success('已更新');
      invalidate();
      setEditing(null);
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const setDefaultMutation = useMutation({
    mutationFn: environmentsApi.setDefault,
    onSuccess: () => {
      message.success('已设为默认');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const deleteMutation = useMutation({
    mutationFn: environmentsApi.remove,
    onSuccess: () => {
      message.success('已删除');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });

  const columns = [
    { title: '环境标识', dataIndex: 'name' },
    { title: '展示名称', dataIndex: 'display_name' },
    { title: 'base_url', dataIndex: 'base_url' },
    { title: '网关前缀', dataIndex: 'gateway_prefix' },
    {
      title: '状态',
      key: 'state',
      // 三态标签：启用/停用、是否默认、内置（无 id）
      render: (_: unknown, row: Environment) => (
        <Space size="small">
          {row.is_active ? <Tag color="blue">启用</Tag> : <Tag>停用</Tag>}
          {row.is_default && <Tag color="gold">默认</Tag>}
          {!row.id && <Tag>内置</Tag>}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      // 权限/保护：内置环境 (!row.id) 不允许编辑、设为默认、删除；默认环境不允许再改默认或删除
      render: (_: unknown, row: Environment) => (
        <Space>
          <Button
            size="small"
            disabled={!row.id}
            onClick={() => setEditing(row)}
          >
            编辑
          </Button>
          <Button
            size="small"
            disabled={!row.id || row.is_default || !row.is_active}
            onClick={() => setDefaultMutation.mutate(row.name)}
          >
            设为默认
          </Button>
          <Button
            size="small"
            danger
            disabled={!row.id || row.is_default}
            onClick={() => deleteMutation.mutate(row.name)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  // 加载中：整页 LoadingState；失败：整页 ErrorState + 重试
  if (listQuery.isPending) return <LoadingState />;
  if (listQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />
      </PageContainer>
    );

  const data: Paginated<Environment> = listQuery.data;

  return (
    <PageContainer>
      <Space
        style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}
      >
        <span style={{ fontSize: 16, fontWeight: 500 }}>环境与目标服务配置</span>
        <Button type="primary" onClick={() => setCreating(true)}>
          新增环境
        </Button>
      </Space>

      <ResourceTable<Environment>
        rowKey={(r) => r.id ?? r.name}
        columns={columns}
        dataSource={data.items}
        loading={listQuery.isFetching}
        total={data.total}
        pagination={pagination}
        onPaginationChange={setPagination}
        emptyText="暂无环境（系统会在表为空时回退到内置环境）"
      />

      {creating && (
        <EnvironmentFormModal
          title="新增环境"
          loading={createMutation.isPending}
          onCancel={() => setCreating(false)}
          onSubmit={(body) =>
            // 新建表单必然含环境标识 name；复用同一表单组件故做一次收窄。
            createMutation.mutate(body as EnvironmentCreate)
          }
        />
      )}
      {editing && (
        <EnvironmentFormModal
          title={`编辑环境：${editing.name}`}
          editing={editing}
          loading={updateMutation.isPending}
          onCancel={() => setEditing(null)}
          onSubmit={(body) =>
            updateMutation.mutate({ name: editing.name, body })
          }
        />
      )}
    </PageContainer>
  );
}

/**
 * 环境新建/编辑共用表单弹窗。
 *
 * 用途：新建时收 name/display_name/base_url/... 等所有字段；
 *       编辑时 name 只读（后端不允许改环境标识），其余字段回填当前值。
 * 是否发请求：本组件不发请求，仅通过 onSubmit 把校验后的 body 抛给父组件。
 * 校验：name 必填且匹配 ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,49}$（字母数字开头，可含 _ -）。
 * 失败呈现：Form 就地展示 rules 提示；提交进行中标记 loading 驱动 confirmLoading。
 */
function EnvironmentFormModal({
  title,
  editing,
  loading,
  onCancel,
  onSubmit,
}: {
  title: string;
  editing?: Environment;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: EnvironmentCreate | EnvironmentUpdate) => void;
}) {
  const [form] = Form.useForm<EnvironmentCreate>();
  return (
    <Modal
      title={title}
      open
      width={560}
      confirmLoading={loading}
      onCancel={onCancel}
      destroyOnClose
      onOk={() => form.validateFields().then((v) => onSubmit(v))}
    >
      <Form
        layout="vertical"
        form={form}
        // 编辑模式：回填环境现有字段；新建模式：给合理默认值（默认启用，不默认）
        initialValues={
          editing
            ? {
                display_name: editing.display_name,
                base_url: editing.base_url,
                gateway_prefix: editing.gateway_prefix,
                description: editing.description,
                is_default: editing.is_default,
                is_active: editing.is_active,
              }
            : {
                display_name: '',
                base_url: '',
                gateway_prefix: '',
                is_default: false,
                is_active: true,
              }
        }
      >
        {/* 环境标识 name 只在创建时出现；创建后不允许修改（后端约束） */}
        {!editing && (
          <Form.Item
            name="name"
            label="环境标识"
            rules={[
              { required: true, message: '请输入环境标识' },
              {
                pattern: /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,49}$/,
                message: '字母/数字开头，可含 _ -，最长 50',
              },
            ]}
            extra="创建后不可修改，如 dev/test/staging/prod"
          >
            <Input placeholder="dev" />
          </Form.Item>
        )}
        <Form.Item name="display_name" label="展示名称">
          <Input />
        </Form.Item>
        <Form.Item name="base_url" label="被测服务 base_url">
          <Input placeholder="https://test-api.example.com" />
        </Form.Item>
        <Form.Item name="gateway_prefix" label="网关前缀">
          <Input placeholder="/api/v1" />
        </Form.Item>
        <Form.Item name="description" label="说明">
          <Input.TextArea rows={2} maxLength={1000} />
        </Form.Item>
        <Space>
          <Form.Item name="is_default" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}
