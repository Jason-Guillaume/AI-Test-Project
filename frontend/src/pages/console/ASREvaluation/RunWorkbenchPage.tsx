// 单模型音频工作台：固定到一个转写运行与音频版本，呈现原文、说话人区间和执行阶段。
import {
  Alert, App, Button, Card, Collapse, Descriptions, Drawer, Empty, Input, Pagination,
  Select, Space, Spin, Tag, Typography,
} from 'antd';
import {
  AudioOutlined, CheckOutlined, DownloadOutlined, LinkOutlined, ReloadOutlined, SoundOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import { modelCenterApi, modelCenterQueryKeys, type ModelAvailableResource } from '@/features/model-configuration/api/modelCenter';
import type {
  AsrAudioMetadata, AsrProcessingRun, AsrSpeaker, AsrSpeakerTurn, AsrTranscriptSegment,
  AsrWorkbench, JsonValue,
} from '@/features/asr-evaluation/contracts';
import { AsrFrame } from './AsrFrame';
import { AudioWorkbenchPlayer } from '@/features/asr-evaluation/components/AudioWorkbenchPlayer';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';

const { Text, Paragraph, Title } = Typography;

const ACTIVE_PROCESSING = new Set(['PENDING', 'SUBMITTING', 'REMOTE_RUNNING', 'RECONCILIATION_REQUIRED']);
const AUDIO_FIELD_LABELS: Record<string, Record<string, string>> = {
  source: {
    name: '文件名', audio_version: '音频版本', url_display: '登记源地址（已脱敏）', playback_url: '平台代理地址',
    source_size_bytes: '源文件大小（字节）', last_modified: '源 Last-Modified', etag: '源 ETag',
    source_label: '来源说明',
  },
  original: {
    container: '容器', codec: '编解码器', codec_configuration: '编码配置', sample_rate_hz: '原文件采样率（Hz）',
    channels: '声道数', channel_layout: '声道布局', bit_rate: '码率（bit/s）',
    bits_per_sample: '可报告的原始样本位数', encoder: '编码器', duration_seconds: '原文件时长（秒）',
  },
  analysis: {
    analysis_side: '分析端', sample_rate_hz: '分析 PCM 采样率（Hz）', channels: '分析声道数',
    format: '分析 PCM 格式', frames: '分析帧数', duration_seconds: '分析时长（秒）',
    source_sample_rate_hz: '来源采样率（Hz）', scope: '统计范围', peak: '峰值', rms: 'RMS',
    dc_offset: 'DC 偏移', full_scale_sample_count: '满幅样本数', sample_count: '样本数',
    start_ms: '起始位置（毫秒）', end_ms: '结束位置（毫秒）',
  },
};

/** 已知字段使用中文说明，服务端新增字段保留原键并标成未知字段。 */
function audioFieldLabel(group: 'source' | 'original' | 'analysis', key: string): string {
  return AUDIO_FIELD_LABELS[group][key] ?? `未识别字段 · ${key}`;
}

/** 格式化区间时间，null 表示没有可信时间戳并明确显示未定位。 */
function formatMs(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '未定位';
  const whole = Math.floor(value);
  return `${Math.floor(whole / 60000).toString().padStart(2, '0')}:${((whole % 60000) / 1000).toFixed(3).padStart(6, '0')}`;
}

/** 将存储的 JSON 值转为可读文本；false 与 0 均按已知值显示。 */
function printable(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未报告';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/** 对历史快照再做一次凭据键过滤，防止旧版本快照误把秘密展示在页面。 */
function redactSnapshot(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactSnapshot);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [
      key,
      ['token', 'secret', 'password', 'authorization', 'cookie', 'api_key'].some((part) => key.toLowerCase().includes(part))
        ? '[已脱敏]' : redactSnapshot(item),
    ]));
  }
  return value;
}

/** 给全文视图按 Unicode code point 偏移标记当前真实播放区间。 */
function highlightedTranscript(
  transcript: string,
  activeSegments: AsrTranscriptSegment[],
): React.ReactNode {
  const codePoints = Array.from(transcript);
  const spans = activeSegments
    .filter((item) => Number.isInteger(item.start_offset) && Number.isInteger(item.end_offset))
    .map((item) => [Math.max(0, item.start_offset!), Math.min(codePoints.length, item.end_offset!)] as const)
    .filter(([start, end]) => end > start)
    .sort((left, right) => left[0] - right[0]);
  if (!spans.length) return transcript || '没有可显示的转写文本';
  const merged: Array<[number, number]> = [];
  spans.forEach(([start, end]) => {
    const previous = merged.at(-1);
    if (previous && start <= previous[1]) previous[1] = Math.max(previous[1], end);
    else merged.push([start, end]);
  });
  const output: React.ReactNode[] = [];
  let cursor = 0;
  merged.forEach(([start, end], index) => {
    if (start > cursor) output.push(codePoints.slice(cursor, start).join(''));
    output.push(<mark key={`active-${index}`}>{codePoints.slice(start, end).join('')}</mark>);
    cursor = end;
  });
  if (cursor < codePoints.length) output.push(codePoints.slice(cursor).join(''));
  return output;
}

/** 生成各类后台阶段的中文状态说明。 */
function processingLabel(run: AsrProcessingRun | null | undefined): string {
  if (!run) return '尚未执行';
  const labels: Record<string, string> = {
    PENDING: '排队中', SUBMITTING: '提交中', REMOTE_RUNNING: '远端处理中', SUCCEEDED: '已完成',
    FAILED: '失败', RECONCILIATION_REQUIRED: '远端提交状态待核实', CANCELLED: '已取消',
  };
  return labels[run.status] ?? run.status;
}

/** 下载 JSON 或 TXT 导出文件，并释放临时浏览器对象地址。 */
function downloadBlob(blob: Blob, filename: string) {
  const address = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = address;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(address);
}

/** 按模型单次运行查看转写、说话人、真实波形、音频信息和可审计确认。 */
export function RunWorkbenchPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const { runId: rawRunId } = useParams();
  const runId = Number(rawRunId);
  const validId = Number.isSafeInteger(runId) && runId > 0;
  const audioRef = useRef<HTMLAudioElement>(null);
  const [audioInfoOpen, setAudioInfoOpen] = useState(false);
  const [requestOpen, setRequestOpen] = useState(false);
  const [playbackTime, setPlaybackTime] = useState(0);
  const [playbackSnapshot, setPlaybackSnapshot] = useState<Record<string, string>>({});
  const [viewMode, setViewMode] = useState<'FULL' | 'DIALOGUE'>('FULL');
  const [search, setSearch] = useState('');
  const [segmentPage, setSegmentPage] = useState(1);
  const [turnPage, setTurnPage] = useState(1);
  const [speakerFilter, setSpeakerFilter] = useState<string>('ALL');
  const [turnFilter, setTurnFilter] = useState<string>('ALL');
  const [selectedResourceId, setSelectedResourceId] = useState<number>();
  const [selectedProfileId, setSelectedProfileId] = useState<number>();
  const [renameDrafts, setRenameDrafts] = useState<Record<number, string>>({});

  const workbenchKey = currentProjectId
    ? asrQueryKeys.project(currentProjectId, 'run-workbench', runId)
    : ['asr', 'run-workbench', null, runId];
  const workbenchQuery = useQuery<AsrWorkbench>({
    queryKey: workbenchKey,
    enabled: validId,
    refetchInterval: (query) => ACTIVE_PROCESSING.has(query.state.data?.diarization.processing_run?.status ?? '') ? 3000 : false,
    queryFn: async ({ signal }) => asrEvaluationApi.getRunWorkbench(runId, signal),
  });
  const workbench = workbenchQuery.data;
  const audio = workbench?.audio;
  const processing = workbench?.diarization.processing_run;
  const resultId = workbench?.diarization.result_id ?? null;
  const run = workbench?.run;
  const queryScope = currentProjectId ?? workbench?.run.project_id ?? null;
  const resourceKey = queryScope
    ? asrQueryKeys.project(queryScope, 'run-workbench', runId)
    : ['asr', 'run-workbench', null, runId];

  const jobQuery = useQuery({
    queryKey: [...resourceKey, 'job'], enabled: Boolean(run?.job_id),
    queryFn: async ({ signal }) => asrEvaluationApi.getJob(run!.job_id, { signal }),
  });
  const diarizationModelsQuery = useQuery({
    queryKey: queryScope ? modelCenterQueryKeys.available(queryScope, 'DIARIZATION') : ['model-center', 'available', null, 'DIARIZATION'],
    enabled: Boolean(queryScope),
    queryFn: ({ signal }) => modelCenterApi.available(queryScope!, 'DIARIZATION', signal),
  });
  const diarizationModels = diarizationModelsQuery.data?.items ?? [];
  const segmentsFilter = useMemo(() => ({
    ...(speakerFilter !== 'ALL' && speakerFilter !== 'UNKNOWN' && speakerFilter !== 'MIXED'
      ? { speaker_id: Number(speakerFilter) } : {}),
    ...(speakerFilter === 'UNKNOWN' ? { unknown_only: true } : {}),
    ...(speakerFilter === 'MIXED' ? { mixed_only: true } : {}),
    ...(search.trim() ? { search: search.trim() } : {}),
  }), [speakerFilter, search]);
  const segmentsKey = [...resourceKey, 'segments', segmentPage, segmentsFilter];
  const segmentsQuery = useQuery({
    queryKey: segmentsKey,
    enabled: Boolean(runId),
    queryFn: async ({ signal }) => asrEvaluationApi.listRunSegments(runId, segmentPage, signal, segmentsFilter),
  });
  const segments = segmentsQuery.data?.items ?? [];
  const speakersQuery = useQuery({
    queryKey: [...resourceKey, 'speakers', resultId], enabled: Boolean(resultId),
    queryFn: async ({ signal }) => asrEvaluationApi.listSpeakers(resultId!, signal),
  });
  const speakers = speakersQuery.data?.items ?? [];
  const turnsFilter = useMemo(() => ({
    ...(turnFilter === 'UNKNOWN' ? { unknown_only: true } : {}),
    ...(turnFilter === 'OVERLAP' ? { overlap_only: true } : {}),
    ...(turnFilter !== 'ALL' && turnFilter !== 'UNKNOWN' && turnFilter !== 'OVERLAP'
      ? { speaker_id: Number(turnFilter) } : {}),
  }), [turnFilter]);
  const turnsQuery = useQuery({
    queryKey: [...resourceKey, 'speaker-turns', resultId, turnPage, turnsFilter],
    enabled: Boolean(resultId),
    queryFn: async ({ signal }) => asrEvaluationApi.listSpeakerTurns(resultId!, turnPage, signal, turnsFilter),
  });
  const turns = turnsQuery.data?.items ?? [];

  const metadataQuery = useQuery<AsrAudioMetadata>({
    queryKey: [...resourceKey, 'audio-metadata', audio?.audio_version_id],
    enabled: Boolean(audioInfoOpen && audio?.id && audio.audio_version_id),
    refetchInterval: (query) => ['PENDING', 'QUEUED', 'SUBMITTING', 'REMOTE_RUNNING'].includes(query.state.data?.analysis_status ?? '') ? 3000 : false,
    queryFn: async ({ signal }) => asrEvaluationApi.getAudioMetadata(audio!.id, audio!.audio_version_id!, signal),
  });
  const peaksQuery = useQuery<Record<string, JsonValue>>({
    queryKey: [...resourceKey, 'audio-peaks', audio?.audio_version_id, 2048],
    // 播放器需要波形时只请求已经后台生成的小型峰值摘要，不读取原始音频字节。
    enabled: Boolean(audio?.id && audio.audio_version_id),
    refetchInterval: (query) => ['PENDING', 'QUEUED', 'SUBMITTING', 'REMOTE_RUNNING'].includes(query.state.data?.status as string ?? '') ? 3000 : false,
    queryFn: async ({ signal }) => asrEvaluationApi.getAudioPeaks(audio!.id, audio!.audio_version_id!, 2048, signal),
  });

  /** 播放位置是 AudioElement 当前值；不要因打开抽屉或查询刷新改写它。 */
  const onTimeChange = useCallback((seconds: number) => setPlaybackTime(seconds), []);
  /** 刷新工作台与关联读模型，保留播放器 DOM 和播放进度。 */
  const refreshWorkbench = () => {
    void queryClient.invalidateQueries({ queryKey: workbenchKey });
    void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'segments'] });
    void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'speakers'] });
    void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'speaker-turns'] });
  };

  const diarizationMutation = useMutation({
    mutationFn: (body: { resource_id: number; revision_id: number; profile_id: number }) =>
      asrEvaluationApi.createDiarizationRun(audio!.id, audio!.audio_version_id!, body),
    onSuccess: (created) => {
      message.success(`说话人阶段 ${created.id} 已排队；不会重跑三家转写`);
      refreshWorkbench();
    },
    onError: () => message.error('说话人任务创建失败；现有转写及三方对比不受影响。'),
  });
  const retryMutation = useMutation({
    mutationFn: () => asrEvaluationApi.retryProcessingRun(processing!.id),
    onSuccess: () => { message.success('说话人阶段已单独重试'); refreshWorkbench(); },
    onError: () => message.error('仅明确失败的说话人阶段可以重试。'),
  });
  const fusionMutation = useMutation({
    mutationFn: () => asrEvaluationApi.createSpeakerFusion(runId, resultId!),
    onSuccess: () => { message.success('同一音频版本的说话人结果已关联'); refreshWorkbench(); },
    onError: () => message.error('说话人结果与当前转写版本不匹配，未建立关联。'),
  });
  const reviewMutation = useMutation({
    mutationFn: (input: { assignmentId: number; expectedVersion: number; speakerId: number | null }) =>
      asrEvaluationApi.reviewSpeakerAssignment(input.assignmentId, {
        expected_version: input.expectedVersion, review_status: 'CONFIRMED', speaker_id: input.speakerId,
      }),
    onSuccess: () => { message.success('人工说话人确认已保存并留有版本记录'); refreshWorkbench(); },
    onError: () => message.error('人工确认保存失败；如版本冲突，请刷新片段后重试。'),
  });
  const renameMutation = useMutation({
    mutationFn: ({ speakerId, displayName }: { speakerId: number; displayName: string }) =>
      asrEvaluationApi.renameSpeaker(speakerId, displayName),
    onSuccess: () => {
      message.success('本次录音的说话人显示名已更新');
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'speakers'] });
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'speaker-turns'] });
    },
    onError: () => message.error('说话人显示名保存失败。'),
  });
  const analysisMutation = useMutation({
    mutationFn: () => metadata?.processing_run?.status === 'FAILED'
      ? asrEvaluationApi.retryProcessingRun(metadata.processing_run.id)
      : asrEvaluationApi.startAudioAnalysis(audio!.id, audio!.audio_version_id!),
    onSuccess: () => {
      message.success('音频解析已加入后台队列；当前播放继续');
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'audio-metadata'] });
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'audio-peaks'] });
    },
    onError: () => message.error('后台音频分析未能启动；原生播放器仍可回听。'),
  });
  const exportMutation = useMutation({
    mutationFn: (format: 'json' | 'txt') => asrEvaluationApi.exportRun(runId, format),
    onSuccess: (blob, format) => downloadBlob(blob, `asr-run-${runId}.${format}`),
    onError: () => message.error('导出失败；当前页面仍可查看识别结果。'),
  });

  useEffect(() => {
    if (!audioInfoOpen) return undefined;
    /** 仅抽屉打开时采样当前播放器状态；关闭后释放 500ms 计时器。 */
    const sample = () => {
      const element = audioRef.current;
      if (!element) return;
      const ranges = (range: TimeRanges) => Array.from({ length: range.length }, (_, index) =>
        `${range.start(index).toFixed(3)}–${range.end(index).toFixed(3)} 秒`).join('、') || '未报告';
      setPlaybackSnapshot({
        duration: Number.isFinite(element.duration) ? `${element.duration.toFixed(3)} 秒` : '未报告',
        current_time: `${element.currentTime.toFixed(3)} 秒`, state: element.ended ? '已结束' : element.paused ? '暂停' : '播放中',
        playback_rate: `${element.playbackRate}×`, volume: `${Math.round(element.volume * 100)}%`,
        muted: element.muted ? '是' : '否', ready_state: String(element.readyState), network_state: String(element.networkState),
        buffered: ranges(element.buffered), seekable: ranges(element.seekable), played: ranges(element.played),
        media_error: element.error ? `${element.error.code} · ${element.error.message || '浏览器媒体错误'}` : '无',
      });
    };
    sample();
    const timer = window.setInterval(sample, 500);
    return () => window.clearInterval(timer);
  }, [audioInfoOpen]);

  /** 依据真实片段时间回听；缺失或无效时间只保留文本查看。 */
  const seekTo = (startMs: number | null, endMs?: number | null) => {
    const player = audioRef.current;
    if (!player || startMs === null || !Number.isFinite(startMs)) return;
    player.ontimeupdate = null;
    player.currentTime = Math.max(0, startMs / 1000);
    if (endMs !== null && endMs !== undefined && endMs > startMs) {
      player.ontimeupdate = () => {
        if (player.currentTime >= endMs / 1000) {
          player.pause();
          player.ontimeupdate = null;
        }
      };
    }
    void player.play().catch(() => message.error('音频无法播放；请检查源文件是否可访问或格式是否受浏览器支持。'));
  };

  const currentSegments = segments.filter((segment) =>
    segment.start_ms !== null && segment.end_ms !== null &&
    segment.start_ms <= playbackTime * 1000 && segment.end_ms > playbackTime * 1000,
  );
  const activeTurns = turns.filter((turn) => turn.start_ms <= playbackTime * 1000 && turn.end_ms > playbackTime * 1000);
  const diarizationModelOptions = diarizationModels.map((item: ModelAvailableResource) => ({
    value: item.id, label: `${item.display_name} · ${item.revision.model_name} · v${item.revision.version} · ${(item.revision.capabilities ?? []).join('、') || '能力未声明'}`,
  }));
  const selectedModel = diarizationModels.find((item: ModelAvailableResource) => item.id === selectedResourceId);
  const selectedProfile = selectedModel?.profiles.find((item) => item.id === selectedProfileId);
  const speakerOptions = [
    { value: 'ALL', label: '全部归属' },
    ...speakers.map((item: AsrSpeaker) => ({ value: String(item.id), label: item.display_name })),
    { value: 'UNKNOWN', label: '未知归属' }, { value: 'MIXED', label: '混合 / 重叠' },
  ];
  const metadata = metadataQuery.data;
  const playbackFields = Object.entries(playbackSnapshot).map(([key, value]) => ({ key, label: ({
    duration: '播放器时长', current_time: '当前时间', state: '播放状态', playback_rate: '倍速', volume: '音量',
    muted: '静音', ready_state: 'readyState', network_state: 'networkState', buffered: '已缓冲范围',
    seekable: '可跳转范围', played: '已播放范围', media_error: '媒体错误',
  } as Record<string, string>)[key] ?? key, value }));

  if (!validId) return <AsrFrame title="单模型音频工作台"><Empty description="运行编号无效" /></AsrFrame>;
  if (workbenchQuery.isPending) return <AsrFrame title="单模型音频工作台"><LoadingState /></AsrFrame>;
  if (workbenchQuery.isError) return <AsrFrame title="单模型音频工作台"><ErrorState error={workbenchQuery.error} onRetry={workbenchQuery.refetch} /></AsrFrame>;
  if (!workbench || !run) return <AsrFrame title="单模型音频工作台"><Empty description="转写运行不存在" /></AsrFrame>;

  const sameAudioRuns = (jobQuery.data?.runs ?? []).filter((item) => item.audio_id === run.audio_id && item.audio_version_id === run.audio_version_id);
  const relatedComparison = (jobQuery.data?.comparisons ?? []).find((item) => item.audio_id === run.audio_id);
  const activeProcessing = processing && ACTIVE_PROCESSING.has(processing.status);
  const analysisStatus = metadata?.analysis_status ?? 'NOT_STARTED';
  const peakChannels = (peaksQuery.data?.channels ?? null) as JsonValue;
  const displayedTranscript = run.transcript ?? '';
  const playbackText = highlightedTranscript(displayedTranscript, currentSegments);

  /** 将当前选择的说话人连接修订和参数版本固定到独立阶段。 */
  const startDiarization = () => {
    if (!audio?.audio_version_id || !selectedModel || !selectedProfile) return message.warning('先选择说话人模型和参数版本');
    diarizationMutation.mutate({
      resource_id: selectedModel.id, revision_id: selectedModel.revision.id, profile_id: selectedProfile.id,
    });
  };

  /** 渲染当前行关联标签并显示可审计的人工归属控件。 */
  const renderAssignment = (segment: AsrTranscriptSegment) => {
    if (!segment.assignments.length) {
      return <Text type="secondary">{segment.native_speaker_id !== null ? `原生标签 ${segment.native_speaker_id}` : '未定位；未按文本长度推断归属'}</Text>;
    }
    return <Space direction="vertical" size={4}>
      {segment.assignments.map((assignment) => {
        const speaker = speakers.find((item) => item.id === assignment.speaker_id);
        const selected = assignment.speaker_id;
        return <Space key={assignment.id} wrap size={6}>
          <Tag color={assignment.source === 'MANUAL' ? 'green' : assignment.status === 'UNKNOWN' || assignment.status === 'UNALIGNED' ? 'default' : 'blue'}>
            {speaker?.display_name ?? (selected === null ? '未知' : `说话人 ${selected}`)} · {assignment.status}
          </Tag>
          <Select
            aria-label="确认说话人归属"
            size="small"
            style={{ minWidth: 135 }}
            value={selected}
            options={[{ value: null, label: '未知 / 无法确认' }, ...speakers.map((item) => ({ value: item.id, label: item.display_name }))]}
            onChange={(speakerId) => reviewMutation.mutate({
              assignmentId: assignment.id, expectedVersion: assignment.review_version, speakerId,
            })}
            loading={reviewMutation.isPending}
          />
          <Button size="small" icon={<CheckOutlined />} onClick={() => reviewMutation.mutate({
            assignmentId: assignment.id, expectedVersion: assignment.review_version, speakerId: selected,
          })}>确认</Button>
        </Space>;
      })}
    </Space>;
  };

  /** 汇总卡在窄屏收起，防止挤压转写与片段区域。 */
  const executionSummary = <div className="asr-execution-summary-content">
    <Space direction="vertical" style={{ display: 'flex' }} size="small">
      <div><Text type="secondary">转写</Text><div><Tag color={run.status === 'SUCCEEDED' ? 'green' : 'blue'}>{run.status}</Tag></div></div>
      <div><Text type="secondary">说话人分析</Text><div><Tag color={processing?.status === 'FAILED' ? 'red' : processing?.status === 'SUCCEEDED' ? 'green' : 'default'}>{processingLabel(processing)}</Tag></div></div>
      <div><Text type="secondary">模型 / 连接版本</Text><div>{workbench.model?.model_id ?? '未报告'} · v{workbench.model?.connection_version ?? '未报告'}</div></div>
      <div><Text type="secondary">请求参数版本</Text><div>{run.parameter_set_id ? `参数方案 ${run.parameter_set_id}` : '逐次请求快照'}</div></div>
      <div><Text type="secondary">运行耗时</Text><div>{run.duration_ms === null ? '未报告' : `${run.duration_ms} ms`}</div></div>
      <div><Text type="secondary">尝试次数</Text><div>{processing?.attempts ?? 0}</div></div>
      {run.error_message && <Alert type="warning" showIcon message="转写阶段提示" description={run.error_message} />}
      {processing?.error_message && <Alert type="error" showIcon message="说话人阶段失败" description={processing.error_message} />}
      {processing?.status === 'FAILED' && <Button icon={<ReloadOutlined />} loading={retryMutation.isPending} onClick={() => retryMutation.mutate()}>单独重试说话人阶段</Button>}
    </Space>
  </div>;

  return (
    <AsrFrame title={audio?.name ? `${audio.name} · ${workbench.model?.name ?? '模型运行'}` : '单模型音频工作台'}>
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Space wrap>
          <Tag color="blue">运行 #{run.id}</Tag>
          <Tag>音频版本 {audio?.content_version ? `v${audio.content_version}` : '不可用'}</Tag>
          <Tag>{workbench.model?.model_id ?? '模型未报告'}</Tag>
          <Text type="secondary">原始标签与人工确认分开保留；说话人名称只在本次结果内有效。</Text>
        </Space>
        <Space wrap>
          <Text>切换同音频模型</Text>
          <Select
            aria-label="切换当前转写模型"
            value={run.id}
            style={{ minWidth: 290 }}
            options={sameAudioRuns.map((item) => ({ value: item.id, label: `${item.role} · 运行 ${item.id} · ${item.status}` }))}
            onChange={(nextId) => navigate(`/console/asr/runs/${nextId}`)}
          />
          {relatedComparison && <Link to={`/console/asr/comparisons/${relatedComparison.id}`}><Button icon={<LinkOutlined />}>三方结果对比</Button></Link>}
          <Button icon={<DownloadOutlined />} loading={exportMutation.isPending} onClick={() => exportMutation.mutate('json')}>导出 JSON</Button>
          <Button icon={<DownloadOutlined />} loading={exportMutation.isPending} onClick={() => exportMutation.mutate('txt')}>导出 TXT</Button>
        </Space>
        {!audio?.version_available && <Alert type="warning" showIcon message="历史音频版本不可用" description="本次运行未绑定可信的固定音频版本，因此不自动切换到当前 URL，也不能启动说话人关联。" />}
        <Card size="small" title={<Space><SoundOutlined />统一音频播放器</Space>}>
          {audio ? <AudioWorkbenchPlayer
            src={audio.media_url}
            durationSeconds={audio.duration_seconds}
            audioRef={audioRef}
            peaks={peakChannels}
            onAudioInfo={() => setAudioInfoOpen(true)}
            onRequestParameters={() => setRequestOpen(true)}
            onTimeChange={onTimeChange}
          /> : <Empty description="音频原文件版本不可用，但转写全文仍可查看" />}
        </Card>
        <div className="asr-workbench-layout">
          <Card size="small" title="转写文本">
            <Space direction="vertical" style={{ display: 'flex' }} size="small">
              <Space wrap>
                <Select aria-label="转写展示模式" value={viewMode} style={{ width: 140 }} onChange={setViewMode} options={[
                  { value: 'FULL', label: '全文' }, { value: 'DIALOGUE', label: '对话片段' },
                ]} />
                <Select aria-label="说话人筛选" value={speakerFilter} style={{ width: 180 }} onChange={(value) => { setSpeakerFilter(value); setSegmentPage(1); }} options={speakerOptions} />
                <Input.Search allowClear placeholder="搜索转写片段" value={search} onChange={(event) => { setSearch(event.target.value); setSegmentPage(1); }} style={{ width: 220 }} />
                <Text type="secondary">{segmentsQuery.data?.total ?? run.segment_count} 个片段</Text>
              </Space>
              {viewMode === 'FULL' ? <Paragraph className="asr-workbench-transcript">{playbackText}</Paragraph> : (
                <div className="asr-workbench-list">
                  {segmentsQuery.isPending ? <Spin /> : segments.length ? segments.map((segment) => {
                    const active = currentSegments.some((item) => item.id === segment.id);
                    return <article key={segment.id} className={`asr-workbench-segment ${active ? 'is-active' : ''}`}>
                      <Space wrap>
                        {segment.start_ms === null || segment.end_ms === null
                          ? <Button type="link" disabled>未定位</Button>
                          : <Button type="link" onClick={() => seekTo(segment.start_ms, segment.end_ms)}>{formatMs(segment.start_ms)}–{formatMs(segment.end_ms)}</Button>}
                        {segment.native_speaker_id !== null && <Tag>原生 {segment.native_speaker_id}</Tag>}
                        {segment.confidence !== null && <Tag>模型置信度 {segment.confidence}</Tag>}
                      </Space>
                      <Paragraph className="asr-transcript-cell">{segment.text || '（空文本片段）'}</Paragraph>
                      {renderAssignment(segment)}
                    </article>;
                  }) : <Empty description="没有可靠时间戳的转写仍显示在全文中；当前筛选没有片段。" />}
                </div>
              )}
              {viewMode === 'DIALOGUE' && <Pagination size="small" current={segmentPage} pageSize={segmentsQuery.data?.page_size ?? 100} total={segmentsQuery.data?.total ?? 0} onChange={setSegmentPage} showSizeChanger={false} />}
              {!run.transcript && <Alert type="info" showIcon message="该运行没有返回完整转写文本" />}
              {viewMode === 'FULL' && !currentSegments.length && playbackTime > 0 && <Text type="secondary">当前播放时间没有对应的可靠转写片段。</Text>}
            </Space>
          </Card>

          <Card size="small" title={<Space><AudioOutlined />说话人片段</Space>}>
            {!resultId ? <Empty description="尚无说话人结果。选择已配置的独立分段接口后可启动后台分析。" /> : (
              <Space direction="vertical" style={{ display: 'flex' }} size="small">
                <Space wrap>
                  <Tag color="blue">{printable(speakersQuery.data?.summary.speaker_count ?? speakers.length)} 人</Tag>
                  <Tag>{printable(speakersQuery.data?.summary.turn_count ?? turnsQuery.data?.total ?? 0)} 段</Tag>
                  <Tag>未知 {printable(speakersQuery.data?.summary.unknown_turn_count ?? 0)}</Tag>
                  <Tag color="orange">重叠 {printable(speakersQuery.data?.summary.overlap_turn_count ?? 0)}</Tag>
                </Space>
                <Text type="secondary">发言时长按每人区间并集统计；不同人同时发言时总和可超过录音时长。</Text>
                <Space direction="vertical" style={{ display: 'flex' }} size={4}>
                  {speakers.map((speaker: AsrSpeaker) => <div className="asr-speaker-summary" key={speaker.id}>
                    <div><Text strong>{speaker.display_name}</Text> <Text type="secondary">原始标签 {speaker.source_label}{speaker.channel ? ` · 声道 ${speaker.channel}` : ''}</Text></div>
                    <Text type="secondary">{speaker.turn_count} 段 · {(speaker.speech_duration_ms / 1000).toFixed(1)} 秒</Text>
                    <Space.Compact block>
                      <Input
                        aria-label={`${speaker.display_name}新显示名`}
                        value={renameDrafts[speaker.id] ?? speaker.display_name}
                        onChange={(event) => setRenameDrafts((old) => ({ ...old, [speaker.id]: event.target.value }))}
                        maxLength={120}
                      />
                      <Button loading={renameMutation.isPending} onClick={() => renameMutation.mutate({
                        speakerId: speaker.id, displayName: (renameDrafts[speaker.id] ?? speaker.display_name).trim(),
                      })}>改名</Button>
                    </Space.Compact>
                  </div>)}
                </Space>
                <Select aria-label="说话人片段筛选" value={turnFilter} onChange={(value) => { setTurnFilter(value); setTurnPage(1); }} options={[
                  { value: 'ALL', label: '全部说话人区间' }, ...speakers.map((item: AsrSpeaker) => ({ value: String(item.id), label: item.display_name })),
                  { value: 'UNKNOWN', label: '未知归属' }, { value: 'OVERLAP', label: '重叠发言' },
                ]} />
                {turnsQuery.isPending ? <Spin /> : turns.length ? <div className="asr-workbench-list">
                  {turns.map((turn: AsrSpeakerTurn) => {
                    const active = activeTurns.some((item) => item.id === turn.id);
                    return <button type="button" key={turn.stable_id} className={`asr-turn-row ${active ? 'is-active' : ''}`} onClick={() => seekTo(turn.start_ms, turn.end_ms)}>
                      <Space wrap>
                        <Text strong>{formatMs(turn.start_ms)}–{formatMs(turn.end_ms)}</Text>
                        <Tag color={turn.speaker_id === null ? 'default' : 'purple'}>{turn.display_name ?? '未知说话人'}</Tag>
                        {turn.is_overlap && <Tag color="orange">重叠</Tag>}
                        {turn.channel && <Tag>声道 {turn.channel}</Tag>}
                        {turn.confidence !== null && <Tag>置信度 {turn.confidence}</Tag>}
                      </Space>
                      <Paragraph className="asr-transcript-cell">{turn.text ?? '模型仅返回说话人时间区间；此处没有文本'}</Paragraph>
                    </button>;
                  })}
                  <Pagination size="small" current={turnPage} pageSize={turnsQuery.data?.page_size ?? 100} total={turnsQuery.data?.total ?? 0} onChange={setTurnPage} showSizeChanger={false} />
                </div> : <Empty description="当前筛选下无说话人区间" />}
              </Space>
            )}
          </Card>

          <div className="asr-execution-summary asr-execution-summary-desktop">
            <Card size="small" title="执行概况">{executionSummary}</Card>
          </div>
          <div className="asr-execution-summary asr-execution-summary-compact">
            <Collapse items={[{ key: 'execution', label: '执行概况', children: executionSummary }]} />
          </div>
        </div>

        <Card size="small" title="独立说话人处理阶段">
          <Space direction="vertical" style={{ display: 'flex' }}>
            <Alert type="info" showIcon message="该阶段按音频版本去重，失败和重试均不重新提交三家 ASR。" description="如果转写没有可靠时间戳，只显示说话人时间轨并标注未对齐，不按字数或标点分配说话人。" />
            <Alert type="info" showIcon message="原生说话人标签与独立分段模型是不同能力来源"
              description="原生标签来自 ASR 响应；独立分段需要项目已授权的 DIARIZATION 模型、固定修订和参数方案。没有分段模型时，历史转写与原生标签仍可查看。" />
            {diarizationModelsQuery.isError && <Alert type="error" showIcon message="说话人模型清单读取失败，暂时不能启动独立分析" action={<Button size="small" onClick={() => void diarizationModelsQuery.refetch()}>重试</Button>} />}
            {!diarizationModelsQuery.isPending && !diarizationModelsQuery.isError && diarizationModels.length === 0 && <Alert type="warning" showIcon
              message="当前项目没有已授权的独立说话人模型"
              description={<>平台管理员需在模型中心配置 DIARIZATION 适配器、端点与凭据，声明分段、说话人 ID 等真实能力，建立参数方案并授权到此项目。<Link to="/console/model-center">查看模型配置入口说明</Link></>} />}
            {processing && <Text>最近阶段：{processingLabel(processing)} · 尝试 {processing.attempts} · {processing.error_message ?? '无错误信息'}</Text>}
            {resultId && <Text>说话人结果 #{resultId} · schema {workbench.diarization.schema_version ?? '未报告'} · 时间轴 {workbench.diarization.timeline ?? '未报告'} · 关联 v{workbench.diarization.fusion_version ?? '尚未关联'} ({workbench.diarization.fusion_status})</Text>}
            {processing?.status === 'FAILED' && <Button icon={<ReloadOutlined />} loading={retryMutation.isPending} onClick={() => retryMutation.mutate()}>重试说话人阶段</Button>}
            {resultId && !workbench.diarization.fusion_version_id && <Button icon={<LinkOutlined />} loading={fusionMutation.isPending} onClick={() => fusionMutation.mutate()}>关联到当前转写</Button>}
            {!resultId && <Space wrap>
              <Select
                aria-label="说话人模型"
                value={selectedResourceId}
                placeholder="选择已授权的说话人模型"
                style={{ minWidth: 300 }}
                options={diarizationModelOptions}
                onChange={(value: number) => {
                  setSelectedResourceId(value);
                  const model = diarizationModels.find((item: ModelAvailableResource) => item.id === value);
                  setSelectedProfileId(model?.profiles[0]?.id);
                }}
                loading={diarizationModelsQuery.isPending}
                notFoundContent={diarizationModelsQuery.isError ? '模型列表不可用，请重试' : '当前项目没有可用的说话人模型'}
              />
              {selectedModel && <Select
                aria-label="说话人参数方案版本"
                value={selectedProfileId}
                placeholder="选择参数方案版本"
                style={{ minWidth: 240 }}
                options={selectedModel.profiles.map((item) => ({ value: item.id, label: `${item.name} · v${item.version}` }))}
                onChange={setSelectedProfileId}
                notFoundContent="该模型修订没有参数方案"
              />}
              <Button type="primary" icon={<ReloadOutlined />} disabled={!audio?.version_available || !selectedModel || !selectedProfile || Boolean(activeProcessing)} loading={diarizationMutation.isPending} onClick={startDiarization}>启动说话人分析</Button>
              {diarizationModels.length === 0 && <Text type="secondary">没有可用的说话人模型，请联系平台管理员配置或授权。</Text>}
            </Space>}
            {!resultId && selectedProfile && <div className="asr-diarization-parameters">
              <Text strong>固定参数方案：{selectedProfile.name} · v{selectedProfile.version}</Text>
              {selectedProfile.definitions.length > 0 && <Text type="secondary">
                可调参数：{selectedProfile.definitions.map((item) => String(item.display_name ?? item.path ?? '')).filter(Boolean).join('、')}
              </Text>}
              <pre>{JSON.stringify(selectedProfile.values, null, 2)}</pre>
              <Text type="secondary">运行会固定模型连接修订与参数方案版本；密钥在后台加密保存，页面只显示非敏感参数。</Text>
            </div>}
            {!audio?.version_available && <Text type="secondary">当前历史运行缺少固定音频版本，不能将其错误关联到最新 URL。</Text>}
            {activeProcessing && <Space><Spin size="small" /><Text>后台阶段独立运行中；本页面按其自身状态恢复查询。</Text></Space>}
          </Space>
        </Card>
      </Space>

      <Drawer
        title="音频信息"
        open={audioInfoOpen}
        onClose={() => setAudioInfoOpen(false)}
        placement="right"
        width="min(680px, 92vw)"
        destroyOnClose={false}
        extra={<Button onClick={() => { void metadataQuery.refetch(); void peaksQuery.refetch(); }}>刷新</Button>}
      >
        <Paragraph type="secondary">原文件、后台分析与当前播放状态分别展示。打开此抽屉不会重置播放器。</Paragraph>
        {metadataQuery.isError && <ErrorState error={metadataQuery.error} onRetry={metadataQuery.refetch} />}
        <Title level={5}>来源与文件</Title>
        <Descriptions size="small" column={1} bordered>
          {Object.entries(metadata?.source_info ?? {}).map(([key, value]) => <Descriptions.Item key={key} label={audioFieldLabel('source', key)}>{printable(value)}</Descriptions.Item>)}
          {!metadata?.source_info && <Descriptions.Item label="状态">读取中或尚未提供</Descriptions.Item>}
        </Descriptions>
        <Title level={5} style={{ marginTop: 20 }}>原文件参数</Title>
        <Descriptions size="small" column={1} bordered>
          {Object.entries(metadata?.original_format ?? {}).map(([key, value]) => <Descriptions.Item key={key} label={audioFieldLabel('original', key)}>{printable(value)}</Descriptions.Item>)}
          {!Object.keys(metadata?.original_format ?? {}).length && <Descriptions.Item label="解析状态">{analysisStatus === 'NOT_STARTED' ? '尚未分析' : `未报告（${analysisStatus}）`}</Descriptions.Item>}
        </Descriptions>
        <Title level={5} style={{ marginTop: 20 }}>分析 PCM 与信号统计</Title>
        <Descriptions size="small" column={1} bordered>
          {[
            ...Object.entries(metadata?.analysis_pcm ?? {}).map(([key, value]) => ({ section: '分析 PCM', key, value })),
            ...Object.entries(metadata?.signal_statistics ?? {}).map(([key, value]) => ({ section: '信号统计', key, value })),
            ...Object.entries(metadata?.processed_range ?? {}).map(([key, value]) => ({ section: '处理范围', key, value })),
          ].map(({ section, key, value }) => <Descriptions.Item key={`${section}-${key}`} label={`${section} · ${audioFieldLabel('analysis', key)}`}>{printable(value)}</Descriptions.Item>)}
          {!metadata?.analysis_pcm && !Object.keys(metadata?.signal_statistics ?? {}).length && <Descriptions.Item label="分析数据">尚未生成；不从浏览器下载整条音频解码</Descriptions.Item>}
        </Descriptions>
        {(metadata?.warnings ?? []).map((warning, index) => <Alert key={index} type="warning" showIcon style={{ marginTop: 8 }} message={warning} />)}
        <Space style={{ marginTop: 12 }} wrap>
          <Tag color={analysisStatus === 'AVAILABLE' ? 'green' : analysisStatus === 'FAILED' || analysisStatus === 'UNAVAILABLE' ? 'orange' : 'default'}>分析状态：{analysisStatus}</Tag>
          {metadata?.processing_run && <Tag>任务 #{metadata.processing_run.id} · {processingLabel(metadata.processing_run)}</Tag>}
          <Button type="primary" disabled={!audio?.version_available || ['QUEUED', 'PENDING', 'SUBMITTING', 'REMOTE_RUNNING'].includes(analysisStatus)} loading={analysisMutation.isPending} onClick={() => analysisMutation.mutate()}>{analysisStatus === 'FAILED' ? '重新分析音频' : '分析音频'}</Button>
        </Space>
        <Title level={5} style={{ marginTop: 20 }}>当前播放状态</Title>
        <Descriptions size="small" column={1} bordered>
          {playbackFields.map((field) => <Descriptions.Item key={field.key} label={field.label}>{field.value}</Descriptions.Item>)}
        </Descriptions>
      </Drawer>

      <Drawer
        title="请求参数"
        open={requestOpen}
        onClose={() => setRequestOpen(false)}
        placement="right"
        width="min(640px, 92vw)"
        destroyOnClose={false}
      >
        <Alert type="info" showIcon message="这是本次转写提交的脱敏请求快照；音频文件采样率与请求中的模型参数是不同信息。" />
        <pre className="asr-json-snapshot">{JSON.stringify(redactSnapshot(run.request_snapshot), null, 2)}</pre>
      </Drawer>
    </AsrFrame>
  );
}
