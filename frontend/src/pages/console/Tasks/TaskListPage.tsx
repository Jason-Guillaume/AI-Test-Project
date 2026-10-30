/**
 * 统一任务列表页面。
 * 导出 ConsoleTasksPage，由任务路由加载；依赖任务 API、控制台作用域和创建弹窗，不承载详情页运行状态。
 */
import { useEffect, useState } from 'react';
import { Button, Flex, Table, Tag, Typography } from 'antd';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { tasksApi } from '@/features/tasks/api/tasks';
import type { Task } from '@/features/tasks/contracts';
import { TaskCreateModal } from '@/widgets/task-assistant/TaskCreateModal';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { fmtTime } from '@/shared/lib/format';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { STATUS_LABEL } from './taskLabels';

/** 展示当前项目范围内的任务，并保留 URL 预填创建语义。 */
export function ConsoleTasksPage() {
  const { currentProjectId } = useConsoleScope();
  const [createOpen, setCreateOpen] = useState(false);
  const [taskPage, setTaskPage] = useState(1);
  const [taskPageSize, setTaskPageSize] = useState(20);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialProjectId = Number(searchParams.get('projectId')) || undefined;
  const initialCaseId = Number(searchParams.get('caseId')) || undefined;
  const requestedType = searchParams.get('type');
  const initialTargetType = requestedType === 'WEB' || requestedType === 'SECURITY' || requestedType === 'WEB_AUTHORING' ? requestedType : 'API';

  useEffect(() => {
    if (searchParams.get('create') === '1') setCreateOpen(true);
  }, [searchParams]);
  useEffect(() => { setTaskPage(1); }, [currentProjectId]);

  const tasksQuery = useQuery({
    queryKey: ['tasks', 'list', currentProjectId, taskPage, taskPageSize],
    queryFn: () => tasksApi.list({ page: taskPage, page_size: taskPageSize, project_id: currentProjectId ?? undefined }),
    refetchInterval: 5000,
  });
  const tasks = tasksQuery.data?.items ?? [];
  const columns: TableColumnsType<Task> = [
    { title: '任务', dataIndex: 'title', render: (_, task) => <Link to={`/console/tasks/${task.id}`}>{task.title}</Link> },
    { title: '目标', dataIndex: 'goal', ellipsis: true },
    { title: '状态', dataIndex: 'status', width: 140, render: (_, task) => <Tag>{STATUS_LABEL[task.latest_run?.status ?? task.status] ?? task.status}</Tag> },
    { title: '阶段', dataIndex: 'stage', width: 120, render: (_, task) => task.latest_run?.stage ?? '—' },
    { title: '更新时间', dataIndex: 'updated_at', width: 180, render: (value: string) => fmtTime(value) },
    { title: '操作', width: 100, render: (_, task) => <Button type="link" onClick={() => navigate(`/console/tasks/${task.id}`)}>打开</Button> },
  ];

  return (
    <PageContainer>
      <Flex justify="space-between" align="start" wrap="wrap" gap={12}>
        <div>
          <Typography.Title level={4} style={{ marginTop: 0 }}>统一任务</Typography.Title>
          <Typography.Text type="secondary">任务在后台持久运行；范围可来自已确认的 API/Web 用例、交互式 Web 编写目标，或由安全 Agent 对已登记 API 生成受控变异计划。</Typography.Text>
        </div>
        <Button type="primary" onClick={() => setCreateOpen(true)}>创建统一任务</Button>
      </Flex>
      {tasksQuery.isLoading ? <LoadingState /> : tasksQuery.isError ? (
        <ErrorState error={tasksQuery.error} onRetry={tasksQuery.refetch} />
      ) : tasks.length === 0 ? (
        <EmptyState description="当前范围暂无任务" />
      ) : (
        <Table
          rowKey="id"
          style={{ marginTop: 20 }}
          columns={columns}
          dataSource={tasks}
          pagination={{ current: taskPage, pageSize: taskPageSize, total: tasksQuery.data?.total, showSizeChanger: true, onChange: (page, size) => { setTaskPage(page); setTaskPageSize(size); } }}
          onRow={(task) => ({ onClick: () => navigate(`/console/tasks/${task.id}`), style: { cursor: 'pointer' } })}
        />
      )}
      <TaskCreateModal
        open={createOpen}
        onClose={() => { setCreateOpen(false); setSearchParams({}); }}
        onCreated={(task) => navigate(`/console/tasks/${task.id}`)}
        initialProjectId={initialProjectId}
        initialCaseIds={initialCaseId ? [initialCaseId] : []}
        initialTargetType={initialTargetType}
      />
    </PageContainer>
  );
}
