import { collectPages } from '@/api/pagination';
// 模型配置：配置维护、启停、默认项、供应商目录。
// API Key 只写入不回读；编辑时留空表示保留原密钥。
import {
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import {
  modelConfigsApi,
  type ModelConfigurationCreate,
  type ModelConfigurationListQuery,
  type ModelConfigurationUpdate,
} from '@/api/modelConfigs';
import type { ModelConfiguration, Paginated } from '@/types';
import {
  ErrorState,
  EmptyState,
  LoadingState,
  PageContainer,
} from '@/components/PageState';
import { type PaginationState } from '@/components/ResourceTable';
import { getErrorMessage } from '@/api/client';
import { PageHeader } from '@/components/PageHeader';

/**
 * 模型配置管理页。
 *
 * 用途：维护全局模型连接、采样参数、成本与有序备用模型路由。
 * 数据来源：modelConfigsApi.list 分页 + 关键词搜索；providers 只在弹窗内单独请求。
 * 是否发请求：是，列表查询 + 各 mutation；providers 独立查询（弹窗打开时按需拉取）。
 * 权限：所有写操作仅平台管理员可用；后端保证「启用状态必须有 API Key」。
 * 失败呈现：mutation 失败通过 message.error(getErrorMessage) 折叠展示；查询失败整页 ErrorState。
 * 空态：无搜索结果时表格空态由 antd 默认展示。
 */
export function AdminModelConfigsPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  // 分页初值：第一页，每页 10 条
  const [pagination, setPagination] = useState<PaginationState>({
    page: 1,
    page_size: 10,
  });
  // 关键词：由搜索框输入，为空则不传给后端
  const [keyword, setKeyword] = useState('');
  // 编辑目标：null 表示不编辑
  const [editing, setEditing] = useState<ModelConfiguration | null>(null);
  // 新建弹窗开关
  const [creating, setCreating] = useState(false);

  // 拼装查询参数：keyword 空串归一为 undefined，避免后端把它当作「空字符串过滤」
  const query: ModelConfigurationListQuery = useMemo(
    () => ({
      page: pagination.page,
      page_size: pagination.page_size,
      keyword: keyword || undefined,
    }),
    [pagination, keyword],
  );

  const listQuery = useQuery({
    queryKey: ['model-configs', query],
    queryFn: () => modelConfigsApi.list(query),
  });

  // 统一缓存失效入口：任何写操作成功后清掉整个 model-configs 命名空间
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['model-configs'] });
  };

  const createMutation = useMutation({
    mutationFn: modelConfigsApi.create,
    onSuccess: () => {
      message.success('已创建');
      invalidate();
      setPagination((p) => ({ ...p, page: 1 }));
      setCreating(false);
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const updateMutation = useMutation({
    // 更新走 (id, body) 二元参数
    mutationFn: ({ id, body }: { id: number; body: ModelConfigurationUpdate }) =>
      modelConfigsApi.update(id, body),
    onSuccess: () => {
      message.success('已更新');
      invalidate();
      setEditing(null);
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const setDefaultMutation = useMutation({
    mutationFn: modelConfigsApi.setDefault,
    onSuccess: () => {
      message.success('已设为默认');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });
  const deleteMutation = useMutation({
    mutationFn: modelConfigsApi.remove,
    onSuccess: () => {
      message.success('已删除');
      invalidate();
      setPagination((p) => ({ ...p, page: 1 }));
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

  const data: Paginated<ModelConfiguration> = listQuery.data;

  return (
    <PageContainer>
      <PageHeader title="模型配置" subtitle="维护模型连接、启用状态与默认模型" />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Input.Search
          placeholder="按名称/供应商搜索"
          allowClear
          enterButton
          style={{ width: 320, maxWidth: '100%' }}
          onSearch={(v) => {
            setKeyword(v);
            setPagination((p) => ({ ...p, page: 1 }));
          }}
        />
        <Button type="primary" onClick={() => setCreating(true)}>新增模型配置</Button>
      </div>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>共 {data.total} 个模型配置</Typography.Text>
      {data.items.length ? <Row gutter={[12, 12]}>
        {data.items.map((model) => <Col xs={24} md={12} xl={8} xxl={6} key={model.id}>
          <Card size="small" style={{ height: '100%', background: model.is_default ? '#fffaf0' : undefined }} styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', padding: 12 } }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ minWidth: 0 }}>
                <Typography.Text strong ellipsis={{ tooltip: model.label }} style={{ display: 'block' }}>{model.label}</Typography.Text>
                <Space size={4} style={{ marginTop: 4 }}>
                  <Tag>{model.provider.toUpperCase()}</Tag>
                  {model.is_default && <Tag color="gold">默认</Tag>}
                </Space>
              </div>
              <Tag color={model.is_enabled ? 'green' : 'default'}>{model.is_enabled ? '正常' : '已停用'}</Tag>
            </div>
            <Typography.Text type="secondary" ellipsis={{ tooltip: model.model_name }} style={{ display: 'block', marginTop: 8 }}>{model.model_name}</Typography.Text>
            <Space wrap size={[4, 4]} style={{ marginTop: 8 }}>
              {model.has_api_key ? <Tag color="green">{model.masked_api_key || '密钥已配置'}</Tag> : <Tag color="orange">密钥未配置</Tag>}
              <Tag>{model.fallback_model_ids.length} 个备用模型</Tag>
            </Space>
            <div style={{ marginTop: 'auto', paddingTop: 10 }}>
              <Button
                block
                disabled={model.is_default || !model.is_enabled}
                loading={setDefaultMutation.isPending && setDefaultMutation.variables === model.id}
                onClick={() => setDefaultMutation.mutate(model.id)}
              >
                {model.is_default ? '已设为默认' : '设为默认'}
              </Button>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
                <Button type="link" style={{ paddingInline: 0 }} onClick={() => setEditing(model)}>编辑配置</Button>
                <Button
                  danger
                  type="text"
                  aria-label={`删除模型配置 ${model.label}`}
                  disabled={model.is_default}
                  loading={deleteMutation.isPending && deleteMutation.variables === model.id}
                  icon={<DeleteOutlined />}
                  onClick={() => modal.confirm({ title: `删除模型配置「${model.label}」？`, okButtonProps: { danger: true }, onOk: () => deleteMutation.mutateAsync(model.id) })}
                />
              </div>
            </div>
          </Card>
        </Col>)}
      </Row> : <EmptyState description={keyword ? '没有匹配的模型配置' : '还没有模型配置'} />}
      {data.total > pagination.page_size && <Pagination
        current={pagination.page}
        pageSize={pagination.page_size}
        total={data.total}
        showSizeChanger
        showTotal={(total) => `共 ${total} 个模型配置`}
        pageSizeOptions={[10, 20, 50]}
        onChange={(page, pageSize) => setPagination({ page, page_size: pageSize })}
        style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 20 }}
      />}

      {creating && (
        <ModelFormModal
          title="新增模型配置"
          loading={createMutation.isPending}
          onCancel={() => setCreating(false)}
          onSubmit={(body) =>
            // 新建表单必然含全部必填字段；复用同一表单组件故做一次收窄。
            createMutation.mutate(body as ModelConfigurationCreate)
          }
        />
      )}
      {editing && (
        <ModelFormModal
          title={`编辑：${editing.label}`}
          editing={editing}
          loading={updateMutation.isPending}
          onCancel={() => setEditing(null)}
          onSubmit={(body) =>
            updateMutation.mutate({ id: editing.id, body })
          }
        />
      )}
    </PageContainer>
  );
}

/**
 * 模型配置新建/编辑共用表单弹窗。
 *
 * 用途：新建时收全部字段；编辑时回填当前值，但 API Key 不回读明文——
 *       留空表示保留原密钥（后端语义），填写新值表示覆盖。
 * 数据来源：providers 通过 useQuery 单独拉取，用于「供应商」下拉。
 * 是否发请求：本组件不发写请求，仅通过 onSubmit 抛 body 给父组件。
 * 校验：label/model_name 必填；is_enabled=true 时 api_key 必填（与后端一致）。
 * 失败呈现：Form 就地展示 rules 提示；提交进行中标记 loading。
 */
function ModelFormModal({
  title,
  editing,
  loading,
  onCancel,
  onSubmit,
}: {
  title: string;
  editing?: ModelConfiguration;
  loading: boolean;
  onCancel: () => void;
  onSubmit: (body: ModelConfigurationCreate | ModelConfigurationUpdate) => void;
}) {
  const [form] = Form.useForm<ModelConfigurationCreate>();
  const { data: providers } = useQuery({
    queryKey: ['model-configs', 'providers'],
    queryFn: () => modelConfigsApi.providers(),
  });
  const { data: modelOptions } = useQuery({
    queryKey: ['model-configs', 'fallback-options'],
    queryFn: () => collectPages((page) => modelConfigsApi.list({ page, page_size: 200 })),
  });

  return (
    <Modal
      title={title}
      open
      width={640}
      confirmLoading={loading}
      onCancel={onCancel}
      destroyOnClose
      onOk={() => form.validateFields().then((v) => onSubmit(v))}
    >
      <Form
        layout="vertical"
        form={form}
        initialValues={
          editing
            ? {
                label: editing.label,
                provider: editing.provider,
                api_base: editing.api_base,
                model_name: editing.model_name,
                temperature: editing.temperature,
                max_tokens: editing.max_tokens,
                timeout: editing.timeout,
                cost_per_1k_input: editing.cost_per_1k_input,
                cost_per_1k_output: editing.cost_per_1k_output,
                is_enabled: editing.is_enabled,
                is_default: editing.is_default,
                fallback_model_ids: editing.fallback_model_ids ?? [],
                sort_order: editing.sort_order,
              }
            : {
                provider: 'openai-compatible',
                temperature: 0.2,
                max_tokens: 4096,
                timeout: 60,
                is_enabled: true,
                is_default: false,
                fallback_model_ids: [],
                sort_order: 0,
              }
        }
      >
        <Form.Item name="label" label="展示名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="provider" label="供应商">
          <Select
            options={(providers ?? []).map((p) => ({
              value: p.value,
              label: p.label,
            }))}
          />
        </Form.Item>
        <Form.Item name="api_base" label="API Base" rules={[{ required: !editing }]}>
          <Input placeholder="https://api.example.com/v1" />
        </Form.Item>
        <Form.Item
          name="api_key"
          label={
            editing
              ? 'API Key（留空保留原密钥，不会回读原值）'
              : 'API Key'
          }
          dependencies={['is_enabled']}
          rules={[
            ({ getFieldValue }) => ({
              // API Key 的联体校验：启用中且非编辑态时必填，口径与后端 400 校验一致。
              validator(_, value) {
                // 与后端保持一致：启用状态的模型必须有密钥，否则直接 400。
                if (!editing && getFieldValue('is_enabled') && !value) {
                  return Promise.reject(new Error('启用状态的模型必须填写 API Key'));
                }
                return Promise.resolve();
              },
            }),
          ]}
        >
          <Input.Password
            placeholder={editing ? '留空表示保留已配置的密钥' : '输入 API Key'}
            autoComplete="new-password"
          />
        </Form.Item>
        <Form.Item name="model_name" label="模型名称" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item
          name="fallback_model_ids"
          label="备用模型（按顺序尝试，最多三个）"
          extra="任务切换前会重新检查启用状态和组织授权；未获授权的候选会跳过。"
        >
          <Select
            mode="multiple"
            maxCount={3}
            allowClear
            placeholder="主模型失败后依次接手"
            options={(modelOptions?.items ?? [])
              .filter((model) => model.id !== editing?.id)
              .map((model) => ({ value: model.id, label: `${model.label}（${model.model_name}）` }))}
          />
        </Form.Item>
        <Space wrap>
          <Form.Item name="temperature" label="采样温度">
            <InputNumber min={0} max={2} step={0.1} />
          </Form.Item>
          <Form.Item name="max_tokens" label="最大输出 Token">
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="timeout" label="超时(秒)">
            <InputNumber min={1} max={600} />
          </Form.Item>
          <Form.Item name="sort_order" label="排序">
            <InputNumber />
          </Form.Item>
        </Space>
        <Space wrap>
          <Form.Item name="cost_per_1k_input" label="千输入 Token 成本">
            <InputNumber min={0} step={0.01} />
          </Form.Item>
          <Form.Item name="cost_per_1k_output" label="千输出 Token 成本">
            <InputNumber min={0} step={0.01} />
          </Form.Item>
        </Space>
        <Space>
          <Form.Item name="is_enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_default" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Space>
        <Table
          size="small"
          pagination={false}
          dataSource={[
            { k: '当前密钥状态', v: editing?.has_api_key ? `已配置 ${editing.masked_api_key}` : '未配置' },
          ]}
          columns={[
            { title: '说明', dataIndex: 'k' },
            { title: '值', dataIndex: 'v' },
          ]}
        />
      </Form>
    </Modal>
  );
}
