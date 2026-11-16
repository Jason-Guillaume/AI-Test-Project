// 自动化项目：绑定 Codeup 仓库和云效流水线或 Dagu DAG。
import { App, Button, Form, Input, InputNumber, Modal, Select, Space, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { automationApi } from '@/features/automation/api/automation';
import type { AutomationProject } from '@/features/automation/contracts';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { PageContainer } from '@/shared/ui/PageState';
import { ResourceTable } from '@/shared/ui/ResourceTable';
import { ProjectRequired, StatusTag } from '@/pages/console/AutomationCenter/shared';

interface ProjectForm {
  integration_config_id: number;
  name: string;
  repository_url?: string;
  repository_id?: string;
  pipeline_id: string;
  pipeline_name?: string;
  default_branch?: string;
  default_environment?: string;
  pytest_args?: string;
  test_tags?: string;
  test_scope?: string;
  timeout_seconds?: number;
  notify_condition?: 'ALWAYS' | 'ONLY_FAILED' | 'NEVER';
  notification_channel_id?: number | null;
}

/** 管理 Codeup 仓库、CI 绑定和项目级测试默认值。 */
export function ConsoleAutomationProjectsPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AutomationProject | null>(null);
  const [form] = Form.useForm<ProjectForm>();
  const projectId = currentProjectId;

  const listQuery = useQuery({
    queryKey: ['automation-projects', projectId],
    queryFn: () => automationApi.listProjects(projectId!),
    enabled: projectId != null,
  });
  const integrations = useQuery({
    queryKey: ['automation-integrations', projectId],
    queryFn: () => automationApi.listIntegrations(projectId!),
    enabled: projectId != null && open,
  });
  const selectedConfigId = Form.useWatch('integration_config_id', form);
  const selectedIntegration = integrations.data?.items.find((item) => item.id === selectedConfigId);
  const isDagu = selectedIntegration?.provider_type === 'DAGU';
  const dags = useQuery({
    queryKey: ['automation-dags', selectedConfigId],
    queryFn: () => automationApi.listDags(selectedConfigId!),
    enabled: open && isDagu && selectedConfigId != null,
  });

  const saveMutation = useMutation({
    mutationFn: (values: ProjectForm) => {
      const { notification_channel_id, ...rest } = values;
      const payload = notification_channel_id == null ? rest : { ...rest, notification_channel_id };
      return editing
        ? automationApi.updateProject(editing.id, payload)
        : automationApi.createProject(projectId!, payload);
    },
    onSuccess: () => {
      message.success(editing ? '已更新' : '已创建');
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ['automation-projects'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '保存失败')),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => automationApi.deleteProject(id),
    onSuccess: () => {
      message.success('已删除');
      queryClient.invalidateQueries({ queryKey: ['automation-projects'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '删除失败')),
  });
  const verifyMutation = useMutation({
    mutationFn: (id: number) => automationApi.verifyProject(id),
    onSuccess: (result) => message.success(result.message),
    onError: (error) => message.error(getErrorMessage(error, '验证失败')),
  });

  /** 初始化新自动化项目，默认绑定 Codeup 主分支和平台限时。 */
  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ default_branch: 'master', timeout_seconds: 3600, notify_condition: 'ALWAYS' });
    setOpen(true);
  };

  /** 将现有项目配置载入表单；归档 Provider 项目只读展示。 */
  const openEdit = (row: AutomationProject) => {
    if (row.provider_type === 'LEGACY') return;
    setEditing(row);
    form.setFieldsValue({
      integration_config_id: row.integration_config_id,
      name: row.name,
      repository_url: row.repository_url,
      repository_id: row.repository_id,
      pipeline_id: row.pipeline_id,
      pipeline_name: row.pipeline_name,
      default_branch: row.default_branch,
      default_environment: row.default_environment,
      pytest_args: row.pytest_args,
      test_tags: row.test_tags,
      test_scope: row.test_scope,
      timeout_seconds: row.timeout_seconds,
      notify_condition: row.notify_condition,
      notification_channel_id: row.notification_channel_id,
    });
    setOpen(true);
  };

  const providerLabel = (value: string) => value === 'DAGU' ? 'Dagu' : value === 'LEGACY' ? '历史记录' : '云效 Flow';

  return (
    <PageContainer>
      <ProjectRequired projectId={projectId} />
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" disabled={projectId == null} onClick={openCreate}>新建自动化项目</Button>
      </Space>
      <ResourceTable
        rowKey={(row) => row.id}
        loading={listQuery.isFetching}
        dataSource={listQuery.data?.items || []}
        total={listQuery.data?.total || 0}
        pagination={{ page: 1, page_size: 100 }}
        onPaginationChange={() => undefined}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: 'CI 平台', dataIndex: 'provider_type', render: (value: string) => value === 'DAGU' ? <Tag color="blue">Dagu</Tag> : <Tag>{providerLabel(value)}</Tag> },
          { title: '仓库', dataIndex: 'repository_url', ellipsis: true },
          { title: '分支', dataIndex: 'default_branch' },
          { title: '流水线 / DAG', dataIndex: 'pipeline_id' },
          { title: '环境', dataIndex: 'default_environment' },
          { title: '最近状态', dataIndex: 'last_status', render: (status: string | null) => <StatusTag status={status} /> },
          { title: '最近执行', dataIndex: 'last_execution_at', render: (value: string | null) => value ? new Date(value).toLocaleString() : '-' },
          {
            title: '操作',
            render: (_value, row: AutomationProject) => (
              <Space>
                <Button size="small" disabled={row.provider_type === 'LEGACY'} onClick={() => verifyMutation.mutate(row.id)}>验证</Button>
                <Button size="small" disabled={row.provider_type === 'LEGACY'} onClick={() => openEdit(row)}>编辑</Button>
                <Button size="small" danger onClick={() => modal.confirm({
                  title: '将自动化项目移入回收站？',
                  content: '执行记录、报告文件和流水线绑定会保留。排队或运行中的执行不能删除。',
                  onOk: () => deleteMutation.mutateAsync(row.id),
                })}>删除</Button>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={editing ? '编辑自动化项目' : '新建自动化项目'}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={saveMutation.isPending}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={(values) => saveMutation.mutate(values)}>
          <Form.Item name="integration_config_id" label="CI 接入" rules={[{ required: true, message: '请选择接入配置' }]}>
            <Select
              options={(integrations.data?.items || []).filter((item) => item.enabled && item.provider_type !== 'LEGACY').map((item) => ({ value: item.id, label: `${item.name} · ${providerLabel(item.provider_type)}` }))}
              onChange={(id: number) => {
                form.setFieldValue('pipeline_id', undefined);
                form.setFieldValue('pipeline_name', undefined);
                queryClient.invalidateQueries({ queryKey: ['automation-dags', id] });
              }}
            />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}><Input /></Form.Item>
          <Form.Item name="repository_url" label="Codeup 仓库地址" rules={isDagu ? [{ required: true, message: 'Dagu 执行需要 Codeup 仓库' }] : []}>
            <Input placeholder="https://codeup.aliyun.com/org/repo.git" />
          </Form.Item>
          <Form.Item name="repository_id" label="仓库标识"><Input /></Form.Item>
          <Form.Item name="pipeline_id" label={isDagu ? 'Dagu DAG Name' : '云效流水线 ID'} rules={[{ required: true, message: '请选择或填写流水线' }]}>
            {isDagu ? (
              <Select
                showSearch
                loading={dags.isFetching}
                placeholder="从当前 Dagu 可用 DAG 中选择"
                options={(dags.data?.items || []).map((dag) => ({ value: dag.name, label: dag.description ? `${dag.name} · ${dag.description}` : dag.name }))}
                optionFilterProp="label"
                onChange={(value: string) => form.setFieldValue('pipeline_name', value)}
              />
            ) : <Input placeholder="云效流水线 ID" />}
          </Form.Item>
          {isDagu && dags.isError && <Typography.Text type="danger">读取 Dagu DAG 列表失败：{getErrorMessage(dags.error, '请检查接入权限和地址')}</Typography.Text>}
          <Form.Item name="pipeline_name" label="流水线 / DAG 显示名称"><Input /></Form.Item>
          <Form.Item name="default_branch" label="默认分支"><Input /></Form.Item>
          <Form.Item name="default_environment" label="测试环境"><Input /></Form.Item>
          <Form.Item name="pytest_args" label="pytest 参数"><Input placeholder="-q --maxfail=1" /></Form.Item>
          <Form.Item name="test_tags" label="测试标签"><Input placeholder="smoke" /></Form.Item>
          <Form.Item name="test_scope" label="测试范围"><Input placeholder="tests/login" /></Form.Item>
          <Form.Item name="timeout_seconds" label="超时（秒，最多 10800）"><InputNumber min={60} max={10800} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="notify_condition" label="飞书通知">
            <Select options={[
              { value: 'ALWAYS', label: '每次完成都通知' },
              { value: 'ONLY_FAILED', label: '仅失败或超时通知' },
              { value: 'NEVER', label: '不通知' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
