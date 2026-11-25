import { useEffect } from 'react';
import { Alert, App, Button, Card, Form, Input, InputNumber, Select, Space, Switch, Table } from 'antd';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, getErrorMessage } from '@/shared/api/client';
import { modelCenterApi } from '@/features/model-configuration/api/modelCenter';

type Config = { enabled: boolean; active_generation_id: number | null; rerank_revision_id: number | null;
  bm25_candidates: number; vector_candidates: number; rerank_window: number; timeout_seconds: number; default_top_k: number;
  fusion_min_score?: number | null; rerank_min_score?: number | null };
type Generation = { id: number; embedding_revision_id: number; dimension: number; distance: string;
  encoding_version: string; state: string; vector_count: number; covered_count: number; eligible_count: number; jobs: Record<string, number> };
type Queue = { queued_count: number; oldest_wait_seconds: number | null; unknown_age_count: number;
  expired_lease_count?: number; oldest_expired_seconds?: number | null };
type State = { config: Config | null; generations: Generation[]; queues?: { parse: Queue; vector: Queue } };
type GenerationForm = { embedding_revision_id: number; dimension: number; distance: string; encoding_version: string;
  document_input_type?: string; query_input_type?: string };

export function KnowledgeRetrieval({ projectId }: { projectId: number }) {
  const { message, modal } = App.useApp();
  const client = useQueryClient();
  const root = `/projects/${projectId}`;
  const [settings] = Form.useForm<Config>();
  const [generation] = Form.useForm<GenerationForm>();
  const state = useQuery({ queryKey: ['retrieval-config', projectId], refetchInterval: 5000,
    queryFn: () => api.get<State>(`${root}/knowledge-retrieval-config`) });
  const embeddings = useQuery({ queryKey: ['retrieval-models', projectId, 'embedding'],
    queryFn: () => modelCenterApi.available(projectId, 'EMBEDDING') });
  const rerankers = useQuery({ queryKey: ['retrieval-models', projectId, 'rerank'],
    queryFn: () => modelCenterApi.available(projectId, 'RERANK') });
  useEffect(() => {
    settings.setFieldsValue(state.data?.config || { enabled: false, rerank_revision_id: null,
      bm25_candidates: 50, vector_candidates: 50, rerank_window: 30, default_top_k: 8, timeout_seconds: 10 });
  }, [projectId, state.data?.config, settings]);
  const run = async (work: () => Promise<unknown>) => {
    try { await work(); message.success('已保存'); await client.invalidateQueries({ queryKey: ['retrieval-config', projectId] }); }
    catch (error) { message.error(getErrorMessage(error, '操作失败')); }
  };
  return <Card title="索引与模型" style={{ marginTop: 16 }}>
    <Alert type="info" showIcon message="先在模型中心配置并诊断检索模型；新索引代完成回填并验证后切换。旧代继续追平，可用于回滚。" />
    {state.isError && <Alert type="error" message={getErrorMessage(state.error, '检索配置加载失败')}
      action={<Button size="small" onClick={() => state.refetch()}>重试</Button>} />}
    <Space wrap style={{ marginTop: 12 }}>
      {(['parse', 'vector'] as const).map((kind) => {
        const queue = state.data?.queues?.[kind];
        return <div key={kind}>{kind === 'parse' ? '解析队列' : '向量队列'} {queue ? `${queue.queued_count} 项` : '未知'}
          {queue && queue.queued_count > 0 && ` · 最久等待 ${queue.oldest_wait_seconds == null ? '未知' : `${queue.oldest_wait_seconds} 秒`}`}
          {Boolean(queue?.expired_lease_count) && ` · 待回收 ${queue?.expired_lease_count} 项，最久过期 ${queue?.oldest_expired_seconds ?? '未知'} 秒`}</div>;
      })}
    </Space>
    <Form form={settings} layout="vertical" onFinish={(values) => run(() => api.put(`${root}/knowledge-retrieval-config`, values))}>
      <Space wrap align="start" style={{ marginTop: 12 }}>
        <Form.Item name="enabled" label="启用混合检索" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="rerank_revision_id" label="重排模型（可关闭）"><Select allowClear style={{ width: 200 }}
          options={(rerankers.data?.items || []).map((item) => ({ value: item.revision.id, label: item.display_name }))} /></Form.Item>
        <Form.Item name="bm25_candidates" label="BM25 候选" rules={[{ required: true }]}><InputNumber min={1} max={5000} /></Form.Item>
        <Form.Item name="vector_candidates" label="向量候选" rules={[{ required: true }]}><InputNumber min={1} max={5000} /></Form.Item>
        <Form.Item name="rerank_window" label="重排窗口" rules={[{ required: true }]}><InputNumber min={1} max={5000} /></Form.Item>
        <Form.Item name="default_top_k" label="默认返回数" rules={[{ required: true }]}><InputNumber min={1} max={50} /></Form.Item>
        <Form.Item name="timeout_seconds" label="超时（秒）" rules={[{ required: true }]}><InputNumber min={1} max={600} /></Form.Item>
        <Form.Item name="fusion_min_score" label="RRF 阈值（可选）"><InputNumber min={0} max={1} step={0.001} /></Form.Item>
        <Form.Item name="rerank_min_score" label="重排阈值（可选）"><InputNumber step={0.01} /></Form.Item>
      </Space>
      <Button htmlType="submit">保存检索配置</Button>
    </Form>
    <Form form={generation} layout="vertical" initialValues={{ distance: 'cosine' }}
      onFinish={(values) => run(() => api.post(`${root}/knowledge-index-generations`, values))}>
      <Space wrap align="start" style={{ marginTop: 16 }}>
        <Form.Item name="embedding_revision_id" label="向量模型" rules={[{ required: true }]}><Select style={{ width: 200 }}
          options={(embeddings.data?.items || []).map((item) => ({ value: item.revision.id, label: item.display_name }))} /></Form.Item>
        <Form.Item name="dimension" label="向量维度" rules={[{ required: true }]}><InputNumber min={1} max={16000} /></Form.Item>
        <Form.Item name="distance" label="距离" rules={[{ required: true }]}><Select style={{ width: 150 }} options={[
          { value: 'cosine', label: '余弦' }, { value: 'l2', label: '欧氏' }, { value: 'inner_product', label: '内积' }]} /></Form.Item>
        <Form.Item name="encoding_version" label="编码版本标记" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="document_input_type" label="文档输入模式（可选）"><Input /></Form.Item>
        <Form.Item name="query_input_type" label="查询输入模式（可选）"><Input /></Form.Item>
      </Space>
      <Button htmlType="submit" type="primary">创建索引代并回填</Button>
    </Form>
    <Table<Generation> style={{ marginTop: 16 }} rowKey="id" size="small" pagination={false} scroll={{ x: 'max-content' }}
      loading={state.isLoading} dataSource={state.data?.generations || []}
      columns={[
        { title: '索引代', dataIndex: 'id' }, { title: '模型修订', dataIndex: 'embedding_revision_id' },
        { title: '维度', dataIndex: 'dimension' }, { title: '距离', dataIndex: 'distance' },
        { title: '编码版本', dataIndex: 'encoding_version' }, { title: '状态', dataIndex: 'state' },
        { title: '向量数', dataIndex: 'vector_count' },
        { title: '向量覆盖', render: (_, row) => `${row.covered_count} / ${row.eligible_count}` },
        { title: '任务', render: (_, row) => Object.entries(row.jobs).map(([key, value]) => `${key}: ${value}`).join(' / ') || '无' },
        { title: '操作', render: (_, row) => <Space wrap>{['backfill', 'retry'].map((action) =>
          <Button key={action} size="small" disabled={row.state === 'RETIRED'} onClick={() => run(() => api.post(`${root}/knowledge-index-generations/${row.id}/commands`, { action }))}>
            {{ backfill: '补齐', retry: '重试失败' }[action]}</Button>)}
          <Button size="small" disabled={row.state === 'RETIRED' || row.state === 'ACTIVE'} onClick={() => modal.confirm({
            title: `切换到索引代 #${row.id}？`, content: '确认前请核对向量覆盖和同题评测结果。', okText: '确认切换', cancelText: '取消',
            onOk: () => run(() => api.post(`${root}/knowledge-index-generations/${row.id}/commands`, { action: 'activate' })),
          })}>切换 / 回滚</Button>
          {(row.state === 'BUILDING' || row.state === 'STANDBY') && <Button danger size="small" onClick={() => modal.confirm({
            title: `退役索引代 #${row.id}？`, content: '退役后该索引代不能再用于切换或回滚，未完成的向量任务将停止。',
            okText: '退役', cancelText: '取消', okButtonProps: { danger: true },
            onOk: () => run(() => api.post(`${root}/knowledge-index-generations/${row.id}/commands`, { action: 'retire' })),
          })}>退役</Button>}</Space> },
      ]} />
  </Card>;
}
