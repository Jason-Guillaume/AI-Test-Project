// 选择分支和环境后触发云效流水线，并展示本次执行状态。
import { App, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Tag, Typography } from 'antd';
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
  const [consoleOpen, setConsoleOpen] = useState(false);
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
  const selectedProjectId = Form.useWatch('automation_project_id', form);
  const selectedProject = projects.data?.items.find((item) => item.id === selectedProjectId);
  const consoleQuery = useQuery({
    queryKey: ['automation-console-log', execution?.id],
    queryFn: () => automationApi.consoleLog(execution!.id),
    enabled: consoleOpen && execution != null,
    refetchInterval: execution?.status === 'PENDING' || execution?.status === 'RUNNING' ? 5000 : false,
  });

  const trigger = useMutation({
    mutationFn: (values: { automation_project_id: number; branch?: string; environment_name?: string; pytest_args?: string; test_tags?: string; test_scope?: string }) => {
      const { automation_project_id, ...body } = values;
      return automationApi.trigger(automation_project_id, body);
    },
    onSuccess: (row) => {
      setCurrent(row);
      message.success(row.provider_type === 'JENKINS'
        ? `已触发 Jenkins Queue ${row.queue_id || '处理中'}`
        : `已触发云效运行实例 ${row.pipeline_run_id || '尚未返回'}`);
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
      <Card title="触发 CI 执行">
        <Form form={form} layout="vertical" onFinish={(values) => trigger.mutate(values)}>
          <Form.Item name="automation_project_id" label="自动化项目" rules={[{ required: true, message: '请选择项目' }]}>
            <Select options={(projects.data?.items || []).map((item) => ({ value: item.id, label: `${item.name} / ${item.pipeline_id}` }))} />
          </Form.Item>
          {selectedProject && <Typography.Paragraph type="secondary">
            {selectedProject.provider_type === 'JENKINS' ? 'Jenkins Job' : '云效流水线'}：{selectedProject.pipeline_id}
          </Typography.Paragraph>}
          <Form.Item name="branch" label="Git 分支"><Input placeholder={`留空使用默认分支${selectedProject ? `（${selectedProject.default_branch}）` : ''}`} /></Form.Item>
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
            <Descriptions.Item label="CI 平台">{execution.provider_type === 'JENKINS' ? <Tag color="blue">Jenkins</Tag> : '云效 Flow'}</Descriptions.Item>
            <Descriptions.Item label="Queue ID">{execution.queue_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="Build Number">{execution.build_number ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="外部运行 ID">{execution.pipeline_run_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="状态"><StatusTag status={execution.status} /></Descriptions.Item>
            <Descriptions.Item label="外部状态">{execution.external_status || '-'}</Descriptions.Item>
            <Descriptions.Item label="构建链接">{execution.external_run_url ? <a href={execution.external_run_url} target="_blank" rel="noreferrer">打开 CI 构建</a> : '-'}</Descriptions.Item>
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
            <Button onClick={() => setConsoleOpen(true)}>Console 日志</Button>
          </Space>
          {execution.log_excerpt && (
            <pre style={{ marginTop: 16, maxHeight: 240, overflow: 'auto', background: '#f6f8fa', padding: 12 }}>
              {execution.log_excerpt}
            </pre>
          )}
        </Card>
      )}
      <Modal title="执行 Console 日志" open={consoleOpen} onCancel={() => setConsoleOpen(false)} footer={null} width={900} destroyOnClose>
        {consoleQuery.data?.truncated && <Typography.Text type="secondary">仅显示最近 200 KB</Typography.Text>}
        {consoleQuery.isError && <Typography.Paragraph type="danger">{getErrorMessage(consoleQuery.error, '读取日志失败')}</Typography.Paragraph>}
        <pre style={{ maxHeight: '65vh', overflow: 'auto', background: '#101820', color: '#e6edf3', padding: 16, whiteSpace: 'pre-wrap' }}>
          {consoleQuery.isFetching ? '正在读取日志…' : consoleQuery.data?.content || '暂无日志'}
        </pre>
      </Modal>
    </PageContainer>
  );
}
