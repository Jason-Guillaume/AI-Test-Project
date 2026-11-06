// ASR 内容评审面板：与单运行、三方对比及实验页组合，显示覆盖和可核验证据。
// 模型意见不会写入人工确认；输入与原回复通过项目授权的产物接口下载。
import { App, Button, Card, Collapse, Empty, Pagination, Select, Space, Tag, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { asrEvaluationApi, asrQueryKeys } from '@/features/asr-evaluation/api/asrEvaluation';
import { hasReviewTime, reviewTimeLabel } from '@/features/asr-evaluation/components/reviewEvidenceTime.mjs';
import { getErrorMessage } from '@/shared/api/client';

interface Props {
  kind: 'runs' | 'comparisons' | 'experiments';
  resourceId: number;
  projectId: number;
}

function reviewStatusLabel(status: string): string {
  return ({ QUEUED: '排队中', RUNNING: '评审中', SUCCEEDED: '已完成', FAILED: '失败',
    RECONCILIATION_REQUIRED: '状态待核实', CANCELLED: '已取消' } as Record<string, string>)[status] ?? status;
}

function coverageLabel(status: string): string {
  return ({ COMPLETE: '覆盖全部证据', PARTIAL: '部分覆盖', UNAVAILABLE: '无法评审', NONE: '无可评审内容' } as Record<string, string>)[status] ?? '未报告覆盖状态';
}

function verdictLabel(value: string): string {
  return ({ candidate_better: '候选文本较好（模型意见）', baseline_better: '基线文本较好（模型意见）',
    tie: '模型判断持平', inconclusive: '模型无法判断', comparison: '比较性评审', reviewed: '单运行评审', CONSISTENT: '未发现明显差异',
    DIVERGENT: '存在需要复核的差异' } as Record<string, string>)[value] ?? `模型意见：${value}`;
}

function dimensionLabel(value: string): string {
  const labels: Record<string, string> = {
    OMISSION: '遗漏', INSERTION: '增补', SUBSTITUTION: '替换', REPETITION: '重复',
    SEGMENTATION: '分段', SPEAKER: '说话人', TIMING: '时间定位', CONTENT: '内容', FLUENCY: '流畅度', OTHER: '其他',
  };
  return labels[value] ?? value;
}

/** 展示后台内容评审，创建和重试只操作评审任务，失败由页面提示。 */
export function ContentReviewPanel({ kind, resourceId, projectId }: Props) {
  const { message } = App.useApp();
  const client = useQueryClient();
  const [modelId, setModelId] = useState<number>();
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<number | null>(null);
  const previousStatuses = useRef<Record<number, string>>({});
  const key = asrQueryKeys.project(projectId, 'content_review', kind, resourceId);
  const reviews = useQuery({
    queryKey: [...key, 'page', page], queryFn: ({ signal }) => asrEvaluationApi.listContentReviews(kind, resourceId, signal, page),
    refetchInterval: (query) => query.state.data?.items.some((item) => ['QUEUED', 'RUNNING'].includes(item.status)) ? 3000 : false,
  });
  const invalidateBatchViews = (jobId: number) => {
    void client.invalidateQueries({ queryKey: ['asr', 'job-content-review-summary', projectId, jobId] });
    void client.invalidateQueries({ queryKey: ['asr', 'job-audio-groups', projectId, jobId] });
  };
  useEffect(() => {
    const rows = reviews.data?.items ?? [];
    for (const row of rows) {
      const previous = previousStatuses.current[row.id];
      if (previous && ['QUEUED', 'RUNNING'].includes(previous) && !['QUEUED', 'RUNNING'].includes(row.status)) {
        invalidateBatchViews(row.job_id);
      }
      previousStatuses.current[row.id] = row.status;
    }
  }, [client, projectId, reviews.data?.items]);
  const detail = useQuery({
    queryKey: [...key, 'detail', openId], enabled: openId !== null,
    queryFn: ({ signal }) => asrEvaluationApi.getContentReview(openId!, signal),
    refetchInterval: (query) => ['QUEUED', 'RUNNING'].includes(query.state.data?.status ?? '') ? 3000 : false,
  });
  const models = useQuery({
    queryKey: asrQueryKeys.project(projectId, 'content-review-models'),
    queryFn: async ({ signal }) => (await asrEvaluationApi.listReviewModels(projectId, signal)).items,
  });
  const create = useMutation({
    mutationFn: () => asrEvaluationApi.createContentReview(kind, resourceId, modelId!),
    onSuccess: (data) => { message.success('内容评审已加入后台队列'); setPage(1); setOpenId(data.id); void client.invalidateQueries({ queryKey: key }); invalidateBatchViews(data.job_id); },
    onError: (error) => message.error(getErrorMessage(error, '创建内容评审失败')),
  });
  const retry = useMutation({
    mutationFn: ({ id, chunkId }: { id: number; chunkId?: number }) => asrEvaluationApi.retryContentReview(id, chunkId),
    onSuccess: (data) => { message.success('明确失败的评审块已重新排队'); void client.invalidateQueries({ queryKey: key }); invalidateBatchViews(data.job_id); },
    onError: (error) => message.error(getErrorMessage(error, '评审块无法重试')),
  });
  const download = useMutation({
    mutationFn: (id: number) => asrEvaluationApi.downloadEvaluationArtifact(id),
    onSuccess: (blob, id) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `asr-review-artifact-${id}`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
    onError: () => message.error('资料下载失败或完整性校验失败'),
  });
  const cancel = useMutation({
    mutationFn: (id: number) => asrEvaluationApi.cancelContentReview(id),
    onSuccess: (data) => { message.info('已请求停止后续评审块；已发送的请求可能仍在处理。'); void client.invalidateQueries({ queryKey: key }); invalidateBatchViews(data.job_id); },
    onError: (error) => message.error(getErrorMessage(error, '无法停止评审任务')),
  });
  return <Card size="small" title="模型内容评审">
    <Space direction="vertical" style={{ display: 'flex' }}>
      <Typography.Text type="secondary">模型意见独立于程序差异和人工确认；没有标准答案时不表示识别正确率。</Typography.Text>
      <Space wrap>
        <Select aria-label="内容评审模型" placeholder="选择文本模型" value={modelId} onChange={setModelId}
          style={{ minWidth: 240 }} loading={models.isPending}
          options={(models.data ?? []).map((model) => ({ value: model.id, label: `${model.label} · ${model.model_name}` }))} />
        <Button type="primary" disabled={!modelId || models.isError} loading={create.isPending} onClick={() => create.mutate()}>创建内容评审</Button>
      </Space>
      {models.isError && <Typography.Text type="danger">文本模型列表读取失败。</Typography.Text>}
      {reviews.isError && <Typography.Text type="danger">内容评审列表读取失败。</Typography.Text>}
      {reviews.data?.items.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无内容评审" />}
      {(reviews.data?.items ?? []).map((summary) => {
        const opened = openId === summary.id;
        const review = opened && detail.data?.id === summary.id ? detail.data : summary;
        const findings = opened && detail.data?.id === summary.id
          ? detail.data.chunks.flatMap((chunk) => (chunk.result.findings ?? []).map((finding) => ({ chunk, finding }))) : [];
        const verdicts = opened && detail.data?.id === summary.id
          ? [...new Set(detail.data.chunks.map((chunk) => chunk.result.verdict).filter((item): item is string => Boolean(item)))] : [];
        return <Card key={review.id} size="small" title={`内容评审 #${review.id}`}>
        <Space direction="vertical" style={{ display: 'flex' }}>
          <Space wrap>
            <Tag color={review.status === 'SUCCEEDED' ? 'green' : review.status === 'FAILED' ? 'red' : review.status === 'RECONCILIATION_REQUIRED' ? 'orange' : 'blue'}>{reviewStatusLabel(review.status)}</Tag>
            <Tag>{coverageLabel(review.coverage_status)} · {review.completed_chunks}/{review.total_chunks} 块</Tag>
            {review.covered_evidence !== null && <Tag>核心证据 {review.covered_evidence}/{review.total_evidence ?? '未报告'}</Tag>}
          </Space>
          <Typography.Text type="secondary">模型评审意见独立于程序差异和人工确认；覆盖情况不表示准确率。</Typography.Text>
          <Button size="small" onClick={() => setOpenId(opened ? null : review.id)}>{opened ? '收起证据详情' : '查看发现与证据'}</Button>
          {opened && detail.isError && <Typography.Text type="danger">评审详情读取失败。</Typography.Text>}
          {opened && detail.isPending && <Typography.Text type="secondary">正在读取评审详情…</Typography.Text>}
          {opened && detail.data?.id === summary.id && <Card size="small" title="评审结论与证据摘要">
            <Space direction="vertical" style={{ display: 'flex' }}>
              <Space wrap>{verdicts.length ? verdicts.map((item) => <Tag key={item}>{verdictLabel(item)}</Tag>) : <Tag>模型未提供结论</Tag>}
                <Tag>{findings.length} 条发现</Tag>
                <Tag>{findings.reduce((sum, item) => sum + item.finding.evidence.length, 0)} 条证据引用</Tag>
              </Space>
              {findings.slice(0, 5).map(({ chunk, finding }, index) => <div key={`${chunk.id}:${index}`}>
              <Typography.Text strong>{dimensionLabel(finding.dimension)}：</Typography.Text>{finding.description}
                <Space wrap>{finding.evidence.map((evidence) => <Link key={evidence.id} to={`/console/asr/runs/${evidence.run_id}/listen${hasReviewTime(evidence.start_ms) ? `?start_ms=${evidence.start_ms}` : ''}`}>
                  {evidence.id}{!hasReviewTime(evidence.start_ms) ? ' · 未定位' : ` · ${reviewTimeLabel(evidence.start_ms)}`}
                </Link>)}</Space>
              </div>)}
              {!findings.length && <Typography.Text type="secondary">当前模型回复没有结构化发现；请结合原文与来源资料人工判断。</Typography.Text>}
            </Space>
          </Card>}
          {opened && <Collapse items={[{ key: 'review-metadata', label: '处理记录', children: <Space wrap>
            <Typography.Text>评审模型 #{review.model_config_id}</Typography.Text>
            <Typography.Text>配置修订 {review.model_revision ?? '未报告'}</Typography.Text>
            <Typography.Text>提示词版本 {review.prompt_version}</Typography.Text>
            <Typography.Text>请求尝试 {review.attempts}</Typography.Text>
          </Space> }]} />}
          {review.error_message && <Typography.Text type="warning">{review.error_message}</Typography.Text>}
          {['QUEUED', 'RUNNING'].includes(review.status) && <Button size="small" disabled={review.cancel_requested}
            loading={cancel.isPending} onClick={() => cancel.mutate(review.id)}>{review.cancel_requested ? '正在停止后续块' : '停止后续评审'}</Button>}
          <Space wrap>{review.source_artifact_ids.map((id, index) => <Button size="small" key={id} onClick={() => download.mutate(id)}>
            下载来源 {Math.floor(index / 2) + 1} {index % 2 === 0 ? 'JSON' : 'Markdown'}</Button>)}</Space>
          {review.report_artifact_id && <Button size="small" onClick={() => download.mutate(review.report_artifact_id!)}>下载结构化报告</Button>}
          {review.failed_chunks > 0 && <Button size="small" loading={retry.isPending}
            disabled={!['FAILED', 'SUCCEEDED'].includes(review.status)} onClick={() => retry.mutate({ id: review.id })}>重试全部失败块</Button>}
          {opened && <Collapse items={[{ key: 'review-chunks', label: `技术明细（${review.chunks.length} 块）`, children: <Space direction="vertical" style={{ display: 'flex' }}>
          {review.chunks.map((chunk) => <Card key={chunk.id} size="small" title={`评审块 ${chunk.ordinal + 1} · ${reviewStatusLabel(chunk.status)}`}>
            <Space direction="vertical" style={{ display: 'flex' }}>
              <Typography.Text type="secondary">{chunk.scope.kind === 'TIME' && chunk.scope.window_start_ms !== null && chunk.scope.window_end_ms !== null
                ? `窗口 ${reviewTimeLabel(chunk.scope.window_start_ms)}–${reviewTimeLabel(chunk.scope.window_end_ms)}` : '无可靠时间，无法精确回听'}</Typography.Text>
              {chunk.error_message && <Typography.Text type="warning">{chunk.error_message}</Typography.Text>}
              {chunk.uncovered_evidence?.length > 0 && <Typography.Text type="warning">未覆盖证据：{chunk.uncovered_evidence.map((item) => `${item.id}（片段内偏移 ${item.piece_offset}，${item.character_count} 字符）`).join('、')}</Typography.Text>}
              {chunk.status === 'FAILED' && <Button size="small" disabled={!['FAILED', 'SUCCEEDED'].includes(review.status)}
                onClick={() => retry.mutate({ id: review.id, chunkId: chunk.id })}>只重试此块</Button>}
              {chunk.result.verdict && <Tag>模型结论：{verdictLabel(chunk.result.verdict)}</Tag>}
              {chunk.result.input_bytes !== undefined && <Typography.Text type="secondary">实际输入 {chunk.result.input_bytes} 字节 · 模型 token 用量 {chunk.result.usage?.total_tokens ?? '未报告'}</Typography.Text>}
              {chunk.result.speaker_mapping && <Typography.Text type="secondary">
                标签映射：{chunk.result.speaker_mapping.status === 'MAPPED' ? '已建立映射' : '对应关系不明确'}；{chunk.result.speaker_mapping.reason}
                {chunk.result.speaker_mapping.pairs.map((pair) => ` ${pair.left_run}:${pair.left_label} ↔ ${pair.right_run}:${pair.right_label}（重叠 ${pair.overlap_score}）`).join('、')}
              </Typography.Text>}
              {(chunk.result.findings ?? []).map((finding, index) => <div key={index}>
                <Typography.Text strong>{dimensionLabel(finding.dimension)}：</Typography.Text>{finding.description}
                {finding.evidence.map((item, evidenceIndex) => <div key={`${item.id}:${evidenceIndex}`}>
                  <Typography.Text>“{item.quote}” </Typography.Text>
                  <Link to={`/console/asr/runs/${item.run_id}/listen${hasReviewTime(item.start_ms) ? `?start_ms=${item.start_ms}` : ''}`}>
                    {item.id}{!hasReviewTime(item.start_ms) ? ' · 未定位' : ` · ${reviewTimeLabel(item.start_ms)}${!hasReviewTime(item.end_ms) ? '' : `–${reviewTimeLabel(item.end_ms)}`}`}
                  </Link>
                </div>)}
              </div>)}
              {(chunk.result.limitations ?? []).map((limit) => <Typography.Text type="secondary" key={limit}>{limit}</Typography.Text>)}
              <Space wrap>
                {chunk.input_artifact_id && <Button size="small" onClick={() => download.mutate(chunk.input_artifact_id!)}>下载实际输入</Button>}
                {chunk.response_artifact_id && <Button size="small" onClick={() => download.mutate(chunk.response_artifact_id!)}>下载模型回复（可能脱敏）</Button>}
              </Space>
            </Space>
          </Card>)}
          </Space> }]} />}
        </Space>
      </Card>; })}
      {(reviews.data?.total ?? 0) > 20 && <Pagination current={page} total={reviews.data?.total} pageSize={20} showSizeChanger={false}
        onChange={(next) => { setPage(next); setOpenId(null); }} />}
    </Space>
  </Card>;
}
