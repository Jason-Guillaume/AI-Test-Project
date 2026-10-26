// 任务创建表单：只引用已保存且 ACTIVE 的 API 用例，并要求明确选择执行环境。
import { useEffect } from 'react';
import { App, Alert, Button, Checkbox, Form, Input, Modal, Select, Spin } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { projectsApi } from '@/api/projects';
import { environmentsApi } from '@/api/environments';
import { testManagementApi } from '@/api/testManagement';
import { webUIApi } from '@/api/webUI';
import { securityApi } from '@/api/securityTesting';
import { getErrorMessage } from '@/api/client';
import { tasksApi, type Task } from '@/api/tasks';
import { useConsoleScope } from '@/hooks/useConsoleScope';

interface FormValues {
  project_id: number;
  title?: string;
  goal: string;
  environment_id: number;
  target_type: 'API' | 'WEB';
  case_ids: number[];
  security_scan_enabled: boolean;
  scan_target_id?: number;
  scan_profile_id?: number;
}

interface CaseOption {
  id: number;
  name: string;
  ready: boolean;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated?: (task: Task) => void;
  initialProjectId?: number;
  initialCaseIds?: number[];
}

/** 创建真实 API 或已确认 Web 任务；资产仍通过原业务 API 读取。 */
export function TaskCreateModal({ open, onClose, onCreated, initialProjectId, initialCaseIds = [] }: Props) {
  const [form] = Form.useForm<FormValues>();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const projectId = Form.useWatch('project_id', form);
  const targetType = Form.useWatch('target_type', form) ?? 'API';
  const environmentId = Form.useWatch('environment_id', form);
  const securityScanEnabled = Form.useWatch('security_scan_enabled', form) ?? false;
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
    queryKey: ['task-create-cases', projectId, targetType],
    queryFn: async () => targetType === 'API'
      ? (await testManagementApi.listCases(projectId!, { target_type: 'API', status: 'ACTIVE' }))
        .map((item): CaseOption => ({ id: item.id, name: item.name, ready: item.enabled && item.status === 'ACTIVE' && item.api_id != null }))
      : (await webUIApi.cases(projectId!, 1)).items
        .map((item): CaseOption => ({ id: item.id, name: item.name, ready: item.confirmed })),
    enabled: open && projectId != null,
  });
  const scanTargetsQuery = useQuery({
    queryKey: ['task-create-scan-targets', projectId],
    queryFn: () => securityApi.listScanTargets(projectId!, { enabled: true, page: 1, page_size: 100 }),
    enabled: open && projectId != null,
  });
  const scanProfilesQuery = useQuery({
    queryKey: ['task-create-scan-profiles', projectId],
    queryFn: () => securityApi.listScanProfiles(projectId!, { enabled: true, page: 1, page_size: 100 }),
    enabled: open && projectId != null,
  });
  const createMutation = useMutation({
    mutationFn: ({ project_id, target_type: _targetType, security_scan_enabled, scan_target_id, scan_profile_id, ...body }: FormValues) => tasksApi.create(project_id, {
      ...body,
      security_scan: security_scan_enabled ? { target_id: scan_target_id!, scan_profile_id: scan_profile_id! } : undefined,
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
  const cases = casesQuery.data ?? [];
  const scanTargets = (scanTargetsQuery.data?.items ?? []).filter((target) =>
    target.environment_id === environmentId && (target.target_type === targetType || target.target_type === 'HYBRID'),
  );
  const scanProfiles = scanProfilesQuery.data?.items ?? [];
  const compatibleProfiles = scanProfiles.filter((profile) =>
    profile.scan_mode.startsWith(targetType) || profile.scan_mode.startsWith('HYBRID') || profile.scan_mode === 'FULL_AUTHORIZED',
  );
  const initialLoading = projectsQuery.isLoading || environmentsQuery.isLoading;

  return (
    <Modal
      title="创建测试任务"
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
          initialValues={{ target_type: 'API', security_scan_enabled: false }}
        >
          <Form.Item name="project_id" label="项目" rules={[{ required: true, message: '请选择项目' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={projects.map((project) => ({ value: project.id, label: project.name }))}
              onChange={() => {
                form.setFieldsValue({ case_ids: [], scan_target_id: undefined, scan_profile_id: undefined });
              }}
            />
          </Form.Item>
          <Form.Item name="target_type" label="执行类型" rules={[{ required: true }]}>
            <Select
              options={[{ value: 'API', label: 'API 自动化' }, { value: 'WEB', label: 'Web 自动化' }]}
              onChange={() => {
                form.setFieldsValue({ case_ids: [], scan_target_id: undefined });
              }}
            />
          </Form.Item>
          <Form.Item name="title" label="任务名称">
            <Input maxLength={200} placeholder="例如：订单 API 回归验证" />
          </Form.Item>
          <Form.Item name="goal" label="整体目标" rules={[{ required: true, min: 3, max: 8000, message: '请输入至少 3 个字符的任务目标' }]}>
            <Input.TextArea rows={3} maxLength={8000} placeholder="描述本次测试目标和关注点" />
          </Form.Item>
          <Form.Item name="environment_id" label="执行环境" rules={[{ required: true, message: '请选择执行环境' }]}>
            <Select
              options={environments.map((item) => ({ value: item.id!, label: item.display_name || item.name }))}
              onChange={() => form.setFieldValue('scan_target_id', undefined)}
            />
          </Form.Item>
          <Form.Item name="case_ids" label={`已确认的${targetType === 'API' ? ' API' : ' Web'}用例`} rules={[{ required: true, type: 'array', min: 1, message: '至少选择一个已确认用例' }]}>
            <Select
              mode="multiple"
              showSearch
              optionFilterProp="label"
              loading={casesQuery.isLoading}
              disabled={projectId == null || cases.length === 0}
              options={cases.map((item) => ({ value: item.id, label: `#${item.id} ${item.name}${item.ready ? '' : '（未确认）'}`, disabled: !item.ready }))}
              placeholder={casesQuery.isError ? '用例加载失败，请重试' : `选择已确认的${targetType === 'API' ? ' API' : ' Web'}用例`}
            />
          </Form.Item>
          <Form.Item name="security_scan_enabled" valuePropName="checked">
            <Checkbox>附加 ZAP 安全扫描（需在任务方案确认时再次批准）</Checkbox>
          </Form.Item>
          {securityScanEnabled && (
            <>
              {scanTargetsQuery.isError || scanProfilesQuery.isError ? (
                <Alert type="error" showIcon message="读取安全扫描目标或策略失败，无法创建附加扫描任务" style={{ marginBottom: 16 }} />
              ) : (
                <>
                  <Form.Item name="scan_target_id" label="扫描目标" rules={[{ required: true, message: '请选择与执行环境匹配的扫描目标' }]}>
                    <Select
                      loading={scanTargetsQuery.isLoading}
                      options={scanTargets.map((target) => ({ value: target.id, label: `#${target.id} ${target.name} · ${target.target_type}` }))}
                      placeholder={scanTargets.length ? '选择已登记且类型匹配的扫描目标' : '当前环境没有兼容的已启用扫描目标'}
                    />
                  </Form.Item>
                  <Form.Item name="scan_profile_id" label="扫描策略" rules={[{ required: true, message: '请选择已启用的扫描策略' }]}>
                    <Select
                      loading={scanProfilesQuery.isLoading}
                      options={compatibleProfiles.map((profile) => ({ value: profile.id, label: `${profile.name}${profile.is_active_scan ? ' · 主动扫描' : ' · 被动扫描'}` }))}
                      placeholder="选择扫描策略"
                    />
                  </Form.Item>
                  <Alert type="warning" showIcon message="安全 Worker 只调用现有 ZAP 队列。主动扫描仍需项目管理员权限、目标授权和人工批准说明；任务取消会请求取消关联扫描。" style={{ marginBottom: 16 }} />
                </>
              )}
            </>
          )}
          {casesQuery.isError && <Alert type="error" showIcon message="读取项目用例失败" style={{ marginBottom: 16 }} />}
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
