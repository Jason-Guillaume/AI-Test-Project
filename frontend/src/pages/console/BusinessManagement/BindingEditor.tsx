// API 绑定编辑器：管理单个步骤与具体 API 接口的绑定关系，以及输入/输出字段映射。
// 核心设计：业务步骤通过 api_id 引用接口管理中的接口，不复制接口 Schema。
// 绑定有效性实时判定：接口被删除 → valid=false（已删除）；接口被废弃 → valid=false（已废弃）。
// 映射 = 业务变量 ↔ API 位置（body/header/query/path/response）+ 字段路径。
import { useState } from 'react';
import { App, Alert, Button, Empty, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag } from 'antd';
import { PlusOutlined, LinkOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { businessApi } from '@/features/business/api/business';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { getErrorMessage } from '@/shared/api/client';
import { API_LOCATION_INPUT_OPTIONS, API_LOCATION_OUTPUT_OPTIONS } from './constants';
import type { BusinessActionDetail, BusinessApiMapping, BusinessApiMappingCreate, BusinessApiMappingUpdate, BusinessBindingCreate, BusinessBindingUpdate } from '@/features/business/contracts';


export function BindingEditor({
  action,
  projectId,
  onChanged,
}: {
  action: BusinessActionDetail;
  projectId: number;
  onChanged: () => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [createForm] = Form.useForm<BusinessBindingCreate & { api_keyword?: string }>();
  const [editForm] = Form.useForm<BusinessBindingUpdate & { api_keyword?: string }>();
  const [createApiKeyword, setCreateApiKeyword] = useState('');
  const [editApiKeyword, setEditApiKeyword] = useState('');

  const binding = action.binding;

  const createApisQuery = useQuery({
    queryKey: ['api-catalog', projectId, 'apis', createApiKeyword, 'select'],
    queryFn: () =>
      apiCatalogApi.listApis(projectId, {
        page: 1,
        page_size: 50,
        keyword: createApiKeyword || undefined,
        status: 'ACTIVE',
      }),
    enabled: createOpen,
  });

  const editApisQuery = useQuery({
    queryKey: ['api-catalog', projectId, 'apis', editApiKeyword, 'select'],
    queryFn: () =>
      apiCatalogApi.listApis(projectId, {
        page: 1,
        page_size: 50,
        keyword: editApiKeyword || undefined,
      }),
    enabled: editOpen,
  });

  const createMutation = useMutation({
    mutationFn: (body: BusinessBindingCreate) => businessApi.createBinding(action.id, body),
    onSuccess: () => {
      message.success('绑定已创建');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setCreateOpen(false);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: BusinessBindingUpdate }) =>
      businessApi.updateBinding(id, body),
    onSuccess: () => {
      message.success('绑定已更新');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setEditOpen(false);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: () => binding! && businessApi.removeBinding(binding.id),
    onSuccess: () => {
      message.success('绑定已删除');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  if (!binding) {
    return (
      <div>
        <Empty description="该步骤尚未绑定 API 接口" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        <Button type="primary" icon={<LinkOutlined />} onClick={() => { createForm.resetFields(); setCreateApiKeyword(''); setCreateOpen(true); }}>
          创建 API 绑定
        </Button>
      </div>
    );
  }

  if (binding.binding_type === 'WEB') {
    return <Space direction="vertical" style={{ width: '100%' }}>
      <Alert type={binding.valid ? 'success' : 'warning'} message={`WEB 绑定：${binding.name ?? ''}`}
        description={binding.invalid_reason ?? '结构化浏览器步骤由 Web UI 自动化模块维护；可通过运行时输出变量连接后续 API 动作。'} />
      <Space>
        <Switch checked={binding.enabled} checkedChildren="启用" unCheckedChildren="停用" onChange={checked => updateMutation.mutate({ id: binding.id, body: { enabled: checked } })} />
        <Button href="/console/web-ui">管理 Web 用例</Button>
        <Popconfirm title="删除 WEB 绑定？" onConfirm={() => deleteMutation.mutate()}><Button danger>删除绑定</Button></Popconfirm>
      </Space>
    </Space>;
  }

  const apis = createApisQuery.data?.items ?? [];
  const editApis = editApisQuery.data?.items ?? [];

  return (
    <div>
      <Alert
        type={binding.valid ? 'success' : 'warning'}
        showIcon
        message={
          <Space>
            <span>绑定状态：</span>
            <Tag color={binding.valid ? 'green' : 'red'}>{binding.valid ? '有效' : '已失效'}</Tag>
            {binding.invalid_reason && <span style={{ color: '#999' }}>{binding.invalid_reason}</span>}
          </Space>
        }
        style={{ marginBottom: 12 }}
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <Space direction="vertical" size={0}>
          <Space size={8}>
            <span style={{ fontWeight: 600 }}>{binding.api_name ?? '（接口已删除）'}</span>
            {binding.api_method && <Tag color="blue">{binding.api_method}</Tag>}
            {binding.api_path && <code style={{ fontSize: 12 }}>{binding.api_path}</code>}
          </Space>
          {binding.api_status && <Tag>{binding.api_status}</Tag>}
        </Space>
        <Space>
          <Switch
            size="small"
            checked={binding.enabled}
            checkedChildren="启用"
            unCheckedChildren="停用"
            onChange={(checked) => updateMutation.mutate({ id: binding.id, body: { enabled: checked } })}
          />
          <Button size="small" onClick={() => {
            editForm.setFieldsValue({ api_id: binding.api_id, enabled: binding.enabled });
            setEditApiKeyword('');
            setEditOpen(true);
          }}>
            更换接口
          </Button>
          <Popconfirm
            title="删除绑定会同时删除其下所有映射，确认？"
            onConfirm={(e) => { e?.stopPropagation(); deleteMutation.mutate(); }}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger>删除绑定</Button>
          </Popconfirm>
        </Space>
      </div>

      <BindingMappingEditor action={action} onChanged={onChanged} />

      <Modal
        title="创建 API 绑定"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          const values = await createForm.validateFields();
          await createMutation.mutateAsync({
            binding_type: 'API',
            api_id: values.api_id,
            enabled: true,
          });
        }}
        confirmLoading={createMutation.isPending}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form<BusinessBindingCreate & { api_keyword?: string }> form={createForm} layout="vertical">
          <Form.Item name="api_id" label="选择 API 接口" rules={[{ required: true, message: '请选择 API 接口' }]}>
            <Select
              showSearch
              filterOption={false}
              onSearch={setCreateApiKeyword}
              loading={createApisQuery.isPending}
              placeholder="搜索接口名称或路径"
              options={apis.map((a) => ({ value: a.id, label: `${a.method} ${a.path} — ${a.name}` }))}
              notFoundContent={createApisQuery.isPending ? '搜索中…' : '无匹配接口'}
            />
          </Form.Item>
          <Alert type="info" message="选择接口后，可在下方配置业务变量与 API 字段的映射关系" style={{ marginTop: 8 }} />
        </Form>
      </Modal>

      <Modal
        title="更换绑定接口"
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={async () => {
          const values = await editForm.validateFields();
          await updateMutation.mutateAsync({
            id: binding.id,
            body: {
              api_id: values.api_id,
              enabled: values.enabled,
            },
          });
        }}
        confirmLoading={updateMutation.isPending}
        okText="更新"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form<BusinessBindingUpdate & { api_keyword?: string }> form={editForm} layout="vertical">
          <Form.Item name="api_id" label="选择 API 接口" rules={[{ required: true, message: '请选择 API 接口' }]}>
            <Select
              showSearch
              filterOption={false}
              onSearch={setEditApiKeyword}
              loading={editApisQuery.isPending}
              placeholder="搜索接口名称或路径"
              options={editApis.map((a) => ({ value: a.id, label: `${a.method} ${a.path} — ${a.name} (${a.status})` }))}
              notFoundContent={editApisQuery.isPending ? '搜索中…' : '无匹配接口'}
            />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ---- 映射编辑器（输入 + 输出） ----
function BindingMappingEditor({
  action,
  onChanged,
}: {
  action: BusinessActionDetail;
  onChanged: () => void;
}) {
  const binding = action.binding;
  if (!binding) return null;

  const inputVars = action.input_variables.map((v) => v.name);
  const outputVars = action.output_variables.map((v) => v.name);

  return (
    <Space direction="vertical" style={{ width: '100%', marginTop: 8 }}>
      <MappingSection
        title="输入映射（业务输入变量 → API 请求位置）"
        direction="INPUT"
        bindings={binding.input_mappings}
        variableOptions={inputVars}
        bindingId={binding.id}
        onChanged={onChanged}
      />
      <MappingSection
        title="输出映射（API 响应位置 → 业务输出变量）"
        direction="OUTPUT"
        bindings={binding.output_mappings}
        variableOptions={outputVars}
        bindingId={binding.id}
        onChanged={onChanged}
      />
    </Space>
  );
}

function MappingSection({
  title,
  direction,
  bindings,
  variableOptions,
  bindingId,
  onChanged,
}: {
  title: string;
  direction: 'INPUT' | 'OUTPUT';
  bindings: BusinessApiMapping[];
  variableOptions: string[];
  bindingId: number;
  onChanged: () => void;
}) {
  const { message } = App.useApp();
  const [addOpen, setAddOpen] = useState(false);
  const [editItem, setEditItem] = useState<{ id: number; values: BusinessApiMappingUpdate } | null>(null);
  const [form] = Form.useForm<BusinessApiMappingCreate>();

  const createMutation = useMutation({
    mutationFn: (body: BusinessApiMappingCreate) => businessApi.createMapping(bindingId, body),
    onSuccess: () => {
      message.success('映射已添加');
      setAddOpen(false);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: BusinessApiMappingUpdate }) =>
      businessApi.updateMapping(id, values),
    onSuccess: () => {
      message.success('映射已更新');
      setEditItem(null);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => businessApi.removeMapping(id),
    onSuccess: () => {
      message.success('映射已删除');
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const columns = [
    {
      title: '业务变量',
      dataIndex: 'business_variable',
      width: 140,
      render: (v: string) => <span style={{ fontWeight: 500 }}>{v}</span>,
    },
    {
      title: 'API 位置',
      dataIndex: 'api_location',
      width: 100,
      render: (v: string) => <Tag color="cyan">{v}</Tag>,
    },
    {
      title: '字段路径 / 表达式',
      key: 'path',
      render: (_: unknown, r: { api_field: string | null; expression: string | null }) => (
        <Space direction="vertical" size={0}>
          {r.api_field && <code style={{ fontSize: 12 }}>{r.api_field}</code>}
          {r.expression && <code style={{ fontSize: 12, color: '#666' }}>{r.expression}</code>}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'op',
      width: 120,
      render: (_: unknown, r: BusinessApiMapping) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setEditItem({
                id: r.id,
                values: {
                  direction: r.direction,
                  business_variable: r.business_variable,
                  api_location: r.api_location,
                  api_field: r.api_field ?? undefined,
                  expression: r.expression ?? undefined,
                },
              });
              form.setFieldsValue(r);
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除？"
            onConfirm={(e) => { e?.stopPropagation(); deleteMutation.mutate(r.id); }}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontWeight: 500, fontSize: 13 }}>{title}</span>
        <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => {
          form.resetFields();
          form.setFieldsValue({ direction, api_location: direction === 'INPUT' ? 'BODY' : 'RESPONSE' });
          setAddOpen(true);
        }}>
          新增映射
        </Button>
      </div>
      {bindings.length === 0 ? (
        <div style={{ color: '#999', fontSize: 12, padding: '4px 0' }}>暂无映射</div>
      ) : (
        <Table rowKey="id" columns={columns} dataSource={bindings} pagination={false} size="small" />
      )}

      <MappingFormModal
        open={addOpen || editItem != null}
        title={editItem ? '编辑映射' : '新增映射'}
        direction={direction}
        variableOptions={variableOptions}
        onClose={() => { setAddOpen(false); setEditItem(null); }}
        onSubmit={async () => {
          const values = await form.validateFields();
          if (editItem) {
            await updateMutation.mutateAsync({
              id: editItem.id,
              values: {
                business_variable: values.business_variable,
                api_location: values.api_location,
                api_field: values.api_field ?? null,
                expression: values.expression ?? null,
              },
            });
          } else {
            await createMutation.mutateAsync({
              ...values,
              direction,
              api_field: values.api_field ?? null,
              expression: values.expression ?? null,
            });
          }
        }}
        form={form}
        submitting={createMutation.isPending || updateMutation.isPending}
      />
    </div>
  );
}

function MappingFormModal({
  open,
  title,
  direction,
  variableOptions,
  onClose,
  onSubmit,
  form,
  submitting,
}: {
  open: boolean;
  title: string;
  direction: 'INPUT' | 'OUTPUT';
  variableOptions: string[];
  onClose: () => void;
  onSubmit: () => Promise<void>;
  form: ReturnType<typeof Form.useForm<BusinessApiMappingCreate>>[0];
  submitting: boolean;
}) {
  const locationOptions = direction === 'INPUT' ? API_LOCATION_INPUT_OPTIONS : API_LOCATION_OUTPUT_OPTIONS;
  return (
    <Modal title={title} open={open} onCancel={onClose} onOk={onSubmit} confirmLoading={submitting} okText="保存" cancelText="取消" destroyOnClose width={520}>
      <Form<BusinessApiMappingCreate> form={form} layout="vertical">
        <Form.Item name="business_variable" label="业务变量" rules={[{ required: true, message: '请选择业务变量' }]}>
          <Select
            options={variableOptions.map((v) => ({ value: v, label: v }))}
            placeholder="选择该步骤的业务变量"
            allowClear
            showSearch
            optionFilterProp="label"
          />
        </Form.Item>
        <Form.Item name="api_location" label="API 位置" rules={[{ required: true, message: '请选择 API 位置' }]}>
          <Select options={locationOptions} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="api_field" label="字段路径" tooltip="如 body.project_id 或 data.id">
          <Input placeholder="如 project_id、$.data.id" />
        </Form.Item>
        <Form.Item name="expression" label="转换表达式（可选）" tooltip="如 String(project_id)">
          <Input />
        </Form.Item>
      </Form>
    </Modal>
  );
}
