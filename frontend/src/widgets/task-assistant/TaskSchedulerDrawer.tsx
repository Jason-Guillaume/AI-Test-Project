// 控制台全局调度抽屉：可查看跨项目可见任务并直接发起真实 API 任务。
import { useState } from 'react';
import { Badge, Button, Drawer, Empty, List, Space, Tag, Typography } from 'antd';
import { PlusOutlined, ScheduleOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { tasksApi } from '@/features/tasks/api/tasks';
import type { Task } from '@/features/tasks/contracts';
import { TaskCreateModal } from './TaskCreateModal';

const STAGE_LABEL: Record<string, string> = {
  MODEL_RETRY: '模型重试中', WAITING_MODEL: '等待修复模型配置',
};

/** 在右侧显示持久化任务状态；抽屉关闭不会停止后台运行。 */
export function TaskSchedulerDrawer() {
  const [open, setOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const navigate = useNavigate();
  const tasksQuery = useQuery({
    queryKey: ['tasks', 'global-drawer'],
    queryFn: () => tasksApi.list({ page: 1, page_size: 100 }),
    refetchInterval: open ? 4000 : false,
  });
  const rows = tasksQuery.data?.items ?? [];
  const activeCount = rows.filter((task) => ['QUEUED', 'RUNNING', 'PAUSE_REQUESTED', 'CANCEL_REQUESTED'].includes(task.status)).length;
  const openTask = (task: Task) => {
    setOpen(false);
    navigate(`/console/tasks/${task.id}`);
  };

  return (
    <>
      <Button
        icon={<ScheduleOutlined />}
        onClick={() => setOpen(true)}
        aria-label="打开全局任务调度抽屉"
      >
        任务 <Badge count={activeCount} size="small" offset={[5, -5]} />
      </Button>
      <Drawer
        title={<Space>全局任务调度 <Tag color="blue">{activeCount} 个进行中</Tag></Space>}
        placement="right"
        width={460}
        open={open}
        onClose={() => setOpen(false)}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建任务</Button>}
      >
        {rows.length === 0 ? (
          <Empty description={tasksQuery.isLoading ? '正在读取任务' : '暂无任务'} />
        ) : (
          <List
            dataSource={rows.slice(0, 12)}
            renderItem={(task) => (
              <List.Item
                onClick={() => openTask(task)}
                style={{ cursor: 'pointer', paddingInline: 4 }}
                actions={[<Tag key="status">{STAGE_LABEL[task.latest_run?.stage ?? ''] ?? task.latest_run?.stage ?? task.status}</Tag>]}
              >
                <List.Item.Meta
                  title={<Typography.Link>{task.title}</Typography.Link>}
                  description={<Typography.Text type="secondary" ellipsis>{task.goal}</Typography.Text>}
                />
              </List.Item>
            )}
          />
        )}
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 16 }}>
          <Button type="link" onClick={() => { setOpen(false); navigate('/console/tasks'); }}>查看全部任务</Button>
        </div>
      </Drawer>
      <TaskCreateModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={openTask}
      />
    </>
  );
}
