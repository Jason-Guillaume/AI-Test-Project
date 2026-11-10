// 单模型音频工作台：固定到一个转写运行与音频版本，呈现原文、说话人区间和执行阶段。
import {
  Alert, App, Button, Card, Collapse, Descriptions, Drawer, Dropdown, Empty, Input, Pagination,
  Select, Space, Spin, Tag, Typography,
} from 'antd';
import {
  AudioOutlined, CheckOutlined, DownloadOutlined, DownOutlined, LinkOutlined, ReloadOutlined, SoundOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import { modelCenterApi, modelCenterQueryKeys, type ModelAvailableResource } from '@/features/model-configuration/api/modelCenter';
import type {
  AsrAudioMetadata, AsrProcessingRun, AsrSpeaker, AsrSpeakerTurn, AsrTranscriptSegment,
  AsrJob, AsrWorkbench, JsonValue,
} from '@/features/asr-evaluation/contracts';
import { AsrFrame } from './AsrFrame';
import { AudioWorkbenchPlayer } from '@/features/asr-evaluation/components/AudioWorkbenchPlayer';
import { shouldLookupPlaybackWindow } from '@/features/asr-evaluation/components/playbackSegmentPage.mjs';
import { fetchCompletePlaybackWindow } from '@/features/asr-evaluation/components/playbackSegmentWindow.mjs';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { ContentReviewPanel } from './ContentReviewPanel';
import { confirmDraftDiscard, useDraftNavigationGuard } from '@/features/asr-evaluation/useDraftNavigationGuard';
import { clearSpeakerDrafts, updateSpeakerNameDraft } from '@/features/asr-evaluation/speakerNameDraft.mjs';
import { modelSwitchOption } from '@/features/asr-evaluation/modelSwitchOption.mjs';

const { Text, Paragraph, Title } = Typography;

const ACTIVE_PROCESSING = new Set(['PENDING', 'SUBMITTING', 'REMOTE_RUNNING', 'RECONCILIATION_REQUIRED']);
const ACTIVE_ASR = new Set(['PENDING', 'SUBMITTING', 'REMOTE_RUNNING']);
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
  const wholeSeconds = Math.floor(value / 1000);
  const seconds = (wholeSeconds % 60).toString().padStart(2, '0');
  const minutes = Math.floor(wholeSeconds / 60);
  if (minutes >= 60) {
    return `${Math.floor(minutes / 60).toString().padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}:${seconds}`;
  }
  return `${minutes.toString().padStart(2, '0')}:${seconds}`;
}

/** JSON 评审文件使用分钟:秒显示；精确时间仍保存在 start/end 毫秒字段。 */
function formatExportTime(value: number): string {
  const seconds = Math.floor(Math.max(0, value) / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}

/** 导出模型原始 speaker 标签，纯数字标签转为数字以兼容示例格式。 */
function exportSpeakerLabel(value: string | null): number | string | null {
  if (value === null) return null;
  return /^\d+$/.test(value) ? Number(value) : value;
}

/** Ultra 等仅返回全文的模型按句末标点拆分供阅读；不伪造模型片段或时间戳。 */
function splitTranscriptForDisplay(transcript: string): string[] {
  const sentences: string[] = [];
  const endings = new Set(['。', '！', '？', '!', '?', '；', ';', '\n']);
  let current = '';
  for (const character of transcript) {
    current += character;
    if (endings.has(character)) {
      const sentence = current.trim();
      if (sentence) sentences.push(sentence);
      current = '';
    }
  }
  const remainder = current.trim();
  if (remainder) sentences.push(remainder);
  return sentences;
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

/** 给全文同时标记真实播放区间、全文命中与当前命中。 */
function highlightedTranscript(
  transcript: string,
  activeSegments: AsrTranscriptSegment[],
  search: string,
  currentSearchIndex: number,
): React.ReactNode {
  const codePoints = Array.from(transcript);
  const codePointOffsets = [0];
  codePoints.forEach((point) => codePointOffsets.push(codePointOffsets.at(-1)! + point.length));
  const spans = activeSegments
    .filter((item) => Number.isInteger(item.start_offset) && Number.isInteger(item.end_offset))
    .map((item) => [codePointOffsets[Math.min(codePoints.length, Math.max(0, item.start_offset!))],
      codePointOffsets[Math.min(codePoints.length, item.end_offset!)] ] as const)
    .filter(([start, end]) => end > start)
    .sort((left, right) => left[0] - right[0]);
  const searchRanges: Array<[number, number]> = [];
  const query = search.trim();
  if (query) {
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const matcher = new RegExp(escaped, 'giu');
    let match: RegExpExecArray | null;
    while ((match = matcher.exec(transcript)) !== null) {
      searchRanges.push([match.index, match.index + match[0].length]);
      if (!match[0].length) matcher.lastIndex += 1;
    }
  }
  if (!spans.length && !searchRanges.length) return transcript || '没有可显示的转写文本';
  const boundaries = [...new Set([0, transcript.length, ...spans.flat(), ...searchRanges.flat()])].sort((a, b) => a - b);
  const output: React.ReactNode[] = [];
  boundaries.slice(0, -1).forEach((start, index) => {
    const end = boundaries[index + 1];
    if (end <= start) return;
    const active = spans.some(([left, right]) => left < end && right > start);
    const searchIndex = searchRanges.findIndex(([left, right]) => left <= start && right >= end);
    const classes = [active ? 'asr-playback-highlight' : '', searchIndex >= 0 ? 'asr-search-hit' : '',
      searchIndex === currentSearchIndex ? 'asr-search-current' : ''].filter(Boolean).join(' ');
    const text = transcript.slice(start, end);
    if (classes) output.push(<mark className={classes} key={`text-${index}`} data-asr-search-hit={searchIndex >= 0 ? searchIndex : undefined}>{text}</mark>);
    else output.push(text);
  });
  return output;
}

/** 在全文中标出所有直接文本命中；只改变呈现，不重写原文或偏移。 */
function countSearchMatches(transcript: string, search: string): number {
  const query = search.trim();
  if (!query) return 0;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return Array.from(transcript.matchAll(new RegExp(escaped, 'giu'))).length;
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

function asrStatusLabel(status: string): string {
  return ({ PENDING: '排队中', SUBMITTING: '提交中', REMOTE_RUNNING: '识别中', SUCCEEDED: '已完成',
    FAILED: '失败', CANCELLED: '已取消', RECONCILIATION_REQUIRED: '状态待核实' } as Record<string, string>)[status] ?? status;
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
function RunWorkbench({ listenMode }: { listenMode: boolean }) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const returnToAudio = (location.state as { returnTo?: string } | null)?.returnTo;
  const queryClient = useQueryClient();
  const { runId: rawRunId } = useParams();
  const runId = Number(rawRunId);
  const validId = Number.isSafeInteger(runId) && runId > 0;
  const audioRef = useRef<HTMLAudioElement>(null);
  const playbackRangeEnd = useRef<number | null>(null);
  const lastAutoLocatedSegment = useRef<string | null>(null);
  const previousAudioVersion = useRef<number | null>(null);
  const [audioInfoOpen, setAudioInfoOpen] = useState(false);
  const [requestOpen, setRequestOpen] = useState(false);
  const [playbackTime, setPlaybackTime] = useState(0);
  const [playbackSnapshot, setPlaybackSnapshot] = useState<Record<string, string>>({});
  const [viewMode, setViewMode] = useState<'FULL' | 'DIALOGUE' | null>(listenMode ? 'DIALOGUE' : null);
  const [search, setSearch] = useState('');
  const [segmentPage, setSegmentPage] = useState(1);
  const [turnPage, setTurnPage] = useState(1);
  const [speakerFilter, setSpeakerFilter] = useState<string>('ALL');
  const [turnFilter, setTurnFilter] = useState<string>('ALL');
  const [selectedResourceId, setSelectedResourceId] = useState<number>();
  const [selectedProfileId, setSelectedProfileId] = useState<number>();
  const [renameDrafts, setRenameDrafts] = useState<Record<number, string>>({});
  const [speakerEditingOpen, setSpeakerEditingOpen] = useState(false);
  const [assignmentDrafts, setAssignmentDrafts] = useState<Record<number, number | null>>({});
  const [searchMatch, setSearchMatch] = useState(0);
  const hasDrafts = Object.keys(assignmentDrafts).length > 0 || Object.keys(renameDrafts).length > 0;
  useDraftNavigationGuard(hasDrafts);

  useEffect(() => {
    setViewMode(listenMode ? 'DIALOGUE' : null);
    setSegmentPage(1);
    setTurnPage(1);
    setSearch('');
    setSpeakerFilter('ALL');
    setTurnFilter('ALL');
    setAssignmentDrafts({});
    setRenameDrafts(clearSpeakerDrafts());
    setSpeakerEditingOpen(false);
    setSearchMatch(0);
    playbackRangeEnd.current = null;
    lastAutoLocatedSegment.current = null;
  }, [runId, listenMode]);
  useEffect(() => { setSearchMatch(0); }, [search]);

  // 运行编号全局唯一；先读所属项目，再使用该项目隔离其余查询，避免顶栏项目覆盖深链。
  const workbenchKey = ['asr', 'run-workbench', runId];
  const workbenchQuery = useQuery<AsrWorkbench>({
    queryKey: workbenchKey,
    enabled: validId,
    placeholderData: (previous) => previous,
    refetchInterval: (query) => ACTIVE_ASR.has(query.state.data?.run.status ?? '')
      || ACTIVE_PROCESSING.has(query.state.data?.diarization.processing_run?.status ?? '') ? 3000 : false,
    queryFn: async ({ signal }) => asrEvaluationApi.getRunWorkbench(runId, signal),
  });
  const workbench = workbenchQuery.data;
  const audio = workbench?.audio;
  const processing = workbench?.diarization.processing_run;
  const resultId = workbench?.diarization.result_id ?? null;
  const run = workbench?.run;
  const loadedRunId = run?.id ?? runId;
  useEffect(() => {
    if (audio?.audio_version_id == null) return;
    if (previousAudioVersion.current !== null && previousAudioVersion.current !== audio.audio_version_id) {
      playbackRangeEnd.current = null;
      audioRef.current?.pause();
      if (audioRef.current) audioRef.current.currentTime = 0;
      setPlaybackTime(0);
    }
    previousAudioVersion.current = audio.audio_version_id;
  }, [audio?.audio_version_id]);
  const queryScope = workbench?.run.project_id ?? null;
  const resourceKey = useMemo(() => queryScope
    ? asrQueryKeys.project(queryScope, 'run-workbench', loadedRunId)
    : ['asr', 'run-workbench', null, loadedRunId], [queryScope, loadedRunId]);

  const jobQuery = useQuery<AsrJob>({
    queryKey: [...resourceKey, 'job'], enabled: Boolean(run?.job_id),
    refetchInterval: (query) => {
      const job = query.state.data;
      const jobIsActive = ['QUEUED', 'RUNNING'].includes(job?.status ?? '');
      const runIsActive = job?.runs?.some((item) => ACTIVE_ASR.has(item.status)) ?? false;
      return jobIsActive || runIsActive ? 3000 : false;
    },
    queryFn: async ({ signal }) => asrEvaluationApi.getJob(run!.job_id, { signal, params: { include_text: false } }),
  });
  const diarizationModelsQuery = useQuery({
    queryKey: queryScope ? modelCenterQueryKeys.available(queryScope, 'DIARIZATION') : ['model-center', 'available', null, 'DIARIZATION'],
    enabled: Boolean(queryScope),
    queryFn: ({ signal }) => modelCenterApi.available(queryScope!, 'DIARIZATION', signal),
  });
  const diarizationModels = diarizationModelsQuery.data?.items ?? [];
  const segmentsFilter = useMemo(() => ({
    ...(speakerFilter.startsWith('native:') ? { native_speaker_id: speakerFilter.slice(7) } : {}),
    ...(speakerFilter.startsWith('linked:') ? { speaker_id: Number(speakerFilter.slice(7)) } : {}),
    ...(speakerFilter === 'UNKNOWN' ? { unknown_only: true } : {}),
    ...(speakerFilter === 'MIXED' ? { mixed_only: true } : {}),
    ...(search.trim() ? { search: search.trim() } : {}),
  }), [speakerFilter, search]);
  const segmentsKey = [...resourceKey, 'segments', segmentPage, segmentsFilter];
  const segmentsQuery = useQuery({
    queryKey: segmentsKey,
    enabled: Boolean(run),
    refetchInterval: () => ACTIVE_ASR.has(run?.status ?? '') ? 3000 : false,
    queryFn: async ({ signal }) => asrEvaluationApi.listRunSegments(loadedRunId, segmentPage, signal, segmentsFilter),
  });
  const segments = segmentsQuery.data?.items ?? [];
  const timedSegmentCount = segmentsQuery.data?.timed_segment_count;
  const timedLookupMs = Math.floor(playbackTime / 5) * 5000;
  const playbackSegmentsQuery = useQuery({
    queryKey: [...resourceKey, 'segment-window', timedLookupMs],
    enabled: shouldLookupPlaybackWindow(Boolean(run?.transcript), playbackTime, timedSegmentCount),
    staleTime: 5_000,
    gcTime: 0,
    queryFn: ({ signal }) => fetchCompletePlaybackWindow((page, requestSignal) =>
      asrEvaluationApi.listRunSegments(loadedRunId, page, requestSignal,
        { start_ms: timedLookupMs, end_ms: timedLookupMs + 5_000, page_size: 1000 }), signal),
  });
  const playbackSegments = (playbackSegmentsQuery.data?.items ?? []).filter((segment) =>
    segment.start_ms !== null && segment.end_ms !== null
      && segment.start_ms <= playbackTime * 1000 && segment.end_ms > playbackTime * 1000);
  const statisticsQuery = useQuery({
    queryKey: [...resourceKey, 'statistics'], enabled: Boolean(run),
    refetchInterval: () => ACTIVE_ASR.has(run?.status ?? '') ? 3000 : false,
    queryFn: ({ signal }) => asrEvaluationApi.getRunStatistics(loadedRunId, signal),
  });
  const artifactsKey = [...resourceKey, 'evaluation-artifacts'];
  const artifactsQuery = useQuery({
    queryKey: artifactsKey, enabled: Boolean(run),
    refetchInterval: () => ACTIVE_ASR.has(run?.status ?? '') ? 3000 : false,
    queryFn: ({ signal }) => asrEvaluationApi.listEvaluationArtifacts(loadedRunId, signal),
  });
  const reviewSummaryKey = useMemo(() => queryScope
    ? asrQueryKeys.project(queryScope, 'content_review', 'runs', loadedRunId)
    : ['asr', 'content_review', null, loadedRunId], [queryScope, loadedRunId]);
  const reviewSummaryQuery = useQuery({
    queryKey: reviewSummaryKey,
    enabled: Boolean(run && queryScope),
    queryFn: ({ signal }) => asrEvaluationApi.listContentReviews('runs', loadedRunId, signal),
    refetchInterval: (query) => query.state.data?.items.some((item) => ['QUEUED', 'RUNNING'].includes(item.status)) ? 3000 : false,
  });
  const speakersQuery = useQuery({
    queryKey: [...resourceKey, 'speakers', resultId], enabled: Boolean(resultId),
    refetchInterval: () => Boolean(processing && ACTIVE_PROCESSING.has(processing.status)) ? 3000 : false,
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
    refetchInterval: () => Boolean(processing && ACTIVE_PROCESSING.has(processing.status)) ? 3000 : false,
    queryFn: async ({ signal }) => asrEvaluationApi.listSpeakerTurns(resultId!, turnPage, signal, turnsFilter),
  });
  const turns = turnsQuery.data?.items ?? [];
  const previousRunStatus = useRef<{ id: number; status: string } | null>(null);
  const playbackLocationAbort = useRef<AbortController | null>(null);
  const observedRunId = run?.id;
  const observedRunStatus = run?.status;
  useEffect(() => {
    if (observedRunId == null || observedRunStatus == null) return;
    const previous = previousRunStatus.current;
    if (previous?.id === observedRunId && ACTIVE_ASR.has(previous.status) && !ACTIVE_ASR.has(observedRunStatus)) {
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'segments'] });
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'statistics'] });
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'evaluation-artifacts'] });
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'speakers'] });
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'speaker-turns'] });
      void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'job'] });
      void queryClient.invalidateQueries({ queryKey: reviewSummaryKey });
    }
    previousRunStatus.current = { id: observedRunId, status: observedRunStatus };
  }, [observedRunId, observedRunStatus, queryClient, resourceKey, reviewSummaryKey]);
  const nativeSegmentTotal = Math.max(workbench?.run.segment_count ?? 0, segmentsQuery.data?.total ?? 0);
  const effectiveViewMode = viewMode ?? (nativeSegmentTotal ? 'FULL' : 'DIALOGUE');
  useEffect(() => {
    if (effectiveViewMode !== 'DIALOGUE' || search.trim() || speakerFilter !== 'ALL') return;
    const activeSegment = playbackSegments[0];
    if (!activeSegment) {
      lastAutoLocatedSegment.current = null;
      return;
    }
    if (segmentsQuery.data?.items.some((item) => item.id === activeSegment.id)) {
      lastAutoLocatedSegment.current = activeSegment.id;
      playbackLocationAbort.current?.abort();
      playbackLocationAbort.current = null;
      return;
    }
    if (lastAutoLocatedSegment.current === activeSegment.id) return;
    lastAutoLocatedSegment.current = activeSegment.id;
    playbackLocationAbort.current?.abort();
    const controller = new AbortController();
    playbackLocationAbort.current = controller;
    void asrEvaluationApi.locateRunSegmentPage(loadedRunId, activeSegment.id, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || lastAutoLocatedSegment.current !== activeSegment.id) return;
        if (result.located_page && result.located_page > 0) setSegmentPage(result.located_page);
        else lastAutoLocatedSegment.current = null;
      })
      .catch(() => {
        if (!controller.signal.aborted && lastAutoLocatedSegment.current === activeSegment.id) lastAutoLocatedSegment.current = null;
      });
  }, [effectiveViewMode, playbackSegments, search, speakerFilter, segmentsQuery.data?.items, loadedRunId]);
  useEffect(() => () => playbackLocationAbort.current?.abort(), []);
  const displaySentences = useMemo(() => {
    const query = search.trim();
    return splitTranscriptForDisplay(workbench?.run.transcript ?? '')
      .filter((sentence) => !query || sentence.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  }, [workbench?.run.transcript, search]);
  const displaySentencePage = displaySentences.slice((segmentPage - 1) * 100, segmentPage * 100);

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
  const onTimeChange = useCallback((seconds: number) => {
    setPlaybackTime(seconds);
    const rangeEnd = playbackRangeEnd.current;
    const player = audioRef.current;
    if (rangeEnd !== null && player && seconds >= rangeEnd) {
      playbackRangeEnd.current = null;
      player.pause();
    }
  }, []);
  const clearPlaybackRange = useCallback(() => { playbackRangeEnd.current = null; }, []);
  /** 刷新工作台与关联读模型，保留播放器 DOM 和播放进度。 */
  const refreshWorkbench = () => {
    void queryClient.invalidateQueries({ queryKey: workbenchKey });
    void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'segments'] });
    void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'speakers'] });
    void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'speaker-turns'] });
    void queryClient.invalidateQueries({ queryKey: [...resourceKey, 'statistics'] });
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
    mutationFn: () => asrEvaluationApi.createSpeakerFusion(loadedRunId, resultId!),
    onSuccess: () => { message.success('同一音频版本的说话人结果已关联'); refreshWorkbench(); },
    onError: () => message.error('说话人结果与当前转写版本不匹配，未建立关联。'),
  });
  const reviewMutation = useMutation({
    mutationFn: (input: { assignmentId: number; expectedVersion: number; speakerId: number | null }) =>
      asrEvaluationApi.reviewSpeakerAssignment(input.assignmentId, {
        expected_version: input.expectedVersion, review_status: 'CONFIRMED', speaker_id: input.speakerId,
      }),
    onSuccess: (_data, variables) => {
      setAssignmentDrafts((current) => {
        const next = { ...current };
        delete next[variables.assignmentId];
        return next;
      });
      message.success('人工说话人确认已保存并留有版本记录');
      refreshWorkbench();
    },
    onError: () => message.error('人工确认保存失败；如版本冲突，请刷新片段后重试。'),
  });
  const renameMutation = useMutation({
    mutationFn: ({ speakerId, displayName }: { speakerId: number; displayName: string }) =>
      asrEvaluationApi.renameSpeaker(speakerId, displayName),
    onSuccess: (_result, variables) => {
      setRenameDrafts((current) => { const next = { ...current }; delete next[variables.speakerId]; return next; });
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
    mutationFn: (format: 'json' | 'txt') => asrEvaluationApi.exportRun(loadedRunId, format),
    onSuccess: (blob, format) => downloadBlob(blob, `asr-run-${loadedRunId}.${format}`),
    onError: () => message.error('导出失败；当前页面仍可查看识别结果。'),
  });
  const speakerJsonExportMutation = useMutation({
    mutationFn: async () => {
      if (!resultId || !workbench?.audio || !workbench.run) throw new Error('当前运行没有可导出的说话人结果');
      const firstPage = await asrEvaluationApi.listSpeakerTurns(resultId, 1);
      const pageSize = firstPage.page_size > 0 ? firstPage.page_size : 100;
      const pageCount = Math.ceil(firstPage.total / pageSize);
      const pages = [firstPage];
      for (let start = 2; start <= pageCount; start += 8) {
        const pageNumbers = Array.from({ length: Math.min(8, pageCount - start + 1) }, (_, index) => start + index);
        pages.push(...await Promise.all(pageNumbers.map((page) => asrEvaluationApi.listSpeakerTurns(resultId, page))));
      }
      const turns = pages.flatMap((page) => page.items);
      if (turns.length !== firstPage.total) throw new Error('分段分页读取不完整');
      const exportData = {
        schema_version: '1.0',
        time_unit: 'milliseconds',
        audio: {
          id: workbench.audio.id,
          name: workbench.audio.name,
          version: workbench.audio.content_version,
          duration_seconds: workbench.audio.duration_seconds,
        },
        transcription: {
          run_id: workbench.run.id,
          model_id: workbench.model?.model_id ?? null,
          text: workbench.run.transcript ?? '',
        },
        speaker_result: {
          result_id: resultId,
          processing_run_id: workbench.diarization.processing_run?.id ?? null,
          timeline: workbench.diarization.timeline,
          alignment_status: workbench.diarization.fusion_status,
        },
        sentences: turns.map((turn) => ({
          start: turn.start_ms,
          end: turn.end_ms,
          spk: exportSpeakerLabel(turn.source_speaker_id),
          text: turn.text ?? '',
          time: `${formatExportTime(turn.start_ms)}-${formatExportTime(turn.end_ms)}`,
        })),
      };
      return new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json;charset=utf-8' });
    },
    onSuccess: (blob) => downloadBlob(blob, `asr-run-${loadedRunId}-speaker-review.json`),
    onError: () => message.error('分段 JSON 导出失败；请确认说话人结果已完成后重试。'),
  });
  const artifactMutation = useMutation({
    mutationFn: () => asrEvaluationApi.createEvaluationArtifacts(loadedRunId),
    onSuccess: () => {
      message.success('已生成重新构建的评测快照和 Markdown');
      void queryClient.invalidateQueries({ queryKey: artifactsKey });
    },
    onError: () => message.error('评测资料生成失败，请检查运行状态与持久存储配置。'),
  });
  const artifactDownload = useMutation({
    mutationFn: (item: { id: number; kind: string }) => asrEvaluationApi.downloadEvaluationArtifact(item.id),
    onSuccess: (blob, item) => downloadBlob(blob, `asr-artifact-${item.id}.${item.kind === 'MARKDOWN' ? 'md' : 'json'}`),
    onError: () => message.error('评测资料无法读取或完整性校验失败。'),
  });

  useEffect(() => {
    const requested = new URLSearchParams(location.search).get('start_ms');
    if (requested === null || !/^\d+$/.test(requested)) return undefined;
    const audioElement = audioRef.current;
    const milliseconds = Number(requested);
    if (!audioElement || !Number.isSafeInteger(milliseconds)) return undefined;
    /** 证据深链只定位真实时间，播放须由用户主动触发。 */
    const seekEvidence = () => { playbackRangeEnd.current = null; audioElement.currentTime = milliseconds / 1000; };
    if (audioElement.readyState >= 1) seekEvidence();
    else {
      audioElement.addEventListener('loadedmetadata', seekEvidence, { once: true });
      // The player intentionally uses preload="none". A deep link must ask
      // the browser for metadata explicitly or this listener can wait forever.
      audioElement.load();
    }
    return () => audioElement.removeEventListener('loadedmetadata', seekEvidence);
  }, [location.search, audio?.media_url]);

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
    playbackRangeEnd.current = endMs !== null && endMs !== undefined && endMs > startMs ? endMs / 1000 : null;
    player.currentTime = Math.max(0, startMs / 1000);
    void player.play().catch(() => message.error('音频无法播放；请检查源文件是否可访问或格式是否受浏览器支持。'));
  };

  const currentSegments = playbackSegments;
  const activeTurns = turns.filter((turn) => turn.start_ms <= playbackTime * 1000 && turn.end_ms > playbackTime * 1000);
  const diarizationModelOptions = diarizationModels.map((item: ModelAvailableResource) => ({
    value: item.id, label: `${item.display_name} · ${item.revision.model_name} · v${item.revision.version} · ${(item.revision.capabilities ?? []).join('、') || '能力未声明'}`,
  }));
  const selectedModel = diarizationModels.find((item: ModelAvailableResource) => item.id === selectedResourceId);
  const selectedProfile = selectedModel?.profiles.find((item) => item.id === selectedProfileId);
  const speakerOptions = [
    { value: 'ALL', label: '全部归属' },
    ...(statisticsQuery.data?.speakers ?? []).map((item) => ({ value: `native:${item.native_speaker_id}`, label: `原生 ${item.native_speaker_id}` })),
    ...speakers.map((item: AsrSpeaker) => ({ value: `linked:${item.id}`, label: `关联 ${item.display_name}` })),
    { value: 'UNKNOWN', label: '未知归属' }, { value: 'MIXED', label: '混合 / 重叠' },
  ];
  const metadata = metadataQuery.data;
  const playbackFields = Object.entries(playbackSnapshot).map(([key, value]) => ({ key, label: ({
    duration: '播放器时长', current_time: '当前时间', state: '播放状态', playback_rate: '倍速', volume: '音量',
    muted: '静音', ready_state: 'readyState', network_state: 'networkState', buffered: '已缓冲范围',
    seekable: '可跳转范围', played: '已播放范围', media_error: '媒体错误',
  } as Record<string, string>)[key] ?? key, value }));

  if (!validId) return <AsrFrame title="单模型音频工作台"><Empty description="运行编号无效" /></AsrFrame>;
  if (workbenchQuery.isPending && !workbench) return <AsrFrame title="单模型音频工作台"><LoadingState /></AsrFrame>;
  if (workbenchQuery.isError && !workbench) return <AsrFrame title="单模型音频工作台"><ErrorState error={workbenchQuery.error} onRetry={workbenchQuery.refetch} /></AsrFrame>;
  if (!workbench || !run) return <AsrFrame title="单模型音频工作台"><Empty description="转写运行不存在" /></AsrFrame>;

  const sameAudioRuns = (jobQuery.data?.runs ?? []).filter((item) => item.audio_id === run.audio_id && item.audio_version_id === run.audio_version_id);
  const workbenchMatchesRoute = workbench.run.id === runId;
  const relatedComparison = (jobQuery.data?.comparisons ?? []).find((item) => item.audio_id === run.audio_id);
  const jobSnapshot = jobQuery.data?.config_snapshot as Parameters<typeof modelSwitchOption>[1];
  const activeProcessing = processing && ACTIVE_PROCESSING.has(processing.status);
  const displayMode = effectiveViewMode;
  const analysisStatus = metadata?.analysis_status ?? 'NOT_STARTED';
  const peakChannels = (peaksQuery.data?.channels ?? null) as JsonValue;
  const displayedTranscript = run.transcript ?? '';
  const searchMatchCount = countSearchMatches(displayedTranscript, search);
  const playbackText = highlightedTranscript(displayedTranscript, currentSegments, search, searchMatch);
  const moveSearchMatch = (direction: number) => {
    if (!searchMatchCount) return;
    const next = (searchMatch + direction + searchMatchCount) % searchMatchCount;
    setSearchMatch(next);
    requestAnimationFrame(() => document.querySelectorAll<HTMLElement>('[data-asr-search-hit]')[next]
      ?.scrollIntoView({ block: 'center', behavior: 'smooth' }));
  };

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
        const selected = Object.prototype.hasOwnProperty.call(assignmentDrafts, assignment.id)
          ? assignmentDrafts[assignment.id] : assignment.speaker_id;
        const dirty = Object.prototype.hasOwnProperty.call(assignmentDrafts, assignment.id)
          && assignmentDrafts[assignment.id] !== assignment.speaker_id;
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
            onChange={(speakerId) => setAssignmentDrafts((current) => {
              const next = { ...current };
              if (speakerId === assignment.speaker_id) delete next[assignment.id];
              else next[assignment.id] = speakerId;
              return next;
            })}
            loading={reviewMutation.isPending}
          />
          <Button size="small" icon={<CheckOutlined />}
            disabled={!dirty && assignment.review_status === 'CONFIRMED'} loading={reviewMutation.isPending}
            onClick={() => reviewMutation.mutate({
              assignmentId: assignment.id, expectedVersion: assignment.review_version, speakerId: selected,
            })}>{dirty ? '保存归属' : assignment.review_status === 'CONFIRMED' ? '已确认' : '确认归属'}</Button>
        </Space>;
      })}
    </Space>;
  };

  /** 汇总卡在窄屏收起，防止挤压转写与片段区域。 */
  const executionSummary = <div className="asr-execution-summary-content">
    <Space direction="vertical" style={{ display: 'flex' }} size="small">
      <div><Text type="secondary">转写</Text><div><Tag color={run.status === 'SUCCEEDED' ? 'green' : run.status === 'FAILED' ? 'red' : 'blue'}>{asrStatusLabel(run.status)}</Tag></div></div>
      <div><Text type="secondary">说话人分析</Text><div><Tag color={processing?.status === 'FAILED' ? 'red' : processing?.status === 'SUCCEEDED' ? 'green' : 'default'}>{processingLabel(processing)}</Tag></div></div>
      <div><Text type="secondary">模型 / 连接版本</Text><div>{workbench.model?.model_id ?? '未报告'} · v{workbench.model?.connection_version ?? '未报告'}</div></div>
      <div><Text type="secondary">请求参数版本</Text><div>{run.parameter_set_id ? `参数方案 ${run.parameter_set_id}` : '逐次请求快照'}</div></div>
      <div><Text type="secondary">ASR 请求耗时</Text><div>{run.duration_ms === null ? '未报告' : `${run.duration_ms} ms`}</div></div>
      <div><Text type="secondary">转写尝试次数</Text><div>未报告</div></div>
      <div><Text type="secondary">说话人尝试次数</Text><div>{processing?.attempts ?? '未报告'}</div></div>
      <div><Text type="secondary">LLM 内容评审</Text><div>{reviewSummaryQuery.data?.items[0]
        ? `${reviewSummaryQuery.data.items[0].status} · 尝试 ${reviewSummaryQuery.data.items[0].attempts} · ${reviewSummaryQuery.data.items[0].completed_chunks}/${reviewSummaryQuery.data.items[0].total_chunks} 块`
        : reviewSummaryQuery.isError ? '读取失败' : '尚未执行'}</div></div>
      <div><Text type="secondary">原生标签统计（完整结果）</Text><div>
        {statisticsQuery.isError ? '读取失败' : statisticsQuery.data
          ? `${statisticsQuery.data.character_count} 字符 · ${statisticsQuery.data.segment_count} 片段 · ${statisticsQuery.data.speaker_count} 人 · 未知 ${statisticsQuery.data.unknown_segment_count} 片段`
          : '加载中'}
      </div></div>
      {statisticsQuery.data?.speakers.map((item) => <div key={item.native_speaker_id}>
        原生 {item.native_speaker_id}：{item.timed_intervals ? `${(item.speech_duration_ms / 1000).toFixed(1)} 秒` : '无可靠时间'}
        {item.share !== null ? ` · ${(item.share * 100).toFixed(1)}%` : ''}
      </div>)}
      <Text type="secondary">时长按各原生标签的区间并集计算，重叠发言分别计入；标签仅在本次运行内有效。</Text>
      {resultId && <div><Text type="secondary">独立说话人结果（按该结果全量区间）</Text>
        {speakers.map((speaker: AsrSpeaker) => {
          const total = speakers.reduce((sum, item) => sum + item.speech_duration_ms, 0);
          return <div key={speaker.id}>{speaker.display_name}：{(speaker.speech_duration_ms / 1000).toFixed(1)} 秒
            {total > 0 ? ` · ${(speaker.speech_duration_ms / total * 100).toFixed(1)}%` : ' · 占比未知'}</div>;
        })}
      </div>}
      {statisticsQuery.data?.fusion_summary && <div><Text type="secondary">关联版本 v{statisticsQuery.data.fusion_summary.fusion_version}</Text><div>
        人工确认 {statisticsQuery.data.fusion_summary.manual_confirmed} · 未确认自动关联 {statisticsQuery.data.fusion_summary.automatic} ·
        原始状态未知 {statisticsQuery.data.fusion_summary.unknown} · 混合 {statisticsQuery.data.fusion_summary.mixed} · 重叠 {statisticsQuery.data.fusion_summary.overlap}
      </div><Text type="secondary">按关联记录计数；人工确认不推断发言时长。</Text></div>}
      {run.error_message && <Alert type="warning" showIcon message="转写阶段提示" description={run.error_message} />}
      {processing?.error_message && <Alert type="error" showIcon message="说话人阶段失败" description={processing.error_message} />}
      {processing?.status === 'FAILED' && <Button icon={<ReloadOutlined />} loading={retryMutation.isPending} onClick={() => retryMutation.mutate()}>单独重试说话人阶段</Button>}
    </Space>
  </div>;

  return (
    <AsrFrame title={audio?.name ?? '语音识别工作台'} projectId={run.project_id}>
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        {!workbenchMatchesRoute && <Alert type="info" showIcon message="正在切换到所选模型；原音频播放器保持当前播放位置。" />}
        {workbenchQuery.isError && <Alert type="warning" showIcon message="新模型结果读取失败；当前仍显示上一个模型的音频和结果。" action={<Button size="small" onClick={() => void workbenchQuery.refetch()}>重试</Button>} />}
        <Space wrap>
          <Tag color="blue">运行 #{run.id}</Tag>
          <Tag>音频版本 {audio?.content_version ? `v${audio.content_version}` : '不可用'}</Tag>
          <Tag color={run.status === 'SUCCEEDED' ? 'green' : run.status === 'FAILED' ? 'red' : 'blue'}>{asrStatusLabel(run.status)}</Tag>
          <Text type="secondary">{workbench.model?.name ?? workbench.model?.model_id ?? '模型未报告'} · 运行 #{run.id}</Text>
        </Space>
        <Space wrap className="asr-run-actions">
          <div className="asr-run-model-select">
          <Text>切换同音频模型</Text>
          <Select
            aria-label="切换当前转写模型"
            value={run.id}
            style={{ minWidth: 290 }}
            options={sameAudioRuns.map((item) => modelSwitchOption(item, jobSnapshot, asrStatusLabel))}
            onChange={(nextId) => {
              if (hasDrafts && !confirmDraftDiscard()) return;
              setAssignmentDrafts({});
              setRenameDrafts(clearSpeakerDrafts());
              navigate(`/console/asr/runs/${nextId}${listenMode ? '/listen' : ''}`, { state: location.state });
            }}
          />
          </div>
          <Link to={`/console/asr/runs/${run.id}${listenMode ? '' : '/listen'}`} state={location.state}><Button>{listenMode ? '完整工作台' : '收听'}</Button></Link>
          <Link to={`/console/asr/jobs/${run.job_id}`} state={returnToAudio ? { returnTo: returnToAudio } : undefined}><Button>返回批次</Button></Link>
          {returnToAudio && <Button onClick={() => navigate(returnToAudio)}>返回音频列表</Button>}
          {relatedComparison && <Link to={`/console/asr/comparisons/${relatedComparison.id}`} state={returnToAudio ? { returnTo: returnToAudio } : undefined}><Button icon={<LinkOutlined />}>三方结果对比</Button></Link>}
          <Button icon={<ReloadOutlined />} onClick={refreshWorkbench}>刷新</Button>
          <Button disabled={!run.transcript} onClick={() => {
            // 复制由明确用户手势触发；权限或非安全上下文失败时显示提示。
            if (!navigator.clipboard) { message.error('无法访问剪贴板，请手动选择文本复制。'); return; }
            void navigator.clipboard.writeText(run.transcript ?? '').then(() => message.success('全文已复制'))
              .catch(() => message.error('无法访问剪贴板，请手动选择文本复制。'));
          }}>复制全文</Button>
          <Dropdown menu={{ items: [
            { key: 'txt', label: '转写文本（TXT）' },
            { key: 'json', label: '运行数据（JSON）' },
            { key: 'speaker', label: '说话人分段（JSON）', disabled: !resultId },
          ], onClick: ({ key }) => key === 'speaker' ? speakerJsonExportMutation.mutate() : exportMutation.mutate(key as 'json' | 'txt') }}>
            <Button icon={<DownloadOutlined />} loading={exportMutation.isPending || speakerJsonExportMutation.isPending}>导出 <DownOutlined /></Button>
          </Dropdown>
        </Space>
        {!audio?.version_available && <Alert type="warning" showIcon message="历史音频版本不可用" description="本次运行未绑定可信的固定音频版本，因此不自动切换到当前 URL，也不能启动说话人关联。" />}
        <Card className="asr-sticky-player" size="small" title={<Space><SoundOutlined />音频播放</Space>}>
          {audio ? <AudioWorkbenchPlayer
            src={audio.media_url}
            durationSeconds={audio.duration_seconds}
            audioRef={audioRef}
            peaks={peakChannels}
            onAudioInfo={() => setAudioInfoOpen(true)}
            onRequestParameters={() => setRequestOpen(true)}
            onTimeChange={onTimeChange}
            onClearPlaybackRange={clearPlaybackRange}
          /> : <Empty description="音频原文件版本不可用，但转写全文仍可查看" />}
        </Card>
        <div className={`asr-workbench-layout${resultId ? ' has-speakers' : ''}`}>
          <Card size="small" title="转写文本">
            <Space direction="vertical" style={{ display: 'flex' }} size="small">
              <Space wrap>
                <Select aria-label="转写展示模式" value={displayMode} style={{ width: 140 }} onChange={setViewMode} options={[
                  { value: 'FULL', label: '全文' }, { value: 'DIALOGUE', label: nativeSegmentTotal ? '模型片段' : '按句查看' },
                ]} />
                {displayMode === 'DIALOGUE' && <Select aria-label="说话人筛选" value={speakerFilter} disabled={!nativeSegmentTotal} style={{ width: 180 }} onChange={(value) => { setSpeakerFilter(value); setSegmentPage(1); }} options={speakerOptions} />}
                <Input.Search allowClear placeholder={displayMode === 'FULL' ? '查找全文' : '筛选转写片段'} value={search}
                  onChange={(event) => { setSearch(event.target.value); setSegmentPage(1); setSearchMatch(0); }} style={{ width: 220 }} />
                <Text type="secondary">{nativeSegmentTotal ? `${nativeSegmentTotal} 个模型片段` : `${displaySentences.length} 个展示分句`}</Text>
              </Space>
              {displayMode === 'FULL' && search.trim() && <Space wrap>
                <Button size="small" disabled={!searchMatchCount} onClick={() => moveSearchMatch(-1)}>上一个匹配</Button>
                <Button size="small" disabled={!searchMatchCount} onClick={() => moveSearchMatch(1)}>下一个匹配</Button>
                <Text type="secondary">{searchMatchCount ? `当前第 ${searchMatch % searchMatchCount + 1} / ${searchMatchCount} 处` : '全文没有匹配内容'}</Text>
              </Space>}
              {Object.keys(assignmentDrafts).length > 0 && <Alert type="warning" showIcon
                message={`有 ${Object.keys(assignmentDrafts).length} 项说话人归属尚未保存；草稿会保留在当前运行中。`} />}
              {displayMode === 'FULL' ? <>
                <Paragraph className="asr-workbench-transcript">{playbackText}</Paragraph>
                {playbackTime > 0 && playbackSegmentsQuery.isPending && <Text type="secondary">正在定位当前播放位置…</Text>}
                {playbackTime > 0 && playbackSegmentsQuery.isError && <Text type="danger">播放位置定位失败；全文仍可阅读和搜索。</Text>}
                {playbackTime > 0 && timedSegmentCount === 0 && <Text type="secondary">此运行没有可靠时间戳，无法按播放位置高亮。</Text>}
                {playbackTime > 0 && timedSegmentCount !== undefined && timedSegmentCount > 0
                  && playbackSegmentsQuery.data && !playbackSegments.length && <Text type="secondary">
                  当前播放时间没有对应的转写片段。
                </Text>}
              </> : (
                <div className="asr-workbench-list">
                  {segmentsQuery.isError ? <ErrorState error={segmentsQuery.error} onRetry={segmentsQuery.refetch} /> : segmentsQuery.isPending ? <Spin /> : nativeSegmentTotal ? segments.length ? segments.map((segment) => {
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
                  }) : <Empty description="当前筛选下没有模型片段。" /> : displaySentencePage.length ? <>
                    <Alert
                      type="info"
                      showIcon
                      message="当前 ASR 只返回全文；此处按句末标点拆分，便于阅读，不代表模型原生片段，也不含时间戳或说话人标签。时间和说话人见右侧独立分段结果。"
                    />
                    {displaySentencePage.map((sentence, index) => (
                      <article key={`display-sentence-${(segmentPage - 1) * 100 + index}`} className="asr-workbench-segment">
                        <Space wrap>
                          <Tag color="blue">展示分句 {(segmentPage - 1) * 100 + index + 1}</Tag>
                          <Text type="secondary">按原文顺序</Text>
                        </Space>
                        <Paragraph className="asr-transcript-cell">{sentence}</Paragraph>
                      </article>
                    ))}
                  </> : <Empty description="没有匹配的分句。" />}
                </div>
              )}
              {displayMode === 'DIALOGUE' && <Pagination size="small" current={segmentPage} pageSize={nativeSegmentTotal ? (segmentsQuery.data?.page_size ?? 100) : 100} total={nativeSegmentTotal ? (segmentsQuery.data?.total ?? nativeSegmentTotal) : displaySentences.length} onChange={setSegmentPage} showSizeChanger={false} />}
              {!run.transcript && <Alert type="info" showIcon message="该运行没有返回完整转写文本" />}
            </Space>
          </Card>

          {resultId && <Card size="small" title={<Space><AudioOutlined />说话人片段</Space>}>
            {speakersQuery.isError ? <ErrorState error={speakersQuery.error} onRetry={speakersQuery.refetch} /> : speakersQuery.isPending ? <Spin /> : (
              <Space direction="vertical" style={{ display: 'flex' }} size="small">
                <Space wrap>
                  <Tag color="blue">{speakersQuery.data?.summary.speaker_count ?? speakers.length} 人</Tag>
                  <Tag>{speakersQuery.data?.summary.turn_count ?? (turnsQuery.isError ? '读取失败' : turnsQuery.data?.total ?? '加载中')} 段</Tag>
                  <Tag>未知 {speakersQuery.data?.summary.unknown_turn_count ?? '未报告'}</Tag>
                  <Tag color="orange">重叠 {speakersQuery.data?.summary.overlap_turn_count ?? '未报告'}</Tag>
                </Space>
                <Text type="secondary">发言时长按每人区间并集统计；不同人同时发言时总和可超过录音时长。</Text>
                <Space direction="vertical" style={{ display: 'flex' }} size={4}>
                  {speakers.map((speaker: AsrSpeaker) => <div className="asr-speaker-summary" key={speaker.id}>
                    <div><Text strong>{speaker.display_name}</Text> <Text type="secondary">原始标签 {speaker.source_label}{speaker.channel ? ` · 声道 ${speaker.channel}` : ''}</Text></div>
                    <Text type="secondary">{speaker.turn_count} 段 · {(speaker.speech_duration_ms / 1000).toFixed(1)} 秒</Text>
                  </div>)}
                </Space>
                <Button size="small" onClick={() => setSpeakerEditingOpen((open) => !open)}>
                  {speakerEditingOpen ? '收起名称编辑' : '编辑说话人名称'}
                </Button>
                {speakerEditingOpen && <Space direction="vertical" style={{ display: 'flex' }}>
                  {speakers.map((speaker: AsrSpeaker) => <Space.Compact block key={`rename-${speaker.id}`}>
                    <Input aria-label={`${speaker.display_name}新显示名`}
                      value={renameDrafts[speaker.id] ?? speaker.display_name} maxLength={120}
                      onChange={(event) => setRenameDrafts((old) =>
                        updateSpeakerNameDraft(old, speaker.id, event.target.value, speaker.display_name))} />
                    <Button loading={renameMutation.isPending} onClick={() => renameMutation.mutate({
                      speakerId: speaker.id, displayName: (renameDrafts[speaker.id] ?? speaker.display_name).trim(),
                    })}>保存名称</Button>
                  </Space.Compact>)}
                </Space>}
                <Select aria-label="说话人片段筛选" value={turnFilter} onChange={(value) => { setTurnFilter(value); setTurnPage(1); }} options={[
                  { value: 'ALL', label: '全部说话人区间' }, ...speakers.map((item: AsrSpeaker) => ({ value: String(item.id), label: item.display_name })),
                  { value: 'UNKNOWN', label: '未知归属' }, { value: 'OVERLAP', label: '重叠发言' },
                ]} />
                {turnsQuery.isError ? <ErrorState error={turnsQuery.error} onRetry={turnsQuery.refetch} /> : turnsQuery.isPending ? <Spin /> : turns.length ? <div className="asr-workbench-list">
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
          </Card>}
        </div>

        <Collapse items={[{ key: 'execution', label: '运行详情', children: executionSummary }]} />

        {!listenMode && <Collapse items={[{ key: 'artifacts', label: '评测文件与来源详情', children: <Card size="small" title="评测资料">
          <Space direction="vertical" style={{ display: 'flex' }}>
            <Text type="secondary">快照和 Markdown 根据当前保存的规范化结果重新生成，不代表当时 Provider 的原始响应。</Text>
            {artifactsQuery.isError && <Text type="danger">产物列表读取失败。</Text>}
            {artifactsQuery.data && !artifactsQuery.data.raw_response_available && <Text type="secondary">当时的 ASR 响应未留存。</Text>}
            <Button disabled={run.status !== 'SUCCEEDED'} loading={artifactMutation.isPending} onClick={() => artifactMutation.mutate()}>生成评测快照与 Markdown</Button>
            {(artifactsQuery.data?.items ?? []).map((item) => <Space key={item.id} wrap>
              <Text>{item.kind === 'MARKDOWN' ? 'Markdown' : item.kind === 'SNAPSHOT_JSON' ? '规范化 JSON' : item.kind} #{item.id}</Text>
              <Tag>{item.status}</Tag><Text type="secondary">{item.schema_version} · {item.byte_size} 字节 · SHA-256 {item.sha256}</Text>
              {item.redaction_version && <Text type="secondary">响应脱敏策略 {item.redaction_version} · {item.redacted ? '内容已脱敏' : '未发生替换'}</Text>}
              <Button size="small" disabled={item.status !== 'READY'} loading={artifactDownload.isPending} onClick={() => artifactDownload.mutate(item)}>下载</Button>
            </Space>)}
          </Space>
        </Card> }]} />}
        {!listenMode && <Collapse items={[{ key: 'content-review', label: '内容评审', children: <ContentReviewPanel kind="runs" resourceId={run.id} projectId={run.project_id} /> }]} />}
        {!listenMode && <Collapse
          defaultActiveKey={resultId ? ['speaker-details'] : []}
          items={[{ key: 'speaker-details', label: resultId ? '说话人分析与证据' : '添加说话人分析', children: <Space direction="vertical" style={{ display: 'flex' }}>
            <Alert type="info" showIcon message="该阶段按音频版本去重，失败和重试均不重新提交三家 ASR。" description="如果转写没有可靠时间戳，只显示说话人时间轨并标注未对齐，不按字数或标点分配说话人。" />
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
          </Space> }]} />}
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

/** 打开完整运行工作台；数据加载及错误态由工作台统一处理。 */
export function RunWorkbenchPage() {
  return <RunWorkbench listenMode={false} />;
}

/** 打开同一运行的收听视图，复用播放器、片段同步和资源授权。 */
export function RunListenPage() {
  return <RunWorkbench listenMode />;
}
