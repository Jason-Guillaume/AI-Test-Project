// 任务创建表单：只引用已保存且 ACTIVE 的 API 用例，并要求明确选择执行环境。
import { useEffect } from 'react';
import { App, Alert, Button, Form, Input, Modal, Select, Spin } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { projectsApi } from '@/api/projects';
import { environmentsApi } from '@/api/environments';
import { testManagementApi } from '@/api/testManagement';
import { getErrorMessage } from '@/api/client';
import { tasksApi, type Task } from '@/api/tasks';
import { useConsoleScope } from '@/hooks/useConsoleScope';

interface FormValues {
  project_id: number;
  title?: string;
  goal: string;
  environment_id: number;
  case_ids: number[];
}

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated?: (task: Task) => void;
  initialProjectId?: number;
  initialCaseIds?: number[];
}

/** 创建真实 API 任务；项目、环境和用例仍通过原业务 API 读取。 */
export function TaskCreateModal({ open, onClose, onCreated, initialProjectId, initialCaseIds = [] }: Props) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const projectId = Form.useWatch('project_id', form);
  const projectsQuery = useQuery({
    queryKey: ['projects', { taskCreate: true }],
    queryFn: () => projectsApi.list({ page: 1, page_size: 100 }),
    enabled: open,
  });
  const environmentsQuery = useQuery({
    queryKey: ['task-create-environments'],
    queryFn: () => environmentsApi.list({ page: 1, page_size: 100 }),
    enabled: open,
  });
  const casesQuery = useQuery({
    queryKey: ['task-create-cases', projectId],
    queryFn: () => testManagementApi.listCases(projectId!, { target_type: 'API', status: 'ACTIVE' }),
    enabled: open && projectId != null,
  });
  const createMutation = useMutation({
    mutationFn: ({ project_id, ...body }: FormValues) => tasksApi.create(project_id, {
      ...body,
      request_key: `task-create-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    }),
    onSuccess: async (task) => {
      await queryClient.invalidateQueries({ queryKey: ['tasks'] });
      message.success('任务已加入持久化调度队列');
      form.resetFields();
      onCreated?.(task);
      onClose();
    },
    onError: (error) => message.error(getErrorMessage(error, '任务创建失败')),
  });

  useEffect(() => {
    if (open) form.setFieldValue('project_id', initialProjectId ?? currentProjectId ?? projectsQuery.data?.items[0]?.id);
  }, [currentProjectId, form, initialProjectId, open, projectsQuery.data?.items]);

  useEffect(() => {
    if (!open || initialCaseIds.length === 0 || projectId !== (initialProjectId ?? projectId) || !casesQuery.data) return;
    if (!form.getFieldValue('case_ids')) form.setFieldValue('case_ids', initialCaseIds);
  }, [casesQuery.data, form, initialCaseIds, initialProjectId, open, projectId]);

  const projects = projectsQuery.data?.items ?? [];
  const environments = (environmentsQuery.data?.items ?? []).filter((item) => item.is_active && item.id != null);
  const cases = (casesQuery.data ?? []).filter((item) => item.enabled && item.status === 'ACTIVE' && item.api_id != null);
  const initialLoading = projectsQuery.isLoading || environmentsQuery.isLoading;

  return (
    <Modal
      title="创建 API 测试任务"
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnClose
      width={640}
    >
      {initialLoading ? <Spin /> : projects.length === 0 ? (
        <Alert type="warning" showIcon message="当前账号没有可创建任务的项目" />
      ) : environments.length === 0 ? (
        <Alert type="warning" showIcon message="没有可用的执行环境，请先到环境配置中启用一个环境" />
      ) : (
        <Form<FormValues>
          form={form}
          layout="vertical"
          onFinish={(values) => createMutation.mutate(values)}
        >
          <Form.Item name="project_id" label="项目" rules={[{ required: true, message: '请选择项目' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={projects.map((project) => ({ value: project.id, label: project.name }))}
              onChange={() => form.setFieldValue('case_ids', [])}
            />
          </Form.Item>
          <Form.Item name="title" label="任务名称">
            <Input maxLength={200} placeholder="例如：订单 API 回归验证" />
          </Form.Item>
          <Form.Item name="goal" label="整体目标" rules={[{ required: true, min: 3, max: 8000, message: '请输入至少 3 个字符的任务目标' }]}>
            <Input.TextArea rows={3} maxLength={8000} placeholder="描述本次测试目标和关注点" />
          </Form.Item>
          <Form.Item name="environment_id" label="执行环境" rules={[{ required: true, message: '请选择执行环境' }]}>
            <Select options={environments.map((item) => ({ value: item.id!, label: item.display_name || item.name }))} />
          </Form.Item>
          <Form.Item name="case_ids" label="已确认的 API 用例" rules={[{ required: true, type: 'array', min: 1, message: '至少选择一个 ACTIVE API 用例' }]}>
            <Select
              mode="multiple"
              showSearch
              optionFilterProp="label"
              loading={casesQuery.isLoading}
              disabled={projectId == null || cases.length === 0}
              options={cases.map((item) => ({ value: item.id, label: `#${item.id} ${item.name}` }))}
              placeholder={casesQuery.isError ? '用例加载失败，请重试' : '选择已启用的 ACTIVE API 用例'}
            />
          </Form.Item>
          {casesQuery.isError && <Alert type="error" showIcon message="读取项目 API 用例失败" style={{ marginBottom: 16 }} />}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" htmlType="submit" loading={createMutation.isPending}>
              创建并开始规划
            </Button>
          </div>
        </Form>
      )}
    </Modal>
  );
}
