// 统一管理云效 Flow 与 Dagu 接入配置。
import { App, Button, Form, Input, InputNumber, Modal, Select, Space, Switch, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { automationApi } from '@/features/automation/api/automation';
import type { AutomationIntegration, AutomationProviderType } from '@/features/automation/contracts';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { PageContainer } from '@/shared/ui/PageState';
import { ResourceTable } from '@/shared/ui/ResourceTable';
import { sequenceColumn } from '@/shared/lib/sequence';
import { ProjectRequired } from '@/pages/console/AutomationCenter/shared';

function isPrivateHttpHost(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, '').toLowerCase().replace(/\.$/, '');
  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.internal') || host.endsWith('.local')) return true;
  if (host === '::1' || host.startsWith('fc') || host.startsWith('fd') || host.startsWith('fe80:')) return true;
  const octets = host.split('.').map(Number);
  if (octets.length !== 4 || octets.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false;
  return octets[0] === 10 || octets[0] === 127 || octets[0] === 169 && octets[1] === 254 ||
    octets[0] === 192 && octets[1] === 168 || octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31;
}

interface IntegrationForm {
  provider_type: AutomationProviderType;
  name: string;
  api_base_url?: string;
  organization_id?: string;
  deployment?: 'central' | 'region';
  access_token?: string;
  dagu_base_url?: string;
  dagu_api_key?: string;
  callback_secret?: string;
  default_timeout_seconds?: number;
  enabled?: boolean;
}

/** 管理 CI 接入与凭证状态；明文凭证仅写入，不从接口读取。 */
export function ConsoleAutomationIntegrationPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AutomationIntegration | null>(null);
  const [form] = Form.useForm<IntegrationForm>();
  const [providerType, setProviderType] = useState('YUNXIAO');
  const [daguBaseUrl, setDaguBaseUrl] = useState('');
  const listQuery = useQuery({
    queryKey: ['automation-integrations', currentProjectId],
    queryFn: () => automationApi.listIntegrations(currentProjectId!),
    enabled: currentProjectId != null,
  });

  const save = useMutation({
    mutationFn: (values: IntegrationForm) => {
      const payload: Record<string, unknown> = { ...values };
      for (const key of ['access_token', 'dagu_api_key', 'callback_secret']) {
        if (!payload[key]) delete payload[key];
      }
      if (editing) return automationApi.updateIntegration(editing.id, payload);
      return automationApi.createIntegration(currentProjectId!, payload);
    },
    onSuccess: () => {
      message.success(editing ? '配置已更新' : '配置已创建');
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ['automation-integrations'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '保存失败')),
  });
  const toggleEnabled = useMutation({
    mutationFn: (row: AutomationIntegration) => automationApi.updateIntegration(row.id, { enabled: !row.enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['automation-integrations'] }),
    onError: (error) => message.error(getErrorMessage(error, '状态更新失败')),
  });
  const test = useMutation({
    mutationFn: ({ id, pipelineId }: { id: number; pipelineId?: string }) => automationApi.testConnection(id, pipelineId),
    onSuccess: (result) => message.success(result.service_version ? `${result.message}（版本 ${result.service_version}）` : result.message),
    onError: (error) => message.error(getErrorMessage(error, '连接失败')),
  });

  /** 初始化新接入表单，默认使用云效，避免误提交空的 Dagu 凭证。 */
  const openCreate = () => {
    setEditing(null);
    setProviderType('YUNXIAO');
    setDaguBaseUrl('');
    form.resetFields();
    form.setFieldsValue({
      provider_type: 'YUNXIAO', deployment: 'central', api_base_url: 'https://openapi-rdc.aliyuncs.com',
      default_timeout_seconds: 3600, enabled: true,
    });
    setOpen(true);
  };

  /** 将可编辑的非密文配置载入表单。 */
  const openEdit = (row: AutomationIntegration) => {
    if (row.provider_type === 'LEGACY') return;
    setEditing(row);
    setProviderType(row.provider_type);
    setDaguBaseUrl(row.dagu_base_url || '');
    form.resetFields();
    form.setFieldsValue({
      provider_type: row.provider_type,
      name: row.name,
      api_base_url: row.api_base_url,
      organization_id: row.organization_id,
      deployment: row.deployment,
      dagu_base_url: row.dagu_base_url || undefined,
      default_timeout_seconds: row.default_timeout_seconds,
      enabled: row.enabled,
    });
    setOpen(true);
  };

  /** Dagu 仅验证 API 与 DAG 列表；云效需要用户提供一个流水线 ID。 */
  const testConnection = (row: AutomationIntegration) => {
    if (row.provider_type === 'DAGU') {
      test.mutate({ id: row.id });
      return;
    }
    const pipelineId = window.prompt('用于验证的云效流水线 ID');
    if (pipelineId?.trim()) test.mutate({ id: row.id, pipelineId: pipelineId.trim() });
  };

  const providerLabel = (value: string) => value === 'DAGU' ? 'Dagu' : value === 'LEGACY' ? '已停用历史配置' : '云效 Flow';

  return (
    <PageContainer>
      <ProjectRequired projectId={currentProjectId} />
      <Typography.Paragraph>
        Dagu API Key 由平台加密保存。Dagu Runner 的 Codeup Deploy Key 和回调密钥需保存在执行主机的受限凭证文件中；这些凭证不会放入 DAG 参数。
      </Typography.Paragraph>
      <Button type="primary" disabled={currentProjectId == null} onClick={openCreate}>新建 CI 接入</Button>
      <ResourceTable
        rowKey={(row) => row.id}
        loading={listQuery.isFetching}
        dataSource={listQuery.data?.items || []}
        total={listQuery.data?.total || 0}
        pagination={{ page: 1, page_size: 100 }}
        onPaginationChange={() => undefined}
        columns={[
          sequenceColumn<AutomationIntegration>({ page: 1, pageSize: 100 }),
          { title: '名称', dataIndex: 'name' },
          { title: '平台', dataIndex: 'provider_type', render: providerLabel },
          { title: '地址 / 企业', render: (_value, row: AutomationIntegration) => row.provider_type === 'DAGU' ? row.dagu_base_url : row.organization_id || row.api_base_url },
          { title: '凭证', render: (_value, row: AutomationIntegration) => {
            const configured = row.provider_type === 'DAGU' ? row.dagu_api_key_configured : row.token_configured;
            return configured ? <Tag color="green">已配置</Tag> : <Tag>未配置</Tag>;
          } },
          { title: '状态', render: (_value, row: AutomationIntegration) => <Switch checked={row.enabled} size="small" disabled={row.provider_type === 'LEGACY'} loading={toggleEnabled.isPending} onChange={() => toggleEnabled.mutate(row)} /> },
          { title: '回调地址', dataIndex: 'callback_path', ellipsis: true },
          {
            title: '操作',
            render: (_value, row: AutomationIntegration) => (
              <Space>
                <Button size="small" disabled={row.provider_type === 'LEGACY'} loading={test.isPending} onClick={() => testConnection(row)}>测试连接</Button>
                <Button size="small" disabled={row.provider_type === 'LEGACY'} onClick={() => openEdit(row)}>编辑</Button>
                <Button size="small" danger onClick={() => modal.confirm({
                  title: '将接入配置移入回收站？',
                  content: '仍被自动化项目使用时会拒绝删除。',
                  onOk: async () => {
                    await automationApi.deleteIntegration(row.id);
                    queryClient.invalidateQueries({ queryKey: ['automation-integrations'] });
                  },
                })}>删除</Button>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={editing ? '编辑 CI 接入' : '新建 CI 接入'}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={save.isPending}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          onValuesChange={(changed: Partial<IntegrationForm>) => {
            if (changed.provider_type !== undefined) setProviderType(changed.provider_type);
            if (changed.dagu_base_url !== undefined) setDaguBaseUrl(changed.dagu_base_url || '');
          }}
          onFinish={(values) => save.mutate(values)}
        >
          <Form.Item name="provider_type" label="执行平台" rules={[{ required: true }]}>
            <Select disabled={Boolean(editing)} options={[{ value: 'YUNXIAO', label: '云效 Flow' }, { value: 'DAGU', label: 'Dagu' }]} />
          </Form.Item>
          <Form.Item name="name" label="实例名称" rules={[{ required: true, message: '请填写名称' }]}><Input /></Form.Item>
          {providerType === 'YUNXIAO' ? <>
            <Form.Item name="deployment" label="部署形态"><Select options={[{ value: 'central', label: '中心版' }, { value: 'region', label: 'Region 版' }]} /></Form.Item>
            <Form.Item name="api_base_url" label="API 地址" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="organization_id" label="企业 ID"><Input /></Form.Item>
            <Form.Item name="access_token" label="个人访问令牌" rules={!editing ? [{ required: true, min: 8 }] : []}>
              <Input.Password placeholder={editing ? '留空表示不修改' : ''} autoComplete="new-password" />
            </Form.Item>
          </> : <>
            <Form.Item
              name="dagu_base_url"
              label="Dagu API Base URL"
              rules={[
                { required: !editing, message: '请填写 Dagu HTTPS 地址' },
                { validator: async (_rule, value) => {
                  if (!value && editing) return;
                  try {
                    const parsed = new URL(value);
                    if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash || !['', '/', '/api/v1'].includes(parsed.pathname)) {
                      throw new Error('invalid');
                    }
                    if (parsed.protocol === 'http:' && !isPrivateHttpHost(parsed.hostname)) throw new Error('public-http');
                  } catch {
                    throw new Error('请使用 HTTPS；受控私网 HTTP 需为 loopback、私有 IP 或内部域名');
                  }
                } },
              ]}
            ><Input placeholder="https://dagu.example.com/api/v1" /></Form.Item>
            {daguBaseUrl.startsWith('http://') && <Typography.Paragraph type="warning">
              私网 HTTP 仅在服务端显式启用 DAGU_ALLOW_INSECURE_HTTP 后可连接；公网 HTTP 地址会被拒绝。生产环境请配置 HTTPS 反向代理。
            </Typography.Paragraph>}
            <Form.Item name="dagu_api_key" label="Dagu API Key" rules={!editing ? [{ required: true, min: 8 }] : []}>
              <Input.Password placeholder={editing && editing.dagu_api_key_configured ? '已配置；留空保持原值' : ''} autoComplete="new-password" />
            </Form.Item>
          </>}
          <Form.Item name="callback_secret" label="回调 HMAC 密钥" rules={!editing ? [{ required: true, min: 8 }] : []}>
            <Input.Password placeholder={editing?.callback_secret_configured ? '已配置；留空保持原值' : ''} autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="default_timeout_seconds" label="默认超时（秒，最多 10800）"><InputNumber min={60} max={10800} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="enabled" label="启用接入" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
