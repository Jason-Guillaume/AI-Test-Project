import { useState } from 'react';
import { App, Button, Card, Drawer, Form, Input, Popconfirm, Select, Space, Switch, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { zapApi } from '@/features/security-testing/zap/api';
import type { ScanAuthProfile, ScanAuthProfileCreate, ScanAuthProfileUpdate } from '@/features/security-testing/zap/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { AUTH_MODE_OPTIONS, authModeLabel } from './constants';
import { PAGE_SIZE } from './policyUtils';

export function AuthProfilesBlock({ projectId }: { projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [drawer, setDrawer] = useState<{
    mode: 'create' | 'edit';
    data?: ScanAuthProfile;
  } | null>(null);

  const listQuery = useQuery({
    queryKey: ['zap-auth-profiles', projectId],
    queryFn: () =>
      zapApi.listScanAuthProfiles(projectId, { page: 1, page_size: PAGE_SIZE }),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['zap-auth-profiles', projectId] });
  };

  const createMutation = useMutation({
    mutationFn: (body: ScanAuthProfileCreate) =>
      zapApi.createScanAuthProfile(projectId, body),
    onSuccess: () => {
      message.success('认证配置已创建');
      setDrawer(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: ScanAuthProfileUpdate }) =>
      zapApi.updateScanAuthProfile(projectId, id, body),
    onSuccess: () => {
      message.success('认证配置已更新');
      setDrawer(null);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => zapApi.removeScanAuthProfile(projectId, id),
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
        <Space wrap className="ui-list-toolbar">
          <Typography.Text type="secondary">
            凭据加密入库，接口永不回显明文；列表中只显示是否有凭据与指纹前缀。
          </Typography.Text>
          <Button type="primary" onClick={() => setDrawer({ mode: 'create' })}>
            新建认证配置
          </Button>
        </Space>
      </Card>

      <Table<ScanAuthProfile> scroll={{ x: 'max-content' }}
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
