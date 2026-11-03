// 评测任务与夜间计划：新建后立即返回批次 ID，Web 页面不等待长音频识别。
import { Alert, App, Button, DatePicker, Empty, Form, Input, Modal, Pagination, Radio, Select, Space, Table, Tag, TimePicker, Typography } from 'antd';
import { PlusOutlined, StopOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import dayjs, { type Dayjs } from 'dayjs';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import type { AsrAudio, AsrJob, AsrSchedule } from '@/features/asr-evaluation/contracts';
import { modelCenterApi, modelCenterQueryKeys, type ModelAvailableResource } from '@/features/model-configuration/api/modelCenter';
import { AsrFrame } from './AsrFrame';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';

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
  };
  const [label, color] = labels[value] ?? [value, 'default'];
  return <Tag color={color}>{label}</Tag>;
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
  const { currentProjectId } = useConsoleScope();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<JobFormValues>();
  const [open, setOpen] = useState(false);
  const [jobsPage, setJobsPage] = useState(1);
  const [audioPickerPage, setAudioPickerPage] = useState(1);
  const [audioKeyword, setAudioKeyword] = useState('');
  useEffect(() => {
    setJobsPage(1);
    setAudioPickerPage(1);
    setAudioKeyword('');
    form.setFieldValue('audio_ids', []);
  }, [currentProjectId, form]);
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
      setOpen(false);
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
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); form.setFieldValue('mode', 'NOW'); setOpen(true); }}>
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
      <Modal title="新建评测任务或夜间计划" open={open} width={700}
        confirmLoading={createJob.isPending || createSchedule.isPending}
        okButtonProps={{ disabled: readyAsrResources < 3 || asrModelsQuery.isError || audioQuery.isError }}
        onCancel={() => setOpen(false)} onOk={() => form.submit()}>
        <Form<JobFormValues> form={form} layout="vertical" onFinish={submitJob}
          initialValues={{ mode: 'NOW', timezone: 'Asia/Shanghai', daily_time: dayjs('01:00', 'HH:mm') }}>
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
          <Typography.Paragraph className="asr-muted-note">
            每个槽位固定保存各自的连接修订和参数版本；同一模型资源可在不同任务中承担不同角色。夜间计划固定本次音频与配置版本，不自动纳入后续导入项。
          </Typography.Paragraph>
          {asrModels.length > 0 && readyAsrResources < 3 && <Alert type="warning" showIcon message={`当前只有 ${readyAsrResources} 个不同 ASR 模型资源；三方评测需要 3 个。请联系平台管理员配置并授权真实模型。`} />}
          {diarizationModelsQuery.isError && <Alert type="warning" showIcon message="说话人模型列表暂时不可用；这不影响普通三方转写任务。" action={<Button size="small" onClick={() => void diarizationModelsQuery.refetch()}>重试</Button>} />}
          {schedulesQuery.isError && <Alert type="warning" showIcon message="夜间计划接口不可用；任务列表仍可查看，但当前不能保存或管理计划。" />}
          {runtimeQuery.data && !runtimeQuery.data.business_ready && <Alert type="warning" showIcon message="ASR Worker 当前未就绪；创建任务会进入持久队列，Worker 恢复后继续处理。夜间计划也需要 Worker 常驻。" />}
        </Form>
      </Modal>
    </AsrFrame>
  );
}

/** 批次详情页显示每家模型的独立状态、结果文本和对比入口。 */
export function JobDetailPage() {
  const { message } = App.useApp();
  const { jobId: rawJobId } = useParams();
  const { currentProjectId } = useConsoleScope();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const jobId = Number(rawJobId);
  const validId = Number.isSafeInteger(jobId) && jobId > 0;
  const queryKey = currentProjectId ? asrQueryKeys.project(currentProjectId, 'job', jobId) : ['asr', 'job', jobId];
  const jobQuery = useQuery({
    queryKey, enabled: Boolean(currentProjectId && validId), refetchInterval: 5000,
    queryFn: async ({ signal }) => (await asrEvaluationApi.getJob(jobId, { signal })),
  });
  const retryJob = useMutation({
    mutationFn: () => asrEvaluationApi.retryJob(jobId),
    onSuccess: (newJob) => {
      message.success(`已创建新批次 ASR-${newJob.id}，原批次结果保留`);
      void queryClient.invalidateQueries({ queryKey: currentProjectId ? asrQueryKeys.project(currentProjectId, 'jobs') : ['asr', 'jobs'] });
      navigate('/console/asr/jobs/' + newJob.id);
    },
    onError: (error) => message.error(getErrorMessage(error, '创建重试批次失败')),
  });
  if (!currentProjectId) return <AsrFrame title="任务详情"><Empty description="先选择项目" /></AsrFrame>;
  if (!validId) return <AsrFrame title="任务详情"><Empty description="任务编号无效" /></AsrFrame>;
  if (jobQuery.isPending) return <AsrFrame title="任务详情"><LoadingState /></AsrFrame>;
  if (jobQuery.isError) return <AsrFrame title="任务详情"><ErrorState error={jobQuery.error} onRetry={jobQuery.refetch} /></AsrFrame>;
  const job = jobQuery.data;
  return (
    <AsrFrame title={'评测任务 ASR-' + job.id}>
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Space>{jobStatusTag(job.status)}<Typography.Text type="secondary">任务会在 Worker 后台继续运行。</Typography.Text></Space>
        {['FAILED', 'PARTIAL_FAILED'].includes(job.status) && <Button onClick={() => Modal.confirm({
          title: '创建新的三方重跑批次？',
          content: `将按原音频与连接配置新建批次，最多产生 ${((job.config_snapshot.audio_ids as number[] | undefined)?.length ?? 0) * 3} 次模型请求；本批次和原结果会保留。`,
          okText: '创建新批次', cancelText: '返回', onOk: () => retryJob.mutateAsync(),
        })} loading={retryJob.isPending}>按原配置重试</Button>}
        {job.status === 'RECONCILIATION_REQUIRED' && <Typography.Paragraph type="warning">
          提交状态不确定。平台不会盲目重复调用；请按任务运行记录中的状态与幂等标识核实远端。
        </Typography.Paragraph>}
        {(job.runs ?? []).map((run) => {
          const comparison = job.comparisons?.find((item) => item.audio_id === run.audio_id);
          return (
            <div key={run.id} className="asr-run-row">
              <Space wrap>
                <Tag>{run.role === 'TEST' ? '待测模型' : '参考模型'}</Tag>
                {jobStatusTag(run.status)}
                <Typography.Text>音频 #{run.audio_id}</Typography.Text>
                {run.request_snapshot.model_id && <Typography.Text>{String(run.request_snapshot.model_id)}</Typography.Text>}
                {run.parameter_set_id && <Typography.Text type="secondary">参数方案 #{run.parameter_set_id}</Typography.Text>}
                {run.duration_ms != null && <Typography.Text type="secondary">本次请求 {Math.round(run.duration_ms / 1000)} 秒</Typography.Text>}
                {run.remote_task_id && <Typography.Text type="secondary">远端任务 ID：{run.remote_task_id}</Typography.Text>}
              </Space>
              {run.error_message && <Typography.Paragraph type="danger">{run.error_message}</Typography.Paragraph>}
              {run.transcript != null && <Typography.Paragraph className="asr-transcript-cell">{run.transcript}</Typography.Paragraph>}
              <Link to={'/console/asr/runs/' + run.id}>打开单模型音频工作台</Link>
              {comparison && <Link to={'/console/asr/comparisons/' + comparison.id}>打开识别结果对比</Link>}
            </div>
          );
        })}
      </Space>
    </AsrFrame>
  );
}
