// 任务创建表单：引用已确认用例或已登记安全范围，并要求明确选择执行环境。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { App, Alert, Button, Collapse, Form, Input, InputNumber, Modal, Select, Spin, Typography } from 'antd';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { useNavigate } from 'react-router-dom';
import { collectPages } from '@/shared/api/pagination';
import { projectsApi } from '@/features/projects/api/projects';
import { apiCatalogApi } from '@/features/api-catalog/api/apiCatalog';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { webUIApi } from '@/features/web-testing/api/webUI';
import { webAgentApi } from '@/features/browser-authoring/api';
import { securityApi } from '@/features/security-testing/api/securityTesting';
import { getErrorMessage } from '@/shared/api/client';
import { tasksApi } from '@/features/tasks/api/tasks';
import { clearTaskCreateUncertainty, readTaskCreateUncertainty, rememberTaskCreateUncertainty, type TaskCreateUncertainty } from '@/features/tasks/createUncertainty';
import type { AvailableTaskAgent, Task, TaskTemplate, TaskCreateRequest } from '@/features/tasks/contracts';
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
  initialTemplateId?: number;
  initialTemplateMode?: 'apply' | 'edit';
  initialReplayTaskId?: number;
}

const WORKFLOW_NAMES: Record<string, string> = {
  api_test: '接口测试',
  web_ui: 'Web UI 测试',
  security: '安全测试',
  reporting: '测试报告',
};

/** 创建 API/Web 任务或绑定既有安全策略的自研安全评估；资产仍通过原业务 API 读取。 */
function toTaskConfig(values: FormValues): TaskCreateRequest {
  const { target_type, web_auth_profile_id, web_target_page_path, web_step_budget, security_api_ids, security_web_session_id, security_strategy_ids } = values;
  const base: Partial<FormValues> = { ...values };
  delete base.project_id;
  delete base.target_type;
  delete base.security_api_ids;
  delete base.security_web_session_id;
  delete base.security_strategy_ids;
  delete base.web_auth_profile_id;
  delete base.web_target_page_path;
  delete base.web_step_budget;
  return {
    ...base,
    goal: values.goal,
    environment_id: values.environment_id,
    target_type,
    case_ids: target_type === 'SECURITY' || target_type === 'WEB_AUTHORING' ? [] : (base.case_ids ?? []),
    task_mode: target_type === 'WEB_AUTHORING' ? 'WEB_AUTHORING' : 'TEST_EXECUTION',
    web_authoring: target_type === 'WEB_AUTHORING'
      ? { auth_profile_id: web_auth_profile_id, target_page_path: web_target_page_path ?? '', step_budget: web_step_budget ?? 20 }
      : undefined,
    security_assessment: target_type === 'SECURITY'
      ? { api_ids: security_api_ids ?? [], web_session_id: security_web_session_id, strategy_ids: security_strategy_ids ?? [] }
      : undefined,
  };
}

function toTemplateConfig(values: Partial<FormValues>): TaskTemplate['config'] {
  const target_type = values.target_type ?? 'API';
  return {
    title: values.title,
    goal: values.goal ?? '',
    environment_id: values.environment_id,
    agent_definition_id: values.agent_definition_id,
    target_type,
    case_ids: target_type === 'SECURITY' || target_type === 'WEB_AUTHORING' ? [] : values.case_ids ?? [],
    task_mode: target_type === 'WEB_AUTHORING' ? 'WEB_AUTHORING' : 'TEST_EXECUTION',
    web_authoring: target_type === 'WEB_AUTHORING'
      ? { target_page_path: values.web_target_page_path ?? '', step_budget: values.web_step_budget ?? 20 }
      : undefined,
    security_assessment: target_type === 'SECURITY'
      ? { api_ids: values.security_api_ids ?? [], strategy_ids: values.security_strategy_ids ?? [] }
      : undefined,
  };
}

export function TaskCreateModal({ open, onClose, onCreated, initialProjectId, initialCaseIds = [], initialTargetType = 'API', initialTemplateId, initialTemplateMode = 'apply', initialReplayTaskId }: Props) {
  const [form] = Form.useForm<FormValues>();
  const initialized = useRef(false);
  const restoredCase = useRef(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [caseSearchInput, setCaseSearchInput] = useState('');
  const [caseKeyword, setCaseKeyword] = useState('');
  const [securityApiSearchInput, setSecurityApiSearchInput] = useState('');
  const [securityApiKeyword, setSecurityApiKeyword] = useState('');
  const [securityStrategySearchInput, setSecurityStrategySearchInput] = useState('');
  const [securityStrategyKeyword, setSecurityStrategyKeyword] = useState('');
  const [selectedCaseLabels, setSelectedCaseLabels] = useState<CaseOption[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<TaskTemplate | null>(null);
  const [templateSearch, setTemplateSearch] = useState('');
  const [templateSaveOpen, setTemplateSaveOpen] = useState(false);
  const [templateName, setTemplateName] = useState('');
  const [templateDescription, setTemplateDescription] = useState('');
  const [unknownCreate, setUnknownCreate] = useState<TaskCreateUncertainty | null>(() => readTaskCreateUncertainty());
  const createIntent = useRef<{ fingerprint: string; requestKey: string } | null>(null);
  const templateApplied = useRef(false);
  const replayApplied = useRef(false);
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const projectId = Form.useWatch('project_id', form);
  const environmentId = Form.useWatch('environment_id', form);
  const targetType = Form.useWatch('target_type', form) ?? 'API';
  const selectedAgentId = Form.useWatch('agent_definition_id', form);
  const selectedCaseIds = Form.useWatch('case_ids', form) ?? [];
  const selectedCaseIdsKey = selectedCaseIds.join(',');
  const PAGE_SIZE = 100;
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
  const templatesQuery = useQuery({
    queryKey: ['task-templates', projectId, templateSearch],
    queryFn: () => tasksApi.templates(projectId!, { keyword: templateSearch || undefined }),
    enabled: open && projectId != null,
  });
  const initialTemplateQuery = useQuery({
    queryKey: ['task-template', initialTemplateId],
    queryFn: () => tasksApi.getTemplate(initialTemplateId!),
    enabled: open && initialTemplateId != null,
  });
  const replayQuery = useQuery({
    queryKey: ['task-create-replay', initialReplayTaskId],
    queryFn: () => tasksApi.get(initialReplayTaskId!),
    enabled: open && initialReplayTaskId != null,
  });
  const casesQuery = useInfiniteQuery({
    queryKey: ['task-create-cases', projectId, targetType, caseKeyword],
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      if (targetType === 'API') {
        const items = await testManagementApi.listCases(projectId!, {
          target_type: 'API', status: 'ACTIVE', keyword: caseKeyword || undefined,
          page: pageParam, page_size: PAGE_SIZE,
        });
        return {
          items: items.map((item): CaseOption => ({ id: item.id, name: item.name, ready: item.enabled && item.status === 'ACTIVE' && item.api_id != null })),
          hasMore: items.length === PAGE_SIZE,
        };
      }
      const result = await webUIApi.cases(projectId!, pageParam, PAGE_SIZE, {
        keyword: caseKeyword || undefined,
        confirmed_only: true,
      });
      return {
        items: result.items.map((item): CaseOption => ({ id: item.id, name: item.name, ready: item.confirmed })),
        hasMore: pageParam * PAGE_SIZE < result.total,
      };
    },
    getNextPageParam: (lastPage, allPages) => lastPage.hasMore ? allPages.length + 1 : undefined,
    enabled: open && projectId != null && targetType !== 'SECURITY' && targetType !== 'WEB_AUTHORING',
  });
  const agentsQuery = useQuery({
    queryKey: ['task-create-agents', projectId, targetType],
    queryFn: () => tasksApi.availableAgents(projectId!, {
      target_type: targetType === 'WEB_AUTHORING' ? 'WEB' : targetType,
    }),
    enabled: open && projectId != null && advancedOpen,
  });
  const authoringAuthQuery = useQuery({
    queryKey: ['task-create-web-auth', projectId],
    queryFn: () => collectPages((page) => webUIApi.auth(projectId!, page, 200)),
    enabled: open && projectId != null && targetType === 'WEB_AUTHORING',
  });
  const securityApiIds = Form.useWatch('security_api_ids', form) ?? [];
  const securityStrategyIds = Form.useWatch('security_strategy_ids', form) ?? [];
  const securityApisQuery = useInfiniteQuery({
    queryKey: ['task-create-security-apis', projectId, securityApiKeyword],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => apiCatalogApi.listApis(projectId!, {
      status: 'ACTIVE', keyword: securityApiKeyword || undefined, page: pageParam, page_size: PAGE_SIZE,
    }),
    getNextPageParam: (lastPage) => lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined,
    enabled: open && projectId != null && targetType === 'SECURITY',
  });
  const selectedSecurityApisQuery = useQuery({
    queryKey: ['task-create-selected-security-apis', projectId, securityApiIds.join(',')],
    queryFn: () => Promise.all(securityApiIds.map((id) => apiCatalogApi.getApi(id))),
    enabled: open && projectId != null && targetType === 'SECURITY' && securityApiIds.length > 0,
  });
  const securityStrategiesQuery = useInfiniteQuery({
    queryKey: ['task-create-security-strategies', projectId, securityStrategyKeyword],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => securityApi.listStrategies(projectId!, {
      enabled: true, keyword: securityStrategyKeyword || undefined, page: pageParam, page_size: PAGE_SIZE,
    }),
    getNextPageParam: (lastPage) => lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined,
    enabled: open && projectId != null && targetType === 'SECURITY',
  });
  const selectedSecurityStrategiesQuery = useQuery({
    queryKey: ['task-create-selected-security-strategies', projectId, securityStrategyIds.join(',')],
    queryFn: () => Promise.all(securityStrategyIds.map((id) => securityApi.getStrategy(id))),
    enabled: open && projectId != null && targetType === 'SECURITY' && securityStrategyIds.length > 0,
  });
  const securityWebSessionsQuery = useQuery({
    queryKey: ['task-create-security-web-sessions', projectId],
    queryFn: () => collectPages((page) => webAgentApi.sessions(projectId!, page, 200)),
    enabled: open && projectId != null && targetType === 'SECURITY' && environmentId != null,
  });
  const createMutation = useMutation({
    mutationFn: (submission: { projectId: number; requestKey: string; fingerprint: string; formValues: FormValues; body: TaskCreateRequest }) =>
      tasksApi.create(submission.projectId, submission.body),
    onSuccess: async (task, submission) => {
      clearTaskCreateUncertainty(submission.requestKey);
      if (createIntent.current?.requestKey === submission.requestKey) createIntent.current = null;
      setUnknownCreate((previous) => previous?.request_key === submission.requestKey ? null : previous);
      await queryClient.invalidateQueries({ queryKey: ['tasks'] });
      message.success('任务已加入持久化调度队列');
      const current = { ...submission.formValues, ...form.getFieldsValue(true) } as FormValues;
      const currentFingerprint = JSON.stringify({ project_id: current.project_id, body: {
        ...toTaskConfig(current),
        template_id: selectedTemplate?.id,
        template_version: selectedTemplate?.version,
      } });
      if (currentFingerprint === submission.fingerprint && createIntent.current == null) {
        form.resetFields();
        onCreated?.(task);
        onClose();
      } else {
        message.info('较早提交的任务已创建；当前表单内容已保留');
      }
    },
    onError: (error, submission) => {
      message.error(getErrorMessage(error, '任务创建失败'));
      if (!isAxiosError(error) || !error.response || error.response.status >= 500) {
        const marker = { kind: 'task' as const, project_id: submission.projectId, request_key: submission.requestKey, recorded_at: Date.now() };
        rememberTaskCreateUncertainty(marker);
        setUnknownCreate(marker);
      } else clearTaskCreateUncertainty(submission.requestKey);
    },
  });
  const templateMutation = useMutation({
    mutationFn: async ({ values, mode }: { values: Partial<FormValues> & Pick<FormValues, 'project_id'>; mode: 'create' | 'update' }) => {
      const config = toTemplateConfig(values);
      const name = templateName.trim();
      const description = templateDescription.trim();
      if (mode === 'update' && selectedTemplate) {
        return tasksApi.updateTemplate(selectedTemplate.id, {
          expected_version: selectedTemplate.version, name, description, config,
        });
      }
      return tasksApi.createTemplate(values.project_id, { name, description, config, is_active: true });
    },
    onSuccess: async (template) => {
      setSelectedTemplate(template);
      setTemplateName(template.name);
      setTemplateDescription(template.description);
      setTemplateSaveOpen(false);
      await queryClient.invalidateQueries({ queryKey: ['task-templates', projectId] });
      message.success(`模板已保存为 v${template.version}`);
    },
    onError: (error) => message.error(getErrorMessage(error, '模板保存失败；草稿仍保留，请刷新并核对版本')),
  });

  const applyTemplate = useCallback(async (template: TaskTemplate) => {
    const config = template.config;
    const inferredTarget = config.target_type ?? (config.security_assessment ? 'SECURITY' : config.task_mode === 'WEB_AUTHORING' ? 'WEB_AUTHORING' : 'API');
    const security = config.security_assessment;
    const web = config.web_authoring;
    form.setFieldsValue({
      project_id: template.project_id,
      target_type: inferredTarget,
      title: config.title,
      goal: config.goal,
      environment_id: config.environment_id,
      case_ids: config.case_ids ?? [],
      agent_definition_id: config.agent_definition_id,
      security_api_ids: security?.api_ids ?? (security?.api_id ? [security.api_id] : []),
      security_strategy_ids: security?.strategy_ids ?? [],
      web_target_page_path: web?.target_page_path ?? '',
      web_step_budget: web?.step_budget ?? 20,
      web_auth_profile_id: undefined,
    });
    setSelectedTemplate(template);
    setTemplateName(template.name);
    setTemplateDescription(template.description);
    setAdvancedOpen(false);
    const caseIds = config.case_ids ?? [];
    if (caseIds.length && (inferredTarget === 'API' || inferredTarget === 'WEB')) {
      const labels = await Promise.all(caseIds.map(async (id): Promise<CaseOption | null> => {
        try {
          if (inferredTarget === 'WEB') {
            const item = await webUIApi.case(id);
            return item.project_id === template.project_id ? { id, name: item.name, ready: item.confirmed } : null;
          }
          const item = await testManagementApi.getCase(id);
          return item.project_id === template.project_id ? { id, name: item.name, ready: item.enabled && item.status === 'ACTIVE' && item.api_id != null } : null;
        } catch { return null; }
      }));
      if (form.getFieldValue('project_id') === template.project_id) {
        setSelectedCaseLabels(labels.filter((item): item is CaseOption => item != null));
      }
    } else {
      setSelectedCaseLabels([]);
    }
  }, [form]);
  const applyReplay = useCallback(async (task: Task) => {
    const snapshot = task.latest_run?.input_snapshot ?? {};
    const security = snapshot.security_assessment as { api_ids?: number[]; api_id?: number; strategy_ids?: number[] } | null;
    const web = snapshot.web_authoring as { target_page_path?: string; step_budget?: number } | null;
    const savedTarget = snapshot.target_type;
    const submittedInput = snapshot.submitted_input as { agent_definition_id?: number | null } | null;
    const replayTarget: FormValues['target_type'] = savedTarget === 'SECURITY'
      ? 'SECURITY'
      : savedTarget === 'WEB_AUTHORING' || task.task_mode === 'WEB_AUTHORING'
        ? 'WEB_AUTHORING'
        : savedTarget === 'WEB' ? 'WEB' : 'API';
    const caseIds = replayTarget === 'API' || replayTarget === 'WEB' ? task.input_case_ids ?? [] : [];
    const agent = snapshot.agent_definition as { id?: number } | null;
    form.setFieldsValue({
      project_id: task.project_id,
      target_type: replayTarget,
      title: `${task.title}（再次执行）`.slice(0, 200),
      goal: task.goal,
      environment_id: task.environment_id ?? undefined,
      case_ids: caseIds,
      agent_definition_id: agent?.id ?? submittedInput?.agent_definition_id ?? undefined,
      security_api_ids: security?.api_ids ?? (security?.api_id ? [security.api_id] : []),
      security_strategy_ids: security?.strategy_ids ?? [],
      security_web_session_id: undefined,
      web_target_page_path: web?.target_page_path ?? '',
      web_step_budget: web?.step_budget ?? 20,
      web_auth_profile_id: undefined,
    });
    setSelectedTemplate(null);
    setAdvancedOpen(false);
    const labels = await Promise.all(caseIds.map(async (id): Promise<CaseOption | null> => {
      try {
        if (replayTarget === 'WEB') {
          const item = await webUIApi.case(id);
          return item.project_id === task.project_id ? { id, name: item.name, ready: item.confirmed } : null;
        }
        const item = await testManagementApi.getCase(id);
        return item.project_id === task.project_id ? { id, name: item.name, ready: item.enabled && item.status === 'ACTIVE' && item.api_id != null } : null;
      } catch { return null; }
    }));
    setSelectedCaseLabels(labels.filter((item): item is CaseOption => item != null));
  }, [form]);

  useEffect(() => {
    if (!open) {
      initialized.current = false;
      restoredCase.current = false;
      templateApplied.current = false;
      replayApplied.current = false;
      setSelectedTemplate(null);
      setTemplateName('');
      setTemplateDescription('');
      setUnknownCreate(null);
      setAdvancedOpen(false);
      setCaseSearchInput('');
      setCaseKeyword('');
      setSelectedCaseLabels([]);
      return;
    }
    if (!initialized.current && (initialProjectId || currentProjectId || projectsQuery.data)) {
      form.setFieldValue('project_id', initialProjectId ?? currentProjectId ?? projectsQuery.data?.items[0]?.id);
      initialized.current = true;
    }
  }, [currentProjectId, form, initialProjectId, open, projectsQuery.data]);

  useEffect(() => {
    if (!open || templateApplied.current || !initialTemplateId || !initialTemplateQuery.data) return;
    const template = initialTemplateQuery.data;
    templateApplied.current = true;
    if (initialTemplateMode === 'apply' && !template.is_active) return;
    if (initialTemplateMode === 'edit') {
      setTemplateName(template.name);
      setTemplateDescription(template.description);
    }
    void applyTemplate(template);
  }, [applyTemplate, initialTemplateId, initialTemplateMode, initialTemplateQuery.data, open]);

  useEffect(() => {
    if (!open || replayApplied.current || initialReplayTaskId == null || !replayQuery.data) return;
    replayApplied.current = true;
    void applyReplay(replayQuery.data);
  }, [applyReplay, initialReplayTaskId, open, replayQuery.data]);

  useEffect(() => {
    if (open) form.setFieldValue('target_type', initialTargetType);
    else form.resetFields();
  }, [form, initialTargetType, open]);

  const initialCasesQuery = useQuery({
    queryKey: ['task-create-initial-cases', projectId, initialTargetType, initialCaseIds.join(',')],
    queryFn: async () => Promise.all(initialCaseIds.map(async (id) => {
      if (initialTargetType === 'WEB') {
        const item = await webUIApi.case(id);
        return { id: item.id, name: item.name, ready: item.confirmed, projectId: item.project_id };
      }
      const item = await testManagementApi.getCase(id);
      return { id: item.id, name: item.name, ready: item.enabled && item.status === 'ACTIVE' && item.api_id != null, projectId: item.project_id };
    })),
    enabled: open && projectId != null && initialCaseIds.length > 0 && targetType === initialTargetType && (targetType === 'API' || targetType === 'WEB'),
  });

  useEffect(() => {
    if (!open || restoredCase.current || initialCaseIds.length === 0 || !initialCasesQuery.isSuccess) return;
    const selected = initialCasesQuery.data.filter((item) => item.projectId === projectId && item.ready);
    form.setFieldValue('case_ids', selected.map((item) => item.id));
    setSelectedCaseLabels(selected.map(({ id, name, ready }) => ({ id, name, ready })));
    restoredCase.current = true;
  }, [form, initialCaseIds.length, initialCasesQuery.data, initialCasesQuery.isSuccess, open, projectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => setCaseKeyword(caseSearchInput.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [caseSearchInput]);
  useEffect(() => {
    const timer = window.setTimeout(() => setSecurityApiKeyword(securityApiSearchInput.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [securityApiSearchInput]);
  useEffect(() => {
    const timer = window.setTimeout(() => setSecurityStrategyKeyword(securityStrategySearchInput.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [securityStrategySearchInput]);

  const projects = projectsQuery.data?.items ?? [];
  const environments = (environmentsQuery.data?.items ?? []).filter((item) => item.is_active && item.id != null);
  const cases = useMemo(() => casesQuery.data?.pages.flatMap((page) => page.items) ?? [], [casesQuery.data]);
  const caseOptions = useMemo(() => {
    const byId = new Map<number, CaseOption>();
    [...selectedCaseLabels, ...cases].forEach((item) => byId.set(item.id, item));
    return [...byId.values()];
  }, [cases, selectedCaseLabels]);
  useEffect(() => {
    const selectedIds = (form.getFieldValue('case_ids') as number[] | undefined) ?? [];
    setSelectedCaseLabels((previous) => {
      const byId = new Map<number, CaseOption>();
      [...previous, ...cases].forEach((item) => byId.set(item.id, item));
      const next = selectedIds.map((id) => byId.get(id)).filter((item): item is CaseOption => item != null);
      return next.length === previous.length && next.every((item, index) => item.id === previous[index]?.id)
        ? previous
        : next;
    });
  }, [cases, form, selectedCaseIdsKey]);
  const agents = agentsQuery.data ?? [];
  const securityApis = (securityApisQuery.data?.pages.flatMap((page) => page.items) ?? []).filter((api) => api.status === 'ACTIVE');
  const selectedSecurityApis = (selectedSecurityApisQuery.data ?? []).filter((api) => api.project_id === projectId);
  const securityApiOptionsById = new Map([...selectedSecurityApis, ...securityApis].map((api) => [api.id, api]));
  const securityStrategies = (securityStrategiesQuery.data?.pages.flatMap((page) => page.items) ?? []).filter((strategy) => strategy.enabled);
  const selectedSecurityStrategies = (selectedSecurityStrategiesQuery.data ?? []).filter((strategy) => strategy.project_id == null || strategy.project_id === projectId);
  const securityStrategyOptionsById = new Map([...selectedSecurityStrategies, ...securityStrategies].map((strategy) => [strategy.id, strategy]));
  // Keep the form mounted while a project’s environments load. Unmounting the
  // Form unregisters project_id, which disables the environment query and can
  // otherwise make the loading state oscillate indefinitely.
  const initialLoading = projectsQuery.isLoading;
  const validateTemplateForm = async () => {
    const fields = ['project_id', 'target_type', 'goal'];
    if (targetType === 'API' || targetType === 'WEB') fields.push('case_ids');
    if (targetType === 'SECURITY') fields.push('security_api_ids', 'security_strategy_ids');
    await form.validateFields(fields);
    return form.getFieldsValue(true) as Partial<FormValues> & Pick<FormValues, 'project_id'>;
  };
  const handleCreate = (validatedValues: FormValues) => {
    if (createMutation.isPending) return;
    if (selectedTemplate && !selectedTemplate.is_active) {
      message.error('此模板已停用，可以编辑保存或重新启用后再套用');
      return;
    }
    const values = { ...form.getFieldsValue(true), ...validatedValues } as FormValues;
    const config = {
      ...toTaskConfig(values),
      template_id: selectedTemplate?.id,
      template_version: selectedTemplate?.version,
    };
    const fingerprint = JSON.stringify({ project_id: values.project_id, body: config });
    const retryingIntent = createIntent.current?.fingerprint === fingerprint ? createIntent.current : null;
    const previousUnknown = readTaskCreateUncertainty();
    if (previousUnknown && retryingIntent?.requestKey !== previousUnknown.request_key) {
      message.warning('请先到任务列表核对上一条结果未知的创建请求，再开始新的任务创建');
      return;
    }
    const intent = retryingIntent ?? { fingerprint, requestKey: `task-create-${crypto.randomUUID()}` };
    createIntent.current = intent;
    const marker = { kind: 'task' as const, project_id: values.project_id, request_key: intent.requestKey, recorded_at: Date.now() };
    rememberTaskCreateUncertainty(marker);
    createMutation.mutate({
      projectId: values.project_id,
      requestKey: intent.requestKey,
      fingerprint,
      formValues: values,
      body: { ...config, request_key: intent.requestKey },
    });
  };
  const requestClose = () => {
    if (createMutation.isPending) {
      message.info('任务正在提交，请等待服务器返回结果后再离开');
      return;
    }
    if (unknownCreate) {
      modal.confirm({
        title: unknownCreate.kind === 'defect' ? '缺陷关联结果尚未确认' : '任务创建结果尚未确认',
        content: `请求已发出但没有收到可靠响应。请检查项目 #${unknownCreate.project_id} 的相关记录；当前表单不会写入浏览器存储。`,
        okText: unknownCreate.kind === 'defect' ? '查看缺陷记录' : '返回任务列表核对',
        cancelText: '留在表单',
        onOk: () => { navigate(unknownCreate.kind === 'defect' ? '/console/defects' : '/console/tasks'); onClose(); },
      });
      return;
    }
    onClose();
  };

  return (
    <Modal
      title="创建任务"
      open={open}
      onCancel={requestClose}
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
      ) : initialLoading ? <Spin /> : initialTemplateId && initialTemplateQuery.isLoading ? <Spin /> : initialTemplateId && initialTemplateQuery.isError ? (
        <Alert
          type="error"
          showIcon
          message="无法读取此模板，表单未加载"
          description="模板不存在、已删除或当前账号没有读取权限。请返回模板列表刷新后重试。"
          action={<Button size="small" onClick={() => void initialTemplateQuery.refetch()}>重试</Button>}
        />
      ) : initialTemplateId && initialTemplateMode === 'apply' && initialTemplateQuery.data && !initialTemplateQuery.data.is_active ? (
        <Alert type="warning" showIcon message="此模板已停用，不能套用" description="有写入权限的成员可从模板列表进入“编辑”修改配置或重新启用。" />
      ) : projects.length === 0 ? (
        <Alert type="warning" showIcon message="当前账号没有可创建任务的项目" />
      ) : (
        <Form<FormValues>
          form={form}
          layout="vertical"
          onValuesChange={(changed) => {
            if ('target_type' in changed) {
              // Editing an existing template must keep its ID/version when its
              // configuration type changes. Applying a template to create a
              // different task still detaches it from the creation intent.
              if (initialTemplateMode !== 'edit') {
                setSelectedTemplate(null);
                setTemplateName('');
                setTemplateDescription('');
              }
              form.setFieldValue('agent_definition_id', undefined);
              form.setFieldValue('case_ids', []);
              setCaseSearchInput('');
              setCaseKeyword('');
              setSelectedCaseLabels([]);
            }
            if ('project_id' in changed) {
              setSelectedTemplate(null);
              setTemplateName('');
              setTemplateDescription('');
              form.setFieldsValue({ environment_id: undefined, case_ids: [], security_api_ids: [], security_web_session_id: undefined, security_strategy_ids: [], agent_definition_id: undefined, web_auth_profile_id: undefined, web_target_page_path: '', web_step_budget: 20 });
              setCaseSearchInput('');
              setCaseKeyword('');
              setSelectedCaseLabels([]);
            }
            if ('environment_id' in changed) form.setFieldValue('security_web_session_id', undefined);
          }}
          onFinish={handleCreate}
          initialValues={{ target_type: initialTargetType }}
        >
          <Form.Item name="project_id" label="项目" rules={[{ required: true, message: '请选择项目' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={projects.map((project) => ({ value: project.id, label: project.name }))}
              onChange={() => {
                restoredCase.current = true;
                setSelectedCaseLabels([]);
              }}
            />
          </Form.Item>
          <Form.Item label="从模板开始">
            <Select
              allowClear
              showSearch
              filterOption={false}
              onSearch={setTemplateSearch}
              onChange={(id: number | undefined) => {
                const template = templatesQuery.data?.find((item) => item.id === id);
                if (template) void applyTemplate(template);
                else { setSelectedTemplate(null); setTemplateName(''); setTemplateDescription(''); }
              }}
              value={selectedTemplate?.id}
              loading={templatesQuery.isLoading}
              disabled={projectId == null || templatesQuery.isError}
              options={(templatesQuery.data ?? []).map((item) => ({ value: item.id, label: `${item.name} · v${item.version}` }))}
              placeholder={templatesQuery.isError ? '读取模板失败，请刷新重试' : '可选：预填项目共享模板'}
            />
          </Form.Item>
          {selectedTemplate && (
            <div style={{ marginBottom: 16 }}>
              <Input value={templateName} onChange={(event) => setTemplateName(event.target.value)} maxLength={120} aria-label="模板名称" placeholder="模板名称" style={{ marginBottom: 8 }} />
              <Input.TextArea value={templateDescription} onChange={(event) => setTemplateDescription(event.target.value)} maxLength={500} rows={2} aria-label="模板说明" placeholder="模板说明（可选）" />
              {!selectedTemplate.is_active && <Alert type="warning" showIcon message="模板已停用：可编辑保存；重新启用前不能用于创建任务。" style={{ marginTop: 8 }} />}
            </div>
          )}
          <Form.Item name="target_type" label="执行类型" rules={[{ required: true }]}>
            <Select
              options={[{ value: 'API', label: 'API 自动化（已确认用例）' }, { value: 'WEB', label: 'Web 自动化（已确认用例）' }, { value: 'WEB_AUTHORING', label: '交互式 Web 编写' }, { value: 'SECURITY', label: '自研安全评估' }]}
              onChange={() => {
                restoredCase.current = true;
                setSelectedCaseLabels([]);
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
              {securityApisQuery.isError || selectedSecurityApisQuery.isError || securityStrategiesQuery.isError || selectedSecurityStrategiesQuery.isError || securityWebSessionsQuery.isError ? (
                <Alert type="error" showIcon message="读取接口、安全策略或 Web 会话失败，无法创建安全评估任务" style={{ marginBottom: 16 }} />
              ) : (
                <>
                  <Form.Item name="security_api_ids" label="评估接口（最多 10 个）" rules={[{ required: true, type: 'array', min: 1, max: 10, message: '请选择 1 到 10 个已登记的 API 接口' }]}>
                    <Select
                      showSearch
                      filterOption={false}
                      mode="multiple"
                      maxCount={10}
                      loading={securityApisQuery.isLoading || securityApisQuery.isFetchingNextPage || selectedSecurityApisQuery.isLoading}
                      onSearch={setSecurityApiSearchInput}
                      onPopupScroll={(event) => {
                        const node = event.currentTarget;
                        if (node.scrollTop + node.clientHeight >= node.scrollHeight - 32 && securityApisQuery.hasNextPage && !securityApisQuery.isFetchingNextPage) void securityApisQuery.fetchNextPage();
                      }}
                      options={[...securityApiOptionsById.values()].map((api) => ({ value: api.id, disabled: api.status !== 'ACTIVE', label: `#${api.id} ${api.method} ${api.path} · ${api.name}${api.status !== 'ACTIVE' ? '（已停用）' : ''}` }))}
                      placeholder={securityApis.length ? '选择当前项目中的 ACTIVE API；每个 API 需有功能用例作为基线' : '当前项目没有可用的 ACTIVE API'}
                    />
                  </Form.Item>
                  <Typography.Text type="secondary">接口候选按名称或路径在服务端搜索；滚动列表加载后续分页。</Typography.Text>
                  <Form.Item name="security_strategy_ids" label="安全策略" rules={[{ required: true, type: 'array', min: 1, message: '至少选择一个已启用的安全策略' }]}>
                    <Select
                      mode="multiple"
                      showSearch
                      filterOption={false}
                      loading={securityStrategiesQuery.isLoading || securityStrategiesQuery.isFetchingNextPage || selectedSecurityStrategiesQuery.isLoading}
                      onSearch={setSecurityStrategySearchInput}
                      onPopupScroll={(event) => {
                        const node = event.currentTarget;
                        if (node.scrollTop + node.clientHeight >= node.scrollHeight - 32 && securityStrategiesQuery.hasNextPage && !securityStrategiesQuery.isFetchingNextPage) void securityStrategiesQuery.fetchNextPage();
                      }}
                      options={[...securityStrategyOptionsById.values()].map((strategy) => ({ value: strategy.id, disabled: !strategy.enabled, label: `${strategy.name} · ${strategy.category}${strategy.enabled ? '' : '（已停用）'}` }))}
                      placeholder={securityStrategies.length ? '选择结构化安全策略' : '当前项目没有已启用的安全策略'}
                    />
                  </Form.Item>
                  <Typography.Text type="secondary">策略按名称、标识或说明在服务端搜索；滚动列表加载后续分页。</Typography.Text>
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
                filterOption={false}
                onSearch={setCaseSearchInput}
                onPopupScroll={(event) => {
                  const node = event.currentTarget;
                  if (node.scrollTop + node.clientHeight >= node.scrollHeight - 32 && casesQuery.hasNextPage && !casesQuery.isFetchingNextPage) {
                    void casesQuery.fetchNextPage();
                  }
                }}
                loading={casesQuery.isLoading || casesQuery.isFetchingNextPage}
                disabled={projectId == null || (casesQuery.isError && cases.length === 0)}
                options={caseOptions.map((item) => ({ value: item.id, label: `#${item.id} ${item.name}`, disabled: !item.ready }))}
                placeholder={casesQuery.isError ? '用例加载失败，请重试' : `搜索并选择已确认的${targetType === 'API' ? ' API' : ' Web'}用例`}
              />
            </Form.Item>
          )}
          {targetType !== 'SECURITY' && targetType !== 'WEB_AUTHORING' && casesQuery.isError && (
            <Alert
              type="error"
              showIcon
              message="读取项目用例失败"
              action={<Button size="small" onClick={() => void casesQuery.refetch()}>重试</Button>}
              style={{ marginBottom: 16 }}
            />
          )}
          <Collapse
            activeKey={advancedOpen ? ['advanced'] : []}
            onChange={(keys) => setAdvancedOpen(Array.isArray(keys) ? keys.includes('advanced') : keys === 'advanced')}
            items={[{
              key: 'advanced',
              label: '高级设置',
              children: (
                <>
                  <Form.Item name="agent_definition_id" label="执行 Agent（可选）">
                    <Select
                      allowClear
                      showSearch
                      optionFilterProp="label"
                      loading={agentsQuery.isLoading}
                      disabled={projectId == null || (agents.length === 0 && !agentsQuery.isError)}
                      options={agents.map((agent: AvailableTaskAgent) => ({
                        value: agent.id,
                        label: `${agent.name} · ${WORKFLOW_NAMES[agent.workflow_template] ?? agent.workflow_template} · ${agent.model_label ?? '全局默认模型'}${agent.child_agents?.length ? ` · 子 Agent ${agent.child_agents.length}` : ''}`,
                        title: agent.description || undefined,
                      }))}
                      placeholder={agentsQuery.isError ? 'Agent 列表加载失败' : agents.length ? '留空使用平台默认编排' : '当前项目暂无满足权限的 Agent，留空使用平台默认编排'}
                    />
                  </Form.Item>
                  {agents.find((agent) => agent.id === selectedAgentId)?.child_agents?.map((child) => <Typography.Paragraph key={child.id} type="secondary" style={{ marginBottom: 4 }}>
                    主 Agent → {child.name} · v{child.version} · {child.model_label ?? '继承主 Agent 模型'}
                  </Typography.Paragraph>)}
                  {agentsQuery.isError ? (
                    <Alert type="error" showIcon message="读取可用 Agent 失败" action={<Button size="small" onClick={() => void agentsQuery.refetch()}>重试</Button>} />
                  ) : agents.length > 0 && (
                    <Alert type="info" showIcon message="Agent 配置将在本次运行中固定" description="指令、Skill、工作流与工具配置会记录到运行快照；版本修改只影响新任务。停用 Agent、关闭组织智能体权限或撤销模型授权会立即阻止后续工作项。" />
                  )}
                </>
              ),
            }]}
          />
          {templatesQuery.isError && <Alert type="error" showIcon message="读取任务模板失败，仍可手动创建" style={{ marginTop: 12 }} />}
          {unknownCreate && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 12 }}
              message={unknownCreate.kind === 'defect' ? '缺陷关联结果未知' : '任务创建结果未知'}
              description={`请核对项目 #${unknownCreate.project_id} 的相关记录。刷新后不会恢复敏感表单内容；如未找到，请先完成核对再发起新请求。`}
              action={<Button size="small" onClick={() => { navigate(unknownCreate.kind === 'defect' ? '/console/defects' : '/console/tasks'); onClose(); }}>{unknownCreate.kind === 'defect' ? '查看缺陷' : '查看任务列表'}</Button>}
            />
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button
              onClick={async () => {
                try {
                  const values = await validateTemplateForm();
                  if (selectedTemplate) templateMutation.mutate({ values, mode: 'update' });
                  else setTemplateSaveOpen(true);
                } catch { /* Form displays field validation feedback. */ }
              }}
              loading={templateMutation.isPending}
              disabled={projectId == null}
            >{selectedTemplate ? '更新当前模板' : '保存为模板'}</Button>
            <Button onClick={requestClose}>取消</Button>
            <Button type="primary" htmlType="submit" loading={createMutation.isPending} disabled={selectedTemplate != null && !selectedTemplate.is_active}>
              创建并开始规划
            </Button>
          </div>
        </Form>
      )}
      <Modal
        title="保存项目任务模板"
        open={templateSaveOpen}
        onCancel={() => setTemplateSaveOpen(false)}
        onOk={async () => {
          if (!templateName.trim()) return;
          try {
            const values = await validateTemplateForm();
            templateMutation.mutate({ values, mode: 'create' });
          } catch { /* Form displays field validation feedback. */ }
        }}
        confirmLoading={templateMutation.isPending}
        okText="保存模板"
      >
        <Input value={templateName} onChange={(event) => setTemplateName(event.target.value)} maxLength={120} placeholder="模板名称" style={{ marginBottom: 12 }} />
        <Input.TextArea value={templateDescription} onChange={(event) => setTemplateDescription(event.target.value)} maxLength={500} rows={3} placeholder="模板说明（可选）" />
      </Modal>
    </Modal>
  );
}
