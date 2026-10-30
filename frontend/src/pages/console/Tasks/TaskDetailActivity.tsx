/**
 * 任务详情中的消息、事件和资源列表组件。
 * 导出详情页使用的只读展示单元；数据及刷新由 TaskDetailPage 负责，消息文案与任务状态映射协作。
 */
import { Card, Empty, Flex, List, Space, Tag, Typography } from 'antd';
import { Link } from 'react-router-dom';
import type { TaskEvent, TaskMessage, TaskResourceRef } from '@/features/tasks/contracts';
import { fmtTime } from '@/shared/lib/format';
import { EVENT_LABEL } from './taskLabels';

/** 渲染当前参与者会话消息，不混合其他角色的会话。 */
export function MessageRow({ message, projectId }: { message: TaskMessage; projectId: number }) {
  const isUser = message.sender_type === 'USER';
  return (
    <List.Item>
      <Card size="small" style={{ width: '100%', background: isUser ? 'rgba(22, 119, 255, .04)' : undefined }}>
        <Flex justify="space-between" gap={12}>
          <Typography.Text strong>{isUser ? '你' : message.message_type === 'PLAN' ? '方案' : message.message_type === 'REVIEW' ? '审阅结论' : 'Agent'}</Typography.Text>
          <Typography.Text type="secondary">{fmtTime(message.created_at)}</Typography.Text>
        </Flex>
        <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: '8px 0 0' }}>{message.content}</Typography.Paragraph>
        {message.message_type === 'RESULT' && typeof message.metadata_json.test_run_id === 'number' && (
          <Link to={`/console/execution-history?runId=${message.metadata_json.test_run_id}&projectId=${projectId}`}>打开执行记录 #{message.metadata_json.test_run_id}</Link>
        )}
      </Card>
    </List.Item>
  );
}

/** 展示服务端记录的事件事实，支持刷新后的续读事件流。 */
export function EventTimeline({ events }: { events: TaskEvent[] }) {
  return (
    <List
      size="small"
      dataSource={events}
      locale={{ emptyText: <Empty description="暂无事件" /> }}
      renderItem={(event) => (
        <List.Item>
          <List.Item.Meta
            title={<Space><Tag color="blue">#{event.event_seq}</Tag><span>{EVENT_LABEL[event.event_type] ?? event.event_type}</span></Space>}
            description={`${fmtTime(event.created_at)} · ${JSON.stringify(event.payload)}`}
          />
        </List.Item>
      )}
    />
  );
}

/** 把任务产物引用还原成既有管理页面地址。 */
export function ResourceList({ resources, projectId, targetType }: { resources: TaskResourceRef[]; projectId: number; targetType: unknown }) {
  return (
    <List
      dataSource={resources}
      locale={{ emptyText: <Empty description="暂无产物引用" /> }}
      renderItem={(resource) => {
        const id = Number(resource.resource_id);
        const href = resource.resource_type === 'REPORT'
          ? `/console/test-reports/${id}`
          : resource.resource_type === 'TEST_RUN'
            ? `/console/execution-history?runId=${id}&projectId=${projectId}`
            : resource.resource_type === 'SECURITY_FINDING'
              ? `/console/security-testing?tab=findings&projectId=${projectId}&findingId=${id}`
              : resource.resource_type === 'TEST_CASE'
                ? targetType === 'WEB' || targetType === 'WEB_AUTHORING' ? `/console/web-ui?caseId=${id}&projectId=${projectId}` : targetType === 'API' ? `/console/test-asset?caseId=${id}&projectId=${projectId}` : undefined
                : undefined;
        return (
          <List.Item>
            <List.Item.Meta
              title={href ? <Link to={href}>{resource.display_name ?? `${resource.resource_type} #${resource.resource_id}`}</Link> : (resource.display_name ?? `${resource.resource_type} #${resource.resource_id}`)}
              description={`${resource.direction === 'INPUT' ? '输入引用' : '真实业务产物'} · ${fmtTime(resource.created_at)}`}
            />
          </List.Item>
        );
      }}
    />
  );
}
