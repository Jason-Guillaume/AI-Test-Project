// Allure 原生报告页。统计卡片之外，用受控地址打开完整 HTML。
import { Button, Card, Col, Descriptions, Row, Select, Statistic, Table } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { automationApi } from '@/features/automation/api/automation';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';

/** 单次 Allure 报告、趋势和批次对比。 */
export function ConsoleAutomationReportPage() {
  const { reportId } = useParams();
  const id = Number(reportId);
  const { currentProjectId } = useConsoleScope();
  const [compareId, setCompareId] = useState<number | null>(null);
  const reportQuery = useQuery({
    queryKey: ['automation-report', id],
    queryFn: () => automationApi.getReport(id),
    enabled: Number.isFinite(id),
  });
  const grantQuery = useQuery({
    queryKey: ['automation-report-grant', id],
    queryFn: () => automationApi.grant(id),
    enabled: reportQuery.data?.status === 'READY',
  });
  const trendQuery = useQuery({
    queryKey: ['automation-report-trend', currentProjectId, reportQuery.data?.automation_project_id],
    queryFn: () => automationApi.trend(currentProjectId!, reportQuery.data!.automation_project_id),
    enabled: currentProjectId != null && reportQuery.data != null,
  });
  const compareQuery = useQuery({
    queryKey: ['automation-report-compare', id, compareId],
    queryFn: () => automationApi.compare(id, compareId!),
    enabled: compareId != null && compareId !== id,
  });

  if (reportQuery.isPending) return <LoadingState />;
  if (reportQuery.isError) return <PageContainer><ErrorState error={reportQuery.error} onRetry={reportQuery.refetch} /></PageContainer>;
  const report = reportQuery.data;

  return (
    <PageContainer>
      <Row gutter={16}>
        <Col span={4}><Statistic title="总数" value={report.total_cases} /></Col>
        <Col span={4}><Statistic title="成功" value={report.passed_cases} /></Col>
        <Col span={4}><Statistic title="失败" value={report.failed_cases} /></Col>
        <Col span={4}><Statistic title="中断" value={report.broken_cases} /></Col>
        <Col span={4}><Statistic title="跳过" value={report.skipped_cases} /></Col>
        <Col span={4}><Statistic title="通过率" value={report.pass_rate} suffix="%" /></Col>
      </Row>
      <Descriptions style={{ marginTop: 16 }} column={3}>
        <Descriptions.Item label="项目">{report.automation_project_name}</Descriptions.Item>
        <Descriptions.Item label="分支">{report.branch || '-'}</Descriptions.Item>
        <Descriptions.Item label="环境">{report.environment_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="提交">{report.git_commit || '-'}</Descriptions.Item>
        <Descriptions.Item label="耗时">{report.duration_ms ?? '-'} ms</Descriptions.Item>
        <Descriptions.Item label="Allure 趋势">{report.history_included ? '已包含 history' : '本次没有 history'}</Descriptions.Item>
      </Descriptions>
      <Button style={{ margin: '16px 0' }} href={`/api/v1/automation-reports/${report.id}/download`}>下载完整报告</Button>
      <Card title="测试套件">
        <Table
          rowKey={(row) => row.name}
          pagination={false}
          dataSource={report.suite_summary}
          columns={[
            { title: '套件', dataIndex: 'name' },
            { title: '总数', dataIndex: 'total' },
            { title: '成功', dataIndex: 'passed' },
            { title: '失败', dataIndex: 'failed' },
            { title: '中断', dataIndex: 'broken' },
            { title: '跳过', dataIndex: 'skipped' },
          ]}
        />
      </Card>
      <Card title="历史趋势" style={{ marginTop: 16 }}>
        <Table
          rowKey={(row) => row.id}
          pagination={false}
          dataSource={trendQuery.data || []}
          columns={[
            { title: '时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString() },
            { title: '分支', dataIndex: 'branch' },
            { title: '环境', dataIndex: 'environment_name' },
            { title: '通过率', dataIndex: 'pass_rate', render: (value: number) => `${value}%` },
            { title: '失败', dataIndex: 'failed_cases' },
            { title: '跳过', dataIndex: 'skipped_cases' },
          ]}
        />
      </Card>
      <Card title="与其他批次对比" style={{ marginTop: 16 }}>
        <Select
          allowClear
          placeholder="选择另一份报告"
          style={{ width: 360, marginBottom: 16 }}
          options={(trendQuery.data || []).filter((item) => item.id !== id).map((item) => ({
            value: item.id,
            label: `#${item.id} ${item.branch} ${new Date(item.created_at).toLocaleString()}`,
          }))}
          onChange={(value) => setCompareId(value ?? null)}
        />
        {compareQuery.data && (
          <Descriptions column={3}>
            <Descriptions.Item label="总数变化">{compareQuery.data.delta.total_cases}</Descriptions.Item>
            <Descriptions.Item label="失败变化">{compareQuery.data.delta.failed_cases}</Descriptions.Item>
            <Descriptions.Item label="通过率变化">{compareQuery.data.delta.pass_rate}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
      <Card title="Allure 报告" style={{ marginTop: 16 }}>
        {grantQuery.data ? (
          <iframe
            title="Allure 报告"
            src={grantQuery.data.index_url}
            sandbox="allow-scripts allow-popups allow-downloads"
            style={{ width: '100%', height: '80vh', border: '1px solid #f0f0f0' }}
          />
        ) : '正在准备报告地址'}
      </Card>
    </PageContainer>
  );
}
