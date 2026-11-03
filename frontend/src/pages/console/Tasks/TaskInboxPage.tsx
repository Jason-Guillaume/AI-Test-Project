import { useEffect, useState } from 'react';
import { Button, Card, Col, Flex, Pagination, Row, Select, Space, Tag, Typography } from 'antd';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '@/features/tasks/api/tasks';
import type { TaskInboxCategory } from '@/features/tasks/contracts';
import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { fmtTime } from '@/shared/lib/format';

const CATEGORIES: { value: TaskInboxCategory; label: string }[] = [
  { value: 'approval', label: '待确认' },
  { value: 'model_blocked', label: '模型配置阻塞' },
  { value: 'failed', label: '失败待处理' },
  { value: 'reconcile', label: '待核对' },
];

export function ConsoleTaskInboxPage() {
  const { currentProjectId } = useConsoleScope();
  const [category, setCategory] = useState<TaskInboxCategory | undefined>();
  const [page, setPage] = useState(1);
  useEffect(() => { setPage(1); }, [currentProjectId]);
  const query = useQuery({
    queryKey: ['tasks', 'inbox', currentProjectId, category, page],
    queryFn: () => tasksApi.inbox({ project_id: currentProjectId ?? undefined, category, page, page_size: 20 }),
    refetchInterval: 10000,
  });
  useEffect(() => {
    const lastPage = Math.max(1, Math.ceil((query.data?.total ?? 0) / 20));
    if (page > lastPage) setPage(lastPage);
  }, [page, query.data?.total]);
  if (query.isPending) return <PageContainer><LoadingState /></PageContainer>;
  if (query.isError) return <PageContainer><ErrorState error={query.error} onRetry={query.refetch} /></PageContainer>;
  const data = query.data;
  return (
    <PageContainer>
      <PageHeader title="待我处理" subtitle="只汇总你发起且仍有权访问的最新任务运行；计数由服务端按完整范围计算。" />
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        {CATEGORIES.map(({ value, label }) => (
          <Col xs={12} md={6} key={value}>
            <Card size="small" hoverable onClick={() => { setCategory(value); setPage(1); }} aria-label={`筛选${label}`}>
              <Typography.Text type="secondary">{label}</Typography.Text><br />
              <Typography.Title level={4} style={{ margin: 0 }}>{data.counts[value]}</Typography.Title>
            </Card>
          </Col>
        ))}
      </Row>
      <Flex justify="space-between" align="center" wrap="wrap" gap={12} style={{ marginBottom: 12 }}>
        <Typography.Title level={5} style={{ margin: 0 }}>处理列表 · {data.total}</Typography.Title>
        <Select
          allowClear
          aria-label="待办类型"
          placeholder="所有类型"
          value={category}
          options={CATEGORIES}
          onChange={(value) => { setCategory(value); setPage(1); }}
          style={{ width: 220 }}
        />
      </Flex>
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        {data.items.map((item) => (
          <Card key={item.run_id} size="small">
            <Flex justify="space-between" align="start" wrap="wrap" gap={12}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <Space wrap><Typography.Text strong>{item.task_title}</Typography.Text><Tag>{CATEGORIES.find((entry) => entry.value === item.category)?.label}</Tag></Space>
                <Typography.Paragraph type="secondary" style={{ margin: '6px 0' }}>{item.reason}</Typography.Paragraph>
                <Typography.Text type="secondary">{item.project_name} · 运行 #{item.run_number} · {fmtTime(item.updated_at)}</Typography.Text>
                <div><Typography.Text>{item.next_action}</Typography.Text></div>
              </div>
              <Link to={`/console/tasks/${item.task_id}?runId=${item.run_id}`}><Button type="primary">打开并处理</Button></Link>
            </Flex>
          </Card>
        ))}
        {data.items.length === 0 && <Card><Typography.Text type="secondary">当前没有待处理任务</Typography.Text></Card>}
      </Space>
      <Pagination style={{ marginTop: 16, textAlign: 'right' }} current={page} pageSize={20} total={data.total} onChange={setPage} showSizeChanger={false} />
    </PageContainer>
  );
}
