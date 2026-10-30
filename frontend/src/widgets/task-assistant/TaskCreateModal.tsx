// 任务创建表单：引用已确认用例或已登记安全范围，并要求明确选择执行环境。
import { useEffect, useRef } from 'react';
import { App, Alert, Button, Form, Input, InputNumber, Modal, Select, Spin } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { collectArrayPages, collectPages } from '@/shared/api/pagination';
import { projectsApi } from '@/features/projects/api/projects';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { webUIApi } from '@/features/web-testing/api/webUI';
import { webAgentApi } from '@/features/browser-authoring/api';
import { securityApi } from '@/features/security-testing/api/securityTesting';
import { getErrorMessage } from '@/shared/api/client';
import { tasksApi } from '@/features/tasks/api/tasks';
import type { AvailableTaskAgent, Task } from '@/features/tasks/contracts';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';

interface FormValues {
  project_id: number;
  title?: string;
  goal: string;
  agent_definition_id?: number;
  environment_id: number;
  target_type: 'API' | 'WEB' | 'SECURITY' | 'WEB_AUTHORING';
  case_ids: number[];
  web_auth_profile_id?: number;
  web_target_page_path?: string;
  web_step_budget?: number;
  security_api_ids?: number[];
  security_web_session_id?: number;
  security_strategy_ids?: number[];
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
  initialTargetType?: 'API' | 'WEB' | 'SECURITY' | 'WEB_AUTHORING';
}

const WORKFLOW_NAMES: Record<string, string> = {
  api_test: '接口测试',
  web_ui: 'Web UI 测试',
  security: '安全测试',
  reporting: '测试报告',
};

/** 创建 API/Web 任务或绑定既有安全策略的自研安全评估；资产仍通过原业务 API 读取。 */
export function TaskCreateModal({ open, onClose, onCreated, initialProjectId, initialCaseIds = [], initialTargetType = 'API' }: Props) {
  const [form] = Form.useForm<FormValues>();
  const initialized = useRef(false);
  const restoredCase = useRef(false);
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const projectId = Form.useWatch('project_id', form);
  const environmentId = Form.useWatch('environment_id', form);
  const targetType = Form.useWatch('target_type', form) ?? 'API';
  const projectsQuery = useQuery({
    queryKey: ['projects', { taskCreate: true }],
    queryFn: () => collectPages((page) => projectsApi.list({ page, page_size: 200 })),
    enabled: open,
  });
  const environmentsQuery = useQuery({
    queryKey: ['task-create-environments', projectId],
    queryFn: () => projectsApi.listEnvironments(projectId!),
    enabled: open && projectId != null,
  });
  const casesQuery = useQuery({
    queryKey: ['task-create-cases', projectId, targetType],
    queryFn: async () => {
      if (targetType === 'API') {
        const pageSize = 200;
        const all = await collectArrayPages(
          (page) => testManagementApi.listCases(projectId!, {
            target_type: 'API', status: 'ACTIVE', page, page_size: pageSize,
          }),
          pageSize,
        );
        return all.map((item): CaseOption => ({ id: item.id, name: item.name, ready: item.enabled && item.status === 'ACTIVE' && item.api_id != null }));
      }
      const all = await collectPages((page) => webUIApi.cases(projectId!, page, 200));
      return all.items
        .map((item): CaseOption => ({ id: item.id, name: item.name, ready: item.confirmed }));
    },
    enabled: open && projectId != null && targetType !== 'SECURITY' && targetType !== 'WEB_AUTHORING',
  });
  const agentsQuery = useQuery({
    queryKey: ['task-create-agents', projectId, targetType],
    queryFn: () => tasksApi.availableAgents(projectId!, {
      target_type: targetType === 'WEB_AUTHORING' ? 'WEB' : targetType,
    }),
    enabled: open && projectId != null,
  });
  const authoringAuthQuery = useQuery({
    queryKey: ['task-create-web-auth', projectId],
    queryFn: () => collectPages((page) => webUIApi.auth(projectId!, page, 200)),
    enabled: open && projectId != null,
  });
  const securityApisQuery = useQuery({
    queryKey: ['task-create-security-apis', projectId],
    queryFn: () => collectPages((page) => apiCatalogApi.listApis(projectId!, { status: 'ACTIVE', page, page_size: 200 })),
    enabled: open && projectId != null,
  });
  const securityStrategiesQuery = useQuery({
    queryKey: ['task-create-security-strategies', projectId],
    queryFn: () => collectPages((page) => securityApi.listStrategies(projectId!, { enabled: true, page, page_size: 200 })),
    enabled: open && projectId != null,
  });
  const securityWebSessionsQuery = useQuery({
    queryKey: ['task-create-security-web-sessions', projectId],
    queryFn: () => collectPages((page) => webAgentApi.sessions(projectId!, page, 200)),
    enabled: open && projectId != null,
  });
  const createMutation = useMutation({
    mutationFn: ({ project_id, target_type, security_api_ids, security_web_session_id, security_strategy_ids, web_auth_profile_id, web_target_page_path, web_step_budget, ...body }: FormValues) => tasksApi.create(project_id, {
      ...body,
      case_ids: target_type === 'SECURITY' || target_type === 'WEB_AUTHORING' ? [] : body.case_ids,
      task_mode: target_type === 'WEB_AUTHORING' ? 'WEB_AUTHORING' : 'TEST_EXECUTION',
      web_authoring: target_type === 'WEB_AUTHORING'
        ? { auth_profile_id: web_auth_profile_id, target_page_path: web_target_page_path ?? '', step_budget: web_step_budget ?? 20 }
        : undefined,
      security_assessment: target_type === 'SECURITY'
        ? { api_ids: security_api_ids!, web_session_id: security_web_session_id, strategy_ids: security_strategy_ids! }
        : undefined,
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
    if (!open) {
      initialized.current = false;
      restoredCase.current = false;
      return;
    }
    if (!initialized.current && (initialProjectId || currentProjectId || projectsQuery.data)) {
      form.setFieldValue('project_id', initialProjectId ?? currentProjectId ?? projectsQuery.data?.items[0]?.id);
      initialized.current = true;
    }
  }, [currentProjectId, form, initialProjectId, open, projectsQuery.data]);

  useEffect(() => {
    if (open) form.setFieldValue('target_type', initialTargetType);
    else form.resetFields();
  }, [form, initialTargetType, open]);

  useEffect(() => {
    if (!open || restoredCase.current || initialCaseIds.length === 0 || projectId !== (initialProjectId ?? projectId) || targetType !== initialTargetType || !casesQuery.data) return;
    // 仅恢复当前项目和类型中仍可执行的用例，避免误选同 ID 的其他资产。
    form.setFieldValue('case_ids', initialCaseIds.filter((id) => casesQuery.data.some((item) => item.id === id && item.ready)));
    restoredCase.current = true;
  }, [casesQuery.data, form, initialCaseIds, initialProjectId, initialTargetType, open, projectId, targetType]);

  const projects = projectsQuery.data?.items ?? [];
  const environments = (environmentsQuery.data?.items ?? []).filter((item) => item.is_active && item.id != null);
  const cases = casesQuery.data ?? [];
  const agents = agentsQuery.data ?? [];
  const securityApis = (securityApisQuery.data?.items ?? []).filter((api) => api.status === 'ACTIVE');
  const securityStrategies = (securityStrategiesQuery.data?.items ?? []).filter((strategy) => strategy.enabled);
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
      {projectsQuery.isError ? (
        <Alert
          type="error"
          showIcon
          message="读取项目列表失败"
          action={<Button size="small" onClick={() => void projectsQuery.refetch()}>重试</Button>}
        />
      ) : initialLoading ? <Spin /> : projects.length === 0 ? (
        <Alert type="warning" showIcon message="当前账号没有可创建任务的项目" />
      ) : (
        <Form<FormValues>
          form={form}
          layout="vertical"
          onValuesChange={(changed) => {
            if ('target_type' in changed) form.setFieldValue('agent_definition_id', undefined);
            if ('environment_id' in changed) form.setFieldValue('security_web_session_id', undefined);
          }}
          onFinish={(values) => createMutation.mutate(values)}
          initialValues={{ target_type: initialTargetType }}
        >
          <Form.Item name="project_id" label="项目" rules={[{ required: true, message: '请选择项目' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={projects.map((project) => ({ value: project.id, label: project.name }))}
              onChange={() => {
                restoredCase.current = true;
                form.setFieldsValue({ environment_id: undefined, case_ids: [], security_api_ids: [], security_web_session_id: undefined, security_strategy_ids: [], agent_definition_id: undefined, web_auth_profile_id: undefined, web_target_page_path: '', web_step_budget: 20 });
              }}
            />
          </Form.Item>
          <Form.Item name="target_type" label="执行类型" rules={[{ required: true }]}>
            <Select
              options={[{ value: 'API', label: 'API 自动化（已确认用例）' }, { value: 'WEB', label: 'Web 自动化（已确认用例）' }, { value: 'WEB_AUTHORING', label: '交互式 Web 编写' }, { value: 'SECURITY', label: '自研安全评估' }]}
              onChange={() => {
                restoredCase.current = true;
                form.setFieldsValue({ case_ids: [], security_api_ids: [], security_web_session_id: undefined, security_strategy_ids: [], agent_definition_id: undefined, web_auth_profile_id: undefined, web_target_page_path: '', web_step_budget: 20 });
              }}
            />
          </Form.Item>
          <Form.Item name="agent_definition_id" label="执行 Agent（可选）">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              loading={agentsQuery.isLoading}
              disabled={projectId == null || agents.length === 0}
              options={agents.map((agent: AvailableTaskAgent) => ({
                value: agent.id,
                label: `${agent.name} · ${WORKFLOW_NAMES[agent.workflow_template] ?? agent.workflow_template}`,
                title: agent.description || undefined,
              }))}
              placeholder={agentsQuery.isError ? 'Agent 列表加载失败' : agents.length ? '留空使用平台默认编排' : '当前项目暂无满足权限的 Agent，留空使用平台默认编排'}
            />
          </Form.Item>
          {agentsQuery.isError ? (
            <Alert type="error" showIcon message="读取可用 Agent 失败" style={{ marginBottom: 16 }} />
          ) : agents.length > 0 && (
            <Alert type="info" showIcon message="Agent 配置将在本次运行中固定" description="指令、Skill、工作流与工具配置会记录到运行快照；版本修改只影响新任务。停用 Agent、关闭组织智能体权限或撤销模型授权会立即阻止后续工作项。" style={{ marginBottom: 16 }} />
          )}
          <Form.Item name="title" label="任务名称">
            <Input maxLength={200} placeholder="例如：订单 API 回归验证" />
          </Form.Item>
          <Form.Item name="goal" label="整体目标" rules={[{ required: true, min: 3, max: 8000, message: '请输入至少 3 个字符的任务目标' }]}>
            <Input.TextArea rows={3} maxLength={8000} placeholder="描述本次测试目标和关注点" />
          </Form.Item>
          <Form.Item name="environment_id" label="执行环境" rules={[{ required: true, message: '请选择执行环境' }]}>
            <Select
              loading={environmentsQuery.isLoading}
              options={environments.map((item) => ({ value: item.id!, label: item.display_name || item.name }))}
            />
          </Form.Item>
          {environmentsQuery.isError ? <Alert type="error" showIcon message="读取执行环境失败" style={{ marginBottom: 16 }} /> : environments.length === 0 && <Alert type="warning" showIcon message="当前项目没有可用的执行环境，请选择其他项目或先绑定环境" style={{ marginBottom: 16 }} />}
          {targetType === 'WEB_AUTHORING' ? (
            <>
              <Alert type="info" showIcon message="交互式 Web 编写会创建独立任务运行和 UI Worker。批准方案后启动受控浏览器；每个页面操作都需人工确认，完成后只生成未确认草稿。" style={{ marginBottom: 16 }} />
              <Form.Item name="web_target_page_path" label="目标页路径">
                <Input maxLength={2000} placeholder="例如 /orders；留空从环境入口开始" />
              </Form.Item>
              <Form.Item name="web_auth_profile_id" label="受控登录态（可选）">
                <Select
                  allowClear
                  loading={authoringAuthQuery.isLoading}
                  disabled={environmentId == null}
                  options={(authoringAuthQuery.data?.items ?? []).filter((item) => item.environment_id === environmentId).map((item) => ({ value: item.id, label: `${item.name} · 到期 ${item.expires_at}` }))}
                  placeholder="仅显示当前环境的登录态引用；凭据不会交给模型"
                />
              </Form.Item>
              <Form.Item name="web_step_budget" label="最大确认步骤数" initialValue={20} rules={[{ required: true, type: 'number', min: 1, max: 100 }]}>
                <InputNumber min={1} max={100} style={{ width: '100%' }} />
              </Form.Item>
              {authoringAuthQuery.isError && <Alert type="error" showIcon message="读取受控登录态失败" style={{ marginBottom: 16 }} />}
            </>
          ) : targetType === 'SECURITY' ? (
            <>
              {securityApisQuery.isError || securityStrategiesQuery.isError || securityWebSessionsQuery.isError ? (
                <Alert type="error" showIcon message="读取接口、安全策略或 Web 会话失败，无法创建安全评估任务" style={{ marginBottom: 16 }} />
              ) : (
                <>
                  <Form.Item name="security_api_ids" label="评估接口（最多 10 个）" rules={[{ required: true, type: 'array', min: 1, max: 10, message: '请选择 1 到 10 个已登记的 API 接口' }]}>
                    <Select
                      showSearch
                      optionFilterProp="label"
                      mode="multiple"
                      maxCount={10}
                      loading={securityApisQuery.isLoading}
                      options={securityApis.map((api) => ({ value: api.id, label: `#${api.id} ${api.method} ${api.path} · ${api.name}` }))}
                      placeholder={securityApis.length ? '选择当前项目中的 ACTIVE API；每个 API 需有功能用例作为基线' : '当前项目没有可用的 ACTIVE API'}
                    />
                  </Form.Item>
                  <Form.Item name="security_strategy_ids" label="安全策略" rules={[{ required: true, type: 'array', min: 1, message: '至少选择一个已启用的安全策略' }]}>
                    <Select
                      mode="multiple"
                      showSearch
                      optionFilterProp="label"
                      loading={securityStrategiesQuery.isLoading}
                      options={securityStrategies.map((strategy) => ({ value: strategy.id, label: `${strategy.name} · ${strategy.category}` }))}
                      placeholder={securityStrategies.length ? '选择结构化安全策略' : '当前项目没有已启用的安全策略'}
                    />
                  </Form.Item>
                  <Form.Item name="security_web_session_id" label="被动检查当前 Web 页面（可选）">
                    <Select
                      allowClear
                      loading={securityWebSessionsQuery.isLoading}
                      disabled={environmentId == null}
                      options={(securityWebSessionsQuery.data?.items ?? [])
                        .filter((session) => session.status === 'ACTIVE' && session.environment_id === environmentId)
                        .map((session) => ({ value: session.id, label: `会话 #${session.id} · 环境 #${session.environment_id} · ${session.target_page_path || '当前页'}` }))}
                      placeholder="仅显示当前执行环境仍打开的会话；不选则只进行 API 安全评估"
                    />
                  </Form.Item>
                  <Alert type="warning" showIcon message="安全 Agent 可批量评估最多 10 个已登记 API，并可选检查同一执行环境中已打开的受控 Web 页面。页面检查只读取当前响应头与有限 DOM 信号，不导航、不点击、不提交表单。方案需人工确认；高风险变异另需显式确认。" style={{ marginBottom: 16 }} />
                </>
              )}
            </>
          ) : (
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
          )}
          {targetType !== 'SECURITY' && casesQuery.isError && <Alert type="error" showIcon message="读取项目用例失败" style={{ marginBottom: 16 }} />}
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
