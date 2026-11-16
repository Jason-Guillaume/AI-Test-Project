// 自动化执行历史，可按项目、状态、分支和环境筛选。
import { Form, Select } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { automationApi } from '@/features/automation/api/automation';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { PageContainer } from '@/shared/ui/PageState';
import { ResourceTable, type PaginationState } from '@/shared/ui/ResourceTable';
import { ProjectRequired, ReportLink, StatusTag } from '@/pages/console/AutomationCenter/shared';

/** 执行历史列表。 */
export function ConsoleAutomationHistoryPage() {
  const { currentProjectId } = useConsoleScope();
  const [pagination, setPagination] = useState<PaginationState>({ page: 1, page_size: 20 });
  const [filters, setFilters] = useState<{ automation_project_id?: number; status?: string; branch?: string; environment_name?: string }>({});
  const projects = useQuery({
    queryKey: ['automation-projects', currentProjectId],
    queryFn: () => automationApi.listProjects(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const listQuery = useQuery({
    queryKey: ['automation-executions', currentProjectId, pagination, filters],
    queryFn: () => automationApi.listExecutions(currentProjectId!, { ...pagination, ...filters }),
    enabled: currentProjectId != null,
  });

  return (
    <PageContainer>
      <ProjectRequired projectId={currentProjectId} />
      <Form layout="inline" style={{ marginBottom: 16 }} onValuesChange={(_value, all) => {
        setFilters(all);
        setPagination((current) => ({ ...current, page: 1 }));
      }}>
        <Form.Item name="automation_project_id">
          <Select allowClear placeholder="自动化项目" style={{ width: 180 }} options={(projects.data?.items || []).map((item) => ({ value: item.id, label: item.name }))} />
        </Form.Item>
        <Form.Item name="status">
          <Select allowClear placeholder="状态" style={{ width: 140 }} options={['PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'CANCELLED', 'TIMEOUT'].map((value) => ({ value, label: value }))} />
        </Form.Item>
        <Form.Item name="branch"><Select allowClear placeholder="分支" style={{ width: 140 }} options={[...new Set((listQuery.data?.items || []).map((item) => item.branch).filter(Boolean))].map((value) => ({ value, label: value }))} /></Form.Item>
        <Form.Item name="environment_name"><Select allowClear placeholder="环境" style={{ width: 140 }} options={[...new Set((listQuery.data?.items || []).map((item) => item.environment_name).filter(Boolean))].map((value) => ({ value, label: value }))} /></Form.Item>
      </Form>
      <ResourceTable
        rowKey={(row) => row.id}
        loading={listQuery.isFetching}
        dataSource={listQuery.data?.items || []}
        total={listQuery.data?.total || 0}
        pagination={pagination}
        onPaginationChange={setPagination}
        columns={[
          { title: '执行', dataIndex: 'id' },
          { title: '项目', dataIndex: 'automation_project_name' },
          { title: '云效运行', dataIndex: 'pipeline_run_id', render: (value: string | null) => value || '-' },
          { title: '来源', dataIndex: 'trigger_source' },
          { title: '分支', dataIndex: 'branch' },
          { title: '环境', dataIndex: 'environment_name' },
          { title: '状态', dataIndex: 'status', render: (status: string) => <StatusTag status={status} /> },
          { title: '时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString() },
          { title: '报告', dataIndex: 'report_id', render: (reportId: number | null) => <ReportLink reportId={reportId} /> },
        ]}
      />
    </PageContainer>
  );
}
