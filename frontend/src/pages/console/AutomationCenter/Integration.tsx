// 统一管理云效 Flow 与 Jenkins 接入配置。
import { App, Button, Form, Input, InputNumber, Modal, Select, Space, Switch, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { automationApi } from '@/features/automation/api/automation';
import type { AutomationIntegration, AutomationProviderType } from '@/features/automation/contracts';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { PageContainer } from '@/shared/ui/PageState';
import { ResourceTable } from '@/shared/ui/ResourceTable';
import { ProjectRequired } from '@/pages/console/AutomationCenter/shared';

interface IntegrationForm {
  provider_type: AutomationProviderType;
  name: string;
  api_base_url?: string;
  organization_id?: string;
  deployment?: 'central' | 'region';
  access_token?: string;
  jenkins_base_url?: string;
  jenkins_username?: string;
  jenkins_api_token?: string;
  allow_private_network?: boolean;
  callback_secret?: string;
  default_timeout_seconds?: number;
  enabled?: boolean;
}

/** CI 接入配置管理。凭证只写入，表格仅显示已配置状态。 */
export function ConsoleAutomationIntegrationPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AutomationIntegration | null>(null);
  const [form] = Form.useForm<IntegrationForm>();
  const providerType = Form.useWatch('provider_type', form) || 'YUNXIAO';
  const listQuery = useQuery({
    queryKey: ['automation-integrations', currentProjectId],
    queryFn: () => automationApi.listIntegrations(currentProjectId!),
    enabled: currentProjectId != null,
  });

  const save = useMutation({
    mutationFn: (values: IntegrationForm) => {
      const payload: Record<string, unknown> = { ...values };
      delete payload.pipeline_id;
      for (const key of ['access_token', 'jenkins_api_token', 'callback_secret']) {
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
    mutationFn: ({ id, pipelineId }: { id: number; pipelineId: string }) => automationApi.testConnection(id, pipelineId),
    onSuccess: (result) => message.success(result.message),
    onError: (error) => message.error(getErrorMessage(error, '连接失败')),
  });

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      provider_type: 'YUNXIAO', deployment: 'central',
      api_base_url: 'https://openapi-rdc.aliyuncs.com',
      default_timeout_seconds: 3600, allow_private_network: false, enabled: true,
    });
    setOpen(true);
  };
  const openEdit = (row: AutomationIntegration) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({
      provider_type: row.provider_type,
      name: row.name,
      api_base_url: row.api_base_url,
      organization_id: row.organization_id,
      deployment: row.deployment,
      jenkins_base_url: row.jenkins_base_url || undefined,
      jenkins_username: row.jenkins_username || undefined,
      allow_private_network: row.allow_private_network,
      default_timeout_seconds: row.default_timeout_seconds,
      enabled: row.enabled,
    });
    setOpen(true);
  };

  return (
    <PageContainer>
      <ProjectRequired projectId={currentProjectId} />
      <Typography.Paragraph>
        Jenkins API Token 和回调密钥只保存在服务端密文中。Jenkins 的回调密钥需另存到 Jenkins Credentials；内网 Jenkins 仅允许项目管理员授权。
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
          { title: '名称', dataIndex: 'name' },
          { title: '平台', dataIndex: 'provider_type', render: (value: AutomationProviderType) => value === 'JENKINS' ? 'Jenkins' : '云效 Flow' },
          { title: '地址 / 企业', render: (_value, row: AutomationIntegration) => row.provider_type === 'JENKINS' ? row.jenkins_base_url : row.organization_id || row.api_base_url },
          { title: '凭证', render: (_value, row: AutomationIntegration) => row.token_configured ? <Tag color="green">已配置</Tag> : <Tag>未配置</Tag> },
          { title: '状态', render: (_value, row: AutomationIntegration) => <Switch checked={row.enabled} size="small" loading={toggleEnabled.isPending} onChange={() => toggleEnabled.mutate(row)} /> },
          { title: '回调地址', dataIndex: 'callback_path', ellipsis: true },
          {
            title: '操作',
            render: (_value, row: AutomationIntegration) => (
              <Space>
                <Button size="small" onClick={() => {
                  const pipelineId = window.prompt(row.provider_type === 'JENKINS' ? '用于验证的 Jenkins Job 路径' : '用于验证的云效流水线 ID');
                  if (pipelineId) test.mutate({ id: row.id, pipelineId });
                }}>测试连接</Button>
                <Button size="small" onClick={() => openEdit(row)}>编辑</Button>
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
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={(values) => save.mutate(values)}>
          <Form.Item name="provider_type" label="执行平台" rules={[{ required: true }]}>
            <Select disabled={Boolean(editing)} options={[{ value: 'YUNXIAO', label: '云效 Flow' }, { value: 'JENKINS', label: 'Jenkins' }]} />
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
            <Form.Item name="jenkins_base_url" label="Jenkins Base URL" rules={[{ required: !editing, type: 'url' }]}><Input placeholder="https://jenkins.example.com" /></Form.Item>
            <Form.Item name="jenkins_username" label="Username" rules={[{ required: !editing }]}><Input autoComplete="username" /></Form.Item>
            <Form.Item name="jenkins_api_token" label="API Token" rules={!editing ? [{ required: true, min: 8 }] : []}>
              <Input.Password placeholder={editing && editing.api_token_configured ? '已配置；留空保持原值' : ''} autoComplete="new-password" />
            </Form.Item>
            <Form.Item name="allow_private_network" label="允许访问管理员授权的内网 Jenkins" valuePropName="checked"><Switch /></Form.Item>
          </>}
          <Form.Item name="callback_secret" label="回调密钥" rules={!editing ? [{ required: true, min: 8 }] : []}>
            <Input.Password placeholder={editing?.callback_secret_configured ? '已配置；留空保持原值' : ''} autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="default_timeout_seconds" label="默认超时（秒）"><InputNumber min={60} max={86400} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="enabled" label="启用接入" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
