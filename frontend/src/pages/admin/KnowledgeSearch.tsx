import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Drawer, Empty, Input, InputNumber, Space, Spin, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { api, getErrorMessage } from '@/shared/api/client';

type Source = {
  chunk_id: number;
  version_id: number;
  version: number;
  document_name: string;
  score: number;
  score_type: string;
  page: number | null;
  position: number;
  text: string;
};

type SearchResult = {
  items: Source[];
  snapshot?: { access_mode: 'PROJECT_SHARED' | 'AGENT_SCOPED'; revision: number };
  retrieval: {
    strategy: string;
    candidate_count: number;
    candidate_limit: number;
    candidate_truncated: boolean;
    vector_candidate_count: number;
    vector_candidate_limit?: number | null;
    fusion_candidate_count?: number;
    fusion_candidate_limit?: number | null;
    rerank_candidate_count?: number;
    rerank_candidate_limit?: number | null;
    result_count: number;
    duration_ms: number;
    vector_status: string;
    reranker_status: string;
  };
};

type SearchState = { question: string; result?: SearchResult; error?: string };

export function KnowledgeSearch({ endpoint, scopeLabel, query, onQuery, disabled }: {
  endpoint: string;
  scopeLabel: string;
  query: string;
  onQuery: (value: string) => void;
  disabled: boolean;
}) {
  const controller = useRef<AbortController | null>(null);
  const [state, setState] = useState<SearchState>();
  const [topK, setTopK] = useState<number | null>(null);
  const [minimumScore, setMinimumScore] = useState<number | null>(0);
  const [candidateK, setCandidateK] = useState<number | null>(null);
  const [source, setSource] = useState<Source>();
  const detail = useQuery({
    queryKey: ['knowledge-source', endpoint, source?.chunk_id],
    enabled: source != null,
    retry: false,
    queryFn: ({ signal }) => api.get<{ id: number; version_id: number; text: string }>(
      `${endpoint}/knowledge-sources/${source!.chunk_id}`, { signal }),
  });
  useEffect(() => () => controller.current?.abort(), []);

  const search = async () => {
    if (disabled) return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    const question = query;
    setSource(undefined);
    setState({ question });
    try {
      const result = await api.post<SearchResult>(`${endpoint}/knowledge-search`, {
        query: question, top_k: topK, candidate_k: candidateK, minimum_score: minimumScore ?? 0,
      }, { signal: request.signal });
      if (!request.signal.aborted) setState({ question, result });
    } catch (error) {
      if (!request.signal.aborted) setState({ question, error: getErrorMessage(error, '请求失败') });
    }
  };

  const retrieval = state?.result?.retrieval;
  const scope = state?.result?.snapshot;
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Space wrap className="knowledge-search-controls">
      <Input aria-label="检索问题" placeholder="输入业务词、规则或字段" value={query}
        maxLength={4000} onChange={(event) => onQuery(event.target.value)} onPressEnter={search} />
      <Space.Compact><Space.Addon>Top‑K</Space.Addon><InputNumber aria-label="Top-K" placeholder="项目设置" min={1} max={50} value={topK} onChange={setTopK} /></Space.Compact>
      <Space.Compact><Space.Addon>最低分</Space.Addon><InputNumber aria-label="BM25 最低分" min={0} max={100} step={0.1} value={minimumScore} onChange={setMinimumScore} /></Space.Compact>
      <Space.Compact><Space.Addon>BM25 候选</Space.Addon><InputNumber aria-label="BM25 候选" placeholder="项目设置" min={1} max={5000} value={candidateK} onChange={setCandidateK} /></Space.Compact>
      <Button type="primary" disabled={disabled} onClick={search}>检索</Button>
    </Space>
    {state && <div style={{ overflowWrap: 'anywhere' }}>
      <Typography.Text strong>本次范围：{scopeLabel}{scope ? ` · ${scope.access_mode === 'AGENT_SCOPED' ? '限定资料' : '共享项目资料'} · 配置修订 ${scope.revision}` : ''}</Typography.Text>
      <div>本次问题：{state.question.trim() ? state.question : '浏览资料'}</div>
    </div>}
    {state && !state.result && !state.error && <div role="status"><Spin size="small" /> 检索中…</div>}
    {state?.error && <Alert type="error" showIcon message="检索失败，请重试" description={state.error} />}
    {retrieval && <Alert type="info" showIcon
      message={`${retrieval.strategy} · 命中 ${retrieval.result_count} · ${retrieval.duration_ms} ms`}
      description={<Space wrap size="small">
        <span>BM25 候选 {retrieval.candidate_count}/{retrieval.candidate_limit}{retrieval.candidate_truncated ? '（已截断）' : ''}</span>
        <span>向量 {retrieval.vector_status}（{retrieval.vector_candidate_count}/{retrieval.vector_candidate_limit ?? '—'}）</span>
        {retrieval.fusion_candidate_limit != null && <span>融合 {retrieval.fusion_candidate_count}/{retrieval.fusion_candidate_limit}</span>}
        <span>重排 {retrieval.reranker_status}{retrieval.rerank_candidate_limit != null ? `（${retrieval.rerank_candidate_count}/${retrieval.rerank_candidate_limit}）` : ''}</span>
      </Space>} />}
    {state?.result?.items.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前范围未找到匹配片段" />}
    {state?.result?.items.map((item) => <Card key={item.chunk_id} size="small">
      <Space direction="vertical" style={{ width: '100%', overflowWrap: 'anywhere' }}>
        <Typography.Text strong>{item.document_name} · v{item.version} · 版本 ID {item.version_id}</Typography.Text>
        <Typography.Text type="secondary">片段 {item.chunk_id} · {item.page ? `第 ${item.page} 页 · ` : ''}{item.score_type} {item.score.toFixed(6)}</Typography.Text>
        <div style={{ whiteSpace: 'pre-wrap' }}>{item.text}</div>
        <Button size="small" onClick={() => setSource(item)}>查看来源</Button>
      </Space>
    </Card>)}
    <Drawer open={source != null} title="片段来源" width="min(480px, 100vw)" onClose={() => setSource(undefined)}>
      {detail.isFetching && <Spin />}
      {detail.isError && <Alert type="error" showIcon message="当前范围无法读取此来源" description={getErrorMessage(detail.error)}
        action={<Button size="small" onClick={() => detail.refetch()}>重试</Button>} />}
      {source && !detail.isFetching && !detail.isError && detail.data?.version_id === source.version_id && <Space direction="vertical">
        <Typography.Title level={5}>{source.document_name} · v{source.version} · 版本 ID {source.version_id}</Typography.Title>
        <Typography.Text type="secondary">片段 {source.chunk_id}{source.page ? ` · 第 ${source.page} 页` : ''} · 文档内第 {source.position + 1} 段</Typography.Text>
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{detail.data.text}</Typography.Paragraph>
      </Space>}
    </Drawer>
  </Space>;
}
