// 云效接入配置。令牌和回调密钥只写不读。
import { App, Button, Form, Input, InputNumber, Modal, Select, Space, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { automationApi } from '@/features/automation/api/automation';
import type { AutomationIntegration } from '@/features/automation/contracts';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { PageContainer } from '@/shared/ui/PageState';
import { ResourceTable } from '@/shared/ui/ResourceTable';
import { ProjectRequired } from '@/pages/console/AutomationCenter/shared';

interface IntegrationForm {
  name: string;
  api_base_url?: string;
  organization_id?: string;
  deployment?: 'central' | 'region';
  access_token?: string;
  callback_secret?: string;
  default_timeout_seconds?: number;
  pipeline_id?: string;
}

/** 管理云效连接、回调地址和连通性。 */
export function ConsoleAutomationIntegrationPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AutomationIntegration | null>(null);
  const [form] = Form.useForm<IntegrationForm>();
  const listQuery = useQuery({
    queryKey: ['automation-integrations', currentProjectId],
    queryFn: () => automationApi.listIntegrations(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const save = useMutation({
    mutationFn: (values: IntegrationForm) => {
      const body = { ...values };
      delete body.pipeline_id;
      if (editing) {
        const payload = { ...body };
        if (!payload.access_token) delete payload.access_token;
        if (!payload.callback_secret) delete payload.callback_secret;
        return automationApi.updateIntegration(editing.id, payload);
      }
      return automationApi.createIntegration(currentProjectId!, body);
    },
    onSuccess: () => {
      message.success(editing ? '已更新' : '已创建');
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ['automation-integrations'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '保存失败')),
  });
  const test = useMutation({
    mutationFn: ({ id, pipelineId }: { id: number; pipelineId: string }) => automationApi.testConnection(id, pipelineId),
    onSuccess: (result) => message.success(result.message),
    onError: (error) => message.error(getErrorMessage(error, '连接失败')),
  });

  return (
    <PageContainer>
      <ProjectRequired projectId={currentProjectId} />
      <Typography.Paragraph>
        云效个人访问令牌和回调密钥只保存在服务端密文中。流水线里的回调密钥请配置为云效秘密变量，不要写进仓库。
      </Typography.Paragraph>
      <Button type="primary" disabled={currentProjectId == null} onClick={() => {
        setEditing(null);
        form.resetFields();
        form.setFieldsValue({ deployment: 'central', api_base_url: 'https://openapi-rdc.aliyuncs.com', default_timeout_seconds: 3600 });
        setOpen(true);
      }}>新建接入</Button>
      <ResourceTable
        rowKey={(row) => row.id}
        loading={listQuery.isFetching}
        dataSource={listQuery.data?.items || []}
        total={listQuery.data?.total || 0}
        pagination={{ page: 1, page_size: 100 }}
        onPaginationChange={() => undefined}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '企业', dataIndex: 'organization_id' },
          { title: '部署', dataIndex: 'deployment' },
          { title: '令牌', dataIndex: 'token_configured', render: (value: boolean) => value ? '已配置' : '未配置' },
          { title: '回调地址', dataIndex: 'callback_path', ellipsis: true },
          {
            title: '操作',
            render: (_value, row: AutomationIntegration) => (
              <Space>
                <Button size="small" onClick={() => {
                  const pipelineId = window.prompt('用于验证的云效流水线 ID');
                  if (pipelineId) test.mutate({ id: row.id, pipelineId });
                }}>测试连接</Button>
                <Button size="small" onClick={() => {
                  setEditing(row);
                  form.setFieldsValue({
                    name: row.name,
                    api_base_url: row.api_base_url,
                    organization_id: row.organization_id,
                    deployment: row.deployment,
                    default_timeout_seconds: row.default_timeout_seconds,
                  });
                  setOpen(true);
                }}>编辑</Button>
                <Button size="small" danger onClick={() => modal.confirm({
                  title: '将接入配置移入回收站？',
                  content: '仍被自动化项目使用时会拒绝。令牌不会出现在回收站详情中。',
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
      <Modal title={editing ? '编辑接入配置' : '新建接入配置'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={save.isPending} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={(values) => save.mutate(values)}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}><Input /></Form.Item>
          <Form.Item name="deployment" label="部署形态"><Select options={[{ value: 'central', label: '中心版' }, { value: 'region', label: 'Region 版' }]} /></Form.Item>
          <Form.Item name="api_base_url" label="API 地址"><Input /></Form.Item>
          <Form.Item name="organization_id" label="企业 ID"><Input /></Form.Item>
          <Form.Item name="access_token" label="个人访问令牌" rules={editing ? [] : [{ required: true, message: '请填写令牌' }]}>
            <Input.Password placeholder={editing ? '留空表示不修改' : ''} autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="callback_secret" label="回调密钥" rules={editing ? [] : [{ required: true, message: '请填写回调密钥' }]}>
            <Input.Password placeholder={editing ? '留空表示不修改' : ''} autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="default_timeout_seconds" label="默认超时（秒）"><InputNumber min={60} max={86400} style={{ width: '100%' }} /></Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
