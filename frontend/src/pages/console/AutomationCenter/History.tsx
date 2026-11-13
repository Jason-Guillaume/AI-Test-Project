// 自动化执行历史，可按项目、状态、分支和环境筛选。
import { Form, Input, InputNumber, Select, Tag } from 'antd';
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
  const [filters, setFilters] = useState<{ automation_project_id?: number; status?: string; branch?: string; environment_name?: string; provider_type?: string; pipeline_id?: string; build_number?: number }>({});
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
        <Form.Item name="provider_type"><Select allowClear placeholder="CI 平台" style={{ width: 140 }} options={[{ value: 'YUNXIAO', label: '云效 Flow' }, { value: 'JENKINS', label: 'Jenkins' }]} /></Form.Item>
        <Form.Item name="pipeline_id"><Input allowClear placeholder="Job / 流水线" style={{ width: 190 }} /></Form.Item>
        <Form.Item name="build_number"><InputNumber min={1} placeholder="Build Number" style={{ width: 145 }} /></Form.Item>
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
          { title: 'CI 平台', dataIndex: 'provider_type', render: (value: string) => value === 'JENKINS' ? <Tag color="blue">Jenkins</Tag> : '云效 Flow' },
          { title: 'Job / 流水线', dataIndex: 'pipeline_id', ellipsis: true },
          { title: 'Build', dataIndex: 'build_number', render: (value: number | null, row) => value && row.external_run_url ? <a href={row.external_run_url} target="_blank" rel="noreferrer">#{value}</a> : value ?? row.pipeline_run_id ?? '-' },
          { title: '外部状态', dataIndex: 'external_status' },
          { title: '来源', dataIndex: 'trigger_source' },
          { title: '分支', dataIndex: 'branch' },
          { title: '环境', dataIndex: 'environment_name' },
          { title: '状态', dataIndex: 'status', render: (status: string) => <StatusTag status={status} /> },
          { title: '耗时', dataIndex: 'duration_ms', render: (value: number | null) => value == null ? '-' : `${Math.round(value / 1000)} 秒` },
          { title: '时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString() },
          { title: '报告', dataIndex: 'report_id', render: (reportId: number | null) => <ReportLink reportId={reportId} /> },
        ]}
      />
    </PageContainer>
  );
}
