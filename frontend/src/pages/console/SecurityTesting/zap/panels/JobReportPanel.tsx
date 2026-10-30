// OWASP ZAP Job Report Panel 面板。
import { Card, Col, Descriptions, Empty, Row, Space, Statistic, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { zapApi } from '@/features/security-testing/zap/api';
import type { ScanAlert, ScanReport } from '@/features/security-testing/zap/contracts';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { severityColor, severityLabel } from '../../constants';
import { confidenceColor, coverageStageLabel } from "../constants";
import { POLL_MS } from './constants';

export function JobReportPanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const query = useQuery({
    queryKey: ['zap-report', projectId, jobId],
    queryFn: () => zapApi.getScanReport(projectId, jobId),
    refetchInterval: running ? POLL_MS : false,
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const report: ScanReport = query.data!;
  const { job, target, profile, alert_counts } = report;

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic title="告警总数" value={alert_counts.total} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic title="高" value={alert_counts.high} valueStyle={{ color: '#cf1322' }} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic title="中" value={alert_counts.medium} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic title="低" value={alert_counts.low} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic title="提示" value={alert_counts.info} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card size="small">
            <Statistic
              title="关联疑似问题"
              value={report.findings.length}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col xs={24} md={8}>
          <Card size="small" title="任务">
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="任务 ID">#{job.id}</Descriptions.Item>
              <Descriptions.Item label="目标">{target?.name ?? `#${job.target_id}`}</Descriptions.Item>
              <Descriptions.Item label="策略">{profile?.name ?? `#${job.scan_profile_id}`}</Descriptions.Item>
              <Descriptions.Item label="开始">{job.started_at ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="耗时">{job.duration_ms != null ? `${job.duration_ms} 毫秒` : '-'}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="覆盖摘要">
            {Object.keys(report.coverage_summary).length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无覆盖数据" />
            ) : (
              <Row gutter={[8, 8]}>
                {Object.entries(report.coverage_summary).map(([stage, count]) => (
                  <Col key={stage} xs={12}>
                    <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                      <Typography.Text type="secondary">{coverageStageLabel(stage)}</Typography.Text>
                      <Typography.Text strong>{count}</Typography.Text>
                    </Space>
                  </Col>
                ))}
              </Row>
            )}
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card size="small" title="报告生成">
            <Typography.Text>{report.generated_at ?? '-'}</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>
              报告数字全部来自本次扫描任务记录本身，不接受前端传入。
            </Typography.Paragraph>
          </Card>
        </Col>
      </Row>

      <Card size="small" title={`高危告警（${report.high_risk_alerts.length}）`}>
        {report.high_risk_alerts.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有高危告警" />
        ) : (
          <Table<ScanAlert> scroll={{ x: 'max-content' }}
            rowKey={(r) => `${r.rule_id}|${r.url}|${r.parameter}`}
            size="small"
            pagination={false}
            columns={[
              { title: '规则 ID', dataIndex: 'rule_id', width: 90, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
              { title: '告警', dataIndex: 'name' },
              { title: 'risk', dataIndex: 'risk', width: 100, render: (v: string) => v || '-' },
              {
                title: 'Severity',
                dataIndex: 'severity',
                width: 110,
                render: (v: string) => <Tag color={severityColor(v)}>{severityLabel(v)}</Tag>,
              },
              {
                title: 'Confidence',
                dataIndex: 'confidence',
                width: 100,
                render: (v: number) => <Tag color={confidenceColor(v)}>{v}</Tag>,
              },
            ]}
            dataSource={report.high_risk_alerts}
          />
        )}
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- 状态徽标

/** 任务状态徽标：区分 11 种状态。 */
