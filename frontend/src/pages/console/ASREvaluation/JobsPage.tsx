// 评测任务与夜间计划：新建后立即返回批次 ID，Web 页面不等待长音频识别。
import { Alert, App, Button, Card, Collapse, DatePicker, Empty, Form, Input, Modal, Pagination, Radio, Select, Space, Steps, Table, Tag, TimePicker, Typography } from 'antd';
import { PlusOutlined, StopOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import type { AsrAudio, AsrJob, AsrJobAudioGroup, AsrPage, AsrSchedule } from '@/features/asr-evaluation/contracts';
import { modelCenterApi, modelCenterQueryKeys, type ModelAvailableResource } from '@/features/model-configuration/api/modelCenter';
import { AsrFrame } from './AsrFrame';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { enteredTerminalJobState, shouldPollBatchSummary } from '@/features/asr-evaluation/batchRefresh.mjs';

interface JobFormValues {
  audio_ids: number[];
  test_model_slot: string;
  reference_a_model_slot: string;
  reference_b_model_slot: string;
  diarization_model_slot?: string;
  mode: 'NOW' | 'DAILY' | 'ONCE';
  schedule_name?: string;
  timezone: string;
  daily_time?: Dayjs;
  scheduled_at?: Dayjs;
}

interface AudioPickerProps {
  value?: number[];
  onChange?: (audioIds: number[]) => void;
  items: AsrAudio[];
  total: number;
  page: number;
  keyword: string;
  loading: boolean;
  onPageChange: (page: number) => void;
  onKeywordChange: (keyword: string) => void;
}

/** 带服务端分页的跨页多选；名称筛选保留选择，切换项目时由页面主动清空。 */
function AudioPicker({
  value = [], onChange, items, total, page, keyword, loading, onPageChange, onKeywordChange,
}: AudioPickerProps) {
  return <Space direction="vertical" style={{ display: 'flex' }} size="small">
    <Input.Search aria-label="按名称筛选可选音频" allowClear placeholder="按音频名称筛选" value={keyword}
      onChange={(event) => onKeywordChange(event.target.value)} />
    <Table<AsrAudio>
      rowKey="id" size="small" loading={loading} dataSource={items} pagination={false}
      rowSelection={{
        selectedRowKeys: value, preserveSelectedRowKeys: true,
        onChange: (keys) => onChange?.(keys.map(Number)),
      }}
      columns={[{ title: '音频名称', dataIndex: 'name', key: 'name' }, {
        title: '版本', dataIndex: 'content_version', key: 'version', width: 90, render: (version: number) => `v${version}`,
      }]}
      locale={{ emptyText: '当前项目没有匹配的音频' }}
    />
    <Space style={{ width: '100%', justifyContent: 'space-between' }}>
      <Typography.Text type="secondary">已选 {value.length} 条，共 {total} 条匹配音频</Typography.Text>
      <Pagination size="small" current={page} pageSize={20} total={total} showSizeChanger={false} onChange={onPageChange} />
    </Space>
  </Space>;
}

/** 将用户选择的墙上时间按 IANA 时区转换为 ISO 时间，避免误用浏览器本地时区。 */
function toZonedIso(value: Dayjs, timezone: string): string {
  const wall = value.format('YYYY-MM-DDTHH:mm:ss');
  const [date, clock] = wall.split('T');
  const [year, month, day] = date.split('-').map(Number);
  const [hour, minute, second] = clock.split(':').map(Number);
  const wallAsUtc = Date.UTC(year, month - 1, day, hour, minute, second);
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  let instant = new Date(wallAsUtc);
  for (let index = 0; index < 3; index += 1) {
    const parts = Object.fromEntries(formatter.formatToParts(instant).map((part) => [part.type, part.value]));
    const observedAsUtc = Date.UTC(
      Number(parts.year), Number(parts.month) - 1, Number(parts.day),
      Number(parts.hour), Number(parts.minute), Number(parts.second),
    );
    instant = new Date(instant.getTime() + wallAsUtc - observedAsUtc);
  }
  const roundTrip = Object.fromEntries(formatter.formatToParts(instant).map((part) => [part.type, part.value]));
  if (!Number.isFinite(instant.getTime())
    || Number(roundTrip.year) !== year || Number(roundTrip.month) !== month || Number(roundTrip.day) !== day
    || Number(roundTrip.hour) !== hour || Number(roundTrip.minute) !== minute || Number(roundTrip.second) !== second) {
    throw new Error('所选时区没有这个本地时间');
  }
  return instant.toISOString();
}

/** 按批次状态显示确定事实，不把排队或轮询包装成百分比。 */
function jobStatusTag(value: string) {
  const labels: Record<string, [string, string]> = {
    QUEUED: ['排队中', 'default'], RUNNING: ['识别中', 'processing'],
    COMPLETED: ['已完成', 'success'], PARTIAL_FAILED: ['部分失败', 'warning'],
    FAILED: ['失败', 'error'], CANCELLED: ['已取消', 'default'],
    RECONCILIATION_REQUIRED: ['提交状态待核实', 'warning'],
    PENDING: ['排队中', 'default'], SUBMITTING: ['提交中', 'processing'], REMOTE_RUNNING: ['识别中', 'processing'],
    SUCCEEDED: ['已完成', 'success'],
  };
  const [label, color] = labels[value] ?? [value, 'default'];
  return <Tag color={color}>{label}</Tag>;
}

function reviewStatusLabel(value: string): string {
  return ({ QUEUED: '排队中', RUNNING: '评审中', SUCCEEDED: '已完成', FAILED: '失败',
    RECONCILIATION_REQUIRED: '状态待核实', CANCELLED: '已取消', COMPLETE: '已覆盖', PARTIAL: '部分覆盖',
    UNAVAILABLE: '不可用' } as Record<string, string>)[value] ?? value;
}

function jobRequestKey(jobId: number, action: 'retry' | 'rerun'): string {
  const storageKey = `asr-job-${action}:${jobId}`;
  try {
    const previous = sessionStorage.getItem(storageKey);
    if (previous) return previous;
    const value = globalThis.crypto?.randomUUID?.() ?? `asr-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(storageKey, value);
    return value;
  } catch {
    return globalThis.crypto?.randomUUID?.() ?? `asr-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

function clearJobRequestKey(jobId: number, action: 'retry' | 'rerun') {
  try { sessionStorage.removeItem(`asr-job-${action}:${jobId}`); } catch { /* 当前标签页不支持会话存储。 */ }
}

/** 使用计划自身时区显示触发时刻，而不借用浏览器当前时区。 */
function formatInTimezone(value: string | null, timezone: string): string {
  if (!value) return '无';
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

/** 列表、计划创建和执行器在线状态。 */
export function JobsPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { currentProjectId } = useConsoleScope();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<JobFormValues>();
  const [open, setOpen] = useState(false);
  const [jobsPage, setJobsPage] = useState(1);
  const [audioPickerPage, setAudioPickerPage] = useState(1);
  const [audioKeyword, setAudioKeyword] = useState('');
  const [wizardStep, setWizardStep] = useState(0);
  const [autoOpenedAudioId, setAutoOpenedAudioId] = useState<string | null>(null);
  useEffect(() => {
    setJobsPage(1);
    setAudioPickerPage(1);
    setAudioKeyword('');
    form.setFieldValue('audio_ids', []);
    setWizardStep(0);
  }, [currentProjectId, form]);
  useEffect(() => {
    const rawAudioId = searchParams.get('audio_id');
    const audioId = rawAudioId ? Number(rawAudioId) : NaN;
    if (!open && currentProjectId && rawAudioId !== autoOpenedAudioId && Number.isSafeInteger(audioId) && audioId > 0) {
      form.resetFields();
      form.setFieldsValue({ mode: 'NOW', audio_ids: [audioId] });
      setWizardStep(0);
      setAutoOpenedAudioId(rawAudioId);
      setOpen(true);
    }
  }, [autoOpenedAudioId, currentProjectId, form, open, searchParams]);
  const jobsKey = currentProjectId ? asrQueryKeys.project(currentProjectId, 'jobs', jobsPage) : ['asr', 'jobs', null, jobsPage];
  const schedulesKey = currentProjectId ? asrQueryKeys.project(currentProjectId, 'schedules') : ['asr', 'schedules', null];
  const jobsQuery = useQuery({
    queryKey: jobsKey, enabled: Boolean(currentProjectId), refetchInterval: 5000,
    queryFn: async ({ signal }) => (await asrEvaluationApi.listJobs(currentProjectId!, jobsPage, signal)),
  });
  const runtimeQuery = useQuery({
    queryKey: ['asr', 'runtime-status'], refetchInterval: 15000,
    queryFn: async ({ signal }) => (await asrEvaluationApi.runtimeStatus(signal)),
  });
  const schedulesQuery = useQuery({
    queryKey: schedulesKey, enabled: Boolean(currentProjectId),
    queryFn: async ({ signal }) => (await asrEvaluationApi.listSchedules(currentProjectId!, signal)).items,
  });
  const audioQuery = useQuery({
    queryKey: currentProjectId
      ? asrQueryKeys.project(currentProjectId, 'audio-picker', audioPickerPage, audioKeyword)
      : ['asr', 'audio-picker', null, audioPickerPage, audioKeyword],
    enabled: Boolean(currentProjectId && open),
    queryFn: async ({ signal }) => asrEvaluationApi.listAudios(
      currentProjectId!, audioPickerPage, 20, signal, audioKeyword,
    ),
  });
  const asrModelsQuery = useQuery({
    queryKey: currentProjectId ? modelCenterQueryKeys.available(currentProjectId, 'ASR') : ['model-center', 'available', null, 'ASR'],
    enabled: Boolean(currentProjectId),
    queryFn: async ({ signal }) => (await modelCenterApi.available(currentProjectId!, 'ASR', signal)).items,
  });
  const diarizationModelsQuery = useQuery({
    queryKey: currentProjectId ? modelCenterQueryKeys.available(currentProjectId, 'DIARIZATION') : ['model-center', 'available', null, 'DIARIZATION'],
    enabled: Boolean(currentProjectId),
    queryFn: async ({ signal }) => (await modelCenterApi.available(currentProjectId!, 'DIARIZATION', signal)).items,
  });
  const createJob = useMutation({
    mutationFn: (body: { project_id: number; audio_ids: number[]; model_slots: Array<{ slot: 'TEST' | 'REFERENCE_A' | 'REFERENCE_B' | 'DIARIZATION'; resource_id: number; revision_id: number; profile_id: number }> }) =>
      asrEvaluationApi.createJob(body),
    onSuccess: (data) => {
      message.success('评测任务已加入后台队列');
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: jobsKey });
      navigate('/console/asr/jobs/' + data.id);
    },
    onError: (error) => message.error(getErrorMessage(error, '创建评测任务失败')),
  });
  const createSchedule = useMutation({
    mutationFn: (body: Record<string, unknown>) => asrEvaluationApi.createSchedule(body),
    onSuccess: () => {
      message.success('夜间计划已保存；请保持 ASR Worker 常驻运行');
      closeCreate();
      void queryClient.invalidateQueries({ queryKey: jobsKey });
      void queryClient.invalidateQueries({ queryKey: schedulesKey });
    },
    onError: (error) => message.error(getErrorMessage(error, '创建夜间计划失败')),
  });
  const updateSchedule = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => asrEvaluationApi.updateSchedule(id, enabled),
    onSuccess: (data) => {
      message.info(data.enabled ? '夜间计划已恢复' : '夜间计划已暂停');
      void queryClient.invalidateQueries({ queryKey: schedulesKey });
    },
    onError: (error) => message.error(getErrorMessage(error, '更新夜间计划失败')),
  });
  const cancelJob = useMutation({
    mutationFn: (jobId: number) => asrEvaluationApi.cancelJob(jobId),
    onSuccess: () => {
      message.info('已停止本地新提交或轮询跟踪');
      void queryClient.invalidateQueries({ queryKey: jobsKey });
    },
    onError: (error) => message.error(getErrorMessage(error, '取消任务失败')),
  });

  const closeCreate = () => {
    setOpen(false);
    setSearchParams((previous) => { const next = new URLSearchParams(previous); next.delete('audio_id'); return next; }, { replace: true });
  };
  const startCreate = () => {
    form.resetFields();
    form.setFieldValue('mode', 'NOW');
    setWizardStep(0);
    setOpen(true);
  };
  const nextStep = async () => {
    if (wizardStep === 0 && (audioQuery.isPending || audioQuery.isError)) {
      message.warning(audioQuery.isError ? '音频列表尚未读取成功，请先重试' : '正在读取音频列表，请稍候');
      return;
    }
    const fields: Array<keyof JobFormValues> = wizardStep === 0
      ? ['audio_ids']
      : ['test_model_slot', 'reference_a_model_slot', 'reference_b_model_slot'];
    try {
      await form.validateFields(fields);
      setWizardStep((current) => Math.min(2, current + 1));
    } catch { /* Form 自身显示字段校验信息。 */ }
  };

  /** 根据所选运行模式创建即时批次、每日计划或一次性指定时间计划。 */
  const submitJob = (values: JobFormValues) => {
    if (!currentProjectId) return;
    const parseSelection = (value: string | undefined, slot: 'TEST' | 'REFERENCE_A' | 'REFERENCE_B' | 'DIARIZATION') => {
      if (!value) return null;
      const [resourceId, revisionId, profileId] = value.split(':').map(Number);
      if (![resourceId, revisionId, profileId].every((item) => Number.isSafeInteger(item) && item > 0)) {
        throw new Error('所选模型或参数版本无效');
      }
      return { slot, resource_id: resourceId, revision_id: revisionId, profile_id: profileId };
    };
    let modelSlots: Array<{ slot: 'TEST' | 'REFERENCE_A' | 'REFERENCE_B' | 'DIARIZATION'; resource_id: number; revision_id: number; profile_id: number }>;
    try {
      modelSlots = [
        parseSelection(values.test_model_slot, 'TEST'),
        parseSelection(values.reference_a_model_slot, 'REFERENCE_A'),
        parseSelection(values.reference_b_model_slot, 'REFERENCE_B'),
        parseSelection(values.diarization_model_slot, 'DIARIZATION'),
      ].filter((item): item is NonNullable<typeof item> => item !== null);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '模型槽位无效');
      return;
    }
    const transcriptionSlots = modelSlots.filter((item) => item.slot !== 'DIARIZATION');
    if (readyAsrResources < 3) {
      message.error(`当前只有 ${readyAsrResources} 个已授权 ASR 模型资源，三方评测需要 3 个；请联系平台管理员配置或授权。`);
      return;
    }
    if (transcriptionSlots.length !== 3 || new Set(transcriptionSlots.map((item) => item.resource_id)).size !== 3) {
      message.error('待测模型、参考模型 A 和参考模型 B 必须选择三个不同的模型资源。');
      return;
    }
    if (values.mode === 'NOW') {
      createJob.mutate({
        project_id: currentProjectId, audio_ids: values.audio_ids,
        model_slots: modelSlots,
      });
      return;
    }
    const common = {
      project_id: currentProjectId, name: values.schedule_name || 'ASR 夜间评测',
      audio_ids: values.audio_ids, model_slots: modelSlots, timezone: values.timezone || 'Asia/Shanghai',
    };
    if (values.mode === 'DAILY') {
      createSchedule.mutate({
        ...common, schedule_type: 'DAILY', local_time: values.daily_time?.format('HH:mm') || '01:00',
      });
    } else if (values.scheduled_at) {
      try {
        createSchedule.mutate({
          ...common, schedule_type: 'ONCE', local_time: values.scheduled_at.format('HH:mm'),
          scheduled_at: toZonedIso(values.scheduled_at, values.timezone || 'Asia/Shanghai'),
        });
      } catch (error) {
        message.error(error instanceof Error ? error.message : '请检查计划时区和执行时间');
      }
    } else {
      message.error('请选择一次性任务的执行时间');
    }
  };

  /** 任务列表列出运行状态、音频范围和取消入口。 */
  const columns = [
    { title: '任务编号', dataIndex: 'id', key: 'id', width: 110, render: (id: number) => <Link to={'/console/asr/jobs/' + id}>ASR-{id}</Link> },
    { title: '状态', dataIndex: 'status', key: 'status', render: jobStatusTag },
    { title: '模型', key: 'models', render: (_: unknown, row: AsrJob) => {
      const connections = row.config_snapshot.connections;
      const names = Array.isArray(connections) ? connections.map((item) => {
        if (item && typeof item === 'object' && !Array.isArray(item)) {
          const connection = item as Record<string, unknown>;
          return String(connection.name ?? connection.model_id ?? '模型未报告');
        }
        return '';
      }).filter(Boolean) : [];
      return names.length ? <Typography.Text ellipsis style={{ maxWidth: 280 }}>{names.join(' · ')}</Typography.Text> : '模型快照未报告';
    } },
    {
      title: '音频数', key: 'audio_count',
      render: (_: unknown, row: AsrJob) => {
        const value = row.config_snapshot.audio_ids;
        return Array.isArray(value) ? value.length + ' 条' : '—';
      },
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm') },
    {
      title: '操作', key: 'action',
      render: (_: unknown, row: AsrJob) => <Space>
        <Button size="small" onClick={() => navigate('/console/asr/jobs/' + row.id)}>查看</Button>
        {['QUEUED', 'RUNNING'].includes(row.status) && <Button
          danger size="small" icon={<StopOutlined />} loading={cancelJob.isPending && cancelJob.variables === row.id}
          onClick={() => cancelJob.mutate(row.id)}
        >停止</Button>}
      </Space>,
    },
  ];

  if (!currentProjectId) return <AsrFrame title="评测任务"><Empty description="先选择项目" /></AsrFrame>;
  if (jobsQuery.isPending) return <AsrFrame title="评测任务"><LoadingState /></AsrFrame>;
  if (jobsQuery.isError) return <AsrFrame title="评测任务"><ErrorState error={jobsQuery.error} onRetry={jobsQuery.refetch} /></AsrFrame>;

  const audios = audioQuery.data?.items ?? [];
  const asrModels = asrModelsQuery.data ?? [];
  const diarizationModels = diarizationModelsQuery.data ?? [];
  const modelSlotOptions = (items: ModelAvailableResource[]) => items.flatMap((item) =>
    item.profiles.map((profile) => ({
      value: `${item.id}:${item.revision.id}:${profile.id}`,
      label: `${item.display_name} · ${item.revision.model_name} v${item.revision.version} · ${profile.name} v${profile.version}`,
    })),
  );
  const readyAsrResources = new Set(asrModels.map((item) => item.id)).size;
  return (
    <AsrFrame title="评测任务">
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Space wrap>
          <Button type="primary" icon={<PlusOutlined />} onClick={startCreate}>
            新建评测任务
          </Button>
          {runtimeQuery.isError
            ? <Tag color="orange">Worker 状态读取失败</Tag>
            : runtimeQuery.isPending
              ? <Tag>正在检查 Worker</Tag>
              : <Tag color={runtimeQuery.data?.business_ready ? 'green' : 'red'}>{runtimeQuery.data?.status ?? '后台执行器状态未知'}</Tag>}
          {runtimeQuery.isError && <Button size="small" onClick={() => void runtimeQuery.refetch()}>重试状态检查</Button>}
          {runtimeQuery.data?.last_seen_at && <Typography.Text type="secondary">
            最近心跳：{dayjs(runtimeQuery.data.last_seen_at).format('YYYY-MM-DD HH:mm:ss')}
          </Typography.Text>}
        </Space>
        <Table<AsrJob>
          rowKey="id" columns={columns} dataSource={jobsQuery.data?.items ?? []}
          pagination={{ current: jobsPage, pageSize: jobsQuery.data?.page_size ?? 20, total: jobsQuery.data?.total ?? 0, showSizeChanger: false, onChange: setJobsPage }}
          locale={{ emptyText: '还没有评测任务；先配置一个待测模型和两个不同的参考模型。' }}
          scroll={{ x: 850 }}
        />
        <Typography.Title level={4}>夜间计划</Typography.Title>
        {schedulesQuery.isPending && <Typography.Text type="secondary">正在读取夜间计划…</Typography.Text>}
        {schedulesQuery.isError && <Alert type="error" showIcon message="夜间计划读取失败；历史评测任务仍可查看" action={<Button size="small" onClick={() => void schedulesQuery.refetch()}>重试</Button>} />}
        <Table<AsrSchedule>
          rowKey="id" dataSource={schedulesQuery.data ?? []} pagination={{ pageSize: 8 }}
          locale={{ emptyText: '尚未保存夜间计划' }}
          columns={[
            { title: '计划', dataIndex: 'name', key: 'name' },
            { title: '执行频率', key: 'schedule_type', render: (_: unknown, row: AsrSchedule) => row.schedule_type === 'DAILY' ? `每日 ${row.local_time} · ${row.timezone}` : `一次性 · ${formatInTimezone(row.scheduled_at, row.timezone)} · ${row.timezone}` },
            { title: '固定音频数', key: 'audio_count', render: (_: unknown, row: AsrSchedule) => row.audio_ids.length },
            { title: '下次触发', dataIndex: 'next_run_at', key: 'next_run_at', render: (value: string | null, row: AsrSchedule) => formatInTimezone(value, row.timezone) },
            { title: '最近触发', dataIndex: 'last_trigger_status', key: 'last_trigger_status', render: (value: string | null) => value ?? '尚未触发' },
            { title: '状态', dataIndex: 'enabled', key: 'enabled', render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '已启用' : '已暂停'}</Tag> },
            { title: '操作', key: 'action', render: (_: unknown, row: AsrSchedule) => <Button size="small" disabled={!row.enabled && row.schedule_type === 'ONCE' && !row.next_run_at}
              loading={updateSchedule.isPending && updateSchedule.variables?.id === row.id}
              onClick={() => updateSchedule.mutate({ id: row.id, enabled: !row.enabled })}>{row.enabled ? '暂停' : '恢复'}</Button> },
          ]}
          scroll={{ x: 1000 }}
        />
      </Space>
      <Modal title="创建评测任务" open={open} width={700}
        confirmLoading={createJob.isPending || createSchedule.isPending}
        footer={<Space>
          <Button onClick={closeCreate}>取消</Button>
          {wizardStep > 0 && <Button onClick={() => setWizardStep((current) => current - 1)}>上一步</Button>}
          {wizardStep < 2
            ? <Button type="primary" onClick={() => void nextStep()}>下一步</Button>
            : <Button type="primary" loading={createJob.isPending || createSchedule.isPending} onClick={() => form.submit()}>确认创建</Button>}
        </Space>}
        onCancel={closeCreate}>
        <Form<JobFormValues> form={form} layout="vertical"
          onFinish={(registeredValues) => submitJob({ ...form.getFieldsValue(true), ...registeredValues })}
          initialValues={{ mode: 'NOW', timezone: 'Asia/Shanghai', daily_time: dayjs('01:00', 'HH:mm') }}>
          <Steps current={wizardStep} size="small" style={{ marginBottom: 20 }} items={[{ title: '选择音频' }, { title: '模型参数' }, { title: '确认执行' }]} />
          <div hidden={wizardStep !== 0} aria-hidden={wizardStep !== 0}>
          <Form.Item name="audio_ids" label="选择音频" rules={[{
            validator: (_rule, value: number[] | undefined) => value?.length
              ? Promise.resolve() : Promise.reject(new Error('至少选择一条音频')),
          }]}>
            <AudioPicker
              items={audios} total={audioQuery.data?.total ?? 0} page={audioPickerPage}
              keyword={audioKeyword} loading={audioQuery.isPending}
              onPageChange={setAudioPickerPage}
              onKeywordChange={(value) => { setAudioKeyword(value); setAudioPickerPage(1); }}
            />
          </Form.Item>
          {audioQuery.isError && <Alert type="error" showIcon message="音频列表读取失败，无法创建评测任务" action={<Button size="small" onClick={() => void audioQuery.refetch()}>重试</Button>} />}
          </div>
          <div hidden={wizardStep !== 1} aria-hidden={wizardStep !== 1}>
          {asrModelsQuery.isPending && <Typography.Text type="secondary">正在检查项目已授权 ASR 模型…</Typography.Text>}
          {asrModelsQuery.isError && <Alert type="error" showIcon message="模型列表读取失败；请重试或联系平台管理员检查授权" action={<Button size="small" onClick={() => void asrModelsQuery.refetch()}>重试</Button>} />}
          {!asrModelsQuery.isPending && !asrModelsQuery.isError && <Alert type={readyAsrResources < 3 ? 'warning' : 'info'} showIcon
            message={`三方评测模型资源就绪：${readyAsrResources}/3`}
            description={readyAsrResources < 3 ? '需要三个不同且已授权的 ASR 模型资源，并分别有可用修订和参数方案；不足时不能创建任务或计划。不会生成模拟模型或识别结果。' : '请选择三个不同模型资源；服务端会再次检查项目授权、修订和参数版本。'} />}
          {(['test_model_slot', 'reference_a_model_slot', 'reference_b_model_slot'] as const).map((field, index) => (
            <Form.Item key={field} noStyle shouldUpdate={(previous, current) =>
              previous.test_model_slot !== current.test_model_slot || previous.reference_a_model_slot !== current.reference_a_model_slot || previous.reference_b_model_slot !== current.reference_b_model_slot
            }>
              {({ getFieldValue }) => {
                const otherFields = (['test_model_slot', 'reference_a_model_slot', 'reference_b_model_slot'] as const).filter((item) => item !== field);
                const selectedElsewhere = new Set(otherFields.map((item) => String(getFieldValue(item) ?? '').split(':')[0]).filter(Boolean));
                return <Form.Item name={field} label={['待测模型 · 参数版本', '参考模型 A · 参数版本', '参考模型 B · 参数版本'][index]}
                  rules={[{ required: true, message: '请选择模型资源与参数版本' }]}>
                  <Select options={modelSlotOptions(asrModels).map((option) => ({
                    ...option, disabled: selectedElsewhere.has(option.value.split(':')[0]),
                  }))} />
                </Form.Item>;
              }}
            </Form.Item>
          ))}
          <Form.Item name="diarization_model_slot" label="说话人模型 · 参数版本（可选）">
            <Select allowClear options={modelSlotOptions(diarizationModels)} />
          </Form.Item>
          </div>
          <div hidden={wizardStep !== 2} aria-hidden={wizardStep !== 2}>
          <Form.Item name="mode" label="执行方式">
            <Radio.Group options={[
              { value: 'NOW', label: '立即执行' },
              { value: 'DAILY', label: '每日夜间' },
              { value: 'ONCE', label: '指定时间' },
            ]} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, next) => prev.mode !== next.mode}>
            {({ getFieldValue }) => getFieldValue('mode') !== 'NOW' && <>
              <Form.Item name="schedule_name" label="计划名称" rules={[{ required: true }]}>
                <Input maxLength={160} placeholder="夜间会议录音对照" />
              </Form.Item>
              <Form.Item name="timezone" label="计划时区（IANA 名称）" rules={[{ required: true, whitespace: true }]}>
                <Input maxLength={80} placeholder="Asia/Shanghai" />
              </Form.Item>
              {getFieldValue('mode') === 'DAILY'
                ? <Form.Item name="daily_time" label="每日触发时间（所选时区）" rules={[{ required: true }]}>
                  <TimePicker format="HH:mm" />
                </Form.Item>
                : <Form.Item name="scheduled_at" label="指定执行时间" rules={[{ required: true }]}>
                  <DatePicker showTime format="YYYY-MM-DD HH:mm" disabledDate={(date) => date.isBefore(dayjs(), 'day')} />
                </Form.Item>}
            </>}
          </Form.Item>
          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }) => {
              const labels = modelSlotOptions(asrModels);
              const chosen = ['test_model_slot', 'reference_a_model_slot', 'reference_b_model_slot']
                .map((field) => labels.find((option) => option.value === getFieldValue(field))?.label ?? '未选择');
              return <Card size="small" title="任务摘要">
                <Space direction="vertical" style={{ display: 'flex' }}>
                  <Typography.Text>音频：{(getFieldValue('audio_ids') ?? []).length} 条</Typography.Text>
                  <Typography.Text>待测：{chosen[0]}</Typography.Text>
                  <Typography.Text>参考 A：{chosen[1]}</Typography.Text>
                  <Typography.Text>参考 B：{chosen[2]}</Typography.Text>
                  <Typography.Text type="secondary">任务固定当前音频版本和模型参数；后续音频更新不会改变本批次。</Typography.Text>
                </Space>
              </Card>;
            }}
          </Form.Item>
          <Typography.Paragraph className="asr-muted-note">
            每个槽位固定保存各自的连接修订和参数版本；同一模型资源可在不同任务中承担不同角色。夜间计划固定本次音频与配置版本，不自动纳入后续导入项。
          </Typography.Paragraph>
          {schedulesQuery.isError && <Alert type="warning" showIcon message="夜间计划接口不可用；任务列表仍可查看，但当前不能保存或管理计划。" />}
          {runtimeQuery.data && !runtimeQuery.data.business_ready && <Alert type="warning" showIcon message="ASR Worker 当前未就绪；创建任务会进入持久队列，Worker 恢复后继续处理。夜间计划也需要 Worker 常驻。" />}
          </div>
        </Form>
      </Modal>
    </AsrFrame>
  );
}

/** 批次详情页显示每家模型的独立状态、结果文本和对比入口。 */
export function JobDetailPage() {
  const { message } = App.useApp();
  const { jobId: rawJobId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [audioPage, setAudioPage] = useState(1);
  const jobId = Number(rawJobId);
  const validId = Number.isSafeInteger(jobId) && jobId > 0;
  const queryKey = ['asr', 'job-detail', jobId];
  const jobQuery = useQuery<AsrJob>({
    queryKey, enabled: validId,
    refetchInterval: (query) => ['QUEUED', 'RUNNING'].includes(query.state.data?.status ?? '') ? 3000 : false,
    queryFn: async ({ signal }) => (await asrEvaluationApi.getJob(jobId, { signal, params: { summary_only: true } })),
  });
  const audioGroupsQuery = useQuery<AsrPage<AsrJobAudioGroup>>({
    queryKey: ['asr', 'job-audio-groups', jobQuery.data?.project_id, jobId, audioPage, keyword, statusFilter],
    enabled: Boolean(jobQuery.data),
    refetchInterval: (query) => {
      if (['QUEUED', 'RUNNING'].includes(jobQuery.data?.status ?? '')) return 3000;
      return query.state.data?.items.some((item) => ['PENDING', 'QUEUED', 'SUBMITTING', 'REMOTE_RUNNING'].includes(item.diarization_status ?? '')
        || ['QUEUED', 'RUNNING'].includes(item.content_review_status ?? '')) ? 3000 : false;
    },
    queryFn: ({ signal }) => asrEvaluationApi.listJobAudioRuns(jobId, audioPage, keyword.trim(), statusFilter, signal),
  });
  const summaryQuery = useQuery<Awaited<ReturnType<typeof asrEvaluationApi.getContentReviewSummary>>>({
    queryKey: ['asr', 'job-content-review-summary', jobQuery.data?.project_id, jobId],
    enabled: Boolean(jobQuery.data),
    refetchInterval: (query) => shouldPollBatchSummary(jobQuery.data?.status, query.state.data) ? 3000 : false,
    queryFn: ({ signal }) => asrEvaluationApi.getContentReviewSummary(jobId, signal),
  });
  const previousJobStatus = useRef<{ id: number; status: string } | null>(null);
  useEffect(() => {
    if (!jobQuery.data) return;
    const previous = previousJobStatus.current;
    if (previous?.id === jobId && enteredTerminalJobState(previous.status, jobQuery.data.status)) {
      void queryClient.invalidateQueries({ queryKey: ['asr', 'job-content-review-summary', jobQuery.data.project_id, jobId] });
      void queryClient.invalidateQueries({ queryKey: ['asr', 'job-audio-groups', jobQuery.data.project_id, jobId] });
    }
    previousJobStatus.current = { id: jobId, status: jobQuery.data.status };
  }, [jobId, jobQuery.data?.project_id, jobQuery.data?.status, queryClient]);
  const retryJob = useMutation({
    mutationFn: (requestKey: string) => asrEvaluationApi.retryJob(jobId, requestKey),
    onSuccess: (newJob) => {
      clearJobRequestKey(jobId, 'retry');
      message.success(`已创建 ASR-${newJob.id}：只重试明确失败项，成功结果和原批次均保留`);
      void queryClient.invalidateQueries({ queryKey: asrQueryKeys.project(newJob.project_id, 'jobs') });
      navigate('/console/asr/jobs/' + newJob.id);
    },
    onError: (error) => message.error(getErrorMessage(error, '创建重试批次失败')),
  });
  const rerunJob = useMutation({
    mutationFn: (requestKey: string) => asrEvaluationApi.rerunJob(jobId, requestKey),
    onSuccess: (newJob) => {
      clearJobRequestKey(jobId, 'rerun');
      message.success(`已创建完整重跑批次 ASR-${newJob.id}；原任务、模型配置和音频版本保持不变`);
      void queryClient.invalidateQueries({ queryKey: asrQueryKeys.project(newJob.project_id, 'jobs') });
      navigate('/console/asr/jobs/' + newJob.id);
    },
    onError: (error) => message.error(getErrorMessage(error, '创建完整重跑批次失败')),
  });
  if (!validId) return <AsrFrame title="任务详情"><Empty description="任务编号无效" /></AsrFrame>;
  if (jobQuery.isPending) return <AsrFrame title="任务详情"><LoadingState /></AsrFrame>;
  if (jobQuery.isError) return <AsrFrame title="任务详情"><ErrorState error={jobQuery.error} onRetry={jobQuery.refetch} /></AsrFrame>;
  const job = jobQuery.data;
  const canFullRerun = job.can_full_rerun === true;
  const audioRows = audioGroupsQuery.data?.items ?? [];
  return (
    <AsrFrame title={'评测任务 ASR-' + job.id} projectId={job.project_id}>
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Space>{jobStatusTag(job.status)}<Typography.Text type="secondary">任务会在 Worker 后台继续运行。</Typography.Text></Space>
        {summaryQuery.data && <>
          <Space wrap>
            <Tag>音频 {summaryQuery.data.planned_audio} 条</Tag>
            <Tag color="green">三方识别完成 {summaryQuery.data.asr_success_audio}/{summaryQuery.data.planned_audio}</Tag>
            <Tag color={summaryQuery.data.asr_failed_audio ? 'orange' : 'default'}>失败或待核实 {summaryQuery.data.asr_failed_audio}</Tag>
            <Tag>有效对比 {summaryQuery.data.valid_pairs}/{summaryQuery.data.planned_audio}</Tag>
            <Tag>内容评审 {summaryQuery.data.review_denominator === 0 ? '尚未开展' : `完成 ${summaryQuery.data.review_complete}/${summaryQuery.data.review_denominator}`}</Tag>
          </Space>
          <Collapse items={[{ key: 'review-metrics', label: '评审覆盖与模型意见详情', children: <Space wrap>
            <Tag>评审部分完成 {summaryQuery.data.review_partial}/{summaryQuery.data.review_denominator || '未开展'}</Tag>
            <Tag>评审失败或待核实 {summaryQuery.data.review_failed_or_uncertain}/{summaryQuery.data.review_denominator || '未开展'}</Tag>
            <Tag>评审覆盖 {summaryQuery.data.coverage_denominator ? `${summaryQuery.data.coverage_numerator}/${summaryQuery.data.coverage_denominator}` : '尚未开展'}</Tag>
            <Tag>模型意见：候选较好 {summaryQuery.data.ab_verdicts.candidate_better}</Tag>
            <Tag>模型意见：基线较好 {summaryQuery.data.ab_verdicts.baseline_better}</Tag>
            <Tag>模型意见：持平 {summaryQuery.data.ab_verdicts.tie}</Tag>
            <Tag>模型意见：无法判断 {summaryQuery.data.ab_verdicts.inconclusive}</Tag>
            <Typography.Text type="secondary">模型意见是评审结果，不等同人工结论或准确率；分母为零时表示尚未开展。</Typography.Text>
          </Space> }]} />
        </>}
        {summaryQuery.isError && <Typography.Text type="warning">内容评审汇总读取失败。</Typography.Text>}
        {['FAILED', 'PARTIAL_FAILED'].includes(job.status) && <Button onClick={() => Modal.confirm({
          title: '仅重试明确失败项？',
          content: '成功运行会在新批次中复用原结果和固定音频版本；只有明确失败的模型运行会重新提交。远端状态待核实的请求不会自动重发。',
          okText: '重试失败项', cancelText: '返回', onOk: () => retryJob.mutateAsync(jobRequestKey(jobId, 'retry')),
        })} loading={retryJob.isPending}>重试失败项</Button>}
        {canFullRerun && <Button onClick={() => Modal.confirm({
          title: '完整重跑此批次？',
          content: '将按新的批次重新提交全部运行，固定原始音频版本、模型修订和参数配置。原批次与结果保留；包含状态待核实的运行时不会开放此操作。',
          okText: '完整重跑', cancelText: '返回', onOk: () => rerunJob.mutateAsync(jobRequestKey(jobId, 'rerun')),
        })} loading={rerunJob.isPending}>完整重跑（原音频版本）</Button>}
        {job.status === 'RECONCILIATION_REQUIRED' && <Typography.Paragraph type="warning">
          提交状态不确定。平台不会盲目重复调用；请按任务运行记录中的状态与幂等标识核实远端。
        </Typography.Paragraph>}
        <Space wrap>
          <Input.Search aria-label="搜索批次音频" placeholder="搜索音频标题" allowClear value={keyword} onChange={(event) => { setKeyword(event.target.value); setAudioPage(1); }} />
          <Select aria-label="筛选运行状态" value={statusFilter} onChange={(value) => { setStatusFilter(value); setAudioPage(1); }} style={{ minWidth: 140 }} options={[
            { value: 'ALL', label: '全部状态' }, ...[
              ['PENDING', '排队中'], ['SUBMITTING', '提交中'], ['REMOTE_RUNNING', '识别中'], ['SUCCEEDED', '已完成'],
              ['FAILED', '失败'], ['RECONCILIATION_REQUIRED', '状态待核实'], ['CANCELLED', '已取消'],
            ].map(([value, label]) => ({ value, label })),
          ]} />
        </Space>
        {audioGroupsQuery.isError
          ? <Alert type="error" message="音频分组读取失败" action={<Button size="small" onClick={() => void audioGroupsQuery.refetch()}>重试</Button>} />
          : <Table<AsrJobAudioGroup> rowKey="key" dataSource={audioRows} loading={audioGroupsQuery.isPending}
          pagination={{ current: audioPage, total: audioGroupsQuery.data?.total ?? 0, pageSize: 10, showSizeChanger: false, onChange: setAudioPage }} scroll={{ x: 800 }} columns={[
          { title: '音频标题 / 版本', key: 'audio', render: (_: unknown, row: AsrJobAudioGroup) => {
            const testRun = row.runs.find((run) => run.role === 'TEST');
            const title = row.audio_name ?? `音频 #${row.audio_id}`;
            return <Space direction="vertical" size={0}>{testRun ? <Link to={`/console/asr/runs/${testRun.id}`}>{title}</Link> : <Typography.Text>{title}（请选择模型）</Typography.Text>}
              <Typography.Text type="secondary">{row.audio_content_version != null ? `版本 v${row.audio_content_version}` : '固定版本未知'}</Typography.Text></Space>;
          } },
          { title: '模型运行', key: 'runs', render: (_: unknown, row: AsrJobAudioGroup) => <Space direction="vertical" size={4}>{row.runs.map((run) => <Space key={run.id} wrap>
            <Link to={`/console/asr/runs/${run.id}`}>{run.role === 'TEST' ? '待测' : run.request_snapshot.task_slot === 'REFERENCE_A' ? '参考 A' : run.request_snapshot.task_slot === 'REFERENCE_B' ? '参考 B' : '参考'} #{run.id}</Link>
            {jobStatusTag(run.status)}<Link to={`/console/asr/runs/${run.id}/listen`}>听</Link>
          </Space>)}</Space> },
          { title: '音频时长', key: 'duration', render: (_: unknown, row: AsrJobAudioGroup) => row.audio_duration_seconds != null ? `${row.audio_duration_seconds} 秒` : '未知' },
          { title: '后续阶段', key: 'stages', render: (_: unknown, row: AsrJobAudioGroup) => <Space direction="vertical" size={0}>
            <Typography.Text>说话人：{row.diarization_status ? jobStatusTag(row.diarization_status) : '未开始'}</Typography.Text>
            <Typography.Text>内容评审：{row.content_review_status ? reviewStatusLabel(row.content_review_status) : '未开始'}</Typography.Text>
            <Typography.Text type="secondary">已生成转写片段：{row.test_segment_count ?? '未报告'}</Typography.Text>
          </Space> },
          { title: '对比', key: 'comparison', render: (_: unknown, row: AsrJobAudioGroup) => row.comparison_id ? <Link to={`/console/asr/comparisons/${row.comparison_id}`}>查看对比</Link> : '尚无对比' },
        ]} />}
      </Space>
    </AsrFrame>
  );
}
