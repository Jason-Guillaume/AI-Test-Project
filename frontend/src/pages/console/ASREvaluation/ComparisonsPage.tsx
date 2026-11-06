// 识别对比与人工复核：保留三方原文、真实音频回听和可追溯的逐块确认。
import {
  App, Alert, Button, Card, Checkbox, Collapse, Dropdown, Empty, Input, Pagination, Select, Space, Spin, Tag, Typography,
} from 'antd';
import {
  ArrowLeftOutlined, ArrowRightOutlined, CheckOutlined, PlayCircleOutlined, SoundOutlined,
  DownloadOutlined, DownOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import { confirmDraftDiscard, useDraftNavigationGuard } from '@/features/asr-evaluation/useDraftNavigationGuard';
import { getErrorMessage } from '@/shared/api/client';
import type { AsrComparison, AsrComparisonListItem, AsrDiffBlock } from '@/features/asr-evaluation/contracts';
import { AsrFrame } from './AsrFrame';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { ContentReviewPanel } from './ContentReviewPanel';
import { clearMatchingReviewDraft } from '@/features/asr-evaluation/reviewDraftMutation.mjs';

/** 展示不含标准答案时可解释的文本差异比例。 */
function ratioLabel(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '未计算（文本过长）';
}

function suggestionJobStatusLabel(status: string): string {
  return ({ QUEUED: '排队中', RUNNING: '生成中', SUCCEEDED: '已完成', FAILED: '失败', RECONCILIATION_REQUIRED: '请求状态待核实' } as Record<string, string>)[status] ?? status;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '时间未知';
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 浏览项目内已有识别对比版本。 */
export function ComparisonsPage() {
  const { currentProjectId } = useConsoleScope();
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [currentProjectId]);
  const query = useQuery({
    queryKey: currentProjectId ? asrQueryKeys.project(currentProjectId, 'comparisons', page) : ['asr', 'comparisons', null, page],
    enabled: Boolean(currentProjectId),
    queryFn: async ({ signal }) => (await asrEvaluationApi.listComparisons(currentProjectId!, page, 20, signal)),
  });
  if (!currentProjectId) return <AsrFrame title="识别结果对比"><Empty description="先选择项目" /></AsrFrame>;
  if (query.isPending) return <AsrFrame title="识别结果对比"><LoadingState /></AsrFrame>;
  if (query.isError) return <AsrFrame title="识别结果对比"><ErrorState error={query.error} onRetry={query.refetch} /></AsrFrame>;
  return (
    <AsrFrame title="识别结果对比">
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        {(query.data?.items ?? []).length === 0
          ? <Empty description="还没有可查看的对比。至少两家模型完成后会保留部分结果；三方齐备后形成完整对照。" />
          : (query.data?.items ?? []).map((item: AsrComparisonListItem) => (
            <Card key={item.id} size="small" className="asr-model-card">
              <Space direction="vertical" style={{ display: 'flex' }}>
                <Space wrap>
                  <Typography.Text strong>{item.audio_name}</Typography.Text>
                  <Tag>{item.status === 'COMPLETE' ? '三方齐备' : '结果不完整'}</Tag>
                  {item.degraded && <Tag color="warning">长文本降级对齐</Tag>}
                  <Typography.Text type="secondary">批次 ASR-{item.job_id} · 对比 v{item.version}</Typography.Text>
                </Space>
                <Typography.Text type="secondary">
                  {item.summary?.diff_blocks ?? 0} 个差异块 · {item.summary?.unanimous_blocks ?? 0} 个三方一致块（仅供抽查）
                </Typography.Text>
                <Link to={`/console/asr/comparisons/${item.id}`}>打开三方对照与人工复核</Link>
              </Space>
            </Card>
          ))}
        {(query.data?.total ?? 0) > 20 && <Pagination current={page} pageSize={query.data?.page_size ?? 20} total={query.data?.total ?? 0} onChange={setPage} showSizeChanger={false} />}
      </Space>
    </AsrFrame>
  );
}

/** 显示一个音频的三方结果、回听控件、人工确认和参数建议。 */
export function ComparisonDetailPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { comparisonId: rawId } = useParams();
  const comparisonId = Number(rawId);
  const validId = Number.isSafeInteger(comparisonId) && comparisonId > 0;
  const [filter, setFilter] = useState('DIFFERENCES');
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [confirmedTextDrafts, setConfirmedTextDrafts] = useState<Record<number, string>>({});
  const confirmedTextDraftRevisions = useRef<Record<number, number>>({});
  const [includeSample, setIncludeSample] = useState(false);
  const [modelConfigId, setModelConfigId] = useState<number | undefined>();
  const [candidatePath, setCandidatePath] = useState<string>();
  const [candidateValue, setCandidateValue] = useState('');
  const [reuseReferenceResults, setReuseReferenceResults] = useState(false);
  const [audioPlaybackError, setAudioPlaybackError] = useState('');
  const hasReviewDrafts = Object.keys(confirmedTextDrafts).length > 0;
  useDraftNavigationGuard(hasReviewDrafts);
  const audioRef = useRef<HTMLAudioElement>(null);
  const comparisonKey = ['asr', 'comparison-detail', comparisonId];
  const comparisonQuery = useQuery<AsrComparison>({
    queryKey: comparisonKey, enabled: validId,
    refetchInterval: (query) => ['COMPLETED', 'PARTIAL_FAILED', 'FAILED'].includes(query.state.data?.job_status ?? '') ? false : 5000,
    queryFn: async ({ signal }) => (await asrEvaluationApi.getComparison(comparisonId, signal)),
  });
  const blocksQuery = useQuery({
    queryKey: [...comparisonKey, 'blocks', filter, page], enabled: Boolean(comparisonQuery.data && validId),
    queryFn: async ({ signal }) => (await asrEvaluationApi.listBlocks(comparisonId, filter, signal, page)),
  });
  const historyQuery = useQuery({
    queryKey: [...comparisonKey, 'review-history', selectedId], enabled: Boolean(comparisonQuery.data && validId && selectedId),
    queryFn: async ({ signal }) => (await asrEvaluationApi.reviewHistory(comparisonId, selectedId!, signal)).items,
  });
  const suggestionsQuery = useQuery({
    queryKey: [...comparisonKey, 'suggestions'], enabled: Boolean(comparisonQuery.data && validId),
    queryFn: async ({ signal }) => (await asrEvaluationApi.listSuggestions(comparisonId, signal)).items,
  });
  const suggestionJobsQuery = useQuery({
    queryKey: [...comparisonKey, 'suggestion-jobs'], enabled: Boolean(comparisonQuery.data && validId),
    queryFn: async ({ signal }) => (await asrEvaluationApi.listSuggestionJobs(comparisonId, signal)).items,
    refetchInterval: (query) => query.state.data?.some((job) => ['QUEUED', 'RUNNING'].includes(job.status)) ? 2000 : false,
  });
  useEffect(() => {
    if (suggestionJobsQuery.data?.some((job) => job.status === 'SUCCEEDED')) {
      void queryClient.invalidateQueries({ queryKey: ['asr', 'comparison-detail', comparisonId, 'suggestions'] });
    }
  }, [comparisonId, queryClient, suggestionJobsQuery.data]);
  const projectId = comparisonQuery.data?.project_id;
  const modelsQuery = useQuery({
    queryKey: ['model-configs', 'asr-suggestions', projectId], enabled: Boolean(projectId),
    queryFn: async ({ signal }) => (await asrEvaluationApi.listReviewModels(projectId!, signal)).items,
  });
  const parameterQuery = useQuery({
    queryKey: projectId ? asrQueryKeys.project(projectId, 'parameter_sets') : ['asr', 'parameter_sets', null],
    enabled: Boolean(projectId),
    queryFn: async ({ signal }) => (await asrEvaluationApi.listParameterSets(projectId!, signal)).items,
  });
  const blocks = useMemo(() => blocksQuery.data?.items ?? [], [blocksQuery.data?.items]);
  const selectedBlock = blocks.find((item) => item.id === selectedId) ?? blocks[0];
  const confirmedText = selectedBlock
    ? confirmedTextDrafts[selectedBlock.id] ?? selectedBlock.confirmed_text ?? selectedBlock.test_text : '';
  const setConfirmedText = (value: string) => {
    if (!selectedBlock) return;
    confirmedTextDraftRevisions.current[selectedBlock.id] = (confirmedTextDraftRevisions.current[selectedBlock.id] ?? 0) + 1;
    setConfirmedTextDrafts((current) => {
      const next = { ...current };
      const baseline = selectedBlock.confirmed_text ?? selectedBlock.test_text;
      if (value === baseline) delete next[selectedBlock.id];
      else next[selectedBlock.id] = value;
      return next;
    });
  };
  const comparison = comparisonQuery.data;
  const testRun = comparison?.models.find((item) => item.role === 'TEST');
  const parameterSet = parameterQuery.data?.find((item) => item.id === testRun?.parameter_set_id);

  useEffect(() => {
    if (selectedBlock) {
      setSelectedId(selectedBlock.id);
      setIncludeSample(false);
    }
  }, [selectedBlock]);

  const invalidateComparison = (targetComparisonId = comparisonId) => {
    const targetKey = ['asr', 'comparison-detail', targetComparisonId];
    void queryClient.invalidateQueries({ queryKey: targetKey });
    void queryClient.invalidateQueries({ queryKey: [...targetKey, 'blocks'] });
    void queryClient.invalidateQueries({ queryKey: [...targetKey, 'suggestions'] });
    void queryClient.invalidateQueries({ queryKey: [...targetKey, 'review-history'] });
  };
  const reviewMutation = useMutation({
    mutationFn: (input: { comparisonId: number; blockId: number; draftText: string; draftRevision: number; savesDraft: boolean; body: Record<string, unknown> }) =>
      asrEvaluationApi.reviewBlock(input.comparisonId, input.blockId, input.body),
    onSuccess: (_data, variables) => {
      setConfirmedTextDrafts((current) => clearMatchingReviewDraft(current, confirmedTextDraftRevisions.current, {
        blockId: variables.blockId, submittedText: variables.draftText, submittedRevision: variables.draftRevision,
      }));
      message.success('人工复核已保存并保留版本记录');
      invalidateComparison(variables.comparisonId);
    },
    onError: () => message.error('保存复核失败；如版本冲突，请刷新当前片段后重试。'),
  });
  const suggestionMutation = useMutation({
    mutationFn: () => asrEvaluationApi.createSuggestions(comparisonId, modelConfigId!),
    onSuccess: (data) => {
      message.info(`调参建议任务 #${data.id} 已${data.status === 'QUEUED' ? '加入后台队列' : '存在'}；可刷新页面继续查看。`);
      void queryClient.invalidateQueries({ queryKey: [...comparisonKey, 'suggestion-jobs'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '建议任务创建失败；人工复核与识别结果仍已保留。')),
  });
  const retrySuggestionMutation = useMutation({
    mutationFn: (jobId: number) => asrEvaluationApi.retrySuggestionJob(jobId),
    onSuccess: (data) => {
      message.info(`建议任务 #${data.id} 已重新排队。`);
      void queryClient.invalidateQueries({ queryKey: [...comparisonKey, 'suggestion-jobs'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '建议任务重试失败；请检查任务状态和权限。')),
  });
  const experimentMutation = useMutation({
    mutationFn: (body: {
      comparison_id: number; candidate_parameters: Record<string, unknown>; change_summary: string;
      reuse_reference_results: boolean;
    }) =>
      asrEvaluationApi.createExperiment(body),
    onSuccess: (data) => {
      message.success(`候选实验 ${data.id} 已创建，基线参数未改变`);
      void queryClient.invalidateQueries({ queryKey: projectId ? asrQueryKeys.project(projectId, 'experiments') : ['asr', 'experiments'] });
      if (hasReviewDrafts && !confirmDraftDiscard()) return;
      navigate('/console/asr/experiments');
    },
    onError: () => message.error('候选参数未通过定义或范围校验，请检查参数值。'),
  });
  const exportMutation = useMutation({
    mutationFn: (format: 'json' | 'csv') => asrEvaluationApi.exportComparison(comparisonId, format),
    onSuccess: (blob, format) => {
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = `asr-comparison-${comparisonId}.${format}`;
      anchor.click();
      URL.revokeObjectURL(objectUrl);
    },
    onError: () => message.error('导出失败；项目结果仍可在页面查看。'),
  });

  /** 用 JSON Pointer 修改参数副本，候选版本不覆盖原参数方案。 */
  const createCandidate = (path: string | undefined, rawValue: string, summary: string) => {
    if (!parameterSet || !path) return message.error('本次待测运行没有对应的参数定义');
    try {
      const candidate = JSON.parse(JSON.stringify(parameterSet.parameters)) as Record<string, unknown>;
      const parts = path.slice(1).split('/').map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'));
      let current: Record<string, unknown> = candidate;
      for (const part of parts.slice(0, -1)) {
        if (!current[part] || typeof current[part] !== 'object' || Array.isArray(current[part])) throw new Error('路径不存在');
        current = current[part] as Record<string, unknown>;
      }
      const value: unknown = JSON.parse(rawValue);
      current[parts.at(-1)!] = value;
      experimentMutation.mutate({
        comparison_id: comparisonId, candidate_parameters: candidate, change_summary: summary,
        reuse_reference_results: reuseReferenceResults,
      });
    } catch {
      message.error('候选值需要是有效 JSON，且参数路径必须存在');
    }
  };

  /** 仅在有真实模型时间戳时跳转到时间点；未知时间不会估算或伪造。 */
  const seekToBlock = (block: AsrDiffBlock) => {
    if (block.start_seconds == null || block.timing_source === 'UNAVAILABLE' || !audioRef.current) return;
    audioRef.current.currentTime = Math.max(0, block.start_seconds);
  };

  const moveSelection = (offset: number) => {
    const index = blocks.findIndex((item) => item.id === selectedBlock?.id);
    const target = blocks[index + offset];
    if (target) { setSelectedId(target.id); seekToBlock(target); }
  };

  useEffect(() => {
    /** 仅在焦点不位于可编辑控件时启用播放和导航快捷键。 */
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || target?.isContentEditable
        || ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A'].includes(target?.tagName ?? '')
        || target?.closest('[role="button"], [role="menuitem"], [role="option"], [role="combobox"], [role="slider"], [contenteditable="true"]')) return;
      if (event.code === 'Space' && audioRef.current) {
        event.preventDefault();
        if (audioRef.current.paused) void audioRef.current.play(); else audioRef.current.pause();
      }
      if (event.key === 'ArrowLeft' && audioRef.current) audioRef.current.currentTime = Math.max(0, audioRef.current.currentTime - 10);
      if (event.key === 'ArrowRight' && audioRef.current) audioRef.current.currentTime += 10;
      if (event.key === '[') moveSelection(-1);
      if (event.key === ']') moveSelection(1);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  });

  if (!validId) return <AsrFrame title="识别结果对比"><Empty description="对比编号无效" /></AsrFrame>;
  if (comparisonQuery.isPending) return <AsrFrame title="识别结果对比"><LoadingState /></AsrFrame>;
  if (comparisonQuery.isError) return <AsrFrame title="识别结果对比"><ErrorState error={comparisonQuery.error} onRetry={comparisonQuery.refetch} /></AsrFrame>;
  if (!comparison) return <AsrFrame title="识别结果对比"><Empty description="对比结果不存在" /></AsrFrame>;

  const ratio = comparison.summary.text_difference_ratios;
  const onReview = (status: 'CONFIRMED' | 'UNRESOLVED', text: string | null) => {
    if (!selectedBlock) return;
    const blockId = selectedBlock.id;
    const draftText = confirmedTextDrafts[blockId] ?? selectedBlock.confirmed_text ?? selectedBlock.test_text;
    const draftRevision = confirmedTextDraftRevisions.current[blockId] ?? 0;
    reviewMutation.mutate({ comparisonId, blockId, draftText: text ?? draftText, draftRevision,
      savesDraft: status === 'CONFIRMED', body: {
      expected_version: selectedBlock.review_version, review_status: status,
      confirmed_text: text, include_reference_sample: status === 'CONFIRMED' && includeSample,
    } });
  };
  const suggestions = suggestionsQuery.data ?? [];
  const modelOptions = (modelsQuery.data ?? []).map((item) => ({ value: item.id, label: `${item.label} · ${item.model_name}` }));

  return (
    <AsrFrame title={`${comparison.audio?.name ?? '识别结果'} · 对比 v${comparison.version}`} projectId={comparison.project_id}>
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Space wrap>
          <Tag color={comparison.status === 'COMPLETE' ? 'blue' : 'orange'}>{comparison.status === 'COMPLETE' ? '三方结果齐备' : '结果不完整'}</Tag>
          <Typography.Text>批次 ASR-{comparison.job_id}</Typography.Text>
          {comparison.audio && <Typography.Text type="secondary">音频版本 v{comparison.audio.content_version}</Typography.Text>}
          <Typography.Text type="secondary">文本差异比例：待测/A {ratioLabel(ratio.test_vs_reference_a)} · 待测/B {ratioLabel(ratio.test_vs_reference_b)} · A/B {ratioLabel(ratio.reference_a_vs_reference_b)}</Typography.Text>
          <Dropdown menu={{
            items: [
              { key: 'json', label: 'JSON（完整数据）' },
              { key: 'csv', label: 'CSV（差异表格）' },
            ],
            onClick: ({ key }) => exportMutation.mutate(key as 'json' | 'csv'),
          }}>
            <Button size="small" icon={<DownloadOutlined />} loading={exportMutation.isPending}>导出 <DownOutlined /></Button>
          </Dropdown>
          {comparison.models.map((model) => (
            <Link key={model.run_id} to={`/console/asr/runs/${model.run_id}`}>
              <Button size="small">{model.name} · 单模型工作台</Button>
            </Link>
          ))}
        </Space>
        <Alert type="info" showIcon message="三方一致仅表示识别文本相同，不能证明正确；当前没有标准转写文本，不计算准确率。" />
        {comparison.degraded && <Alert type="warning" showIcon message={comparison.summary.degradation_reason ?? '文本过长，本次对齐已降级；全文仍保留。'} />}
        <Card size="small" title={<Space><SoundOutlined />音频回听与差异定位</Space>}>
          {comparison.audio ? <>
            <audio ref={audioRef} className="asr-audio" controls preload="none" src={comparison.audio.media_url ?? undefined}
              onLoadStart={() => setAudioPlaybackError('')} onPlay={() => setAudioPlaybackError('')}
              onError={() => setAudioPlaybackError('音频无法播放。请检查来源、网络或浏览器格式支持；识别文本和人工校对记录仍可查看。')} />
            {audioPlaybackError && <Alert type="error" showIcon message={audioPlaybackError} />}
            <Space wrap>
              <Button icon={<ArrowLeftOutlined />} onClick={() => { if (audioRef.current) audioRef.current.currentTime = Math.max(0, audioRef.current.currentTime - 10); }}>后退 10 秒</Button>
              <Button icon={<ArrowRightOutlined />} onClick={() => { if (audioRef.current) audioRef.current.currentTime += 10; }}>前进 10 秒</Button>
              <Select aria-label="播放倍速" defaultValue={1} style={{ width: 110 }} options={[0.75, 1, 1.25, 1.5, 2].map((value) => ({ value, label: `${value}×` }))}
                onChange={(value) => { if (audioRef.current) audioRef.current.playbackRate = value; }} />
              <Button disabled={!blocks.length} onClick={() => moveSelection(-1)}>上一差异</Button>
              <Button disabled={!blocks.length} onClick={() => moveSelection(1)}>下一差异</Button>
              <Typography.Text type="secondary">快捷键：空格播放/暂停，←/→ 前后 10 秒，[ / ] 上下差异</Typography.Text>
            </Space>
          </> : <Empty description="音频资源已不可用" />}
        </Card>
        <Space wrap>
          <Typography.Text>查看片段</Typography.Text>
          <Select value={filter} style={{ width: 190 }} onChange={(value) => { setFilter(value); setPage(1); setSelectedId(null); }} options={[
            { value: 'DIFFERENCES', label: '全部差异' }, { value: 'PENDING_REVIEW', label: '待人工确认' },
            { value: 'AGREEMENT_SAMPLE', label: '一致片段抽查' }, { value: 'CONFIRMED', label: '已确认' }, { value: 'ALL', label: '全部片段' },
          ]} />
          <Typography.Text type="secondary">{blocksQuery.data?.total ?? 0} 个片段；同一音频片段按文本锚点对齐，时间定位来源独立标注。</Typography.Text>
        </Space>
        {blocksQuery.isError ? <ErrorState error={blocksQuery.error} onRetry={blocksQuery.refetch} />
          : blocksQuery.isPending ? <Spin />
            : blocks.length === 0 ? <Empty description={comparison.status === 'INCOMPLETE' ? '至少两家识别成功后才会生成可对照片段。' : '当前筛选下没有片段。'} />
              : <div className="asr-results-workspace">
                <div className="asr-results-main">
                  {selectedBlock && <Card size="small" className="asr-selected-diff" title={`片段 ${selectedBlock.ordinal + 1} · ${selectedBlock.review_status === 'CONFIRMED' ? '已确认' : selectedBlock.review_status === 'UNRESOLVED' ? '暂无法确认' : '待确认'}`}>
                    <div className="asr-triplet-grid">
                      {[
                        ['待测模型', selectedBlock.test_text], ['参考模型 A', selectedBlock.reference_a_text], ['参考模型 B', selectedBlock.reference_b_text],
                      ].map(([label, text]) => <Card key={label} size="small" className="asr-model-card" title={label}>
                        <Typography.Paragraph className="asr-transcript-cell">{text || '（空文本）'}</Typography.Paragraph>
                      </Card>)}
                    </div>
                    <Space wrap>
                      {selectedBlock.labels.map((label) => <Tag key={label}>{label === 'THREE_WAY_AGREEMENT' ? '三方文本一致 · 仍需抽查' : label === 'SUSPICIOUS_OMISSION' ? '待测文本为空，需回听' : '文本存在差异'}</Tag>)}
                      <Tag color={selectedBlock.timing_source === 'PROVIDER' ? 'blue' : 'default'}>
                        {selectedBlock.timing_source === 'PROVIDER' ? `供应方时间戳${selectedBlock.timing_role ? ` · ${selectedBlock.timing_role}` : ''}` : '未定位'}
                      </Tag>
                      {selectedBlock.start_seconds != null && <Button size="small" icon={<PlayCircleOutlined />} onClick={() => seekToBlock(selectedBlock)}>跳到 {selectedBlock.start_seconds.toFixed(2)} 秒</Button>}
                    </Space>
                  </Card>}
                  {selectedBlock && <Card size="small" title="人工确认">
                    {Object.prototype.hasOwnProperty.call(confirmedTextDrafts, selectedBlock.id) && <Alert type="warning" showIcon message="此片段有未保存的人工文本草稿；切换片段后仍会保留。" />}
                    <Space wrap>
                      <Button size="small" onClick={() => setConfirmedText(selectedBlock.test_text)}>采用待测文本</Button>
                      <Button size="small" onClick={() => setConfirmedText(selectedBlock.reference_a_text)}>采用参考 A</Button>
                      <Button size="small" onClick={() => setConfirmedText(selectedBlock.reference_b_text)}>采用参考 B</Button>
                    </Space>
                    <Input.TextArea value={confirmedText} onChange={(event) => setConfirmedText(event.target.value)} autoSize={{ minRows: 3, maxRows: 8 }} maxLength={100000} aria-label="人工确认文本" />
                    <label className="asr-reference-checkbox"><input type="checkbox" checked={includeSample} onChange={(event) => setIncludeSample(event.target.checked)} />将此人工确认片段加入校对集</label>
                    <Space wrap>
                      <Button type="primary" icon={<CheckOutlined />} loading={reviewMutation.isPending} onClick={() => onReview('CONFIRMED', confirmedText)}>保存人工确认</Button>
                      <Button loading={reviewMutation.isPending} onClick={() => onReview('UNRESOLVED', null)}>暂无法确认</Button>
                      {selectedBlock.review_status !== 'UNREVIEWED' && <Typography.Text type="secondary">当前复核版本 v{selectedBlock.review_version}</Typography.Text>}
                    </Space>
                  </Card>}
                  {blocks.map((block) => <Button key={block.id} className={`asr-diff-row${selectedBlock?.id === block.id ? ' is-selected' : ''}`} onClick={() => { setSelectedId(block.id); seekToBlock(block); }}>
                    <Space wrap><Tag>片段 {block.ordinal + 1}</Tag><Typography.Text>{block.test_text.slice(0, 100) || '（待测文本为空）'}</Typography.Text>
                      {block.review_status === 'CONFIRMED' && <Tag color="blue">已确认</Tag>}{block.review_status === 'UNRESOLVED' && <Tag>暂无法确认</Tag>}</Space>
                  </Button>)}
                  {(blocksQuery.data?.total ?? 0) > 100 && <Pagination current={page} pageSize={100} total={blocksQuery.data?.total} onChange={setPage} showSizeChanger={false} />}
                  {selectedBlock && <Collapse items={[{
                    key: 'review-history', label: '查看人工确认历史',
                    children: historyQuery.isPending ? <Spin />
                      : historyQuery.isError ? <ErrorState error={historyQuery.error} onRetry={historyQuery.refetch} />
                        : (historyQuery.data ?? []).length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该片段还没有人工确认记录" />
                          : <Space direction="vertical" style={{ display: 'flex' }}>
                            {(historyQuery.data ?? []).map((item) => <Card key={item.version} size="small">
                              <Space wrap><Tag>v{item.version}</Tag><Tag>{item.review_status === 'CONFIRMED' ? '人工确认' : '暂无法确认'}</Tag>
                                <Typography.Text>{item.reviewer}</Typography.Text>
                                <Typography.Text type="secondary">{formatDateTime(item.created_at)}</Typography.Text>
                                {item.include_reference_sample && <Tag color="blue">已加入校对集</Tag>}</Space>
                              {item.confirmed_text != null && <Typography.Paragraph className="asr-transcript-cell">{item.confirmed_text || '（确认无语音）'}</Typography.Paragraph>}
                            </Card>)}
                          </Space>,
                  }]} />}
                </div>
                <div className="asr-suggestion-panel">
                  <Card size="small" title="调参建议">
                    <Typography.Paragraph className="asr-muted-note">只引用已确认差异及当前参数方案中真实定义的字段。建议是待验证假设，不表示已改善。</Typography.Paragraph>
                    {modelsQuery.isError && <Alert type="warning" message="无法读取已授权文本模型配置；人工复核不受影响。" />}
                    <Select allowClear value={modelConfigId} onChange={setModelConfigId} placeholder="选择已授权文本模型" style={{ width: '100%', marginBottom: 10 }} options={modelOptions} />
                    <Button block type="primary" loading={suggestionMutation.isPending} disabled={!modelConfigId || comparison.summary.reviewed_blocks === 0 || modelsQuery.isError || modelsQuery.isPending}
                      onClick={() => suggestionMutation.mutate()}>根据已确认片段生成建议</Button>
                    {suggestionJobsQuery.isError && <ErrorState error={suggestionJobsQuery.error} onRetry={suggestionJobsQuery.refetch} />}
                    {(suggestionJobsQuery.data ?? []).map((job) => <Card key={job.id} size="small" title={`建议任务 #${job.id}`}>
                      <Space direction="vertical" style={{ display: 'flex' }}>
                        <Tag color={job.status === 'SUCCEEDED' ? 'green' : job.status === 'FAILED' ? 'red' : job.status === 'RECONCILIATION_REQUIRED' ? 'orange' : 'blue'}>
                          {suggestionJobStatusLabel(job.status)}
                        </Tag>
                        {job.status === 'SUCCEEDED' && <Typography.Text type="secondary">
                          来源：{job.result.source === 'MODEL' ? '文本模型' : job.result.source === 'RULE_FALLBACK' ? '规则降级' : '无可验证建议'}；{job.result.message ?? ''}
                        </Typography.Text>}
                        {(job.status === 'QUEUED' || job.status === 'RUNNING') && <Typography.Text type="secondary">后台任务已持久化，可离开或刷新页面；恢复后会继续显示状态。</Typography.Text>}
                        {job.status === 'FAILED' && <>
                          <Typography.Text type="danger">{job.error_message ?? '任务执行失败'}</Typography.Text>
                          <Button size="small" loading={retrySuggestionMutation.isPending && retrySuggestionMutation.variables === job.id}
                            onClick={() => retrySuggestionMutation.mutate(job.id)}>按原证据和参数版本重试</Button>
                        </>}
                        {job.status === 'RECONCILIATION_REQUIRED' && <Typography.Text type="warning">{job.error_message}请先核实模型服务端是否已处理；平台不会自动重放此请求。</Typography.Text>}
                      </Space>
                    </Card>)}
                    {suggestionsQuery.isError && <ErrorState error={suggestionsQuery.error} onRetry={suggestionsQuery.refetch} />}
                    {suggestions.map((item) => <Card key={item.id} size="small" className="asr-suggestion-card">
                      <Typography.Text strong>{item.observation}</Typography.Text>
                      <Typography.Paragraph>{item.evidence}</Typography.Paragraph>
                      <Typography.Paragraph>{item.rationale}</Typography.Paragraph>
                      <Typography.Text code>{item.parameter_path ?? '排查方向'}</Typography.Text>
                      {item.parameter_path && <Typography.Paragraph>当前值：{JSON.stringify(item.current_value)} → 候选值：{item.candidate_value == null ? '仅方向，需依据接口文档确认' : JSON.stringify(item.candidate_value)}</Typography.Paragraph>}
                      <Typography.Paragraph type="secondary">验证：{item.validation_steps}</Typography.Paragraph>
                      {item.parameter_path && item.candidate_value != null && <Button size="small" onClick={() => {
                        setCandidatePath(item.parameter_path ?? undefined);
                        setCandidateValue(JSON.stringify(item.candidate_value));
                      }}>基于此建议创建候选实验</Button>}
                    </Card>)}
                    {!suggestions.length && !suggestionsQuery.isPending && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无建议；先人工确认差异，再根据已配置模型生成。" />}
                    {parameterSet && <>
                      <Typography.Title level={5}>手动创建候选参数</Typography.Title>
                      <Checkbox checked={reuseReferenceResults} onChange={(event) => setReuseReferenceResults(event.target.checked)}>
                        复用本对比的两家参考结果
                      </Checkbox>
                      <Typography.Paragraph type="secondary" className="asr-muted-note">
                        默认重新请求。仅在两条参考均成功且平台音频资源版本未变时可选用；同一 URL 不证明远端内容未替换，启用前请确认内容相同。复用来源会记入任务快照，参考结果仍不是标准答案。
                      </Typography.Paragraph>
                      <Select allowClear value={candidatePath} onChange={setCandidatePath} placeholder="选择已定义参数" style={{ width: '100%', marginBottom: 8 }} options={parameterSet.definitions.map((item) => ({ value: item.path, label: `${item.display_name} · ${item.path}` }))} />
                      <Input.TextArea value={candidateValue} onChange={(event) => setCandidateValue(event.target.value)} placeholder="候选值 JSON，例如 0.35 或 true" rows={2} />
                      <Button block style={{ marginTop: 8 }} loading={experimentMutation.isPending} disabled={!candidatePath || !candidateValue}
                        onClick={() => createCandidate(candidatePath, candidateValue, `基于对比 ${comparison.id} 的人工候选参数修改`)}>创建候选版本</Button>
                    </>}
                  </Card>
                </div>
              </div>}
        <Collapse items={[{
          key: 'content-review', label: '内容评审摘要与证据',
          children: <ContentReviewPanel kind="comparisons" resourceId={comparison.id} projectId={comparison.project_id} />,
        }]} />
      </Space>
    </AsrFrame>
  );
}
