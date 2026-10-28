import { collectPages } from '@/api/pagination';
// 接口 Mock 与依赖异常模拟 · 服务管理页。
//
// 数据：
//   - GET/POST /projects/{pid}/mock-services        服务列表 / 新建
//   - GET/PATCH/DELETE /mock-services/{id}          详情 / 编辑 / 删除
//   - POST   /mock-services/{id}/reset-token       重置 Runtime Token
//   - POST   /projects/{pid}/mock-from-api/{api_id} 从接口一键创建
//
// 安全红线：Runtime Token 只存 hash，明文仅在新建 / 重置的响应里返回一次。
// 本页只把明文放在「一次性弹窗」里，关闭即消失，不在表格里展示、不写入 localStorage，
// 也不在任何接口响应回读中期待它存在（只读 runtime_token_set 布尔值）。
import { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
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
  Tooltip,
  Typography,
} from 'antd';
import {
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  HistoryOutlined,
  KeyOutlined,
  PlusOutlined,
  SafetyOutlined,
} from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { apiCatalogApi } from '@/api/apiCatalog';
import { getErrorMessage } from '@/api/client';
import { mockManagementApi } from '@/api/mockManagement';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { fmtTime } from '@/shared/format';
import type {
  ApiInterface,
  CreateMockFromApiRequest,
  MockService,
  MockServiceUpdate,
} from '@/types';
import { API_MOCK_TEMPLATES, MOCK_KEY_PATTERN } from './constants';

interface ServiceFormValues {
  name: string;
  service_key: string;
  base_path?: string;
  description?: string;
  enabled: boolean;
  public_runtime: boolean;
  runtime_token?: string;
}

/** 一次性 token 弹窗：明文只在这里出现，关闭后无法再取回。 */
function TokenResultModal({
  token,
  serviceKey,
  projectId,
  title,
  onClose,
}: {
  token: string | null;
  serviceKey: string;
  projectId: number;
  title: string;
  onClose: () => void;
}) {
  const { message: msg } = App.useApp();
  return (
    <Modal
      title={title}
      open={token != null}
      closable={false}
      footer={[
        <Button key="copy" icon={<CopyOutlined />} onClick={() => { void navigator.clipboard.writeText(token!); msg.success('已复制到剪贴板'); }}>
          复制 Token
        </Button>,
        <Button key="close" type="primary" onClick={onClose}>
          我已保存，关闭
        </Button>,
      ]}
      onCancel={onClose}
    >
      <Alert
        type="warning"
        showIcon
        icon={<SafetyOutlined />}
        message="Token 只显示这一次"
        description="平台只保存 Token 的哈希，明文关闭后无法再查看。请立即复制并配置到被测系统的 X-Mock-Token 请求头；丢失请点「重置 Token」重新生成（旧 Token 会立即失效）。"
      />
      <div style={{ margin: '12px 0 8px' }}>
        <Typography.Text type="secondary">service_key</Typography.Text>
        <div><Tag>{serviceKey}</Tag></div>
      </div>
      <Typography.Paragraph copyable={{ text: token ?? '' }} code style={{ fontSize: 13, wordBreak: 'break-all' }}>
        {token}
      </Typography.Paragraph>
      <Alert
        type="info"
        showIcon
        message="被测系统调用地址"
        description={`\`/api/v1/mock/${projectId}/${serviceKey}/{path}\`（执行面不需要平台登录态）`}
      />
    </Modal>
  );
}

/** 新建 / 编辑 Mock 服务弹窗。 */
function ServiceFormModal({
  open,
  editing,
  onClose,
  onSubmit,
  loading,
}: {
  open: boolean;
  editing: MockService | null;
  onClose: () => void;
  onSubmit: (values: ServiceFormValues) => void;
  loading: boolean;
}) {
  const [form] = Form.useForm<ServiceFormValues>();
  const initialValues: ServiceFormValues = editing
    ? {
        name: editing.name,
        service_key: editing.service_key,
        base_path: editing.base_path ?? '',
        description: editing.description ?? '',
        enabled: editing.enabled,
        public_runtime: editing.public_runtime,
        runtime_token: '',
      }
    : { name: '', service_key: '', base_path: '', description: '', enabled: true, public_runtime: false, runtime_token: '' };

  return (
    <Modal
      key={editing ? `edit-${editing.id}` : 'create'}
      title={editing ? `编辑 Mock 服务：${editing.name}` : '新建 Mock 依赖服务'}
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
          label="服务名称"
          rules={[{ required: true, message: '请输入服务名称' }, { max: 200 }]}
        >
          <Input placeholder="如：地图服务" maxLength={200} />
        </Form.Item>
        <Form.Item
          name="service_key"
          label="服务唯一键"
          tooltip="项目内唯一，被测系统调 Mock 地址时使用"
          rules={[
            { required: true, message: '请输入服务唯一键' },
            { pattern: MOCK_KEY_PATTERN, message: '首字母大写，仅允许字母 / 数字 / 下划线（≤100）' },
          ]}
        >
          <Input placeholder="如：MAP_SERVICE" maxLength={100} disabled={!!editing} />
        </Form.Item>
        <Form.Item name="base_path" label="基础路径（展示用）">
          <Input placeholder="/v1/maps" maxLength={500} />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea placeholder="该依赖服务在本项目中的用途" maxLength={1000} rows={2} />
        </Form.Item>
        <Space size="large" wrap>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Form.Item name="public_runtime" label="允许匿名调用执行面" valuePropName="checked">
            <Switch checkedChildren="允许" unCheckedChildren="需 Token" />
          </Form.Item>
        </Space>
        {!editing && (
          <Form.Item
            name="runtime_token"
            label="自定义 Runtime Token（可选）"
            rules={[{ min: 8, max: 200, message: '长度 8-200' }]}
          >
            <Input.Password placeholder="留空则自动生成" autoComplete="new-password" />
          </Form.Item>
        )}
      </Form>
      <Alert
        type="info"
        showIcon
        message="Token 与安全"
        description="平台只保存 Token 的哈希；明文仅在新建 / 重置后返回一次。默认必须携带 X-Mock-Token 才能调用执行面。"
      />
    </Modal>
  );
}

/** 从接口目录一键创建 Mock 弹窗（§二十 / §二十一 推荐场景模板）。 */
function FromApiModal({
  projectId,
  open,
  onClose,
  onSubmit,
  loading,
}: {
  projectId: number;
  open: boolean;
  onClose: () => void;
  onSubmit: (apiId: number, values: CreateMockFromApiRequest) => void;
  loading: boolean;
}) {
  const [form] = Form.useForm<{ api_id: number; service_key: string; service_name?: string; templates: string[] }>();
  const apisQuery = useQuery({
    queryKey: ['apis-for-mock', projectId],
    queryFn: () => collectPages((page) => apiCatalogApi.listApis(projectId, { page, page_size: 200 })),
    enabled: open,
  });
  const apis: ApiInterface[] = apisQuery.data?.items ?? [];

  return (
    <Modal
      title="从接口一键创建 Mock"
      open={open}
      onCancel={onClose}
      confirmLoading={loading}
      onOk={() => {
        form.validateFields().then((values) => {
          const { api_id, ...rest } = values;
          onSubmit(api_id, rest);
        }).catch(() => undefined);
      }}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ templates: ['NORMAL'] }}
        onValuesChange={(changed) => {
          // 选中接口后自动带出服务名，用户仍可改写。
          if ('api_id' in changed) {
            const picked = apis.find((a) => a.id === changed.api_id);
            if (picked) form.setFieldsValue({ service_name: picked.name });
          }
        }}
      >
        <Form.Item
          name="api_id"
          label="选择接口"
          rules={[{ required: true, message: '请选择一个已登记的接口' }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            loading={apisQuery.isLoading}
            options={apis.map((a) => ({
              value: a.id,
              label: `${a.method} ${a.path}（${a.name}）`,
            }))}
            placeholder="选择要 Mock 的接口"
          />
        </Form.Item>
        <Form.Item
          name="service_key"
          label="服务唯一键"
          rules={[
            { required: true, message: '请输入服务唯一键' },
            { pattern: MOCK_KEY_PATTERN, message: '首字母大写，仅允许字母 / 数字 / 下划线（≤100）' },
          ]}
        >
          <Input placeholder="如：MAP_SERVICE" maxLength={100} />
        </Form.Item>
        <Form.Item name="service_name" label="服务名称（可选）">
          <Input placeholder="默认取接口语义" maxLength={200} />
        </Form.Item>
        <Form.Item
          name="templates"
          label="推荐场景模板"
          tooltip="每个模板生成一个场景：正常 / 各类 HTTP 错误 / 空数据 / 延迟 / 超时"
          rules={[{ required: true, message: '至少选择一个模板' }]}
        >
          <Select mode="multiple" options={API_MOCK_TEMPLATES} placeholder="选择要生成的场景" />
        </Form.Item>
      </Form>
      <Alert
        type="info"
        showIcon
        message="生成内容"
        description="按接口的 method + path 建立 Mock 接口并关联 api_id，再按模板生成场景；每个场景的响应体基于接口已登记的响应结构初始化。"
      />
    </Modal>
  );
}

/** Mock 服务管理页。 */
export function ConsoleMockManagementPage() {
  const { currentProjectId } = useConsoleScope();
  const { message: msg } = App.useApp();
  const queryClient = useQueryClient();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MockService | null>(null);
  const [fromApiOpen, setFromApiOpen] = useState(false);
  const [oneTimeToken, setOneTimeToken] = useState<{ token: string; key: string; title: string } | null>(null);

  const servicesQuery = useQuery({
    queryKey: ['mock-services', currentProjectId],
    queryFn: () => collectPages((page) => mockManagementApi.listServices(currentProjectId!, { page, page_size: 100 })),
    enabled: currentProjectId != null,
  });
  const services = servicesQuery.data?.items ?? [];

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['mock-services', currentProjectId] });

  const createMutation = useMutation({
    mutationFn: (values: ServiceFormValues) =>
      mockManagementApi.createService(currentProjectId!, {
        name: values.name,
        service_key: values.service_key,
        base_path: values.base_path || null,
        description: values.description || null,
        enabled: values.enabled,
        public_runtime: values.public_runtime,
        runtime_token: values.runtime_token || null,
      }),
    onSuccess: (data) => {
      invalidate();
      setModalOpen(false);
      setEditing(null);
      setOneTimeToken({ token: data.runtime_token, key: data.service.service_key, title: 'Mock 服务已创建 · Token 只显示这一次' });
    },
    onError: (e) => msg.error(getErrorMessage(e, '创建 Mock 服务失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: MockServiceUpdate }) =>
      mockManagementApi.updateService(id, values),
    onSuccess: () => {
      invalidate();
      msg.success('Mock 服务已更新');
      setModalOpen(false);
      setEditing(null);
    },
    onError: (e) => msg.error(getErrorMessage(e, '更新 Mock 服务失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => mockManagementApi.removeService(id),
    onSuccess: () => {
      invalidate();
      msg.success('Mock 服务已删除（其接口、场景与调用记录一并删除）');
    },
    onError: (e) => msg.error(getErrorMessage(e, '删除 Mock 服务失败')),
  });

  const resetMutation = useMutation({
    mutationFn: (id: number) => mockManagementApi.resetToken(id),
    onSuccess: (data) => {
      invalidate();
      setOneTimeToken({ token: data.runtime_token, key: data.service.service_key, title: 'Token 已重置 · 只显示这一次' });
    },
    onError: (e) => msg.error(getErrorMessage(e, '重置 Token 失败')),
  });

  const fromApiMutation = useMutation({
    mutationFn: ({ apiId, values }: { apiId: number; values: CreateMockFromApiRequest }) =>
      mockManagementApi.createFromApi(currentProjectId!, apiId, values),
    onSuccess: (data) => {
      invalidate();
      setFromApiOpen(false);
      if (data.runtime_token) {
        setOneTimeToken({ token: data.runtime_token, key: data.service.service_key, title: '已从接口创建 Mock · Token 只显示这一次' });
      } else if (data.service.public_runtime) {
        msg.success('已从接口创建 Mock（公共执行面，无需 Token）');
      } else if (data.service.runtime_token_set) {
        // 后端只在「复用已存在的 service_key」时不返回明文 Token——那把 Token 早在
        // 服务创建时显示过一次，这里若报「无需 Token」会让人以为可以直接调，实际 401。
        msg.warning('已从接口创建 Mock，但复用了已存在的服务：Token 在创建该服务时已显示过一次，请到服务列表「重置 Token」重新获取');
      } else {
        msg.warning('已从接口创建 Mock，但复用了已存在的服务且尚未设置执行面 Token，请到服务列表设置');
      }
    },
    onError: (e) => msg.error(getErrorMessage(e, '从接口创建 Mock 失败')),
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const handleForm = (values: ServiceFormValues) => {
    if (editing) {
      updateMutation.mutate({
        id: editing.id,
        values: {
          name: values.name,
          description: values.description || null,
          base_path: values.base_path || null,
          enabled: values.enabled,
          public_runtime: values.public_runtime,
          revision: editing.revision,
        },
      });
    } else {
      createMutation.mutate(values);
    }
  };

  const columns: TableColumnsType<MockService> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    {
      title: '服务键',
      dataIndex: 'service_key',
      width: 200,
      render: (v: string, row) => (
        <Tooltip title={`${v} · 已配置接口 ${row.endpoint_count} 个 / 场景 ${row.scenario_count} 个`}>
          <Tag color="geekblue">{v}</Tag>
        </Tooltip>
      ),
    },
    { title: '名称', dataIndex: 'name', width: 180 },
    {
      title: '基础路径',
      dataIndex: 'base_path',
      width: 160,
      render: (v: string | null) => v || '-',
    },
    {
      title: '接口 / 场景',
      width: 110,
      render: (_, row) => `${row.endpoint_count} / ${row.scenario_count}`,
    },
    {
      title: '执行面',
      width: 110,
      render: (_, row) =>
        row.public_runtime ? (
          <Tag color="orange">匿名可调用</Tag>
        ) : row.runtime_token_set ? (
          <Tag color="green">需 Token</Tag>
        ) : (
          <Tag color="red">未配置</Tag>
        ),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v: string) => fmtTime(v) },
    {
      title: '操作',
      width: 300,
      fixed: 'right',
      render: (_, row) => (
        <Space size="small" wrap>
          <Link to={`/console/mock-management/services/${row.id}`}>
            <Button size="small" icon={<EyeOutlined />}>
              接口 / 场景
            </Button>
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
            title="确认重置 Token？"
            description="旧 Token 将立即失效，已配置的被测系统需要重新配置。"
            onConfirm={() => resetMutation.mutate(row.id)}
          >
            <Button size="small" icon={<KeyOutlined />} loading={resetMutation.isPending}>
              重置 Token
            </Button>
          </Popconfirm>
          <Popconfirm
            title="确认删除该 Mock 服务？"
            description="其接口、场景与调用记录将一并删除；不影响任何测试用例。"
            onConfirm={() => deleteMutation.mutate(row.id)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} loading={deleteMutation.isPending}>
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
        <Flex vertical gap="2">
          <Typography.Title level={5} style={{ margin: 0 }}>
            接口 Mock 与依赖异常模拟
          </Typography.Title>
          <Typography.Text type="secondary">
            在测试执行期间控制依赖服务的表现：正常返回、业务异常、HTTP 错误、空数据、延迟、超时与条件响应。
          </Typography.Text>
        </Flex>
        <Space wrap>
          <Link to="/console/mock-management/executions">
            <Button icon={<HistoryOutlined />}>调用记录</Button>
          </Link>
          <Button icon={<EyeOutlined />} onClick={() => setFromApiOpen(true)}>
            从接口一键创建
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing(null);
              setModalOpen(true);
            }}
          >
            新建 Mock 服务
          </Button>
        </Space>
      </Flex>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Flex gap="middle" wrap="wrap">
          <Alert
            type="info"
            showIcon
            style={{ flex: 1, minWidth: 320 }}
            message="管理面 / 执行面分离"
            description="本页需要平台登录态；被测系统改调 /api/v1/mock/{项目ID}/{服务键}/{路径} 并携带 X-Mock-Token，不需要平台 JWT。"
          />
          <Alert
            type="warning"
            showIcon
            icon={<SafetyOutlined />}
            style={{ flex: 1, minWidth: 320 }}
            message="Token 与快照安全"
            description="Token 只存哈希、明文只返回一次；调用记录的请求 / 响应快照已按敏感字段脱敏（Authorization、X-Api-Key、password、token 等）。"
          />
        </Flex>
      </Card>

      {servicesQuery.isLoading ? (
        <LoadingState />
      ) : servicesQuery.isError ? (
        <ErrorState error={servicesQuery.error} onRetry={servicesQuery.refetch} />
      ) : services.length === 0 ? (
        <EmptyState description="尚未配置 Mock 服务，可点「新建 Mock 服务」或「从接口一键创建」开始" />
      ) : (
        <Table<MockService>
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={services}
          scroll={{ x: 1380 }}
          pagination={false}
        />
      )}

      <ServiceFormModal
        open={modalOpen}
        editing={editing}
        loading={createMutation.isPending || updateMutation.isPending}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
        onSubmit={handleForm}
      />

      {fromApiOpen && (
        <FromApiModal
          projectId={currentProjectId}
          open={fromApiOpen}
          loading={fromApiMutation.isPending}
          onClose={() => setFromApiOpen(false)}
          onSubmit={(apiId, values) => fromApiMutation.mutate({ apiId, values })}
        />
      )}

      <TokenResultModal
        token={oneTimeToken?.token ?? null}
        serviceKey={oneTimeToken?.key ?? ''}
        projectId={currentProjectId}
        title={oneTimeToken?.title ?? ''}
        onClose={() => setOneTimeToken(null)}
      />
    </PageContainer>
  );
}
