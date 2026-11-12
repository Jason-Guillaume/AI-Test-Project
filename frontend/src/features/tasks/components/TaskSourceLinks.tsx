// 原业务管理页的来源任务反向链接；服务端按用户可见项目过滤。
import { Alert, Button, Space, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { tasksApi } from '@/features/tasks/api/tasks';

interface Props {
  resourceType: string;
  resourceId: string | number | null | undefined;
}

/** 在 TestRun / Report 页面列出引用该资源的任务，可回到任务协作上下文。 */
export function TaskSourceLinks({ resourceType, resourceId }: Props) {
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ['task-resource-sources', resourceType, resourceId],
    queryFn: () => tasksApi.sources(resourceType, String(resourceId)),
    enabled: resourceId != null,
  });
  if (resourceId == null || query.isLoading || (!query.isError && (query.data?.length ?? 0) === 0)) return null;
  if (query.isError) return <Alert type="warning" showIcon message="任务来源链接暂时无法读取" />;
  return (
    <Space wrap>
      <Typography.Text type="secondary">关联任务：</Typography.Text>
      {(query.data ?? []).map((ref) => {
        const taskId = ref.task_id ?? (typeof ref.metadata_json.task_id === 'number' ? ref.metadata_json.task_id : null);
        return taskId != null ? (
          <Button
            key={ref.id}
            size="small"
            type="link"
            onClick={() => navigate(`/console/tasks/${taskId}?runId=${ref.task_run_id}`)}
          >
            {ref.task_title ?? `任务 #${taskId}`} · 运行 #{ref.run_number ?? ref.task_run_id}
          </Button>
        ) : <Typography.Text key={ref.id} type="secondary">运行 #{ref.task_run_id}（缺少任务来源）</Typography.Text>;
      })}
    </Space>
  );
}
