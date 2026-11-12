// 选择分支和环境后触发云效流水线，并展示本次执行状态。
import { App, Button, Card, Descriptions, Form, Input, Select, Space, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { automationApi } from '@/features/automation/api/automation';
import type { AutomationExecution } from '@/features/automation/contracts';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { getErrorMessage } from '@/shared/api/client';
import { PageContainer } from '@/shared/ui/PageState';
import { ProjectRequired, ReportLink, StatusTag } from '@/pages/console/AutomationCenter/shared';

/** 手动触发执行任务。 */
export function ConsoleAutomationRunsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const [form] = Form.useForm();
  const [current, setCurrent] = useState<AutomationExecution | null>(null);
  const projects = useQuery({
    queryKey: ['automation-projects', currentProjectId],
    queryFn: () => automationApi.listProjects(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const detail = useQuery({
    queryKey: ['automation-execution', current?.id],
    queryFn: () => automationApi.getExecution(current!.id),
    enabled: current != null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'PENDING' || status === 'RUNNING' ? 3000 : false;
    },
  });
  const execution = detail.data || current;

  const trigger = useMutation({
    mutationFn: (values: { automation_project_id: number; branch?: string; environment_name?: string; pytest_args?: string; test_tags?: string; test_scope?: string }) => {
      const { automation_project_id, ...body } = values;
      return automationApi.trigger(automation_project_id, body);
    },
    onSuccess: (row) => {
      setCurrent(row);
      message.success(`已触发，云效运行实例 ${row.pipeline_run_id || '尚未返回'}`);
      queryClient.invalidateQueries({ queryKey: ['automation-executions'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '触发失败')),
  });
  const cancel = useMutation({
    mutationFn: (id: number) => automationApi.cancel(id),
    onSuccess: (row) => {
      setCurrent(row);
      message.success('已请求取消');
    },
    onError: (error) => message.error(getErrorMessage(error, '取消失败')),
  });

  return (
    <PageContainer>
      <ProjectRequired projectId={currentProjectId} />
      <Card title="触发云效流水线">
        <Form form={form} layout="vertical" onFinish={(values) => trigger.mutate(values)}>
          <Form.Item name="automation_project_id" label="自动化项目" rules={[{ required: true, message: '请选择项目' }]}>
            <Select options={(projects.data?.items || []).map((item) => ({ value: item.id, label: `${item.name} / ${item.pipeline_id}` }))} />
          </Form.Item>
          <Form.Item name="branch" label="Git 分支"><Input placeholder="留空使用默认分支" /></Form.Item>
          <Form.Item name="environment_name" label="测试环境"><Input placeholder="留空使用默认环境" /></Form.Item>
          <Form.Item name="pytest_args" label="pytest 参数"><Input /></Form.Item>
          <Form.Item name="test_tags" label="测试标签"><Input /></Form.Item>
          <Form.Item name="test_scope" label="测试范围"><Input /></Form.Item>
          <Button type="primary" htmlType="submit" loading={trigger.isPending} disabled={currentProjectId == null}>执行</Button>
        </Form>
      </Card>
      {execution && (
        <Card title="本次执行" style={{ marginTop: 16 }}>
          <Descriptions column={2}>
            <Descriptions.Item label="平台执行 ID">{execution.id}</Descriptions.Item>
            <Descriptions.Item label="云效运行 ID">{execution.pipeline_run_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="状态"><StatusTag status={execution.status} /></Descriptions.Item>
            <Descriptions.Item label="分支">{execution.branch || '-'}</Descriptions.Item>
            <Descriptions.Item label="环境">{execution.environment_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="通知">{execution.notify_status}</Descriptions.Item>
            <Descriptions.Item label="报告"><ReportLink reportId={execution.report_id} /></Descriptions.Item>
          </Descriptions>
          {execution.error_message && <Typography.Paragraph type="danger">{execution.error_message}</Typography.Paragraph>}
          <Space>
            <Button
              disabled={execution.status !== 'PENDING' && execution.status !== 'RUNNING'}
              loading={cancel.isPending}
              onClick={() => cancel.mutate(execution.id)}
            >取消</Button>
          </Space>
          {execution.log_excerpt && (
            <pre style={{ marginTop: 16, maxHeight: 240, overflow: 'auto', background: '#f6f8fa', padding: 12 }}>
              {execution.log_excerpt}
            </pre>
          )}
        </Card>
      )}
    </PageContainer>
  );
}
