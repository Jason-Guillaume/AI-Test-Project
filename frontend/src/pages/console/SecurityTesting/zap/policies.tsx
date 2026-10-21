// 安全扫描 · 子 Tab 2：扫描策略与认证。
//
// 两个区块：
//   - 扫描策略：六档 scan_mode、spider / passive / active 开关、时长 / 深度 / 并发 / 请求间隔、
//     max_alerts_per_rule / max_request_budget、include / exclude / selected_rule_ids。
//     平台内置策略（is_builtin=true）全字段只读：后端对全局内置策略的修改与删除返回 400
//     （「平台内置策略为全项目共享，无法在项目内修改」/「平台内置策略不可删除」），
//     前端不给编辑入口并直接给出中文说明，不让用户白点。
//   - 认证配置：五档 auth_mode。凭据永不回显，只显示 has_credential / token_fingerprint /
//     credential_updated_at（§十一）。
import { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { securityApi } from '@/api/securityTesting';
import type {
  ScanAuthProfile,
  ScanAuthProfileCreate,
  ScanAuthProfileUpdate,
  ScanMode,
  ScanProfile,
  ScanProfileCreate,
  ScanProfileUpdate,
} from '@/api/securityTesting';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState } from '@/components/PageState';
import {
  ACTIVE_SCAN_MODES,
  AUTH_MODE_OPTIONS,
  authModeLabel,
  SCAN_MODE_OPTIONS,
  scanModeLabel,
} from './constants';

const PAGE_SIZE = 100;

function splitCsv(text: string | undefined): string[] {
  return (text ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}
function joinCsv(list: string[] | undefined): string {
  return (list ?? []).join(', ');
}

/** 平台内置策略不可修改的中文说明（与后端 400 的 message 同口径）。 */
const BUILTIN_TIP =
  '平台内置策略为全项目共享，无法在项目内修改或删除；如需调整，请新建一条自定义策略后在使用时选择它。';

/** 扫描策略与认证子 Tab。 */
export function PoliciesSubTab({ projectId }: { projectId: number }) {
  return (
    <Tabs
      size="small"
      defaultActiveKey="profiles"
      items={[
        { key: 'profiles', label: '扫描策略', children: <ProfilesBlock projectId={projectId} /> },
        { key: 'auth', label: '认证配置', children: <AuthProfilesBlock projectId={projectId} /> },
      ]}
    />
  );
}

// --------------------------------------------------------------------------- 扫描策略区块

function ProfilesBlock({ projectId }: { projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [drawer, setDrawer] = useState<{
    mode: 'create' | 'edit' | 'view';
    data?: ScanProfile;
  } | null>(null);

  const listQuery = useQuery({
    queryKey: ['zap-profiles', projectId],
    queryFn: () => securityApi.listScanProfiles(projectId, { page: 1, page_size: PAGE_SIZE }),
  });

  const authProfilesQuery = useQuery({
    queryKey: ['zap-auth-profiles', projectId, 'for-select'],
    queryFn: () =>
      securityApi.listScanAuthProfiles(projectId, { page: 1, page_size: PAGE_SIZE, enabled: true }),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['zap-profiles', projectId] });
  };

  const createMutation = useMutation({
    mutationFn: (body: ScanProfileCreate) => securityApi.createScanProfile(projectId, body),
    onSuccess: () => {
      message.success('扫描策略已创建');
      setDrawer(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: ScanProfileUpdate }) =>
      securityApi.updateScanProfile(projectId, id, body),
    onSuccess: () => {
      message.success('扫描策略已更新');
      setDrawer(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败（平台内置策略不可修改）')),
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => securityApi.removeScanProfile(projectId, id),
    onSuccess: () => {
      message.success('扫描策略已删除');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败（平台内置策略不可删除）')),
  });

  const columns: TableColumnsType<ScanProfile> = [
    {
      title: '策略',
      dataIndex: 'name',
      render: (_, r) => (
        <Space direction="vertical" size={0} style={{ maxWidth: 260 }}>
          <Space size={6} wrap>
            <Typography.Text strong>{r.name}</Typography.Text>
            {r.is_builtin ? (
              <Tag color="purple">平台内置</Tag>
            ) : (
              <Tag color="blue">项目</Tag>
            )}
          </Space>
          {r.description ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
              {r.description}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '扫描模式',
      dataIndex: 'scan_mode',
      width: 150,
      render: (v: string, r) => (
        <Space direction="vertical" size={0}>
          <Tag color={r.is_active_scan ? 'volcano' : 'cyan'}>{scanModeLabel(v)}</Tag>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {r.is_active_scan ? '受控主动扫描' : '仅被动扫描'}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '能力开关',
      width: 180,
      render: (_, r) => (
        <Space size={4} wrap>
          {r.spider_enabled && <Tag>爬虫</Tag>}
          {r.client_spider_enabled && <Tag>客户端爬虫</Tag>}
          {r.passive_enabled && <Tag color="cyan">被动</Tag>}
          {r.active_enabled && <Tag color="volcano">主动</Tag>}
        </Space>
      ),
    },
    {
      title: '参数',
      width: 190,
      render: (_, r) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {r.max_duration} 分钟 · 深度 {r.max_depth} · 并发 {r.max_concurrency} · 间隔{' '}
          {r.request_delay}ms
        </Typography.Text>
      ),
    },
    {
      title: '认证',
      width: 110,
      render: (_, r) => (r.authentication_profile_id ? `#${r.authentication_profile_id}` : '未绑定'),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '操作',
      width: 150,
      render: (_, r) =>
        r.is_builtin ? (
          // 不给编辑/删除按钮：后端必 400，白点只会换来一条错误提示。
          <Button size="small" onClick={() => setDrawer({ mode: 'view', data: r })}>
            查看
          </Button>
        ) : (
          <Space size="small">
            <Button size="small" onClick={() => setDrawer({ mode: 'edit', data: r })}>
              编辑
            </Button>
            <Popconfirm
              title="确认删除该扫描策略？"
              description="已有的扫描任务不受影响。"
              onConfirm={() => removeMutation.mutate(r.id)}
            >
              <Button size="small" danger>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ),
    },
  ];

  if (listQuery.isLoading) return <LoadingState />;
  if (listQuery.isError) return <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />;

  const items = listQuery.data?.items ?? [];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Typography.Text type="secondary">
            策略决定扫描范围与强度；认证绑定在策略上，发起任务时不可单独选择认证配置。
          </Typography.Text>
          <Button type="primary" onClick={() => setDrawer({ mode: 'create' })}>
            新建扫描策略
          </Button>
        </Space>
      </Card>

      <Table<ScanProfile>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={false}
      />

      {drawer && (
        <ProfileDrawer
          mode={drawer.mode}
          data={drawer.data}
          authProfileOptions={(authProfilesQuery.data?.items ?? []).map((p) => ({
            value: p.id,
            label: `${p.name}（${authModeLabel(p.auth_mode)}）`,
          }))}
          submitting={createMutation.isPending || updateMutation.isPending}
          onCancel={() => setDrawer(null)}
          onSubmit={(body, id) => {
            if (id != null) updateMutation.mutate({ id, body });
            else createMutation.mutate(body as ScanProfileCreate);
          }}
        />
      )}
    </div>
  );
}

/** 新建 / 编辑 / 查看扫描策略抽屉。view 态（平台内置）全字段禁用。 */
function ProfileDrawer({
  mode,
  data,
  authProfileOptions,
  submitting,
  onCancel,
  onSubmit,
}: {
  mode: 'create' | 'edit' | 'view';
  data?: ScanProfile;
  authProfileOptions: { value: number; label: string }[];
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (body: ScanProfileUpdate, id?: number) => void;
}) {
  const readOnly = mode === 'view';
  const [form] = Form.useForm<
    ScanProfileCreate & {
      include_paths_text: string;
      exclude_paths_text: string;
      selected_rule_ids_text: string;
    }
  >();
  const formKey = `${mode}-${data?.id ?? 'new'}`;

  const handleOk = async () => {
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    onSubmit(
      {
        name: v.name.trim(),
        scan_mode: v.scan_mode,
        spider_enabled: v.spider_enabled ?? true,
        client_spider_enabled: v.client_spider_enabled ?? false,
        passive_enabled: v.passive_enabled ?? true,
        active_enabled: v.active_enabled ?? false,
        authentication_profile_id: v.authentication_profile_id ?? null,
        max_duration: v.max_duration ?? 30,
        max_depth: v.max_depth ?? 5,
        max_concurrency: v.max_concurrency ?? 4,
        request_delay: v.request_delay ?? 300,
        max_alerts_per_rule: v.max_alerts_per_rule ?? null,
        max_request_budget: v.max_request_budget ?? null,
        include_paths: splitCsv(v.include_paths_text),
        exclude_paths: splitCsv(v.exclude_paths_text),
        selected_rule_ids: splitCsv(v.selected_rule_ids_text),
        enabled: v.enabled ?? true,
        description: v.description?.trim() || null,
      },
      data?.id,
    );
  };

  const scanMode = Form.useWatch('scan_mode', form) ?? data?.scan_mode ?? 'API_PASSIVE';
  const isActive = ACTIVE_SCAN_MODES.has(scanMode as ScanMode);

  return (
    <Drawer
      title={
        mode === 'create' ? '新建扫描策略' : mode === 'edit' ? `编辑扫描策略 #${data?.id}` : `查看扫描策略 #${data?.id}`
      }
      open
      onClose={onCancel}
      width={620}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onCancel}>关闭</Button>
          {!readOnly && (
            <Button type="primary" loading={submitting} onClick={handleOk}>
              保存
            </Button>
          )}
        </Space>
      }
    >
      {readOnly && (
        <Alert
          type="warning"
          showIcon
          message="平台内置策略不可修改"
          description={BUILTIN_TIP}
          style={{ marginBottom: 16 }}
        />
      )}

      <Form
        key={formKey}
        form={form}
        layout="vertical"
        disabled={readOnly}
        initialValues={
          data
            ? {
                name: data.name,
                scan_mode: data.scan_mode,
                spider_enabled: data.spider_enabled,
                client_spider_enabled: data.client_spider_enabled,
                passive_enabled: data.passive_enabled,
                active_enabled: data.active_enabled,
                authentication_profile_id: data.authentication_profile_id,
                max_duration: data.max_duration,
                max_depth: data.max_depth,
                max_concurrency: data.max_concurrency,
                request_delay: data.request_delay,
                max_alerts_per_rule: data.max_alerts_per_rule,
                max_request_budget: data.max_request_budget,
                include_paths_text: joinCsv(data.include_paths),
                exclude_paths_text: joinCsv(data.exclude_paths),
                selected_rule_ids_text: joinCsv(data.selected_rule_ids),
                enabled: data.enabled,
                description: data.description ?? '',
              }
            : {
                scan_mode: 'API_PASSIVE',
                spider_enabled: true,
                client_spider_enabled: false,
                passive_enabled: true,
                active_enabled: false,
                max_duration: 30,
                max_depth: 5,
                max_concurrency: 4,
                request_delay: 300,
                enabled: true,
                include_paths_text: '',
                exclude_paths_text: '',
                selected_rule_ids_text: '',
              }
        }
      >
        <Form.Item
          name="name"
          label="策略名称"
          rules={[{ required: true, message: '请输入策略名称' }]}
        >
          <Input maxLength={100} disabled={mode === 'edit'} placeholder="如 测试环境默认被动扫描" />
        </Form.Item>

        <Form.Item name="scan_mode" label="扫描模式" rules={[{ required: true }]}>
          <Select options={SCAN_MODE_OPTIONS} />
        </Form.Item>

        {activeScanAlert(isActive)}

        <Form.Item name="authentication_profile_id" label="认证配置" tooltip="认证绑定在策略上；平台内置策略不能绑定项目认证配置（后端 400）。">
          <Select allowClear placeholder="不绑定认证（以 NONE 模式扫描）" options={authProfileOptions} />
        </Form.Item>

        <Space style={{ display: 'flex' }} size="small" wrap>
          <Form.Item name="max_duration" label="最长时长（分钟）" style={{ width: 160 }}>
            <InputNumber min={1} max={240} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="max_depth" label="最大深度" style={{ width: 130 }}>
            <InputNumber min={1} max={10} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="max_concurrency" label="最大并发" style={{ width: 130 }}>
            <InputNumber min={1} max={50} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="request_delay" label="请求间隔（毫秒）" style={{ width: 160 }}>
            <InputNumber min={0} max={5000} style={{ width: '100%' }} />
          </Form.Item>
        </Space>

        <Space style={{ display: 'flex' }} size="small" wrap>
          <Form.Item name="max_alerts_per_rule" label="单规则最大告警数" style={{ width: 180 }}>
            <InputNumber min={1} max={200} style={{ width: '100%' }} placeholder="不限制" />
          </Form.Item>
          <Form.Item name="max_request_budget" label="请求预算" style={{ width: 180 }}>
            <InputNumber min={1} max={50000} style={{ width: '100%' }} placeholder="不限制" />
          </Form.Item>
        </Space>

        <Form.Item name="include_paths_text" label="包含路径（逗号分隔）">
          <Input placeholder="如 /api/v1/**" />
        </Form.Item>
        <Form.Item name="exclude_paths_text" label="排除路径（逗号分隔）">
          <Input placeholder="如 /health,/metrics" />
        </Form.Item>
        <Form.Item
          name="selected_rule_ids_text"
          label="仅启用规则（selected_rule_ids，逗号分隔）"
          tooltip="留空表示使用 ZAP 默认启用规则集。"
        >
          <Input placeholder="如 10001,40018" />
        </Form.Item>

        <Space size="large">
          <Form.Item name="spider_enabled" label="爬虫（spider）" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="client_spider_enabled" label="客户端爬虫" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="passive_enabled" label="被动扫描" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="active_enabled" label="主动扫描" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Space>

        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} maxLength={500} />
        </Form.Item>
      </Form>
    </Drawer>
  );
}

/** 主动扫描提示：选了受控主动模式就提醒用户发起扫描时需要人工确认授权。 */
function activeScanAlert(active: boolean) {
  if (!active) return null;
  return (
    <Alert
      type="warning"
      showIcon
      message="该模式属于受控主动扫描"
      description="发起扫描时必须勾选授权确认并填写批准说明；后端会独立校验批准行为。"
      style={{ marginBottom: 16 }}
    />
  );
}

// --------------------------------------------------------------------------- 认证配置区块

function AuthProfilesBlock({ projectId }: { projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [drawer, setDrawer] = useState<{
    mode: 'create' | 'edit';
    data?: ScanAuthProfile;
  } | null>(null);

  const listQuery = useQuery({
    queryKey: ['zap-auth-profiles', projectId],
    queryFn: () =>
      securityApi.listScanAuthProfiles(projectId, { page: 1, page_size: PAGE_SIZE }),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['zap-auth-profiles', projectId] });
  };

  const createMutation = useMutation({
    mutationFn: (body: ScanAuthProfileCreate) =>
      securityApi.createScanAuthProfile(projectId, body),
    onSuccess: () => {
      message.success('认证配置已创建');
      setDrawer(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: ScanAuthProfileUpdate }) =>
      securityApi.updateScanAuthProfile(projectId, id, body),
    onSuccess: () => {
      message.success('认证配置已更新');
      setDrawer(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => securityApi.removeScanAuthProfile(projectId, id),
    onSuccess: () => {
      message.success('认证配置已删除');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const columns: TableColumnsType<ScanAuthProfile> = [
    {
      title: '认证配置',
      dataIndex: 'name',
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{r.name}</Typography.Text>
          {r.description ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
              {r.description}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '认证模式',
      dataIndex: 'auth_mode',
      width: 130,
      render: (v: string) => <Tag>{authModeLabel(v)}</Tag>,
    },
    {
      title: '凭据',
      width: 190,
      render: (_, r) =>
        r.has_credential ? (
          <Space direction="vertical" size={0}>
            <Tag color="green">已配置</Tag>
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {r.token_fingerprint ?? '（无指纹）'}
            </Typography.Text>
          </Space>
        ) : (
          <Tag>未配置</Tag>
        ),
    },
    {
      title: '凭据更新',
      width: 150,
      render: (_, r) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {r.credential_updated_at ?? '-'}
        </Typography.Text>
      ),
    },
    {
      title: '凭据过期',
      width: 150,
      render: (_, r) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {r.credential_expires_at ?? '-'}
        </Typography.Text>
      ),
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '操作',
      width: 150,
      render: (_, r) => (
        <Space size="small">
          <Button size="small" onClick={() => setDrawer({ mode: 'edit', data: r })}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除该认证配置？"
            description="绑定到该配置的扫描策略将回退为无认证。"
            onConfirm={() => removeMutation.mutate(r.id)}
          >
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (listQuery.isLoading) return <LoadingState />;
  if (listQuery.isError) return <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />;

  const items = listQuery.data?.items ?? [];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Typography.Text type="secondary">
            凭据加密入库，接口永不回显明文；列表中只显示是否有凭据与指纹前缀。
          </Typography.Text>
          <Button type="primary" onClick={() => setDrawer({ mode: 'create' })}>
            新建认证配置
          </Button>
        </Space>
      </Card>

      <Table<ScanAuthProfile>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={false}
      />

      {drawer && (
        <AuthProfileDrawer
          mode={drawer.mode}
          data={drawer.data}
          submitting={createMutation.isPending || updateMutation.isPending}
          onCancel={() => setDrawer(null)}
          onSubmit={(body, id) => {
            if (id != null) updateMutation.mutate({ id, body });
            else createMutation.mutate(body as ScanAuthProfileCreate);
          }}
        />
      )}
    </div>
  );
}

/** 新建 / 编辑认证配置抽屉。凭据只写不读：编辑态留空表示保持不变。 */
function AuthProfileDrawer({
  mode,
  data,
  submitting,
  onCancel,
  onSubmit,
}: {
  mode: 'create' | 'edit';
  data?: ScanAuthProfile;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (body: ScanAuthProfileUpdate, id?: number) => void;
}) {
  const [form] = Form.useForm<
    ScanAuthProfileCreate & { credential_input: string; remove_credential: boolean }
  >();
  const formKey = `${mode}-${data?.id ?? 'new'}`;

  const handleOk = async () => {
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    const body: ScanAuthProfileUpdate = {
      name: v.name.trim(),
      auth_mode: v.auth_mode ?? 'NONE',
      session_method: v.session_method || null,
      session_header: v.session_header || null,
      session_name: v.session_name || null,
      authentication_check_url: v.authentication_check_url?.trim() || null,
      logged_in_indicator: v.logged_in_indicator || null,
      logged_out_indicator: v.logged_out_indicator || null,
      expected_user_id: v.expected_user_id || null,
      auth_expiry_policy: v.auth_expiry_policy || 'UNKNOWN',
      credential_expires_at: v.credential_expires_at || null,
      description: v.description?.trim() || null,
    };
    if (data) {
      // 删除凭据优先于「保持/更新」：两种互斥，由勾选项决定。
      if (v.remove_credential) body.remove_credential = true;
      else if (v.credential_input) body.credential = v.credential_input;
    } else {
      body.credential = v.credential_input || null;
    }
    onSubmit(body, data?.id);
  };

  return (
    <Drawer
      title={mode === 'create' ? '新建认证配置' : `编辑认证配置 #${data?.id}`}
      open
      onClose={onCancel}
      width={600}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleOk}>
            保存
          </Button>
        </Space>
      }
    >
      <Form
        key={formKey}
        form={form}
        layout="vertical"
        initialValues={
          data
            ? {
                name: data.name,
                auth_mode: data.auth_mode,
                session_method: data.session_method ?? '',
                session_header: data.session_header ?? '',
                session_name: data.session_name ?? '',
                authentication_check_url: data.authentication_check_url ?? '',
                logged_in_indicator: data.logged_in_indicator ?? '',
                logged_out_indicator: data.logged_out_indicator ?? '',
                expected_user_id: data.expected_user_id ?? '',
                auth_expiry_policy: data.auth_expiry_policy || 'UNKNOWN',
                credential_expires_at: data.credential_expires_at ?? '',
                description: data.description ?? '',
                credential_input: '',
                remove_credential: false,
              }
            : {
                auth_mode: 'BEARER_TOKEN',
                auth_expiry_policy: 'UNKNOWN',
                credential_input: '',
                remove_credential: false,
              }
        }
      >
        <Form.Item name="name" label="配置名称" rules={[{ required: true, message: '请输入配置名称' }]}>
          <Input maxLength={100} disabled={mode === 'edit'} />
        </Form.Item>

        <Form.Item name="auth_mode" label="认证模式" rules={[{ required: true }]}>
          <Select options={AUTH_MODE_OPTIONS} />
        </Form.Item>

        <Form.Item name="credential_input" label="凭据（明文，仅用于写入）">
          <Input.Password
            autoComplete="new-password"
            placeholder={mode === 'edit' ? '留空保持不变' : '如 Bearer Token 值'}
          />
        </Form.Item>

        {mode === 'edit' && (
          <Space size="large" style={{ marginTop: -8 }}>
            <Form.Item
              name="remove_credential"
              valuePropName="checked"
              style={{ marginBottom: 0 }}
            >
              <Switch
                checkedChildren="删除凭据"
                unCheckedChildren="保留凭据"
                onChange={(checked) => {
                  if (checked) form.setFieldValue('credential_input', '');
                }}
              />
            </Form.Item>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              当前：{data?.has_credential ? '已配置' : '未配置'}
              {data?.token_fingerprint ? ` · ${data.token_fingerprint}` : ''}
            </Typography.Text>
          </Space>
        )}

        <Space style={{ display: 'flex' }} size="small" wrap>
          <Form.Item name="session_method" label="会话方式" style={{ width: 150 }}>
            <Input maxLength={30} placeholder="如 COOKIE" />
          </Form.Item>
          <Form.Item name="session_header" label="会话头" style={{ width: 200 }}>
            <Input maxLength={100} placeholder="如 X-Session-Id" />
          </Form.Item>
          <Form.Item name="session_name" label="会话名" style={{ width: 200 }}>
            <Input maxLength={100} />
          </Form.Item>
        </Space>

        <Form.Item name="authentication_check_url" label="登录态校验 URL">
          <Input maxLength={500} placeholder="如 /api/v1/me" />
        </Form.Item>

        <Space style={{ display: 'flex' }} size="small" wrap>
          <Form.Item name="logged_in_indicator" label="登录成功标识" style={{ width: 200 }}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="logged_out_indicator" label="未登录标识" style={{ width: 200 }}>
            <Input maxLength={200} />
          </Form.Item>
        </Space>

        <Space style={{ display: 'flex' }} size="small" wrap>
          <Form.Item name="expected_user_id" label="期望用户 ID" style={{ width: 200 }}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="auth_expiry_policy" label="过期策略" style={{ width: 160 }}>
            <Input maxLength={20} />
          </Form.Item>
          <Form.Item name="credential_expires_at" label="凭据过期时间" style={{ width: 220 }}>
            <Input placeholder="ISO 时间，如 2026-12-31T00:00:00" />
          </Form.Item>
        </Space>

        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} maxLength={500} />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
