import { collectPages } from '@/shared/api/pagination';
// 环境与目标服务配置：保留项目作用域与目标授权规则（写操作仅平台管理员）。
import {
  Alert,
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
} from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectsApi } from '@/features/projects/api/projects';
import { environmentsApi } from '@/features/environments/api/environments';
import type { EnvironmentCreate, EnvironmentUpdate, ProjectEnvironmentCreate } from '@/features/environments/contracts';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import type { Environment } from '@/features/environments/contracts';
import type { Paginated } from '@/shared/api/contracts';

import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageContainer,
} from '@/shared/ui/PageState';
import { ResourceTable, type PaginationState } from '@/shared/ui/ResourceTable';
import { getErrorMessage } from '@/shared/api/client';
import { PageHeader } from '@/shared/ui/PageHeader';

/**
 * 环境与目标服务配置页。
 *
 * 用途：按项目维护独立的执行目标；环境类型可复用，各项目 URL 与请求头相互隔离。
 * 数据来源：先选择项目，再查询该项目的环境绑定。
 * 权限：写操作仅平台管理员可用；后端对停用/默认环境有保护，前端 disabled 位与之一致。
 * 失败呈现：任一 mutation 失败通过 message.error 折叠展示 getErrorMessage(e)。
 * 空态：所选项目无环境时显示项目范围的空态与新增入口。
 */
export function AdminEnvironmentsPage() {
  return (
    <Tabs
      items={[
        { key: 'project', label: '项目环境', children: <ProjectEnvironmentsTab /> },
        { key: 'catalog', label: '平台环境类型', children: <EnvironmentCatalogTab /> },
      ]}
    />
  );
}

function ProjectEnvironmentsTab() {
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
  const [selectedProjectId, setSelectedProjectId] = useState<number>();
  const projectsQuery = useQuery({
    queryKey: ['projects', 'environment-admin'],
    queryFn: () => collectPages((page) => projectsApi.list({ page, page_size: 200 })),
  });
  const projectId = selectedProjectId ?? projectsQuery.data?.items[0]?.id;

  // 列表查询：queryKey 同时带上分页与 include_inactive，翻页/搜索都能命中不同缓存槽
  const listQuery = useQuery({
    queryKey: ['environments', projectId, { ...pagination, include_inactive: true }],
    queryFn: () =>
      environmentsApi.list({ ...pagination, include_inactive: true, project_id: projectId }),
    enabled: projectId != null,
  });

  // 写操作成功后的统一缓存失效入口
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['environments'] });

  const createMutation = useMutation({
    mutationFn: ({ projectId, body }: { projectId: number; body: ProjectEnvironmentCreate }) =>
      projectsApi.createEnvironment(projectId, body),
    // 成功后 toast + 失效列表 + 关闭弹窗
    onSuccess: () => {
      message.success('已创建');
      invalidate();
      setCreating(false);
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const updateMutation = useMutation({
    mutationFn: ({ projectId, environmentId, body }: { projectId: number; environmentId: number; body: EnvironmentUpdate }) =>
      projectsApi.updateEnvironment(projectId, environmentId, body),
    onSuccess: () => {
      message.success('已更新');
      invalidate();
      setEditing(null);
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const setDefaultMutation = useMutation({
    mutationFn: ({ projectId, environmentId }: { projectId: number; environmentId: number }) =>
      projectsApi.setDefaultEnvironment(projectId, environmentId),
    onSuccess: () => {
      message.success('已设为默认');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const toggleMutation = useMutation({
    mutationFn: ({ projectId, environmentId, active }: { projectId: number; environmentId: number; active: boolean }) =>
      projectsApi.updateEnvironment(projectId, environmentId, { is_active: active }),
    onSuccess: () => {
      message.success('环境状态已更新');
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
      // 项目环境状态与默认项。
      render: (_: unknown, row: Environment) => (
        <Space size="small">
          {row.is_active ? <Tag color="blue">启用</Tag> : <Tag>停用</Tag>}
          {row.is_default && <Tag color="gold">默认</Tag>}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      // 停用只关闭项目绑定，保留模板和历史执行引用。
      render: (_: unknown, row: Environment) => (
        <Space wrap>
          <Button
            size="small"
            disabled={row.id == null}
            onClick={() => setEditing(row)}
          >
            编辑
          </Button>
          <Button
            size="small"
            disabled={row.id == null || row.is_default || !row.is_active || projectId == null}
            onClick={() => projectId != null && row.id != null && setDefaultMutation.mutate({ projectId, environmentId: row.id })}
          >
            设为默认
          </Button>
          <Button
            size="small"
            danger={row.is_active}
            disabled={row.id == null || projectId == null}
            onClick={() => projectId != null && row.id != null && toggleMutation.mutate({ projectId, environmentId: row.id, active: !row.is_active })}
          >
            {row.is_active ? '停用' : '启用'}
          </Button>
        </Space>
      ),
    },
  ];

  // 加载中：整页 LoadingState；失败：整页 ErrorState + 重试
  if (projectsQuery.isPending) return <LoadingState />;
  if (projectsQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={projectsQuery.error} onRetry={projectsQuery.refetch} />
      </PageContainer>
    );
  const projects = projectsQuery.data.items;
  if (projects.length === 0)
    return <PageContainer><EmptyState description="暂无项目，请先创建项目后再配置环境" /></PageContainer>;
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
      <PageHeader title="环境配置" subtitle="按项目隔离执行环境与目标服务" />
      <Space wrap className="ui-list-toolbar"
        style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}
      >
        <Select
          value={projectId}
          style={{ width: 320 }}
          placeholder="选择项目"
          onChange={(value) => {
            setSelectedProjectId(value);
            setPagination((current) => ({ ...current, page: 1 }));
          }}
          options={projects.map((project) => ({ value: project.id, label: project.name }))}
        />
        <Button type="primary" disabled={projectId == null} onClick={() => setCreating(true)}>
          新增项目环境
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
        emptyText="该项目暂无环境配置"
      />

      {creating && (
        <EnvironmentFormModal
          title={`为 ${projects.find((project) => project.id === projectId)?.name ?? '项目'} 新增环境`}
          loading={createMutation.isPending}
          onCancel={() => setCreating(false)}
          onSubmit={(body) => {
            if (projectId != null) createMutation.mutate({ projectId, body: body as ProjectEnvironmentCreate });
          }}
        />
      )}
      {editing && (
        <EnvironmentFormModal
          title={`编辑环境：${editing.name}`}
          editing={editing}
          loading={updateMutation.isPending}
          onCancel={() => setEditing(null)}
          onSubmit={(body) => {
            if (projectId != null && editing.id != null) {
              updateMutation.mutate({ projectId, environmentId: editing.id, body });
            }
          }}
        />
      )}
    </PageContainer>
  );
}

function EnvironmentCatalogTab() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Environment | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const listQuery = useQuery({
    queryKey: ['environment-catalog'],
    queryFn: () => environmentsApi.list({ include_inactive: true, page: 1, page_size: 200 }),
  });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['environment-catalog'] });
    queryClient.invalidateQueries({ queryKey: ['environments'] });
    queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
  };
  const createMutation = useMutation({
    mutationFn: (body: EnvironmentCreate) => environmentsApi.create(body),
    onSuccess: () => { message.success('环境类型已创建'); setCreating(false); invalidate(); },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  const updateMutation = useMutation({
    mutationFn: ({ name, body }: { name: string; body: EnvironmentUpdate }) => environmentsApi.update(name, body),
    onSuccess: () => { message.success('环境类型已更新'); setEditing(null); invalidate(); },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  const removeMutation = useMutation({
    mutationFn: (name: string) => environmentsApi.remove(name),
    onSuccess: () => { message.success('环境类型已移入回收站'); invalidate(); },
    onError: (error) => message.error(getErrorMessage(error)),
  });
  const deleteMany = () => {
    if (!selectedIds.length) return;
    modal.confirm({
      title: `将 ${selectedIds.length} 个环境类型移入回收站？`,
      content: '默认环境、仍被项目绑定或被数据库/Web 配置使用的环境会逐项拒绝，成功项可在回收站恢复。',
      okText: '移入回收站', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const result = await dataLifecycleApi.deleteMany('environment', null, selectedIds);
          setSelectedIds([]);
          invalidate();
          if (result.failed) {
            modal.info({
              title: `成功 ${result.succeeded} 个，失败 ${result.failed} 个`,
              content: <Space direction="vertical" style={{ width: '100%' }}>{result.items.filter((item) => !item.succeeded).map((item) => <Alert key={item.id} type="error" showIcon message={`环境 #${item.id}`} description={item.error ?? '删除失败'} />)}</Space>,
            });
          } else message.success(`已将 ${result.succeeded} 个环境类型移入回收站`);
        } catch (error) { message.error(getErrorMessage(error, '批量删除失败')); }
      },
    });
  };
  const columns = [
    { title: '环境标识', dataIndex: 'name' },
    { title: '展示名称', dataIndex: 'display_name' },
    { title: '目标地址', dataIndex: 'base_url', ellipsis: true },
    { title: '状态', key: 'status', render: (_: unknown, row: Environment) => <Space>{row.is_active ? <Tag color="blue">启用</Tag> : <Tag>停用</Tag>}{row.is_default && <Tag color="gold">默认</Tag>}</Space> },
    {
      title: '操作', key: 'actions', width: 300,
      render: (_: unknown, row: Environment) => (
        <Space wrap>
          <Button size="small" onClick={() => setEditing(row)}>编辑</Button>
          {!row.is_default && row.is_active && <Button size="small" onClick={() => updateMutation.mutate({ name: row.name, body: { is_default: true } })}>设为默认</Button>}
          <Button size="small" onClick={() => updateMutation.mutate({ name: row.name, body: { is_active: !row.is_active } })}>{row.is_active ? '停用' : '启用'}</Button>
          <Popconfirm title="将环境类型移入回收站？" description="默认环境及仍被项目或运行配置引用的环境不能删除。" onConfirm={() => removeMutation.mutate(row.name)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];
  if (listQuery.isPending) return <PageContainer><LoadingState /></PageContainer>;
  if (listQuery.isError) return <PageContainer><ErrorState error={listQuery.error} onRetry={listQuery.refetch} /></PageContainer>;
  return (
    <PageContainer>
      <PageHeader title="平台环境类型" subtitle="环境类型目录与项目环境绑定分开管理；停用不会删除历史配置。" />
      <Space wrap className="ui-list-toolbar" style={{ marginBottom: 12 }}>
        <Button type="primary" onClick={() => setCreating(true)}>新增环境类型</Button>
        <Button danger disabled={!selectedIds.length} onClick={deleteMany}>批量删除（{selectedIds.length}）</Button>
        <Button onClick={() => navigate('/admin/recycle-bin')}>回收站</Button>
      </Space>
      <Table<Environment>
        rowKey="id" size="small" scroll={{ x: 'max-content' }} columns={columns}
        dataSource={listQuery.data.items} loading={listQuery.isFetching} pagination={false}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: (keys) => setSelectedIds(keys.map(Number)),
          getCheckboxProps: (row) => ({ disabled: row.id == null || row.is_default }),
        }}
        locale={{ emptyText: '暂无平台环境类型' }}
      />
      {creating && <EnvironmentFormModal title="新增平台环境类型" catalogMode loading={createMutation.isPending} onCancel={() => setCreating(false)} onSubmit={(body) => createMutation.mutate(body as EnvironmentCreate)} />}
      {editing && <EnvironmentFormModal title={`编辑平台环境类型：${editing.name}`} editing={editing} catalogMode loading={updateMutation.isPending} onCancel={() => setEditing(null)} onSubmit={(body) => updateMutation.mutate({ name: editing.name, body: body as EnvironmentUpdate })} />}
    </PageContainer>
  );
}

/**
 * 环境新建/编辑共用表单弹窗。
 *
 * 用途：新建时收环境类型、项目展示名和目标地址；编辑时环境类型固定，只更新项目配置。
 * 是否发请求：本组件不发请求，仅通过 onSubmit 把校验后的 body 抛给父组件。
 * 校验：name 必填且匹配 ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,49}$（字母数字开头，可含 _ -）。
 * 失败呈现：Form 就地展示 rules 提示；提交进行中标记 loading 驱动 confirmLoading。
 */
function EnvironmentFormModal({
  title,
  editing,
  catalogMode = false,
  loading,
  onCancel,
  onSubmit,
}: {
  title: string;
  editing?: Environment;
  catalogMode?: boolean;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: ProjectEnvironmentCreate | EnvironmentUpdate) => void;
}) {
  const [form] = Form.useForm<ProjectEnvironmentCreate & { default_headers_text: string }>();
  return (
    <Modal
      title={title}
      open
      width={560}
      confirmLoading={loading}
      onCancel={onCancel}
      destroyOnClose
      onOk={() => form.validateFields().then((values) => {
        let default_headers: Record<string, string>;
        try {
          const parsed = JSON.parse(values.default_headers_text || '{}');
          if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error();
          default_headers = Object.fromEntries(
            Object.entries(parsed).map(([key, value]) => [key, String(value)]),
          );
        } catch {
          form.setFields([{ name: 'default_headers_text', errors: ['请输入有效的 JSON 对象'] }]);
          return;
        }
        onSubmit({
          name: values.name,
          display_name: values.display_name,
          base_url: values.base_url,
          gateway_prefix: values.gateway_prefix,
          default_headers,
          description: values.description,
          is_default: values.is_default,
          is_active: values.is_active,
        } as ProjectEnvironmentCreate | EnvironmentUpdate);
      })}
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
                default_headers_text: JSON.stringify(editing.default_headers ?? {}, null, 2),
                description: editing.description,
                is_default: editing.is_default,
                is_active: editing.is_active,
              }
            : {
                display_name: '',
                base_url: '',
                gateway_prefix: '',
                default_headers_text: '{}',
                is_default: false,
                is_active: true,
              }
        }
      >
        {/* 环境标识创建后固定；每个项目独立配置自己的目标地址。 */}
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
        <Form.Item name="base_url" label="被测服务地址" rules={[{ required: !editing && !catalogMode, message: '请输入被测服务地址' }]}>
          <Input placeholder="https://test-api.example.com" />
        </Form.Item>
        <Form.Item name="gateway_prefix" label="网关前缀">
          <Input placeholder="/api/v1" />
        </Form.Item>
        <Form.Item
          name="default_headers_text"
          label="默认请求头（JSON）"
          extra="仅此项目的请求会使用这些请求头；执行环境选择器不会返回请求头内容。"
        >
          <Input.TextArea rows={3} placeholder={'{\n  "Authorization": "Bearer …"\n}'} />
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
