// 自动化项目：绑定 Codeup 仓库和云效流水线。
import { App, Button, Form, Input, InputNumber, Modal, Select, Space, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { automationApi } from '@/features/automation/api/automation';
import type { AutomationProject, AutomationProviderType } from '@/features/automation/contracts';
import { parseJenkinsCustomParameters } from '@/features/automation/jenkinsParameters';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { PageContainer } from '@/shared/ui/PageState';
import { ResourceTable } from '@/shared/ui/ResourceTable';
import { ProjectRequired, StatusTag } from '@/pages/console/AutomationCenter/shared';

interface ProjectForm {
  integration_config_id: number;
  provider_type?: AutomationProviderType;
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
  pipeline_params_json?: string;
  timeout_seconds?: number;
  notify_condition?: 'ALWAYS' | 'ONLY_FAILED' | 'NEVER';
  notification_channel_id?: number | null;
}

/** 自动化项目列表与维护。 */
export function ConsoleAutomationProjectsPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AutomationProject | null>(null);
  const [folderPath, setFolderPath] = useState('');
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
  const selectedPipelineId = Form.useWatch('pipeline_id', form);
  const selectedIntegration = integrations.data?.items.find((item) => item.id === selectedConfigId);
  const isJenkins = selectedIntegration?.provider_type === 'JENKINS';
  const jobs = useQuery({
    queryKey: ['jenkins-jobs', selectedConfigId, folderPath],
    queryFn: () => automationApi.listJenkinsJobs(selectedConfigId!, folderPath),
    enabled: open && selectedConfigId != null && isJenkins,
  });
  useEffect(() => setFolderPath(''), [selectedConfigId]);

  const saveMutation = useMutation({
    mutationFn: (values: ProjectForm) => {
      const providerType = values.provider_type || selectedIntegration?.provider_type;
      const { pipeline_params_json, ...rest } = values;
      const payload = providerType === 'JENKINS'
        ? { ...rest, provider_type: providerType, pipeline_params: parseJenkinsCustomParameters(pipeline_params_json || '{}') }
        : rest;
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
  const inspectJob = useMutation({
    mutationFn: () => automationApi.inspectJenkinsJob(selectedConfigId!, form.getFieldValue('pipeline_id')),
    onSuccess: (job) => modal.info({
      title: `Jenkins Job：${job.job_path}`,
      content: <div>
        <p>可执行：{job.buildable ? '是' : '否'}；允许并发：{job.concurrent_build ? '是' : '否'}</p>
        <p>参数：{job.parameters.length ? job.parameters.map((item) => item.name).join('、') : '无'}</p>
      </div>,
    }),
    onError: (error) => message.error(getErrorMessage(error, 'Job 检查失败')),
  });

  const openCreate = () => {
    setEditing(null);
    setFolderPath('');
    form.resetFields();
    form.setFieldsValue({ default_branch: 'master', timeout_seconds: 3600, notify_condition: 'ALWAYS', pipeline_params_json: '{}' });
    setOpen(true);
  };
  const openEdit = (row: AutomationProject) => {
    setEditing(row);
    setFolderPath('');
    form.setFieldsValue({
      integration_config_id: row.integration_config_id,
      provider_type: row.provider_type,
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
      pipeline_params_json: JSON.stringify(row.pipeline_params || {}, null, 2),
      timeout_seconds: row.timeout_seconds,
      notify_condition: row.notify_condition,
      notification_channel_id: row.notification_channel_id,
    });
    setOpen(true);
  };

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
          { title: 'CI 平台', dataIndex: 'provider_type', render: (value: string) => value === 'JENKINS' ? <Tag color="blue">Jenkins</Tag> : <Tag>云效 Flow</Tag> },
          { title: '仓库', dataIndex: 'repository_url', ellipsis: true },
          { title: '分支', dataIndex: 'default_branch' },
          { title: '流水线 / Job', dataIndex: 'pipeline_id' },
          { title: '环境', dataIndex: 'default_environment' },
          { title: '最近状态', dataIndex: 'last_status', render: (status: string | null) => <StatusTag status={status} /> },
          { title: '最近执行', dataIndex: 'last_execution_at', render: (value: string | null) => value ? new Date(value).toLocaleString() : '-' },
          {
            title: '操作',
            render: (_value, row: AutomationProject) => (
              <Space>
                <Button size="small" onClick={() => verifyMutation.mutate(row.id)}>验证</Button>
                <Button size="small" onClick={() => openEdit(row)}>编辑</Button>
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
          <Form.Item name="provider_type" hidden><Input /></Form.Item>
          <Form.Item name="integration_config_id" label="CI 接入" rules={[{ required: true, message: '请选择接入配置' }]}>
            <Select
              options={(integrations.data?.items || []).filter((item) => item.enabled).map((item) => ({ value: item.id, label: `${item.name} · ${item.provider_type === 'JENKINS' ? 'Jenkins' : '云效 Flow'}` }))}
              onChange={(id: number) => form.setFieldValue('provider_type', integrations.data?.items.find((item) => item.id === id)?.provider_type)}
            />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}><Input /></Form.Item>
          <Form.Item name="repository_url" label="Codeup 仓库地址"><Input placeholder="https://codeup.aliyun.com/org/demo.git" /></Form.Item>
          <Form.Item name="repository_id" label="仓库标识"><Input /></Form.Item>
          <Form.Item name="pipeline_id" label={isJenkins ? 'Jenkins Job 路径' : '云效流水线 ID'} rules={[{ required: true, message: isJenkins ? '请选择或填写 Job 路径' : '请填写流水线 ID' }]}>
            <Input placeholder={isJenkins ? 'folder/sub-folder/automation-test' : '流水线 ID'} />
          </Form.Item>
          {isJenkins && <>
            <Typography.Text type="secondary">当前 Folder：{folderPath || '根目录'}</Typography.Text>
            <Space wrap style={{ display: 'flex', margin: '8px 0' }}>
              {folderPath && <Button size="small" onClick={() => setFolderPath(folderPath.split('/').slice(0, -1).join('/'))}>返回上级</Button>}
              {(jobs.data?.items || []).filter((item) => item.is_folder).map((item) => (
                <Button key={item.job_path} size="small" onClick={() => setFolderPath(item.job_path)}>📁 {item.name}</Button>
              ))}
            </Space>
            <Form.Item label="当前 Folder 中的 Job">
              <Select
                allowClear
                loading={jobs.isFetching}
                placeholder="选择一个 Job 路径"
                options={(jobs.data?.items || []).filter((item) => !item.is_folder && item.buildable).map((item) => ({ value: item.job_path, label: item.name }))}
                onChange={(value: string | undefined) => value && form.setFieldValue('pipeline_id', value)}
              />
            </Form.Item>
            <Button size="small" loading={inspectJob.isPending} disabled={!selectedConfigId || !selectedPipelineId} onClick={() => inspectJob.mutate()}>
              查询 Job 参数与执行能力
            </Button>
            <Form.Item
              name="pipeline_params_json"
              label="自定义 Job 参数（JSON）"
              extra="仅传递自定义参数；平台保留字段不可覆盖。Token、Secret、Password 等凭据字段由平台过滤，请使用 Jenkins Credentials。"
              rules={[{
                validator: async (_rule, value) => {
                  if (value) parseJenkinsCustomParameters(value);
                },
              }]}
            >
              <Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} placeholder={'{\n  "TEST_SUITE": "smoke"\n}'} />
            </Form.Item>
          </>}
          <Form.Item name="pipeline_name" label={isJenkins ? 'Job 显示名称' : '流水线名称'}><Input /></Form.Item>
          <Form.Item name="default_branch" label="默认分支"><Input /></Form.Item>
          <Form.Item name="default_environment" label="默认环境"><Input /></Form.Item>
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
