import { App, Button, Card, Empty, Flex, List, Space, Tag, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { tasksApi } from '@/features/tasks/api/tasks';
import type { TaskTraceEvent } from '@/features/tasks/contracts';
import { fmtTime } from '@/shared/lib/format';

const EVENT_LABEL: Record<string, string> = {
  AGENT_RUN: '子 Agent 执行',
  AGENT_ATTEMPT: 'Agent 执行',
  MODEL_CALL: '模型调用',
  TOOL_CALL: '工具调用',
  KNOWLEDGE_RETRIEVAL: '知识检索',
  CONTEXT_ASSEMBLY: '上下文组装',
  SKILL_LOAD: 'Skill 加载',
};

function TraceEventRow({ event }: { event: TaskTraceEvent }) {
  const tone = event.status === 'FAILED' || event.status === 'ERROR'
    ? 'red'
    : event.status === 'SUCCEEDED' || event.status === 'COMPLETED' ? 'green' : 'blue';
  const usage = [
    event.input_tokens != null ? `输入 ${event.input_tokens}` : null,
    event.output_tokens != null ? `输出 ${event.output_tokens}` : null,
    event.total_tokens != null ? `合计 ${event.total_tokens} tokens` : null,
    event.cost_amount != null ? `${event.cost_amount} ${event.cost_currency ?? ''}`.trim() : null,
  ].filter(Boolean).join(' · ');
  const metadata = Object.keys(event.metadata ?? {}).length ? JSON.stringify(event.metadata) : null;
  const projectionTone = event.projection_status === 'FAILED' ? 'red'
    : event.projection_status === 'SUCCEEDED' ? 'green'
      : event.projection_status === 'RETRYING' ? 'orange' : 'default';
  return (
    <List.Item>
      <Flex vertical gap={4} style={{ width: '100%' }}>
        <Flex justify="space-between" align="flex-start" gap={12} wrap>
          <Space wrap>
            <Tag>{EVENT_LABEL[event.event_type] ?? event.event_type}</Tag>
            <Typography.Text strong>{event.event_name}</Typography.Text>
            <Tag color={tone}>{event.status}</Tag>
            <Tag color={projectionTone}>投影 {event.projection_status}</Tag>
            {event.agent_name && <Tag color="purple">{event.agent_name}{event.agent_role ? ` · ${event.agent_role}` : ''}</Tag>}
          </Space>
          <Typography.Text type="secondary">{fmtTime(event.occurred_at)}</Typography.Text>
        </Flex>
        <Space wrap size={[12, 4]}>
          <Typography.Text type="secondary">{event.duration_ms} ms</Typography.Text>
          {event.work_item_id != null && <Typography.Text type="secondary">Work #{event.work_item_id}</Typography.Text>}
          {event.attempt_id != null && <Typography.Text type="secondary">Attempt #{event.attempt_id}</Typography.Text>}
          {event.agent_instance_id != null && <Typography.Text type="secondary">Agent run #{event.agent_instance_id}</Typography.Text>}
          {event.agent_session_id != null && <Typography.Text type="secondary">Session #{event.agent_session_id}</Typography.Text>}
          {event.parent_agent_instance_id != null && <Typography.Text type="secondary">父 Agent #{event.parent_agent_instance_id}</Typography.Text>}
          {event.agent_definition_id != null && <Typography.Text type="secondary">Agent #{event.agent_definition_id}</Typography.Text>}
          {event.agent_definition_revision_id != null && <Typography.Text type="secondary">Revision #{event.agent_definition_revision_id}</Typography.Text>}
          {event.model_revision && <Typography.Text type="secondary">模型版本 {event.model_revision}</Typography.Text>}
          {usage && <Typography.Text type="secondary">{usage}</Typography.Text>}
          {event.error_code && <Typography.Text type="danger">错误码 {event.error_code}</Typography.Text>}
        </Space>
        {(event.span_id || metadata) && (
          <Space wrap>
            {event.span_id && <Typography.Text type="secondary" copyable={{ text: event.span_id }}>Span {event.span_id}</Typography.Text>}
            {metadata && <Typography.Text type="secondary">摘要：{metadata}</Typography.Text>}
          </Space>
        )}
      </Flex>
    </List.Item>
  );
}

export function TaskTraceTimeline({ runId, traceId, active }: { runId: number; traceId?: string | null; active: boolean }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const query = useInfiniteQuery({
    queryKey: ['task-trace', runId],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => tasksApi.trace(runId, pageParam),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: (current) => active && (current.state.data?.pages.length ?? 1) === 1 ? 5000 : false,
  });
  const events = query.data?.pages.flatMap((page) => page.items) ?? [];
  const currentTraceId = query.data?.pages[0]?.trace_id ?? traceId;
  const generationBatchId = query.data?.pages[0]?.generation_batch_id;
  const projection = query.data?.pages[0]?.projection;
  const replay = useMutation({
    mutationFn: () => tasksApi.replayTrace(runId),
    onSuccess: async (receipt) => {
      message.success(`已登记 ${receipt.registered} 条投影，重新排队 ${receipt.requeued} 条失败记录`);
      await queryClient.invalidateQueries({ queryKey: ['task-trace', runId] });
    },
    onError: () => message.error('投影重放失败，请检查项目写入权限'),
  });

  return (
    <Card
      size="small"
      title={`Agent Trace · ${events.length} 条时间线记录`}
      extra={(
        <Space wrap>
          {generationBatchId != null && <Typography.Text copyable code>生成批次 #{generationBatchId}</Typography.Text>}
          {currentTraceId && <Typography.Text copyable code>{currentTraceId}</Typography.Text>}
          {projection && <Tag color={projection.status === 'FAILED' ? 'red' : projection.status === 'SUCCEEDED' ? 'green' : 'orange'}>
            Langfuse {projection.status} · 待投影 {projection.counts.PENDING ?? 0} · 重试中 {projection.counts.RETRYING ?? 0} · 失败 {projection.counts.FAILED ?? 0}
          </Tag>}
          {projection && (projection.counts.FAILED ?? 0) > 0 && <Button size="small" loading={replay.isPending} onClick={() => replay.mutate()}>
            重放失败投影
          </Button>}
          <Button size="small" type="text" icon={<ReloadOutlined />} loading={query.isRefetching} onClick={() => void query.refetch()} aria-label="刷新 Trace" />
        </Space>
      )}
    >
      <Flex vertical gap={12}>
        <Typography.Text type="secondary">
          这里展示任务关联、Agent 执行、模型调用、工具与知识事件索引。Trace 正文由 Langfuse 保存；本页不复制提示词或工具参数。
        </Typography.Text>
        {projection?.last_error_code && <Typography.Text type="warning">最近投影错误：{projection.last_error_code}</Typography.Text>}
        {query.isError ? <Typography.Text type="danger">Trace 时间线加载失败</Typography.Text> : (
          <List
            size="small"
            dataSource={events}
            locale={{ emptyText: <Empty description={query.isLoading ? '正在读取 Trace' : '暂无 Trace 事件'} /> }}
            renderItem={(event) => <TraceEventRow key={event.id} event={event} />}
          />
        )}
        {query.hasNextPage && (
          <Button block loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
            加载更早的 Trace 记录
          </Button>
        )}
        {query.isError && <Button onClick={() => void query.refetch()}>重试</Button>}
      </Flex>
    </Card>
  );
}
