// 安全扫描 · 子 Tab 4：扫描结果。
//
// 按任务看四类结果：事件时间线 / 告警（severity 筛选）/ 覆盖率 / 报告，
// 另加「关联疑似问题」把扫描结果接回 Phase 1 的疑似问题状态流。
// 所有面板都是纯读取；报告数字来自任务记录本身（§二十五）。
import { useState } from 'react';
import { Alert, Card, Col, Row, Select, Space, Statistic, Tabs, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { zapApi } from '@/features/security-testing/zap/api';
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/PageState';
import { authModeLabel, isRunningJob, jobStatusLabel, scanModeLabel } from './constants';
import { JobAlertsPanel } from './panels/JobAlertsPanel';
import { JobCoveragePanel } from './panels/JobCoveragePanel';
import { JobEventsPanel } from './panels/JobEventsPanel';
import { JobFindingsPanel } from './panels/JobFindingsPanel';
import { JobReportPanel } from './panels/JobReportPanel';
import { ScanJobStatusBadge } from './panels/ScanJobStatusBadge';

/** 扫描结果子 Tab。projectId 由父页传入（已确保非空）。 */
export function ResultsSubTab({ projectId }: { projectId: number }) {
  const [jobId, setJobId] = useState<number | undefined>(undefined);

  // 只拉已产出结果的任务做选择器；进行中也能选，方便边跑边看事件。
  const jobsQuery = useQuery({
    queryKey: ['zap-jobs', projectId, 'results-picker'],
    queryFn: () => zapApi.listScanJobs(projectId, { page: 1, page_size: 100 }),
    // 只有还有任务在跑时轮询选择器，避免列表空转。
    refetchInterval: (query) =>
      query.state.data?.items.some((j) => isRunningJob(j.status)) ? 10000 : false,
  });

  const jobs = jobsQuery.data?.items ?? [];
  const selected = jobs.find((j) => j.id === jobId);
  const running = selected != null && isRunningJob(selected.status);

  if (jobsQuery.isLoading) return <LoadingState />;
  if (jobsQuery.isError) return <ErrorState error={jobsQuery.error} onRetry={jobsQuery.refetch} />;

  if (jobs.length === 0) {
    return (
      <EmptyState description="还没有扫描任务，请先到「扫描任务」Tab 发起一次扫描" />
    );
  }

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select
            style={{ width: 360 }}
            placeholder="选择扫描任务"
            value={jobId}
            onChange={setJobId}
            options={jobs.map((j) => ({
              value: j.id,
              label: `#${j.id} · ${j.target_name ?? `目标 #${j.target_id}`} · ${jobStatusLabel(j.status)}`,
            }))}
          />
          <Typography.Text type="secondary">选中后可看事件时间线、告警、覆盖率与报告</Typography.Text>
        </Space>
      </Card>

      {selected && (
        <div style={{ marginBottom: 12 }}>
          <Row gutter={16}>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="告警总数" value={selected.total_alerts} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="高危" value={selected.high_count} valueStyle={{ color: '#cf1322' }} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="发现地址" value={selected.urls_discovered} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="发起请求" value={selected.requests_made} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="新增疑似问题" value={selected.new_findings_count} />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Space direction="vertical" size={2}>
                  <ScanJobStatusBadge status={selected.status} />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {scanModeLabel(selected.scan_mode)}
                  </Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {authModeLabel(selected.authentication_mode ?? 'NONE')}
                  </Typography.Text>
                </Space>
              </Card>
            </Col>
          </Row>
        </div>
      )}

      {!selected ? (
        <Alert
          type="info"
          showIcon
          message="请选择一个扫描任务"
          description="选中后可以看到它的事件时间线、告警、覆盖率与报告。"
        />
      ) : (
        <Tabs
          size="small"
          defaultActiveKey="alerts"
          items={[
            {
              key: 'events',
              label: '事件时间线',
              children: <JobEventsPanel projectId={projectId} jobId={selected.id} running={running} />,
            },
            {
              key: 'alerts',
              label: '告警',
              children: <JobAlertsPanel projectId={projectId} jobId={selected.id} running={running} />,
            },
            {
              key: 'coverage',
              label: '覆盖率',
              children: <JobCoveragePanel projectId={projectId} jobId={selected.id} running={running} />,
            },
            {
              key: 'findings',
              label: '关联疑似问题',
              children: <JobFindingsPanel projectId={projectId} jobId={selected.id} running={running} />,
            },
            {
              key: 'report',
              label: '报告',
              children: <JobReportPanel projectId={projectId} jobId={selected.id} running={running} />,
            },
          ]}
        />
      )}
    </div>
  );
}
