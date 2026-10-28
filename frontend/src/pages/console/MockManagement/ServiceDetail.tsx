import { collectPages } from '@/api/pagination';
// Mock 服务详情：服务信息 + Runtime 调用地址 + 接口（Endpoint）管理。
//
// 数据：
//   - GET/PATCH/DELETE /mock-services/{id}
//   - GET/POST  /mock-services/{id}/endpoints
//   - GET/PATCH/DELETE /mock-endpoints/{id}
//
// 接口按 method + path 匹配，path 支持 {param} 路径参数；api_id 可空关联接口目录。
import { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Flex,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  EditOutlined,
  KeyOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { apiCatalogApi } from '@/api/apiCatalog';
import { getErrorMessage } from '@/api/client';
import { buildRuntimeUrl, mockManagementApi } from '@/api/mockManagement';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { fmtTime } from '@/shared/format';
import type { ApiInterface, MockEndpoint } from '@/types';
import { HTTP_METHOD_OPTIONS } from './constants';

interface EndpointFormValues {
  name: string;
  method: string;
  path: string;
  api_id?: number | null;
  description?: string;
  enabled: boolean;
}

/** 新建 / 编辑 Mock 接口弹窗。 */
function EndpointFormModal({
  projectId,
  open,
  editing,
  onClose,
  onSubmit,
  loading,
}: {
  projectId: number;
  serviceId: number;
  open: boolean;
  editing: MockEndpoint | null;
  onClose: () => void;
  onSubmit: (values: EndpointFormValues) => void;
  loading: boolean;
}) {
  const [form] = Form.useForm<EndpointFormValues>();
  const apisQuery = useQuery({
    queryKey: ['apis-for-mock-endpoint', projectId],
    queryFn: () => collectPages((page) => apiCatalogApi.listApis(projectId, { page, page_size: 200 })),
    enabled: open,
  });
  const apis: ApiInterface[] = apisQuery.data?.items ?? [];
  const initialValues: EndpointFormValues = editing
    ? {
        name: editing.name,
        method: editing.method,
        path: editing.path,
        api_id: editing.api_id,
        description: editing.description ?? '',
        enabled: editing.enabled,
      }
    : { name: '', method: 'GET', path: '/items', api_id: null, description: '', enabled: true };

  return (
    <Modal
      key={editing ? `edit-${editing.id}` : 'create'}
      title={editing ? `编辑 Mock 接口：${editing.name}` : '新建 Mock 接口'}
      open={open}
      onCancel={onClose}
      confirmLoading={loading}
      onOk={() => {
        form.validateFields().then((values) => onSubmit(values)).catch(() => undefined);
      }}
    >
      <Form form={form} layout="vertical" initialValues={initialValues}>
        <Form.Item
          name="name"
          label="接口名称"
          rules={[{ required: true, message: '请输入接口名称' }, { max: 200 }]}
        >
          <Input placeholder="如：查询路径" maxLength={200} />
        </Form.Item>
        <Flex gap="small">
          <Form.Item name="method" label="HTTP 方法" rules={[{ required: true }]} style={{ width: 150 }}>
            <Select options={HTTP_METHOD_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="path"
            label="接口路径"
            tooltip="支持 {param} 路径参数，如 /items/{id}"
            rules={[{ required: true, message: '请输入接口路径' }, { max: 500 }]}
            style={{ flex: 1 }}
          >
            <Input placeholder="/items/{id}" maxLength={500} />
          </Form.Item>
        </Flex>
        <Form.Item name="api_id" label="关联接口目录（可选）">
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            loading={apisQuery.isLoading}
            options={apis.map((a) => ({ value: a.id, label: `${a.method} ${a.path}（${a.name}）` }))}
            placeholder="关联已登记的接口，仅关联不复制定义"
          />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea placeholder="该接口 Mock 的用途" maxLength={1000} rows={2} />
        </Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch checkedChildren="启用" unCheckedChildren="停用" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

/** Mock 服务详情页。 */
export function ConsoleMockServiceDetailPage() {
  const { serviceId } = useParams<{ serviceId: string }>();
  const { currentProjectId } = useConsoleScope();
  const { message: msg } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MockEndpoint | null>(null);

  const id = Number(serviceId);
  const serviceQuery = useQuery({
    queryKey: ['mock-service', id],
    queryFn: () => mockManagementApi.getService(id),
    enabled: Number.isFinite(id),
  });
  const service = serviceQuery.data;

  const endpointsQuery = useQuery({
    queryKey: ['mock-endpoints', id],
    queryFn: () => collectPages((page) => mockManagementApi.listEndpoints(id, { page, page_size: 100 })),
    enabled: Number.isFinite(id),
  });
  const endpoints = endpointsQuery.data?.items ?? [];

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['mock-endpoints', id] });
    queryClient.invalidateQueries({ queryKey: ['mock-service', id] });
  };

  const createEndpointMutation = useMutation({
    mutationFn: (values: EndpointFormValues) =>
      mockManagementApi.createEndpoint(id, {
        name: values.name,
        method: values.method,
        path: values.path,
        api_id: values.api_id ?? null,
        description: values.description || null,
        enabled: values.enabled,
      }),
    onSuccess: (created) => {
      invalidate();
      msg.success('Mock 接口已创建');
      setModalOpen(false);
      setEditing(null);
      navigate(`/console/mock-management/endpoints/${created.id}`);
    },
    onError: (e) => msg.error(getErrorMessage(e, '创建 Mock 接口失败')),
  });

  const updateEndpointMutation = useMutation({
    mutationFn: ({ target, values }: { target: MockEndpoint; values: EndpointFormValues }) =>
      mockManagementApi.updateEndpoint(target.id, {
        name: values.name,
        method: values.method,
        path: values.path,
        description: values.description || null,
        enabled: values.enabled,
        revision: target.revision,
      }),
    onSuccess: () => {
      invalidate();
      msg.success('Mock 接口已更新');
      setModalOpen(false);
      setEditing(null);
    },
    onError: (e) => msg.error(getErrorMessage(e, '更新 Mock 接口失败')),
  });

  const deleteEndpointMutation = useMutation({
    mutationFn: (targetId: number) => mockManagementApi.removeEndpoint(targetId),
    onSuccess: () => {
      invalidate();
      msg.success('Mock 接口已删除（其场景与匹配规则一并删除）');
    },
    onError: (e) => msg.error(getErrorMessage(e, '删除 Mock 接口失败')),
  });

  const resetTokenMutation = useMutation({
    mutationFn: () => mockManagementApi.resetToken(id),
    onSuccess: (data) => {
      invalidate();
      msg.success('Token 已重置，请立即复制保存');
      Modal.info({
        title: '新 Token（只显示这一次）',
        icon: <KeyOutlined />,
        content: (
          <div>
            <Alert
              type="warning"
              showIcon
              message="旧 Token 已失效；平台只保存哈希，关闭后无法再查看。"
              style={{ marginBottom: 12 }}
            />
            <Typography.Paragraph copyable={{ text: data.runtime_token }} code style={{ wordBreak: 'break-all' }}>
              {data.runtime_token}
            </Typography.Paragraph>
          </div>
        ),
      });
    },
    onError: (e) => msg.error(getErrorMessage(e, '重置 Token 失败')),
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }
  if (serviceQuery.isLoading) return <LoadingState />;
  if (!service) {
    return (
      <PageContainer>
        <EmptyState description="Mock 服务不存在或已被删除" />
      </PageContainer>
    );
  }

  const handleEndpointForm = (values: EndpointFormValues) => {
    if (editing) updateEndpointMutation.mutate({ target: editing, values });
    else createEndpointMutation.mutate(values);
  };

  const columns: TableColumnsType<MockEndpoint> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '方法',
      dataIndex: 'method',
      width: 100,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: '路径',
      dataIndex: 'path',
      width: 260,
      render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
    },
    { title: '名称', dataIndex: 'name', width: 200 },
    {
      title: '关联接口',
      dataIndex: 'api_id',
      width: 100,
      render: (v: number | null) => (v ? <Tag>#{v}</Tag> : '-'),
    },
    {
      title: '场景数',
      dataIndex: 'scenario_count',
      width: 90,
      render: (v: number) => v,
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
    { title: '更新时间', dataIndex: 'updated_at', width: 160, render: (v: string) => fmtTime(v) },
    {
      title: '操作',
      width: 220,
      fixed: 'right',
      render: (_, row) => (
        <Space size="small" wrap>
          <Link to={`/console/mock-management/endpoints/${row.id}`}>
            <Button size="small">场景</Button>
          </Link>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditing(row);
              setModalOpen(true);
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除该 Mock 接口？"
            description="其场景与匹配规则将一并删除。"
            onConfirm={() => deleteEndpointMutation.mutate(row.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} loading={deleteEndpointMutation.isPending}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }} wrap="wrap" gap="middle">
        <Flex align="center" gap="middle" wrap="wrap">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/console/mock-management')}>
            返回
          </Button>
          <Typography.Title level={5} style={{ margin: 0 }}>
            {service.name} <Tag color="geekblue">{service.service_key}</Tag>
          </Typography.Title>
          {service.enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>}
        </Flex>
        <Space wrap>
          <Popconfirm
            title="确认重置 Token？"
            description="旧 Token 将立即失效，被测系统需要重新配置。"
            onConfirm={() => resetTokenMutation.mutate()}
          >
            <Button icon={<KeyOutlined />} loading={resetTokenMutation.isPending}>
              重置 Token
            </Button>
          </Popconfirm>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null);
              setModalOpen(true);
            }}
          >
            新建 Mock 接口
          </Button>
        </Space>
      </Flex>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions
          size="small"
          column={2}
          items={[
            {
              key: 'url',
              label: 'Runtime 调用地址',
              children: (
                <Space wrap>
                  {/* 用 service.project_id 而非当前作用域：跨项目访问时 currentProjectId 会给出错误地址 */}
                  <Typography.Text copyable={{ text: buildRuntimeUrl(service.project_id, service.service_key, '{path}') }} code>
                    {buildRuntimeUrl(service.project_id, service.service_key, '{path}')}
                  </Typography.Text>
                </Space>
              ),
            },
            {
              key: 'auth',
              label: '执行面鉴权',
              children: service.public_runtime ? (
                <Tag color="orange">匿名可调用（public_runtime）</Tag>
              ) : service.runtime_token_set ? (
                <Tag color="green">需 X-Mock-Token</Tag>
              ) : (
                <Tag color="red">未配置 Token</Tag>
              ),
            },
            { key: 'base_path', label: '基础路径', children: service.base_path || '-' },
            { key: 'desc', label: '描述', children: service.description || '-' },
            { key: 'count', label: '接口 / 场景', children: `${service.endpoint_count} / ${service.scenario_count}` },
            { key: 'created', label: '创建时间', children: fmtTime(service.created_at) },
          ]}
        />
      </Card>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="被测系统如何接入"
        description={(
          <span>
            把被测系统里对该依赖的调用地址改为上面的 Runtime 地址，并设置请求头{' '}
            <Typography.Text code>X-Mock-Token: {service.runtime_token_set ? '****（见「重置 Token」获取）' : '未配置'}</Typography.Text>
            {'、'}<Typography.Text code>Content-Type: application/json</Typography.Text>。
            测试执行期间若用例声明了 required_mocks，平台会自动附带 <Typography.Text code>X-Mock-Context</Typography.Text> 完成场景隔离。
          </span>
        )}
      />

      {endpointsQuery.isLoading ? (
        <LoadingState />
      ) : endpointsQuery.isError ? (
        <ErrorState error={endpointsQuery.error} onRetry={endpointsQuery.refetch} />
      ) : endpoints.length === 0 ? (
        <EmptyState description="该服务下还没有 Mock 接口，点击「新建 Mock 接口」开始" />
      ) : (
        <Table<MockEndpoint>
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={endpoints}
          scroll={{ x: 1280 }}
          pagination={false}
        />
      )}

      <EndpointFormModal
        projectId={currentProjectId}
        serviceId={id}
        open={modalOpen}
        editing={editing}
        loading={createEndpointMutation.isPending || updateEndpointMutation.isPending}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
        onSubmit={handleEndpointForm}
      />
    </PageContainer>
  );
}
