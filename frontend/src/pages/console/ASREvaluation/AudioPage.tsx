// 音频资产列表：项目隔离、版本追踪、试听与标准答案绑定都使用真实服务端能力。
import {
  Alert, App, Button, Descriptions, Drawer, Dropdown, Empty, Flex, Form, Input, Modal, Select,
  Progress, Space, Table, Tag, Typography, Upload,
} from 'antd';
import {
  InboxOutlined, MoreOutlined, PlayCircleOutlined,
  PlusOutlined, ReloadOutlined, UploadOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import { formatAudioDuration, groundTruthUiState, parsePastedAudioRecords, recentRunUiState } from '@/features/asr-evaluation/audioAssetUi.mjs';
import { funasrTuningApi } from '@/features/asr-evaluation/api/funasrTuning';
import type { FunAsrGroundTruth } from '@/features/asr-evaluation/api/funasrTuning';
import type { AsrAudio, JsonValue } from '@/features/asr-evaluation/contracts';
import { AsrFrame } from './AsrFrame';
import { useLocation, useNavigate } from 'react-router-dom';

interface AudioFormValues {
  name: string;
  url: string;
  batch_text?: string;
}
type AudioFormMode = 'CREATE' | 'IMPORT' | 'EDIT';
type GroundTruthStatus = 'ALL' | 'BOUND' | 'UNBOUND';
type RecentRun = {
  audio_id: number;
  run_id: number;
  job_id: number;
  audio_version_id: number | null;
  audio_version: number | null;
  status: string;
  run_status: string;
  created_at: string;
};
type BatchCheckResult =
  | { audioId: number; ok: true; availability: string; audioSource: string; platformAccess: string; httpStatus: number | null }
  | { audioId: number; ok: false; error: string };
type GroundTruthPreviewRow = { key: number; start: number; end: number; speaker: string; text: string };
type AudioCheckState = { audioId: number; projectId: number } | null;

const SAMPLE_JSON_MAPPING: Record<string, unknown> = {
  text_source: 'segments',
  segments_pointer: '',
  segment_text_pointer: '/text',
  start_pointer: '/start',
  end_pointer: '/end',
  speaker_pointer: '/spk',
  time_unit: 'ms',
};

function validateSampleJson(document: JsonValue): asserts document is JsonValue[] {
  if (!Array.isArray(document) || document.length === 0) {
    throw new Error('样例 JSON 须为非空数组，每段包含 start、end、spk、text 字段');
  }
  const invalidIndex = document.findIndex((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return true;
    const row = item as Record<string, JsonValue>;
    return typeof row.text !== 'string'
      || typeof row.start !== 'number' || !Number.isFinite(row.start) || row.start < 0
      || typeof row.end !== 'number' || !Number.isFinite(row.end) || row.end <= row.start
      || (typeof row.spk !== 'number' && typeof row.spk !== 'string' && row.spk !== null);
  });
  if (invalidIndex >= 0) {
    throw new Error('第 ' + (invalidIndex + 1) + ' 段格式无效；需要有效的 start/end、spk 和 text 字段');
  }
}

function previewSegments(document: JsonValue[]): GroundTruthPreviewRow[] {
  return document.slice(0, 5).map((item, index) => {
    const row = item as Record<string, JsonValue>;
    return {
      key: index,
      start: row.start as number,
      end: row.end as number,
      speaker: row.spk == null ? '—' : String(row.spk),
      text: row.text as string,
    };
  });
}

function safeDisplayUrl(value: string): string {
  try {
    const parsed = new URL(value);
    return parsed.origin + parsed.pathname;
  } catch {
    return 'URL 格式无效';
  }
}

function availabilityLabel(value: string): { label: string; color: string } {
  if (value === 'AVAILABLE') return { label: '可访问', color: 'success' };
  if (value === 'PLATFORM_DENIED') return { label: '出站未授权', color: 'error' };
  if (value === 'UNREACHABLE') return { label: '源不可达', color: 'error' };
  return { label: '待检查', color: 'default' };
}

function runStatusLabel(value: string): { label: string; color: string } {
  const statuses: Record<string, { label: string; color: string }> = {
    QUEUED: { label: '排队中', color: 'processing' },
    RUNNING: { label: '运行中', color: 'processing' },
    PENDING: { label: '排队中', color: 'processing' },
    SUBMITTING: { label: '提交中', color: 'processing' },
    REMOTE_RUNNING: { label: '运行中', color: 'processing' },
    SUCCEEDED: { label: '成功', color: 'success' },
    COMPLETED: { label: '完成', color: 'success' },
    PARTIAL_FAILED: { label: '部分失败', color: 'warning' },
    FAILED: { label: '失败', color: 'error' },
    CANCELLED: { label: '已取消', color: 'default' },
    RECONCILIATION_REQUIRED: { label: '状态待核实', color: 'warning' },
  };
  return statuses[value] ?? { label: value || '状态未知', color: 'default' };
}

function checkResultLabel(result: BatchCheckResult): string {
  if (!result.ok) return result.error;
  if (result.platformAccess === 'DENIED') return '项目出站策略未授权';
  if (result.audioSource === 'HEAD_NOT_SUPPORTED') return '音频源不支持 HEAD，保留为待检查';
  if (result.audioSource === 'REACHABLE') return '音频源可访问';
  if (result.audioSource === 'HTTP_ERROR') return '音频源返回 HTTP ' + (result.httpStatus ?? '错误');
  if (result.audioSource === 'NETWORK_ERROR') return '网络检查失败，状态未知';
  return '状态：' + result.availability;
}

/** 音频列表仅播放经服务端项目权限校验的同源媒体流，不会因此创建识别任务。 */
export function AudioPage() {
  const { message } = App.useApp();
  const { currentProjectId } = useConsoleScope();
  const activeProjectRef = useRef(currentProjectId);
  activeProjectRef.current = currentProjectId;
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<AudioFormValues>();
  const [open, setOpen] = useState(false);
  const listParams = new URLSearchParams(location.search);
  const page = Math.max(1, Number(listParams.get('page')) || 1);
  const requestedPageSize = Number(listParams.get('page_size')) || 20;
  const pageSize = [10, 20, 50, 100].includes(requestedPageSize) ? requestedPageSize : 20;
  const keyword = listParams.get('q')?.trim() ?? '';
  const [keywordInput, setKeywordInput] = useState(() => listParams.get('q') ?? '');
  const requestedAvailability = listParams.get('availability') ?? '';
  const availabilityFilter = ['AVAILABLE', 'UNKNOWN', 'UNREACHABLE', 'PLATFORM_DENIED'].includes(requestedAvailability)
    ? requestedAvailability : '';
  const requestedGroundTruth = listParams.get('ground_truth');
  const groundTruthFilter: GroundTruthStatus = requestedGroundTruth === 'BOUND' || requestedGroundTruth === 'UNBOUND'
    ? requestedGroundTruth : 'ALL';
  const [selectedAudioIds, setSelectedAudioIds] = useState<number[]>([]);
  const [selectedAudioLabels, setSelectedAudioLabels] = useState<Record<number, string>>({});
  const [formMode, setFormMode] = useState<AudioFormMode>('CREATE');
  const [batchInput, setBatchInput] = useState('');
  const [editingAudio, setEditingAudio] = useState<AsrAudio | null>(null);
  const [selectedAudio, setSelectedAudio] = useState<AsrAudio | null>(null);
  const [groundTruthAudio, setGroundTruthAudio] = useState<AsrAudio | null>(null);
  const [groundTruthFile, setGroundTruthFile] = useState<File | null>(null);
  const [groundTruthDocument, setGroundTruthDocument] = useState<JsonValue | null>(null);
  const [groundTruthReadError, setGroundTruthReadError] = useState('');
  const [groundTruthReading, setGroundTruthReading] = useState(false);
  const [groundTruthPreview, setGroundTruthPreview] = useState<FunAsrGroundTruth | null>(null);
  const [mediaError, setMediaError] = useState(false);
  const [mediaWaiting, setMediaWaiting] = useState(false);
  const [batchChecking, setBatchChecking] = useState(false);
  const [batchCheckProgress, setBatchCheckProgress] = useState<{ total: number; completed: number } | null>(null);
  const [batchCheckResults, setBatchCheckResults] = useState<BatchCheckResult[] | null>(null);
  const [audioCheckId, setAudioCheckId] = useState<AudioCheckState>(null);
  const mediaAudioRef = useRef<HTMLAudioElement>(null);
  const batchCheckGeneration = useRef(0);
  const groundTruthReadGeneration = useRef(0);
  const previousProjectId = useRef(currentProjectId);

  const updateListQuery = useCallback((updates: Record<string, string | number | undefined>) => {
    const params = new URLSearchParams(location.search);
    const defaults: Record<string, string> = { page: '1', page_size: '20', q: '', availability: '', ground_truth: 'ALL' };
    for (const [key, value] of Object.entries(updates)) {
      if (value === undefined || String(value) === defaults[key]) params.delete(key);
      else params.set(key, String(value));
    }
    const search = params.toString();
    navigate({ pathname: location.pathname, search: search ? '?' + search : '' }, {
      replace: true,
      state: location.state,
    });
  }, [location.pathname, location.search, location.state, navigate]);

  const audioListReturnTo = useCallback(() => {
    const params = new URLSearchParams(location.search);
    const pendingKeyword = keywordInput.trim();
    if (pendingKeyword) params.set('q', pendingKeyword);
    else params.delete('q');
    const search = params.toString();
    return location.pathname + (search ? '?' + search : '');
  }, [keywordInput, location.pathname, location.search]);

  const batchPreview = useMemo(() => {
    if (!batchInput.trim()) return { records: [] as Array<{ name: string; url: string }>, error: '' };
    try { return { records: parsePastedAudioRecords(batchInput), error: '' }; }
    catch (error) {
      return { records: [] as Array<{ name: string; url: string }>, error: error instanceof Error ? error.message : '粘贴内容格式无效' };
    }
  }, [batchInput]);

  useEffect(() => {
    const nextKeyword = keywordInput.trim();
    if (nextKeyword === keyword) return undefined;
    const timer = window.setTimeout(() => updateListQuery({ q: nextKeyword || undefined, page: undefined }), 300);
    return () => window.clearTimeout(timer);
  }, [keywordInput, keyword, updateListQuery]);

  useEffect(() => {
    setKeywordInput(new URLSearchParams(location.search).get('q') ?? '');
  }, [location.search]);

  useEffect(() => {
    if (previousProjectId.current !== null && previousProjectId.current !== currentProjectId) {
      setKeywordInput('');
      navigate({ pathname: location.pathname, search: '' }, { replace: true, state: location.state });
    }
    previousProjectId.current = currentProjectId;
  }, [currentProjectId, location.pathname, location.state, navigate]);

  useEffect(() => {
    batchCheckGeneration.current += 1;
    groundTruthReadGeneration.current += 1;
    setSelectedAudioIds([]);
    setSelectedAudioLabels({});
    setOpen(false);
    setEditingAudio(null);
    setBatchInput('');
    setSelectedAudio(null);
    setGroundTruthAudio(null);
    setGroundTruthFile(null);
    setGroundTruthDocument(null);
    setGroundTruthReadError('');
    setGroundTruthPreview(null);
    setBatchCheckResults(null);
    setBatchCheckProgress(null);
    setBatchChecking(false);
    setGroundTruthReading(false);
    setAudioCheckId(null);
    setMediaError(false);
    form.resetFields();
  }, [currentProjectId, form]);

  const audioKey = currentProjectId
    ? asrQueryKeys.project(currentProjectId, 'audio', page, pageSize, keyword, availabilityFilter, groundTruthFilter)
    : ['asr', 'audio', null, page, pageSize, keyword, availabilityFilter, groundTruthFilter];
  const audioQuery = useQuery({
    queryKey: audioKey,
    enabled: Boolean(currentProjectId),
    queryFn: ({ signal }) => asrEvaluationApi.listAudios(
      currentProjectId!, page, pageSize, signal, keyword,
      { availability: availabilityFilter, groundTruthStatus: groundTruthFilter === 'ALL' ? undefined : groundTruthFilter },
    ),
  });
  const audioRows = audioQuery.data?.items ?? [];
  const audioIds = audioRows.map((item) => item.id);
  const recentRunsQuery = useQuery({
    queryKey: currentProjectId
      ? asrQueryKeys.project(currentProjectId, 'audio-recent-runs', audioIds)
      : ['asr', 'audio-recent-runs', null],
    enabled: Boolean(currentProjectId && audioIds.length),
    queryFn: ({ signal }) => asrEvaluationApi.getRecentAudioRuns(currentProjectId!, audioIds, signal),
  });
  const recentRuns = useMemo(
    () => new Map((recentRunsQuery.data?.items ?? []).map((item) => [item.audio_id, item as RecentRun])),
    [recentRunsQuery.data?.items],
  );
  const groundTruthQuery = useQuery({
    queryKey: currentProjectId
      ? asrQueryKeys.project(currentProjectId, 'funasr-ground-truth')
      : ['asr', 'funasr-ground-truth', null],
    enabled: Boolean(currentProjectId),
    queryFn: () => funasrTuningApi.groundTruth(currentProjectId!),
  });
  const groundTruthByAudioId = useMemo(
    () => new Map((groundTruthQuery.data?.items ?? []).map((item) => [item.audio_id, item])),
    [groundTruthQuery.data?.items],
  );
  const stagedSegments = Array.isArray(groundTruthDocument) ? groundTruthDocument : [];

  const importMutation = useMutation({
    mutationFn: async ({ values, projectId, mode, audio }: {
      values: AudioFormValues; projectId: number | null; mode: AudioFormMode; audio: AsrAudio | null;
    }) => {
      if (mode === 'EDIT' && audio) {
        await asrEvaluationApi.updateAudio(audio.id, {
          name: values.name, url: values.url?.trim() || undefined,
        });
        return { kind: 'EDIT' as const, count: 1 };
      }
      if (!projectId) throw new Error('请先选择项目');
      if (mode === 'IMPORT') {
        const items = parsePastedAudioRecords(values.batch_text ?? '');
        const result = await asrEvaluationApi.importAudios(projectId, items);
        return { kind: 'IMPORT' as const, count: result.items.length };
      }
      const result = await asrEvaluationApi.importAudios(projectId, [{
        name: values.name.trim(), url: values.url.trim(),
      }]);
      return { kind: 'CREATE' as const, count: result.items.length };
    },
    onSuccess: ({ kind, count }, variables) => {
      if (variables.projectId !== activeProjectRef.current) return;
      message.success(kind === 'EDIT' ? '音频资源已更新' : '已加入 ' + count + ' 条音频链接');
      setOpen(false);
      setEditingAudio(null);
      setBatchInput('');
      form.resetFields();
      if (kind !== 'EDIT') {
        setKeywordInput('');
        updateListQuery({ page: undefined, page_size: undefined, q: undefined, availability: undefined, ground_truth: undefined });
      }
      if (variables.projectId) {
        void queryClient.invalidateQueries({ queryKey: asrQueryKeys.project(variables.projectId, 'audio') });
      }
    },
    onError: (error, variables) => {
      if (variables.projectId === activeProjectRef.current) message.error(getErrorMessage(error, '导入音频失败'));
    },
  });

  const checkMutation = useMutation({
    mutationFn: ({ audioId }: { audioId: number; projectId: number }) => asrEvaluationApi.checkAudio(audioId),
    onMutate: ({ audioId, projectId }) => {
      if (activeProjectRef.current === projectId) setAudioCheckId({ audioId, projectId });
    },
    onSuccess: (result, { audioId, projectId }) => {
      if (activeProjectRef.current !== projectId) return;
      setSelectedAudio((current) => current?.id === audioId
        ? { ...current, availability: result.availability }
        : current);
      if (result.platform_access === 'DENIED') message.warning('该音频未通过项目出站授权检查');
      else if (result.audio_source === 'HEAD_NOT_SUPPORTED') message.info('音频源不支持 HEAD；可用性保持待检查');
      else if (result.availability === 'AVAILABLE') message.success('检查完成：音频源可访问');
      else message.warning('检查完成：' + availabilityLabel(result.availability).label);
    },
    onError: (error, { projectId }) => {
      if (activeProjectRef.current === projectId) message.error(getErrorMessage(error, '检查音频链接失败'));
    },
    onSettled: (_data, _error, { audioId, projectId }) => {
      if (activeProjectRef.current === projectId) {
        setAudioCheckId((current) => current?.projectId === projectId && current.audioId === audioId ? null : current);
      }
      void queryClient.invalidateQueries({ queryKey: asrQueryKeys.project(projectId, 'audio') });
    },
  });

  const uploadGroundTruthMutation = useMutation({
    mutationFn: ({ audioId, document }: { audioId: number; document: JsonValue; projectId: number }) =>
      funasrTuningApi.createGroundTruth(audioId, document, SAMPLE_JSON_MAPPING),
    onSuccess: (result, { audioId, projectId }) => {
      if (activeProjectRef.current !== projectId) return;
      message.success('已为音频 #' + audioId + ' 绑定标准答案 v' + result.version);
      setGroundTruthAudio(null);
      setGroundTruthFile(null);
      setGroundTruthDocument(null);
      setGroundTruthReadError('');
      void queryClient.invalidateQueries({ queryKey: asrQueryKeys.project(projectId, 'funasr-ground-truth') });
      void queryClient.invalidateQueries({ queryKey: asrQueryKeys.project(projectId, 'audio') });
    },
    onError: (error, { projectId }) => {
      if (activeProjectRef.current === projectId) message.error(getErrorMessage(error, '绑定标准答案失败；文件预览仍保留，可重试'));
    },
  });

  const openForm = (mode: AudioFormMode, audio?: AsrAudio) => {
    setFormMode(mode);
    setEditingAudio(audio ?? null);
    setBatchInput('');
    form.resetFields();
    if (audio) form.setFieldsValue({ name: audio.name, url: '' });
    setOpen(true);
  };

  const closeForm = () => {
    setOpen(false);
    setEditingAudio(null);
    setBatchInput('');
    form.resetFields();
  };

  const beginGroundTruthUpload = (audio: AsrAudio) => {
    groundTruthReadGeneration.current += 1;
    setGroundTruthAudio(audio);
    setGroundTruthFile(null);
    setGroundTruthDocument(null);
    setGroundTruthReadError('');
    setGroundTruthReading(false);
  };

  const stageGroundTruthFile = async (file: File) => {
    const generation = ++groundTruthReadGeneration.current;
    const projectId = currentProjectId;
    setGroundTruthFile(file);
    setGroundTruthDocument(null);
    setGroundTruthReadError('');
    setGroundTruthReading(false);
    if (file.size > 5_000_000) {
      setGroundTruthReadError('文件大小超过 5 MB，请选择更小的 JSON 文件。');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.json') && file.type !== 'application/json') {
      setGroundTruthReadError('请选择 .json 格式文件。');
      return;
    }
    setGroundTruthReading(true);
    try {
      const document = JSON.parse(await file.text()) as JsonValue;
      validateSampleJson(document);
      if (generation !== groundTruthReadGeneration.current || activeProjectRef.current !== projectId) return;
      setGroundTruthDocument(document);
    } catch (error) {
      if (generation === groundTruthReadGeneration.current && activeProjectRef.current === projectId) {
        setGroundTruthReadError(error instanceof Error ? error.message : 'JSON 文件无法解析');
      }
    } finally {
      if (generation === groundTruthReadGeneration.current && activeProjectRef.current === projectId) setGroundTruthReading(false);
    }
  };

  const runBatchCheck = async () => {
    const ids = [...selectedAudioIds];
    if (!ids.length || batchChecking) return;
    const projectId = currentProjectId;
    if (!projectId) return;
    const generation = ++batchCheckGeneration.current;
    setBatchChecking(true);
    setBatchCheckResults(null);
    setBatchCheckProgress({ total: ids.length, completed: 0 });
    const results: BatchCheckResult[] = new Array(ids.length);
    let cursor = 0;
    let completed = 0;
    const worker = async () => {
      while (cursor < ids.length) {
        const index = cursor;
        cursor += 1;
        const audioId = ids[index];
        if (activeProjectRef.current !== projectId || batchCheckGeneration.current !== generation) return;
        try {
          const result = await asrEvaluationApi.checkAudio(audioId);
          results[index] = {
            audioId, ok: true, availability: result.availability,
            audioSource: result.audio_source, platformAccess: result.platform_access,
            httpStatus: result.http_status,
          };
        } catch (error) {
          results[index] = { audioId, ok: false, error: getErrorMessage(error, '检查失败') };
        }
        completed += 1;
        if (activeProjectRef.current === projectId && batchCheckGeneration.current === generation) {
          setBatchCheckProgress({ total: ids.length, completed });
        }
      }
    };
    try {
      await Promise.all(Array.from({ length: Math.min(3, ids.length) }, () => worker()));
      if (activeProjectRef.current === projectId && batchCheckGeneration.current === generation) {
        setBatchCheckProgress({ total: ids.length, completed: ids.length });
        setBatchCheckResults(results);
        void queryClient.invalidateQueries({ queryKey: asrQueryKeys.project(projectId, 'audio') });
      }
    } finally {
      if (activeProjectRef.current === projectId && batchCheckGeneration.current === generation) setBatchChecking(false);
    }
  };

  const navigateToJobWizard = (ids: number[]) => {
    if (!ids.length || ids.length > 200) {
      message.warning(ids.length > 200 ? '一次最多创建 200 条音频的评测任务' : '请先选择音频');
      return;
    }
    navigate('/console/asr/jobs?project_id=' + currentProjectId + '&audio_ids=' + ids.join(','), {
      state: { returnTo: audioListReturnTo() },
    });
  };

  const checkRow = (audioId: number) => {
    if (currentProjectId && !checkMutation.isPending && !batchChecking) {
      checkMutation.mutate({ audioId, projectId: currentProjectId });
    }
  };

  const columns = [
    {
      title: '音频名称',
      dataIndex: 'name',
      key: 'name',
      width: 240,
      render: (_: unknown, row: AsrAudio) => (
        <Space direction="vertical" size={0} className="asr-audio-name-cell">
          <Button type="link" className="asr-audio-name" onClick={() => { setMediaError(false); setMediaWaiting(false); setSelectedAudio(row); }}>
            {row.name}
          </Button>
          <Typography.Text type="secondary">音频版本 v{row.content_version}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '时长',
      dataIndex: 'duration_seconds',
      key: 'duration',
      width: 110,
      render: (value: number | null) => formatAudioDuration(value),
    },
    {
      title: '可用性',
      dataIndex: 'availability',
      key: 'availability',
      width: 130,
      render: (value: string) => {
        const state = availabilityLabel(value);
        return <Tag color={state.color}>{state.label}</Tag>;
      },
    },
    {
      title: '标准答案（JSON）',
      key: 'ground_truth',
      width: 210,
      render: (_: unknown, row: AsrAudio) => {
        const answer = groundTruthByAudioId.get(row.id);
        const answerState = groundTruthUiState(answer, row.content_version, groundTruthQuery.status);
        if (answerState === 'loading') return <Tag color="processing">读取中</Tag>;
        if (answerState === 'error') return (
          <Space direction="vertical" size={4}>
            <Tag color="error">读取失败</Tag>
            <Button size="small" type="link" onClick={() => void groundTruthQuery.refetch()}>重试读取</Button>
          </Space>
        );
        if (answerState === 'unbound') return (
          <Space direction="vertical" size={4}>
            <Tag color="default">未绑定</Tag>
            <Button size="small" icon={<UploadOutlined />} onClick={() => beginGroundTruthUpload(row)}>上传 JSON</Button>
          </Space>
        );
        if (!answer) return <Tag color="warning">答案状态未知</Tag>;
        const matchesAudio = answerState === 'current';
        return (
          <Space direction="vertical" size={4}>
            <Tag color={matchesAudio ? 'success' : 'warning'}>
              {matchesAudio ? '答案 v' + answer.version : '版本不匹配 · 音频 v' + answer.audio_content_version}
            </Tag>
            <Space size={4} wrap>
              <Button size="small" type="link" onClick={() => setGroundTruthPreview(answer)}>查看内容</Button>
              <Button size="small" icon={<UploadOutlined />} onClick={() => beginGroundTruthUpload(row)}>
                {matchesAudio ? '更换' : '更新答案'}
              </Button>
            </Space>
          </Space>
        );
      },
    },
    {
      title: '最近评测',
      key: 'recent_run',
      width: 210,
      render: (_: unknown, row: AsrAudio) => {
        const recent = recentRuns.get(row.id);
        const recentState = recentRunUiState(recent, recentRunsQuery.status, Boolean(recentRunsQuery.data));
        if (recentState === 'loading') return <Tag color="processing">读取中</Tag>;
        if (recentState === 'error') return (
          <Space direction="vertical" size={4}>
            <Tag color="error">读取失败</Tag>
            <Button size="small" type="link" onClick={() => void recentRunsQuery.refetch()}>重试读取</Button>
          </Space>
        );
        if (recentState === 'unassessed') return <Tag>未评测</Tag>;
        if (!recent) return <Tag color="warning">结果状态未知</Tag>;
        const state = runStatusLabel(recent.status);
        const versionWarning = recent.audio_version != null && recent.audio_version !== row.content_version;
        return (
          <Space direction="vertical" size={2}>
            <Tag color={state.color}>{state.label}</Tag>
            <Typography.Text type="secondary">
              任务 #{recent.job_id} · {versionWarning ? '历史音频 v' + recent.audio_version : '音频 v' + (recent.audio_version ?? '未知')}
            </Typography.Text>
            <Typography.Text type="secondary">{new Date(recent.created_at).toLocaleString()}</Typography.Text>
          </Space>
        );
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 280,
      render: (_: unknown, row: AsrAudio) => {
        const recent = recentRuns.get(row.id);
        const canOpenRecent = Boolean(recent && recentRunsQuery.isSuccess);
        const items = [
          { key: 'create', label: '再次创建评测' },
          ...(canOpenRecent ? [
            { key: 'result', label: '查看最近结果' },
            { key: 'job', label: '查看最近任务' },
          ] : []),
          { type: 'divider' as const },
          { key: 'answer', label: '管理标准答案（JSON）' },
          { key: 'edit', label: '编辑音频信息' },
          { key: 'check', label: '检查链接', disabled: checkMutation.isPending || batchChecking },
        ];
        return (
          <Space size={8} wrap>
            <Button aria-label={'试听 ' + row.name} icon={<PlayCircleOutlined />} onClick={() => { setMediaError(false); setMediaWaiting(false); setSelectedAudio(row); }}>
              试听
            </Button>
            <Button
              type="primary"
              onClick={() => canOpenRecent && recent ? navigate('/console/asr/runs/' + recent.run_id, {
                state: { returnTo: audioListReturnTo() },
              }) : navigateToJobWizard([row.id])}
            >
              {canOpenRecent && recent ? '查看结果' : '创建评测'}
            </Button>
            <Dropdown menu={{
              items,
              onClick: ({ key }) => {
                if (key === 'create') navigateToJobWizard([row.id]);
                if (key === 'result' && recent) navigate('/console/asr/runs/' + recent.run_id, {
                  state: { returnTo: audioListReturnTo() },
                });
                if (key === 'job' && recent) navigate('/console/asr/jobs/' + recent.job_id, {
                  state: { returnTo: audioListReturnTo() },
                });
                if (key === 'answer') beginGroundTruthUpload(row);
                if (key === 'edit') openForm('EDIT', row);
                if (key === 'check') checkRow(row.id);
              },
            }}>
              <Button aria-label={'更多操作 ' + row.name} icon={<MoreOutlined />} />
            </Dropdown>
          </Space>
        );
      },
    },
  ];

  if (!currentProjectId) return <AsrFrame title="音频资产"><Empty description="先选择项目再管理音频链接" /></AsrFrame>;

  const resultFailures = (batchCheckResults ?? []).filter((item) => !item.ok);
  const batchImportPreviewColumns = [
    { title: '音频名称', dataIndex: 'name', key: 'name' },
    { title: '脱敏地址预览', dataIndex: 'url', key: 'url', render: (value: string) => <Typography.Text type="secondary" ellipsis>{safeDisplayUrl(value)}</Typography.Text> },
  ];
  const groundTruthColumns = [
    { title: '开始（毫秒）', dataIndex: 'start', key: 'start', width: 120 },
    { title: '结束（毫秒）', dataIndex: 'end', key: 'end', width: 120 },
    { title: '说话人', dataIndex: 'speaker', key: 'speaker', width: 100 },
    { title: '文本', dataIndex: 'text', key: 'text', render: (value: string) => <Typography.Text ellipsis>{value}</Typography.Text> },
  ];

  return (
    <AsrFrame title="音频资产">
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Space wrap className="asr-audio-toolbar">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openForm('CREATE')}>添加链接</Button>
          <Button icon={<PlusOutlined />} onClick={() => openForm('IMPORT')}>批量粘贴</Button>
          <Button icon={<ReloadOutlined />} loading={audioQuery.isFetching} onClick={() => void audioQuery.refetch()}>刷新</Button>
          <Input.Search
            aria-label="按名称筛选音频"
            allowClear
            placeholder="搜索音频名称"
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            style={{ width: 240 }}
          />
          <Select
            aria-label="按可用性筛选"
            value={availabilityFilter || 'ALL'}
            onChange={(value) => updateListQuery({
              availability: value === 'ALL' ? undefined : value,
              page: undefined,
              q: keywordInput.trim() || undefined,
            })}
            style={{ width: 150 }}
            options={[
              { value: 'ALL', label: '全部可用性' },
              { value: 'AVAILABLE', label: '可访问' },
              { value: 'UNKNOWN', label: '待检查' },
              { value: 'UNREACHABLE', label: '源不可达' },
              { value: 'PLATFORM_DENIED', label: '出站未授权' },
            ]}
          />
          <Select
            aria-label="按标准答案筛选"
            value={groundTruthFilter}
            onChange={(value: GroundTruthStatus) => updateListQuery({
              ground_truth: value === 'ALL' ? undefined : value,
              page: undefined,
              q: keywordInput.trim() || undefined,
            })}
            style={{ width: 150 }}
            options={[
              { value: 'ALL', label: '全部答案状态' },
              { value: 'BOUND', label: '已绑定当前版本' },
              { value: 'UNBOUND', label: '未绑定当前版本' },
            ]}
          />
          {(keywordInput || availabilityFilter || groundTruthFilter !== 'ALL') && (
            <Button onClick={() => {
              setKeywordInput('');
              updateListQuery({ page: undefined, page_size: undefined, q: undefined, availability: undefined, ground_truth: undefined });
            }}>重置筛选</Button>
          )}
        </Space>

        {audioQuery.isError && (
          <Alert
            type="error"
            showIcon
            message="音频列表读取失败"
            description={getErrorMessage(audioQuery.error, '请稍后重试')}
            action={<Button size="small" onClick={() => void audioQuery.refetch()}>重试</Button>}
          />
        )}
        {groundTruthQuery.isError && (
          <Alert
            type="warning"
            showIcon
            message="标准答案状态读取失败"
            description="当前不能确认音频是否已绑定答案；列表中会保留“读取失败”，不会显示为未绑定。"
            action={<Button size="small" onClick={() => void groundTruthQuery.refetch()}>重试</Button>}
          />
        )}
        {recentRunsQuery.isError && (
          <Alert
            type="warning"
            showIcon
            message="最近评测摘要读取失败"
            description="当前不能判断音频是否评测过；可重试或进入评测任务列表查看。"
            action={<Button size="small" onClick={() => void recentRunsQuery.refetch()}>重试</Button>}
          />
        )}

        {selectedAudioIds.length > 0 && (
          <Flex className="asr-audio-selection-toolbar" justify="space-between" wrap="wrap" gap="small" align="center">
            <Space direction="vertical" size={2} style={{ minWidth: 180 }}>
              <Typography.Text strong>已选 {selectedAudioIds.length} 条音频（跨页保留）</Typography.Text>
              {batchChecking && batchCheckProgress && <>
                <Typography.Text type="secondary">正在检查 {batchCheckProgress.completed} / {batchCheckProgress.total}</Typography.Text>
                <Progress size="small" percent={Math.round(batchCheckProgress.completed / batchCheckProgress.total * 100)} status="active" />
              </>}
            </Space>
            <Space wrap>
              <Button type="primary" onClick={() => navigateToJobWizard(selectedAudioIds)} disabled={selectedAudioIds.length > 200}>
                创建评测
              </Button>
              <Button loading={batchChecking} disabled={checkMutation.isPending} onClick={() => void runBatchCheck()}>
                检查链接
              </Button>
              <Button onClick={() => { setSelectedAudioIds([]); setSelectedAudioLabels({}); }}>取消选择</Button>
            </Space>
          </Flex>
        )}

        <Table<AsrAudio>
          rowKey="id"
          columns={columns}
          dataSource={audioRows}
          loading={audioQuery.isPending || (audioQuery.isFetching && Boolean(audioQuery.data))}
          rowSelection={{
            selectedRowKeys: selectedAudioIds,
            preserveSelectedRowKeys: true,
            getCheckboxProps: () => ({ disabled: batchChecking }),
            onChange: (keys) => {
              const ids = keys.map(Number);
              const selected = new Set(ids);
              setSelectedAudioIds(ids);
              setSelectedAudioLabels((previous) => {
                const next = Object.fromEntries(Object.entries(previous).filter(([id]) => selected.has(Number(id))));
                for (const row of audioRows) if (selected.has(row.id)) next[row.id] = row.name;
                return next;
              });
            },
          }}
          locale={{
            emptyText: audioQuery.isError
              ? <Empty description="列表未能加载，请检查上方错误信息并重试" />
              : <Empty description={keyword || availabilityFilter || groundTruthFilter !== 'ALL'
                ? '没有符合当前筛选条件的音频'
                : '还没有音频链接；添加链接后即可试听或创建评测'} />,
          }}
          pagination={{
            current: page,
            pageSize,
            total: audioQuery.data?.total ?? 0,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            showTotal: (total) => '共 ' + total + ' 条',
            onChange: (nextPage, nextPageSize) => {
              updateListQuery({
                page: nextPageSize !== pageSize ? undefined : nextPage,
                page_size: nextPageSize,
                q: keywordInput.trim() || undefined,
              });
            },
          }}
          scroll={{ x: 1140 }}
        />
      </Space>

      <Modal
        title={formMode === 'EDIT' ? '编辑音频资源' : formMode === 'IMPORT' ? '批量粘贴音频链接' : '添加音频链接'}
        open={open}
        onCancel={closeForm}
        confirmLoading={importMutation.isPending}
        okText={formMode === 'EDIT' ? '保存' : '确认导入'}
        cancelText="取消"
        onOk={() => form.submit()}
        width={formMode === 'IMPORT' ? 720 : 560}
        maskClosable={!importMutation.isPending}
        closable={!importMutation.isPending}
      >
        <Form<AudioFormValues>
          form={form}
          layout="vertical"
          onValuesChange={(changed) => { if (typeof changed.batch_text === 'string') setBatchInput(changed.batch_text); }}
          onFinish={(values) => importMutation.mutate({
            values, projectId: currentProjectId, mode: formMode, audio: editingAudio,
          })}
        >
          {formMode !== 'IMPORT' && (
            <Form.Item name="name" label="音频名称" rules={[{ required: true, whitespace: true, message: '请输入音频名称' }]}>
              <Input maxLength={200} placeholder="例如：会议录音 2026-11-02" />
            </Form.Item>
          )}
          {formMode !== 'IMPORT' && (
            <Form.Item name="url" label={formMode === 'EDIT' ? '替换音频 URL（留空保留现有链接）' : '音频 URL'}
              rules={formMode === 'EDIT' ? [] : [{ required: true, type: 'url', message: '请输入有效的 HTTP 或 HTTPS 地址' }]}>
              <Input placeholder={formMode === 'EDIT' ? '留空不更换 URL' : 'https://音频服务/文件.mp3?临时签名'} />
            </Form.Item>
          )}
          {formMode === 'IMPORT' && (
            <Form.Item name="batch_text" label="每条音频两行：名称在前，URL 在后"
              rules={[{ required: true, whitespace: true, message: '请粘贴音频名称和 URL' }]}>
              <Input.TextArea
                rows={8}
                spellCheck={false}
                placeholder={'声音小，噪音大：\nhttps://音频服务/文件1.m4a\n技师顾客全为女：\nhttps://音频服务/文件2.m4a'}
              />
            </Form.Item>
          )}
          {formMode === 'IMPORT' && batchPreview.error && <Alert type="error" showIcon message={batchPreview.error} />}
          {formMode === 'IMPORT' && !batchPreview.error && batchPreview.records.length > 0 && (
            <div className="asr-import-preview">
              <Typography.Text strong>待提交 {batchPreview.records.length} 条</Typography.Text>
              <Table
                size="small"
                rowKey={(_row, index) => String(index)}
                columns={batchImportPreviewColumns}
                dataSource={batchPreview.records.slice(0, 5)}
                pagination={false}
                scroll={{ x: 420 }}
              />
              {batchPreview.records.length > 5 && <Typography.Text type="secondary">另有 {batchPreview.records.length - 5} 条，确认后整批提交。</Typography.Text>}
            </div>
          )}
          {formMode !== 'IMPORT' && (
            <Typography.Text type="secondary">只需填写音频名称和 HTTP(S) URL，时长等信息由平台按需解析。</Typography.Text>
          )}
          <Typography.Paragraph className="asr-muted-note">
            URL 和查询参数加密保存；列表只显示不含签名查询串的地址。播放与 ASR 请求都会重新检查项目出站策略。
          </Typography.Paragraph>
        </Form>
      </Modal>

      <Modal
        title={groundTruthAudio ? '标准答案（JSON） · ' + groundTruthAudio.name : '标准答案（JSON）'}
        open={Boolean(groundTruthAudio)}
        onCancel={() => {
          if (uploadGroundTruthMutation.isPending) return;
          groundTruthReadGeneration.current += 1;
          setGroundTruthAudio(null);
          setGroundTruthFile(null);
          setGroundTruthDocument(null);
          setGroundTruthReadError('');
          setGroundTruthReading(false);
        }}
        destroyOnClose
        maskClosable={!uploadGroundTruthMutation.isPending}
        closable={!uploadGroundTruthMutation.isPending}
        width={760}
        okText="确认绑定"
        cancelText="取消"
        confirmLoading={uploadGroundTruthMutation.isPending}
        okButtonProps={{ disabled: !groundTruthAudio || !groundTruthDocument || groundTruthReading || Boolean(groundTruthReadError) }}
        onOk={() => {
          if (groundTruthAudio && groundTruthDocument && currentProjectId) {
            uploadGroundTruthMutation.mutate({
              audioId: groundTruthAudio.id, document: groundTruthDocument, projectId: currentProjectId,
            });
          }
        }}
      >
        <Typography.Paragraph type="secondary">
          选择文件或拖入文件后先预览，再确认绑定到音频版本。当前映射固定为 text/start/end/spk，时间单位为毫秒，不会自动猜测。
        </Typography.Paragraph>
        {groundTruthAudio && (
          <Alert
            type="info"
            showIcon
            message={'目标音频：' + groundTruthAudio.name + ' · 当前音频版本 v' + groundTruthAudio.content_version}
            description="绑定后会生成一个标准答案版本；若音频 URL 替换并升级版本，旧答案会继续保留为历史版本。"
            style={{ marginBottom: 12 }}
          />
        )}
        <Upload.Dragger
          accept=".json,application/json"
          maxCount={1}
          multiple={false}
          showUploadList={false}
          disabled={groundTruthReading || uploadGroundTruthMutation.isPending}
          beforeUpload={(file) => {
            void stageGroundTruthFile(file);
            return Upload.LIST_IGNORE;
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击选择 JSON 文件，或将文件拖到此处</p>
          <p className="ant-upload-hint">支持 .json 文件，大小不超过 5 MB</p>
        </Upload.Dragger>
        {groundTruthFile && (
          <Descriptions size="small" column={{ xs: 1, sm: 2 }} bordered style={{ marginTop: 12 }}>
            <Descriptions.Item label="文件">{groundTruthFile.name}</Descriptions.Item>
            <Descriptions.Item label="大小">{(groundTruthFile.size / 1024).toFixed(1)} KB</Descriptions.Item>
          </Descriptions>
        )}
        {groundTruthReading && <Alert type="info" showIcon message="正在读取并校验 JSON…" style={{ marginTop: 12 }} />}
        {groundTruthReadError && <Alert type="error" showIcon message="JSON 校验未通过" description={groundTruthReadError} style={{ marginTop: 12 }} />}
        {groundTruthDocument && !groundTruthReadError && (
          <div className="asr-json-preview">
            <Flex justify="space-between" wrap="wrap" gap="small">
              <Typography.Text strong>预览内容</Typography.Text>
              <Typography.Text type="secondary">
                {stagedSegments.length} 段 · {new Set(stagedSegments
                  .map((item) => (item as Record<string, JsonValue>).spk)
                  .filter((speaker) => speaker !== null && speaker !== undefined)
                  .map(String)).size} 位说话人 · 毫秒
              </Typography.Text>
            </Flex>
            <Table<GroundTruthPreviewRow>
              size="small"
              rowKey="key"
              columns={groundTruthColumns}
              dataSource={previewSegments(stagedSegments)}
              pagination={false}
              scroll={{ x: 520 }}
              style={{ marginTop: 8 }}
            />
            {stagedSegments.length > 5 && <Typography.Text type="secondary">展示前 5 段，共 {stagedSegments.length} 段。</Typography.Text>}
          </div>
        )}
        {uploadGroundTruthMutation.isError && (
          <Alert type="error" showIcon message="绑定失败" description={getErrorMessage(uploadGroundTruthMutation.error, '保留文件后可重试或更换文件。')} style={{ marginTop: 12 }} />
        )}
      </Modal>

      <Drawer
        title="音频详情与试听"
        open={Boolean(selectedAudio)}
        onClose={() => { setSelectedAudio(null); setMediaError(false); setMediaWaiting(false); }}
        width={520}
        destroyOnClose
      >
        {selectedAudio && (
          <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
            <Descriptions size="small" bordered column={1}>
              <Descriptions.Item label="音频名称">{selectedAudio.name}</Descriptions.Item>
              <Descriptions.Item label="音频版本">v{selectedAudio.content_version}</Descriptions.Item>
              <Descriptions.Item label="时长">{formatAudioDuration(selectedAudio.duration_seconds)}</Descriptions.Item>
              <Descriptions.Item label="可用性">{availabilityLabel(selectedAudio.availability).label}</Descriptions.Item>
              <Descriptions.Item label="最近评测">{(() => {
                const recent = recentRuns.get(selectedAudio.id);
                if (recentRunsQuery.status === 'pending' && !recentRunsQuery.data) return '读取中';
                if (recentRunsQuery.status === 'error' && !recentRunsQuery.data) return '读取失败';
                return recent ? '任务 #' + recent.job_id + ' · ' + runStatusLabel(recent.status).label
                  + ' · 音频 v' + (recent.audio_version ?? '未知') : '未评测';
              })()}</Descriptions.Item>
              <Descriptions.Item label="脱敏地址">
                <Typography.Text copyable={false} className="asr-safe-url">{selectedAudio.url_display}</Typography.Text>
              </Descriptions.Item>
            </Descriptions>
            <Typography.Title level={5} style={{ margin: 0 }}>试听</Typography.Title>
            <Typography.Text type="secondary">播放使用项目授权后的媒体代理流，不会创建识别任务。首次播放时才请求音频。</Typography.Text>
            <audio
              ref={mediaAudioRef}
              key={selectedAudio.id + ':' + selectedAudio.content_version}
              className="asr-audio"
              aria-label={'试听 ' + selectedAudio.name + ' 音频版本 ' + selectedAudio.content_version}
              controls
              preload="none"
              src={asrEvaluationApi.audioMediaUrl(selectedAudio.id, selectedAudio.current_audio_version_id)}
              onLoadStart={() => { setMediaWaiting(true); setMediaError(false); }}
              onWaiting={() => setMediaWaiting(true)}
              onCanPlay={() => { setMediaWaiting(false); setMediaError(false); }}
              onPlaying={() => setMediaWaiting(false)}
              onError={() => { setMediaWaiting(false); setMediaError(true); }}
            />
            {mediaWaiting && <Alert type="info" showIcon message="正在连接音频源…" />}
            {mediaError && (
              <Alert
                type="error"
                showIcon
                message="音频无法播放"
                description="来源可能不可达、未获项目出站授权或格式不受浏览器支持。可以重试播放，或检查音频链接状态。"
                action={<Button size="small" onClick={() => {
                  const element = mediaAudioRef.current;
                  setMediaError(false);
                  setMediaWaiting(true);
                  element?.load();
                  if (element) void element.play().catch(() => { setMediaWaiting(false); setMediaError(true); });
                }}>重试播放</Button>}
              />
            )}
            <Space wrap>
              <Button type="primary" onClick={() => navigateToJobWizard([selectedAudio.id])}>创建评测</Button>
              <Button disabled={checkMutation.isPending || batchChecking} loading={audioCheckId?.projectId === currentProjectId && audioCheckId.audioId === selectedAudio.id} onClick={() => checkRow(selectedAudio.id)}>检查链接</Button>
              <Button onClick={() => beginGroundTruthUpload(selectedAudio)}>管理标准答案（JSON）</Button>
            </Space>
          </Space>
        )}
      </Drawer>

      <Modal
        title="批量链接检查结果"
        open={batchCheckResults !== null}
        onCancel={() => setBatchCheckResults(null)}
        footer={<Button type="primary" onClick={() => setBatchCheckResults(null)}>完成</Button>}
      >
        {batchCheckResults && (
          <Space direction="vertical" style={{ display: 'flex' }}>
            <Alert
              type={resultFailures.length ? 'warning' : 'success'}
              showIcon
              message={'已完成 ' + batchCheckResults.length + ' / ' + batchCheckResults.length + ' 条；失败 ' + resultFailures.length + ' 条'}
              description="单条检查失败不会中断其他音频；请求最多并发 3 条。"
            />
            <div className="asr-batch-check-results">
              {batchCheckResults.map((result) => {
                const audio = audioRows.find((item) => item.id === result.audioId);
                return <div key={result.audioId}>
                  <Typography.Text strong>{selectedAudioLabels[result.audioId] ?? audio?.name ?? '音频 #' + result.audioId}</Typography.Text>
                  <Typography.Text type={result.ok ? 'secondary' : 'danger'}>{checkResultLabel(result)}</Typography.Text>
                </div>;
              })}
            </div>
          </Space>
        )}
      </Modal>

      <Modal
        title={groundTruthPreview ? '标准答案内容 · ' + groundTruthPreview.audio_name : '标准答案内容'}
        open={groundTruthPreview !== null}
        onCancel={() => setGroundTruthPreview(null)}
        footer={<Button type="primary" onClick={() => setGroundTruthPreview(null)}>关闭</Button>}
      >
        {groundTruthPreview && (
          <Space direction="vertical" style={{ display: 'flex' }}>
            <Typography.Text type="secondary">
              音频版本 v{groundTruthPreview.audio_content_version} · 答案版本 v{groundTruthPreview.version}
            </Typography.Text>
            <Typography.Paragraph className="asr-transcript-cell">{groundTruthPreview.transcript || '答案中没有标准转写文本'}</Typography.Paragraph>
          </Space>
        )}
      </Modal>
    </AsrFrame>
  );
}
