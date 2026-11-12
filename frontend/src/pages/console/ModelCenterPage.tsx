// 统一维护文本推理、ASR 与说话人模型的连接修订和独立参数方案。
import {
  Alert, App, Button, Card, Checkbox, Form, Input, InputNumber, Modal, Select, Space,
  Switch, Table, Tag, Tabs, Typography,
} from 'antd';
import { ExperimentOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '@/app/providers/AuthProvider';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { useSearchParams } from 'react-router-dom';
import { modelCenterApi, modelCenterQueryKeys, type ModelCategory, type ModelConnectionTestResult, type ModelDiagnosticRun, type ModelParameterProfile, type ModelResource, type ModelResourceWrite } from '@/features/model-configuration/api/modelCenter';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { collectPages } from '@/shared/api/pagination';

interface ResourceFormValues {
  visibility?: 'PLATFORM' | 'PROJECT'; project_id?: number; display_name: string; provider: string;
  adapter_key: string; model_name: string; endpoint: string; credential?: string; credential_header?: string;
  config_json: string; capabilities: string[]; parameter_schema_json: string; enabled: boolean;
  profile_name: string; profile_values_json: string; profile_definitions_json: string;
}

interface ProfileFormValues {
  revision_id: number; name: string; values_json: string; definitions_json: string;
}

interface DiagnosticFormValues {
  profile_id?: number; audio_id?: number; confirm_model_call: boolean;
}

const CATEGORY_LABELS: Record<ModelCategory, string> = {
  TEXT_GENERATION: '文本推理', ASR: 'ASR 转写', DIARIZATION: '说话人分段',
};

const CAPABILITY_LABELS: Record<string, string> = {
  text_generation: '文本推理', transcription: '转写文本', timestamped_segments: '句级时间戳',
  word_timestamps: '词级时间戳', native_speaker_labels: '原生说话人标签', channel_metadata: '声道元数据',
  confidence: '置信度', speaker_intervals: '说话人时间区间', speaker_text_segments: '带说话人文本段',
  overlap_intervals: '重叠发言区间',
};

const SILICONFLOW_CONFIG = {
  timeout_seconds: 180, max_response_bytes: 8000000,
  max_audio_bytes: 52428800, audio_download_timeout_seconds: 60,
  response_mapping: {
    text_pointer: '/text', segments_pointer: '/segments', segment_text_pointer: '/text',
    segment_id_pointer: '/id', start_pointer: '/start', end_pointer: '/end',
    speaker_pointer: '/speaker', time_unit: 'seconds',
  },
};

const JSON_CONFIG_EXAMPLES: Record<ModelCategory, string> = {
  TEXT_GENERATION: '{\n  "timeout": 60\n}',
  ASR: '{\n  "method": "POST",\n  "headers": {},\n  "request_template": {\n    "audio_url": "{{audio.url}}",\n    "parameters": "{{experiment.parameters}}"\n  },\n  "response_mapping": { "text_pointer": "/text" },\n  "timeout_seconds": 180,\n  "max_response_bytes": 8000000\n}',
  DIARIZATION: '{\n  "method": "POST",\n  "headers": {},\n  "request_template": {\n    "audio_url": "{{audio.url}}",\n    "parameters": "{{experiment.parameters}}"\n  },\n  "response_mapping": {\n    "segments_pointer": "/segments", "start_pointer": "/segments/0/start",\n    "end_pointer": "/segments/0/end", "speaker_pointer": "/segments/0/speaker_id",\n    "time_unit": "seconds"\n  },\n  "timeout_seconds": 180,\n  "max_response_bytes": 8000000\n}',
};

const PROFILE_EXAMPLES: Record<ModelCategory, string> = {
  TEXT_GENERATION: '{\n  "temperature": 0.2,\n  "max_tokens": 4096\n}',
  ASR: '{\n  "language": "",\n  "hotwords": [],\n  "vad": {},\n  "punctuation": false,\n  "timestamps": false\n}',
  DIARIZATION: '{\n  "language": ""\n}',
};

const PARAMETER_SCHEMA_EXAMPLES: Record<ModelCategory, string> = {
  TEXT_GENERATION: '[]',
  ASR: '[\n  {"path":"/language","display_name":"识别语言","value_type":"string","description":"按当前供应商 API 文档填写"},\n  {"path":"/hotwords","display_name":"热词","value_type":"array"},\n  {"path":"/vad","display_name":"VAD 参数","value_type":"object"},\n  {"path":"/punctuation","display_name":"标点恢复","value_type":"boolean"},\n  {"path":"/timestamps","display_name":"输出时间戳","value_type":"boolean"}\n]',
  DIARIZATION: '[\n  {"path":"/language","display_name":"语言","value_type":"string"}\n]',
};

/** 解析配置 JSON 并将语法错误显示在当前表单上下文。 */
function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(label + '必须是 JSON 对象');
  return parsed as Record<string, unknown>;
}

/** 解析 JSON 数组，兼容空文本作为空列表。 */
function parseJsonArray(value: string, label: string): Array<Record<string, unknown>> {
  const parsed: unknown = JSON.parse(value || '[]');
  if (!Array.isArray(parsed)) throw new Error(label + '必须是 JSON 数组');
  return parsed as Array<Record<string, unknown>>;
}

function readJsonPointer(source: Record<string, unknown>, pointer: string): unknown {
  if (!pointer.startsWith('/')) return undefined;
  return pointer.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'))
    .reduce<unknown>((value, key) => value && typeof value === 'object' ? (value as Record<string, unknown>)[key] : undefined, source);
}

function writeJsonPointer(source: Record<string, unknown>, pointer: string, next: unknown): Record<string, unknown> {
  if (!pointer.startsWith('/')) return source;
  const result = structuredClone(source);
  const parts = pointer.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'));
  let current: Record<string, unknown> = result;
  parts.slice(0, -1).forEach((part) => {
    if (!current[part] || typeof current[part] !== 'object' || Array.isArray(current[part])) current[part] = {};
    current = current[part] as Record<string, unknown>;
  });
  if (next === undefined) delete current[parts.at(-1)!];
  else current[parts.at(-1)!] = next;
  return result;
}

function parseObjectOrEmpty(value: string): Record<string, unknown> {
  try { return parseJsonObject(value, '参数方案'); } catch { return {}; }
}

function StructuredValueField({
  value, onCommit,
}: { value: unknown; onCommit: (value: unknown) => void }) {
  const [text, setText] = useState(JSON.stringify(value ?? {}, null, 2));
  const [invalid, setInvalid] = useState(false);
  useEffect(() => { setText(JSON.stringify(value ?? {}, null, 2)); setInvalid(false); }, [value]);
  return <>
    <Input.TextArea value={text} rows={4} spellCheck={false} status={invalid ? 'error' : undefined}
      onChange={(event) => setText(event.target.value)} onBlur={() => {
        try { onCommit(JSON.parse(text)); setInvalid(false); } catch { setInvalid(true); }
      }} />
    {invalid && <Typography.Text type="danger">请输入有效的 JSON 对象</Typography.Text>}
  </>;
}

/** 根据当前连接声明生成参数控件；未知字段和值会原样保留在 JSON 中。 */
function ParameterValuesEditor({
  value, onChange, definitions,
}: { value?: string; onChange?: (value: string) => void; definitions: Array<Record<string, unknown>> }) {
  const source = parseObjectOrEmpty(value || '{}');
  const update = (path: string, next: unknown) => onChange?.(JSON.stringify(writeJsonPointer(source, path, next), null, 2));

  return <div>
    {definitions.filter((item) => typeof item.path === 'string' && String(item.path).startsWith('/')).map((definition) => {
      const path = String(definition.path);
      const type = String(definition.value_type || 'string');
      const current = readJsonPointer(source, path);
      const title = `${String(definition.display_name || path)}${definition.required ? '（必填）' : ''}`;
      const choices = Array.isArray(definition.choices) ? definition.choices : undefined;
      let control;
      if (choices) {
        control = <Select allowClear value={current} options={choices.map((choice) => ({ value: choice, label: String(choice) }))}
          onChange={(next) => update(path, next)} />;
      } else if (type === 'boolean') {
        control = <Switch checked={Boolean(current)} onChange={(next) => update(path, next)} />;
      } else if (type === 'integer' || type === 'number') {
        control = <InputNumber style={{ width: '100%' }} value={typeof current === 'number' ? current : undefined}
          min={typeof definition.minimum === 'number' ? definition.minimum : undefined}
          max={typeof definition.maximum === 'number' ? definition.maximum : undefined}
          step={type === 'integer' ? 1 : undefined} onChange={(next) => update(path, next ?? undefined)} />;
      } else if (type === 'array') {
        control = <Select mode="tags" value={Array.isArray(current) ? current as string[] : []}
          onChange={(next) => update(path, next)} placeholder="输入后按回车添加" />;
      } else if (type === 'object') {
        control = <StructuredValueField value={current} onCommit={(next) => update(path, next)} />;
      } else {
        const serialized = current === undefined ? '' : String(current);
        control = <Input value={serialized} onChange={(event) => {
          update(path, event.target.value);
        }} />;
      }
      return <Form.Item key={path} label={title} extra={String(definition.description || definition.unit || '')}>{control}</Form.Item>;
    })}
    <Input.TextArea value={value || '{}'} onChange={(event) => onChange?.(event.target.value)} rows={4} spellCheck={false}
      aria-label="参数值 JSON 对象" />
  </div>;
}

/** 递归拒绝导入内容中的凭据字段；header 字段名与 header 密钥值分开判断。 */
function containsSensitiveImportField(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(containsSensitiveImportField);
  if (!value || typeof value !== 'object') return false;
  return Object.entries(value as Record<string, unknown>).some(([key, item]) => {
    const normalized = key.toLowerCase().replace(/-/g, '_');
    if (normalized === 'credential_header' || normalized === 'secret_header') return false;
    return /(authorization|access[-_]?token|auth[-_]?token|secret|password|api[-_]?key|cookie|credential|private[-_]?key)/i.test(key)
      || containsSensitiveImportField(item);
  });
}

/** 统一模型中心页面。 */
export function ModelCenterPage() {
  const { message } = App.useApp();
  const { isPlatformAdmin } = useAuth();
  const { currentProjectId } = useConsoleScope();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [category, setCategory] = useState<ModelCategory>(() => {
    const requested = searchParams.get('category');
    return requested === 'ASR' || requested === 'DIARIZATION' ? requested : 'TEXT_GENERATION';
  });
  const [resourceOpen, setResourceOpen] = useState(false);
  const [connectionTestResult, setConnectionTestResult] = useState<ModelConnectionTestResult | null>(null);
  const [revisionTarget, setRevisionTarget] = useState<ModelResource | null>(null);
  const [profileTarget, setProfileTarget] = useState<ModelResource | null>(null);
  const [diagnosticTarget, setDiagnosticTarget] = useState<ModelResource | null>(null);
  const [diagnosticRunId, setDiagnosticRunId] = useState<number | null>(null);

  const [defaultTarget, setDefaultTarget] = useState<ModelResource | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importJson, setImportJson] = useState('[]');
  const [importPreview, setImportPreview] = useState<{ valid_count: number; invalid_count: number; can_apply: boolean; items: Array<{ index: number; valid: boolean; errors: string[]; display_name?: string | null }> } | null>(null);
  const [resourceForm] = Form.useForm<ResourceFormValues>();
  const [profileForm] = Form.useForm<ProfileFormValues>();
  const [diagnosticForm] = Form.useForm<DiagnosticFormValues>();

  const [defaultForm] = Form.useForm<{
    revision_id: number; profile_id?: number; purpose: string;
    fallback_resource_ids: number[]; automatic_fallback: boolean;
  }>();

  const catalogQuery = useQuery({ queryKey: modelCenterQueryKeys.catalog, queryFn: modelCenterApi.catalog });
  const resourceProjectId = null;
  const resourcesQuery = useQuery({
    queryKey: modelCenterQueryKeys.resources(resourceProjectId, category),
    enabled: true,
    queryFn: ({ signal }) => modelCenterApi.list(resourceProjectId, category, signal),
  });
  const audioQuery = useQuery({
    queryKey: currentProjectId ? ['project', currentProjectId, 'asr', 'audio', 1, 100] : ['asr', 'audio', null],
    enabled: Boolean(currentProjectId && diagnosticTarget && diagnosticTarget.category !== 'TEXT_GENERATION'),
    queryFn: async ({ signal }) => (await import('@/features/asr-evaluation/api/asrEvaluation')).asrEvaluationApi
      .listAudios(currentProjectId!, 1, 200, signal).then((first) => first.total <= first.items.length
        ? first
        : collectPages((page) => (page === 1 ? Promise.resolve(first) : import('@/features/asr-evaluation/api/asrEvaluation')
          .then((module) => module.asrEvaluationApi.listAudios(currentProjectId!, page, 200, signal))))),
  });
  const diagnosticQuery = useQuery<ModelDiagnosticRun>({
    queryKey: diagnosticRunId ? modelCenterQueryKeys.diagnostic(diagnosticRunId) : ['model-center', 'diagnostic', null],
    enabled: diagnosticRunId !== null,
    refetchInterval: (query) => query.state.data?.status === 'QUEUED' || query.state.data?.status === 'RUNNING' ? 1500 : false,
    queryFn: ({ signal }) => modelCenterApi.getDiagnostic(diagnosticRunId!, signal),
  });
  const adapters = useMemo(() => (catalogQuery.data?.adapters || []).filter((item) => item.category === category), [catalogQuery.data, category]);
  const rows = resourcesQuery.data?.items || [];

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['model-center'] });
  const createMutation = useMutation({
    mutationFn: (body: ModelResourceWrite) => modelCenterApi.create(body),
    onSuccess: () => { message.success('模型资源已创建'); setResourceOpen(false); resourceForm.resetFields(); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '模型资源保存失败')),
  });
  const connectionTestMutation = useMutation({
    mutationFn: (body: Parameters<typeof modelCenterApi.testConnection>[0]) => modelCenterApi.testConnection(body),
    onSuccess: setConnectionTestResult,
    onError: (error) => message.error(getErrorMessage(error, '模型测试请求失败')),
  });
  const revisionMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Omit<ModelResourceWrite, 'category' | 'visibility' | 'project_id' | 'display_name' | 'grant_project_ids'> }) => modelCenterApi.addRevision(id, body),
    onSuccess: () => { message.success('连接修订已保存，旧任务快照保持不变'); setRevisionTarget(null); resourceForm.resetFields(); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '连接修订保存失败')),
  });
  const profileMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { revision_id: number; name: string; values: Record<string, unknown>; definitions: Array<Record<string, unknown>> } }) => modelCenterApi.addProfile(id, body),
    onSuccess: () => { message.success('参数方案版本已创建'); setProfileTarget(null); profileForm.resetFields(); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '参数方案创建失败')),
  });
  const defaultMutation = useMutation({
    mutationFn: (body: Parameters<typeof modelCenterApi.setDefault>[0]) => modelCenterApi.setDefault(body),
    onSuccess: () => { message.success('用途默认策略已更新'); setDefaultTarget(null); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '默认策略设置失败')),
  });
  const diagnosticMutation = useMutation({
    mutationFn: ({ resource, values }: { resource: ModelResource; values: DiagnosticFormValues }) => modelCenterApi.createDiagnostic(resource.id, {
      project_id: currentProjectId!, profile_id: values.profile_id, audio_id: values.audio_id, confirm_model_call: true,
    }),
    onSuccess: (run) => { setDiagnosticRunId(run.id); message.info('诊断已排队；正在查询后台结果'); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '模型诊断创建失败')),
  });
  const importPreviewMutation = useMutation({
    mutationFn: (items: Array<Record<string, unknown>>) => modelCenterApi.previewImport(items),
    onSuccess: (data) => setImportPreview(data as typeof importPreview),
    onError: (error) => message.error(getErrorMessage(error, '配置预检失败')),
  });
  const importMutation = useMutation({
    mutationFn: (items: Array<Record<string, unknown>>) => modelCenterApi.importResources(items),
    onSuccess: (data) => { message.success(`已导入 ${data.total} 个模型资源`); setImportOpen(false); setImportPreview(null); setImportJson('[]'); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '批量导入失败')),
  });

  useEffect(() => {
    if (!diagnosticQuery.data || diagnosticQuery.data.status === 'QUEUED' || diagnosticQuery.data.status === 'RUNNING') return;
    const result = diagnosticQuery.data.result;
    if (diagnosticQuery.data.status === 'SUCCEEDED') message.success(result.message || '模型诊断成功');
    else if (diagnosticQuery.data.status === 'FAILED') message.error(result.message || '模型诊断失败');
  }, [diagnosticQuery.data, message]);

  /** 设置新建表单为平台共享资源及当前类别的通用协议示例。 */
  const openCreate = () => {
    setRevisionTarget(null);
    setConnectionTestResult(null);
    resourceForm.resetFields();
    resourceForm.setFieldsValue({
      visibility: 'PLATFORM', project_id: isPlatformAdmin ? undefined : currentProjectId || undefined,
      provider: category === 'TEXT_GENERATION' ? 'openai-compatible' : 'custom',
      adapter_key: adapters[0]?.value, config_json: JSON_CONFIG_EXAMPLES[category],
      capabilities: [], parameter_schema_json: PARAMETER_SCHEMA_EXAMPLES[category], enabled: true,
      profile_name: '默认参数', profile_values_json: PROFILE_EXAMPLES[category], profile_definitions_json: '[]',
    });
    setResourceOpen(true);
  };

  /** 用已知安全摘要预填新修订；凭据和受保护模板需要由维护者重新录入。 */
  const openRevision = (resource: ModelResource) => {
    const revision = resource.current_revision;
    const profile = revision?.profiles[0];
    setConnectionTestResult(null);
    resourceForm.resetFields();
    resourceForm.setFieldsValue({
      provider: revision?.provider, adapter_key: revision?.adapter_key, model_name: revision?.model_name,
      endpoint: revision?.endpoint_display || '', credential: '', credential_header: 'Authorization',
      config_json: revision?.adapter_key === 'siliconflow-audio-transcriptions'
        ? JSON.stringify({ ...SILICONFLOW_CONFIG, ...revision.config,
          headers: {}, request_template: undefined }, null, 2)
        : JSON_CONFIG_EXAMPLES[resource.category],
      capabilities: revision?.capabilities || [],
      parameter_schema_json: JSON.stringify(revision?.parameter_schema || [], null, 2), enabled: true,
      profile_name: profile?.name || '默认参数',
      profile_values_json: JSON.stringify(profile?.values || {}, null, 2),
      profile_definitions_json: JSON.stringify(profile?.definitions || [], null, 2),
    });
    setRevisionTarget(resource);
  };

  /** 保存连接修订或新资源；协议配置和参数值必须是明确的 JSON 对象。 */
  const submitResource = (values: ResourceFormValues) => {
    try {
      const base = {
        provider: values.provider, adapter_key: values.adapter_key, model_name: values.model_name,
        endpoint: values.endpoint, credential: values.credential || '', credential_header: values.credential_header || null,
        config: parseJsonObject(values.config_json, '连接配置'),
        capabilities: values.capabilities || [],
        parameter_schema: parseJsonArray(values.parameter_schema_json, '参数定义'), enabled: values.enabled,
        initial_profile: {
          name: values.profile_name, values: parseJsonObject(values.profile_values_json, '参数方案'),
          definitions: parseJsonArray(values.profile_definitions_json, '参数方案定义'),
        },
      };
      if (revisionTarget) revisionMutation.mutate({ id: revisionTarget.id, body: base });
      else createMutation.mutate({
        ...base, category, visibility: 'PLATFORM',
        project_id: isPlatformAdmin ? undefined : currentProjectId || undefined,
        display_name: values.display_name, grant_project_ids: [],
      });
    } catch (error) {
      message.error(error instanceof Error ? error.message : '配置内容无效');
    }
  };

  /** 使用当前未保存表单配置发送一次低 token 聊天请求。 */
  const testUnsavedModel = async () => {
    try {
      await resourceForm.validateFields(['adapter_key', 'model_name', 'endpoint', 'config_json']);
      const values = resourceForm.getFieldsValue(true);
      if (values.adapter_key !== 'openai-compatible-chat') throw new Error('当前仅支持测试 OpenAI 兼容聊天适配器');
      const visibility: 'PLATFORM' | 'PROJECT' = 'PLATFORM' as 'PLATFORM' | 'PROJECT';
      const projectId = visibility === 'PROJECT' ? currentProjectId ?? undefined : undefined;
      if (visibility === 'PROJECT' && !projectId) throw new Error('请选择项目后再测试项目私有模型');
      setConnectionTestResult(null);
      connectionTestMutation.mutate({
        visibility, project_id: projectId, endpoint: values.endpoint, model_name: values.model_name,
        credential: values.credential || '', config: parseJsonObject(values.config_json, '连接配置'),
        confirm_model_call: true,
      });
    } catch (error) {
      if (error instanceof Error) message.error(error.message);
    }
  };

  /** 保存参数方案新版本；不覆盖任何已被任务引用的方案。 */
  const submitProfile = (values: ProfileFormValues) => {
    if (!profileTarget) return;
    try {
      profileMutation.mutate({ id: profileTarget.id, body: {
        revision_id: values.revision_id, name: values.name,
        values: parseJsonObject(values.values_json, '参数方案'),
        definitions: parseJsonArray(values.definitions_json, '参数方案定义'),
      } });
    } catch (error) {
      message.error(error instanceof Error ? error.message : '参数方案无效');
    }
  };

  /** 解析批量 JSON，并在发送前拒绝任何凭据字段。 */
  const parseImportItems = (): Array<Record<string, unknown>> => {
    const parsed: unknown = JSON.parse(importJson);
    if (!Array.isArray(parsed) || parsed.length === 0) throw new Error('导入内容必须是非空 JSON 数组');
    for (const item of parsed) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) throw new Error('每个导入条目必须是 JSON 对象');
      if (containsSensitiveImportField(item)) throw new Error('导入文件不能包含 Token、API Key 或 secret');
    }
    return parsed as Array<Record<string, unknown>>;
  };

  /** 为所选资源打开用途默认策略表单，评测默认自动备用始终关闭。 */
  const openDefault = (resource: ModelResource) => {
    setDefaultTarget(resource);
    const revision = resource.current_revision;
    const profile = revision?.profiles[0];
    defaultForm.setFieldsValue({
      revision_id: revision?.id, profile_id: profile?.id,
      purpose: resource.category === 'TEXT_GENERATION' ? 'TEXT_INFERENCE' : resource.category === 'ASR' ? 'ASR_EVALUATION' : 'DIARIZATION',
      fallback_resource_ids: [], automatic_fallback: false,
    });
  };

  /** 表格按类别展示能力、当前修订和明确触发的诊断状态。 */
  const columns = [
    { title: '模型资源', key: 'name', render: (_: unknown, row: ModelResource) => <Space direction="vertical" size={0}>
      <Typography.Text strong>{row.display_name}</Typography.Text>
      <Typography.Text type="secondary">{row.visibility === 'PLATFORM' ? '平台共享' : `项目私有 · #${row.project_id}`}</Typography.Text>
      <Space wrap size={[2, 2]}>
        {row.defaults.map((item) => <Tag key={`${item.purpose}:${item.project_id || 0}`} color="blue">默认 · {item.purpose}</Tag>)}
      </Space>
    </Space> },
    { title: '能力', key: 'capabilities', render: (_: unknown, row: ModelResource) => <Space wrap>
      {(row.current_revision?.capabilities || []).length
        ? row.current_revision?.capabilities.map((item) => <Tag key={item}>{item}</Tag>)
        : <Tag color="default">未声明能力</Tag>}
    </Space> },
    { title: '供应商 / 调用适配器', key: 'adapter', render: (_: unknown, row: ModelResource) => row.current_revision
      ? <Space direction="vertical" size={0}><span>{row.current_revision.provider}</span><Typography.Text type="secondary">{row.current_revision.adapter_key}</Typography.Text></Space>
      : '—' },
    { title: '模型 / 修订', key: 'version', render: (_: unknown, row: ModelResource) => row.current_revision
      ? `${row.current_revision.model_name} · v${row.current_revision.version}` : '—' },
    { title: '参数方案', key: 'profiles', render: (_: unknown, row: ModelResource) => <Space wrap>
      {(row.current_revision?.profiles || []).map((item: ModelParameterProfile) => <Tag key={item.id}>{item.name} v{item.version}</Tag>)}
      {!(row.current_revision?.profiles || []).length && <Tag>未配置</Tag>}
    </Space> },
    { title: '凭据 / 诊断', key: 'diagnostic', render: (_: unknown, row: ModelResource) => <Space direction="vertical" size={0}>
      <Typography.Text>{row.current_revision?.has_credential ? '凭据已配置' : '无鉴权凭据'}</Typography.Text>
      <Typography.Text type="secondary">{row.diagnostic ? `${row.diagnostic.status} · ${row.diagnostic.message || '—'}` : '尚未诊断'}</Typography.Text>
    </Space> },
    { title: '操作', key: 'actions', render: (_: unknown, row: ModelResource) => <Space wrap size={[4, 4]}>
      <Button size="small" icon={<ExperimentOutlined />} onClick={() => {
        setDiagnosticRunId(null);
        setDiagnosticTarget(row);
        diagnosticForm.setFieldsValue({ profile_id: row.current_revision?.profiles[0]?.id, confirm_model_call: false });
      }}>诊断</Button>
      <Button size="small" icon={<SettingOutlined />} onClick={() => openDefault(row)}>用途默认</Button>
      <Button size="small" onClick={() => { setProfileTarget(row); profileForm.setFieldsValue({
        revision_id: row.current_revision?.id, name: '调优参数', values_json: PROFILE_EXAMPLES[row.category], definitions_json: JSON.stringify(row.current_revision?.parameter_schema || [], null, 2),
      }); }}>参数版本</Button>
      {isPlatformAdmin && <Button size="small" onClick={() => openRevision(row)}>连接修订</Button>}
      {isPlatformAdmin && <Switch checked={row.status === 'ACTIVE'} checkedChildren="启用" unCheckedChildren="停用" onChange={async (enabled) => {
        try { await modelCenterApi.setEnabled(row.id, enabled); await resourcesQuery.refetch(); }
        catch { message.error('模型状态更新失败'); }
      }} />}
    </Space> },
  ];

  if (catalogQuery.isPending || (resourcesQuery.isPending && (isPlatformAdmin || Boolean(currentProjectId)))) return <LoadingState />;
  if (catalogQuery.isError) return <PageContainer><ErrorState error={catalogQuery.error} onRetry={catalogQuery.refetch} /></PageContainer>;
  if (resourcesQuery.isError) return <PageContainer><ErrorState error={resourcesQuery.error} onRetry={resourcesQuery.refetch} /></PageContainer>;

  return <PageContainer>
    <PageHeader title="统一模型中心" subtitle="全平台统一维护模型连接、参数方案和默认策略；启用后各项目可用" />
    {!isPlatformAdmin && !currentProjectId && <Alert type="info" showIcon message="模型由平台管理员统一维护，启用后即可使用。" />}
    <Card bordered={false}>
      <Tabs activeKey={category} onChange={(key) => setCategory(key as ModelCategory)} items={[
        { key: 'TEXT_GENERATION', label: '文本推理' }, { key: 'ASR', label: 'ASR 转写' }, { key: 'DIARIZATION', label: '说话人分段' },
      ]} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Typography.Text type="secondary">类别、供应商、适配器、能力和任务用途分别记录。仅展示已注册适配器。</Typography.Text>
        <Space>
          {isPlatformAdmin && <Button onClick={() => { setImportPreview(null); setImportOpen(true); }}>批量导入预检</Button>}
          <Button type="primary" icon={<PlusOutlined />} disabled={!isPlatformAdmin} onClick={openCreate}>新增模型资源</Button>
        </Space>
      </div>
      {category !== 'TEXT_GENERATION' && <Alert style={{ marginBottom: 16 }} type="info" showIcon
        message="参数控件按连接声明生成。ASR 新配置会提供语言、热词、VAD、标点和时间戳示例；仅保留当前供应商协议确认支持的字段。通用适配器按模板透传，不代表厂商真实联调已验证。无鉴权服务仍需通过项目出站授权。" />}
      <Table<ModelResource> rowKey="id" dataSource={rows} columns={columns} pagination={{ pageSize: 10, showSizeChanger: true }} locale={{ emptyText: `${CATEGORY_LABELS[category]}暂无资源` }} />
    </Card>

    <Modal title={revisionTarget ? `为「${revisionTarget.display_name}」新增连接修订` : `新增${CATEGORY_LABELS[category]}资源`}
      open={resourceOpen || Boolean(revisionTarget)} onCancel={() => { setResourceOpen(false); setRevisionTarget(null); resourceForm.resetFields(); }}
      width={820} footer={null} destroyOnHidden>
      <Form<ResourceFormValues> form={resourceForm} layout="vertical" onFinish={submitResource}
        onValuesChange={() => setConnectionTestResult(null)}>
        {!revisionTarget && <>
          <Form.Item name="display_name" label="模型名称" rules={[{ required: true }]}><Input maxLength={160} /></Form.Item>
        </>}
        <Space style={{ display: 'flex' }} align="start">
          <Form.Item name="provider" label="供应商" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Select options={(catalogQuery.data?.providers || []).concat([{ value: 'custom', label: '其他供应商' }])
              .filter((item, index, all) => all.findIndex((entry) => entry.value === item.value) === index)} />
          </Form.Item>
          <Form.Item name="adapter_key" label="调用适配器" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Select options={adapters.map((item) => ({ value: item.value, label: item.label }))}
              onChange={(adapter) => {
                if (adapter === 'siliconflow-audio-transcriptions') resourceForm.setFieldsValue({
                  provider: 'siliconflow', endpoint: 'https://api.siliconflow.cn/v1/audio/transcriptions',
                  credential_header: 'Authorization', config_json: JSON.stringify(SILICONFLOW_CONFIG, null, 2),
                  capabilities: ['transcription'], parameter_schema_json: '[]',
                  profile_values_json: '{}', profile_definitions_json: '[]',
                });
                else resourceForm.setFieldsValue({ config_json: JSON_CONFIG_EXAMPLES[category], capabilities: [] });
              }} />
          </Form.Item>
          <Form.Item name="model_name" label="厂商模型 ID" rules={[{ required: true }]} style={{ flex: 1 }}><Input /></Form.Item>
        </Space>
        <Form.Item name="endpoint" label="服务地址" rules={[{ required: true }]}><Input placeholder="https://..." /></Form.Item>
        <Form.Item name="credential" label="Token / API Key（只写入）" style={{ width: '100%' }}>
          <Input.Password autoComplete="new-password" placeholder="留空表示不设置凭据" style={{ width: '100%' }} />
        </Form.Item>
        {category !== 'TEXT_GENERATION' && <Form.Item name="credential_header" label="凭据请求头" style={{ width: '100%' }}>
          <Input placeholder="Authorization" style={{ width: '100%' }} />
        </Form.Item>}
        <Form.Item name="config_json" label="协议连接参数 JSON" rules={[{ required: true }]} extra={category === 'TEXT_GENERATION' ? '仅配置当前适配器支持的接口参数。' : '通用 JSON 适配器需配置请求模板；硅基流动适配器读取音频 URL 后上传文件，响应字段使用 JSON Pointer 映射。'}>
          <Input.TextArea rows={8} spellCheck={false} />
        </Form.Item>
        <Space style={{ display: 'flex' }} align="start">
          <Form.Item name="capabilities" label="适配器可处理的能力声明" style={{ flex: 1 }}>
            <Checkbox.Group options={(adapters.find((item) => item.value === resourceForm.getFieldValue('adapter_key'))?.capabilities || [])
              .map((item) => ({ value: item, label: CAPABILITY_LABELS[item] || item }))} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Space>
        {category !== 'TEXT_GENERATION' && <Form.Item name="parameter_schema_json" label="连接参数定义（JSON Pointer）" rules={[{ required: true }]} extra="只填写经当前供应商接口文档确认可用的字段；示例定义可删除或编辑。">
          <Input.TextArea rows={7} spellCheck={false} />
        </Form.Item>}
        <Typography.Title level={5}>初始参数方案</Typography.Title>
        <Form.Item name="profile_name" label="方案名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item noStyle shouldUpdate={(previous, next) => previous.parameter_schema_json !== next.parameter_schema_json || previous.profile_definitions_json !== next.profile_definitions_json}>
          {({ getFieldValue }) => {
            const readDefinitions = (raw: string | undefined) => {
              try { return parseJsonArray(raw || '[]', '参数定义'); } catch { return []; }
            };
            const profileDefinitions = readDefinitions(getFieldValue('profile_definitions_json'));
            const definitions = profileDefinitions.length ? profileDefinitions : readDefinitions(getFieldValue('parameter_schema_json'));
            return <Form.Item name="profile_values_json" label="参数方案（按定义生成控件；下方 JSON 可直接编辑）" rules={[{ required: true }]}>
              <ParameterValuesEditor definitions={definitions} />
            </Form.Item>;
          }}
        </Form.Item>
        {category !== 'TEXT_GENERATION' && <Form.Item name="profile_definitions_json" label="方案参数定义 JSON 数组"><Input.TextArea rows={3} spellCheck={false} /></Form.Item>}
        {!revisionTarget && category === 'TEXT_GENERATION' && <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message="模型测试会真实发送一次请求，可能产生费用；测试不会保存当前配置。" />}
        {connectionTestResult && <Alert style={{ marginBottom: 12 }} showIcon
          type={connectionTestResult.success ? 'success' : 'error'}
          message={`${connectionTestResult.message} · 耗时 ${connectionTestResult.elapsed_ms} ms`} />}
        <Space style={{ justifyContent: 'flex-end', width: '100%' }}>
          <Button onClick={() => { setResourceOpen(false); setRevisionTarget(null); }}>取消</Button>
          {!revisionTarget && category === 'TEXT_GENERATION' && <Button icon={<ExperimentOutlined />}
            loading={connectionTestMutation.isPending} onClick={testUnsavedModel}>测试模型</Button>}
          <Button type="primary" htmlType="submit" loading={createMutation.isPending || revisionMutation.isPending}>保存配置</Button>
        </Space>
      </Form>
    </Modal>

    <Modal title={`为「${profileTarget?.display_name || ''}」新增参数方案版本`} open={Boolean(profileTarget)} onCancel={() => setProfileTarget(null)} footer={null} width={700} destroyOnHidden>
      <Alert type="info" showIcon style={{ marginBottom: 16 }} message="连接地址和凭据不会随参数方案复制；不同任务槽位可分别选择各自的方案版本。" />
      <Form<ProfileFormValues> form={profileForm} layout="vertical" onFinish={submitProfile}>
        <Form.Item name="revision_id" label="连接修订" rules={[{ required: true }]}>
          <Select options={(profileTarget?.revisions || []).map((item) => ({ value: item.id, label: `v${item.version} · ${item.model_name}` }))} />
        </Form.Item>
        <Form.Item name="name" label="方案名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item noStyle shouldUpdate={(previous, next) => previous.definitions_json !== next.definitions_json || previous.revision_id !== next.revision_id}>
          {({ getFieldValue }) => {
            const profileRevision = profileTarget?.revisions.find((item) => item.id === getFieldValue('revision_id'));
            let definitions: Array<Record<string, unknown>> = [];
            try { definitions = parseJsonArray(getFieldValue('definitions_json') || '[]', '参数定义'); } catch { /* allow editing invalid JSON below */ }
            if (!definitions.length) definitions = profileRevision?.parameter_schema || [];
            return <Form.Item name="values_json" label="参数方案（按定义生成控件；下方 JSON 可直接编辑）" rules={[{ required: true }]}>
              <ParameterValuesEditor definitions={definitions} />
            </Form.Item>;
          }}
        </Form.Item>
        <Form.Item name="definitions_json" label="可验证参数定义 JSON 数组"><Input.TextArea rows={5} spellCheck={false} /></Form.Item>
        <Button type="primary" htmlType="submit" loading={profileMutation.isPending}>创建参数版本</Button>
      </Form>
    </Modal>

    <Modal title="设置用途默认策略" open={Boolean(defaultTarget)} onCancel={() => setDefaultTarget(null)} footer={null} destroyOnHidden>
      <Form form={defaultForm} layout="vertical" onFinish={(values) => {
        if (!defaultTarget) return;
        defaultMutation.mutate({
          category: defaultTarget.category, purpose: values.purpose,
          project_id: defaultTarget.visibility === 'PROJECT' ? currentProjectId || undefined : undefined,
          resource_id: defaultTarget.id, revision_id: values.revision_id, profile_id: values.profile_id,
          fallback_resource_ids: values.fallback_resource_ids || [],
          automatic_fallback: defaultTarget.category === 'ASR' ? false : values.automatic_fallback,
        });
      }}>
        <Form.Item name="purpose" label="用途" rules={[{ required: true }]}>
          <Select options={defaultTarget?.category === 'TEXT_GENERATION'
            ? [{ value: 'TEXT_INFERENCE', label: '文本推理' }]
            : defaultTarget?.category === 'ASR' ? [{ value: 'ASR_EVALUATION', label: 'ASR 评测' }]
              : [{ value: 'DIARIZATION', label: '说话人分段' }]} />
        </Form.Item>
        <Form.Item name="revision_id" label="连接修订" rules={[{ required: true }]}>
          <Select options={(defaultTarget?.revisions || []).map((item) => ({ value: item.id, label: `v${item.version} · ${item.model_name}` }))} />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(previous, current) => previous.revision_id !== current.revision_id}>
          {({ getFieldValue }) => {
            const revision = defaultTarget?.revisions.find((item) => item.id === getFieldValue('revision_id'));
            return <Form.Item name="profile_id" label="参数方案版本">
              <Select allowClear options={(revision?.profiles || []).map((item) => ({ value: item.id, label: `${item.name} v${item.version}` }))} />
            </Form.Item>;
          }}
        </Form.Item>
        <Form.Item name="fallback_resource_ids" label="同类别备用模型">
          <Select mode="multiple" allowClear options={rows.filter((item) => item.visibility === 'PLATFORM')
            .map((item) => ({ value: item.id, label: item.display_name }))
            .filter((item) => item.value !== defaultTarget?.id)} />
        </Form.Item>
        <Form.Item name="automatic_fallback" label="自动切换备用模型" valuePropName="checked">
          <Switch disabled={defaultTarget?.category === 'ASR'} />
        </Form.Item>
        <Alert type="info" showIcon message="ASR 评测默认禁止自动切换模型，避免污染对比结果；备用模型只允许同类别资源。" />
        <Button style={{ marginTop: 16 }} type="primary" htmlType="submit" loading={defaultMutation.isPending}>保存默认策略</Button>
      </Form>
    </Modal>

    <Modal title={`诊断「${diagnosticTarget?.display_name || ''}」`} open={Boolean(diagnosticTarget)} onCancel={() => setDiagnosticTarget(null)} footer={null} destroyOnHidden>
      <Alert type="warning" showIcon style={{ marginBottom: 16 }} message="诊断会真实调用所选模型，可能产生费用。页面打开和保存配置不会调用模型。" />
      <Form form={diagnosticForm} layout="vertical" onFinish={(values) => {
        if (!values.confirm_model_call) { message.warning('请先确认模型调用'); return; }
        if (diagnosticTarget) diagnosticMutation.mutate({ resource: diagnosticTarget, values });
      }}>
        <Form.Item name="profile_id" label="参数方案版本">
          <Select allowClear options={(diagnosticTarget?.current_revision?.profiles || []).map((item) => ({ value: item.id, label: `${item.name} v${item.version}` }))} />
        </Form.Item>
        {diagnosticTarget && diagnosticTarget.category !== 'TEXT_GENERATION' && <Form.Item name="audio_id" label="诊断音频" rules={[{ required: true }]}>
          <Select loading={audioQuery.isPending} options={(audioQuery.data?.items || []).map((item: { id: number; name: string }) => ({ value: item.id, label: item.name }))} />
        </Form.Item>}
        <Form.Item name="confirm_model_call" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error('需要明确确认')) }]}>
          <Checkbox>我确认发起一次真实模型调用，可能产生费用</Checkbox>
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={diagnosticMutation.isPending}>开始后台诊断</Button>
      </Form>
      {diagnosticRunId && diagnosticQuery.data && <Alert style={{ marginTop: 16 }} type={diagnosticQuery.data.status === 'FAILED' ? 'error' : 'info'}
        message={`诊断 ${diagnosticQuery.data.status}`} description={diagnosticQuery.data.result.message} />}
    </Modal>

    <Modal title="非敏感模型配置批量导入" open={importOpen} onCancel={() => { setImportOpen(false); setImportPreview(null); }} footer={null} width={760} destroyOnHidden>
      <Alert type="info" showIcon style={{ marginBottom: 12 }} message="仅预检与保存配置，不会调用模型。凭据字段在浏览器提交前即被拒绝；导入后请在模型中心单独配置凭据。" />
      <Input.TextArea rows={14} value={importJson} onChange={(event) => { setImportJson(event.target.value); setImportPreview(null); }} spellCheck={false} />
      <Space style={{ marginTop: 12 }}>
        <Button loading={importPreviewMutation.isPending} onClick={() => {
          try { importPreviewMutation.mutate(parseImportItems()); }
          catch (error) { message.error(error instanceof Error ? error.message : '导入 JSON 无效'); }
        }}>预检配置</Button>
        <Button type="primary" disabled={!importPreview?.can_apply} loading={importMutation.isPending} onClick={() => {
          try { importMutation.mutate(parseImportItems()); }
          catch (error) { message.error(error instanceof Error ? error.message : '导入 JSON 无效'); }
        }}>导入全部配置</Button>
      </Space>
      {importPreview && <div style={{ marginTop: 16 }}>
        <Alert type={importPreview.can_apply ? 'success' : 'warning'} showIcon
          message={`预检通过 ${importPreview.valid_count} 项，失败 ${importPreview.invalid_count} 项`} />
        {importPreview.items.filter((item) => !item.valid).map((item) => <Alert key={item.index} style={{ marginTop: 8 }} type="error"
          message={`第 ${item.index + 1} 项${item.display_name ? ` · ${item.display_name}` : ''}`} description={item.errors.join('；')} />)}
      </div>}
    </Modal>
  </PageContainer>;
}
