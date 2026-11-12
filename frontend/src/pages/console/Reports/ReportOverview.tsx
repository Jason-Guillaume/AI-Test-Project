import type { ReactNode } from 'react';
import { Alert, Button, Card, Col, Descriptions, Divider, Flex, Progress, Row, Tag, Typography, theme } from 'antd';
import { DeleteOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons';
import { Popconfirm } from 'antd';
import { MetricCard, type MetricTone } from '@/shared/ui/MetricCard';
import { PageHeader } from '@/shared/ui/PageHeader';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { TaskSourceLinks } from '@/features/tasks/components/TaskSourceLinks';
import { fmtDuration, fmtPercent, fmtTime, fmtTimeSec } from '@/shared/lib/format';
import { labelOf } from '@/shared/lib/options';
import { CASE_EXECUTION_STATUS_COLOR, CASE_EXECUTION_STATUS_LABEL, TEST_RUN_STATUS_COLOR } from '@/features/test-management/status';
import { REPORT_RISK_COLOR, REPORT_STATUS_COLOR } from '@/features/reports/status';
import { TEST_RUN_STATUS_OPTIONS } from '@/pages/console/TestManagement/constants';
import { REPORT_RISK_OPTIONS, REPORT_STATUS_OPTIONS } from './constants';
import { SecuritySummaryCard } from './ReportSummaryPanels';
import type { TestReport, TestRunBrief } from '@/features/reports/contracts';
import type { SecuritySummary } from '@/features/security-testing/contracts';

interface ReportOverviewProps {
  report: TestReport;
  testRun: TestRunBrief | null;
  projectName: string | null;
  envName: string | null;
  envId: number | null;
  riskAlerts: { type: 'error' | 'warning'; message: string; description: string }[];
  passTone: MetricTone;
  passColor: string;
  statusCounts: Map<string, number>;
  clusterGrid: ReactNode;
  security: SecuritySummary | null;
  onBack: () => void;
  regenerateLoading: boolean;
  onRegenerate: () => void;
  canNotify: boolean;
  onNotify: () => void;
  deleteLoading: boolean;
  onDelete: () => void;
}

export function ReportOverview({
  report, testRun: test_run, projectName, envName, envId, riskAlerts, passTone, passColor,
  statusCounts, clusterGrid, security, onBack, regenerateLoading, onRegenerate,
  canNotify, onNotify, deleteLoading, onDelete,
}: ReportOverviewProps) {
  const { token } = theme.useToken();
  return (
    <>
      {/* A. 报告头部 */}
      <PageHeader
        back
        onBack={() => onBack()}
        title={report.title}
        titleExtra={
          <>
            <StatusBadge
              value={report.status}
              options={REPORT_STATUS_OPTIONS}
              color={REPORT_STATUS_COLOR[report.status]}
            />
            <Tag color={REPORT_RISK_COLOR[report.risk_level]}>
              风险：{labelOf(REPORT_RISK_OPTIONS, report.risk_level)}
            </Tag>
          </>
        }
        subtitle={`${report.report_no} · 生成于 ${fmtTime(report.created_at)}`}
        meta={[
          { label: '所属项目', value: projectName ?? `#${report.project_id}` },
          { label: '环境', value: envName ?? (envId != null ? `#${envId}` : '-') },
          { label: '关联执行', value: test_run ? `#${test_run.id}` : '关联执行记录已删除' },
          {
            label: '执行时间',
            value: test_run?.started_at
              ? `${fmtTimeSec(test_run.started_at)} → ${fmtTimeSec(test_run.finished_at)}`
              : '-',
          },
          { label: '执行耗时', value: fmtDuration(report.duration_ms) },
          { label: '用例数', value: report.total_cases },
        ]}
        extra={
          <>
            <Button
              icon={<ReloadOutlined />}
              loading={regenerateLoading}
              onClick={onRegenerate}
            >
              重新生成 AI 总结
            </Button>
            <Button
              type="primary"
              icon={<SendOutlined />}
              disabled={!canNotify}
              onClick={onNotify}
            >
              发送飞书通知
            </Button>
            <Popconfirm
              title="确认删除该报告？"
              description="仅删除报告记录，不会删除执行记录与用例执行结果。"
              onConfirm={onDelete}
            >
              <Button danger icon={<DeleteOutlined />} loading={deleteLoading}>
                删除报告
              </Button>
            </Popconfirm>
          </>
        }
      />

      <Flex vertical gap={8} style={{ marginBottom: token.margin }}>
        <TaskSourceLinks resourceType="REPORT" resourceId={report.id} />
        <TaskSourceLinks resourceType="TEST_RUN" resourceId={test_run?.id} />
      </Flex>

      {/* C. 风险提示：只在真的有风险时出现 */}
      {riskAlerts.length > 0 && (
        <Flex vertical gap={token.marginXS} style={{ marginBottom: token.margin }}>
          {riskAlerts.map((a, i) => (
            <Alert key={i} type={a.type} showIcon message={a.message} description={a.description} />
          ))}
        </Flex>
      )}

      {/* B. 概览统计 */}
      <Card size="small" style={{ marginBottom: token.margin }}>
        <Flex gap={token.marginXS} wrap="wrap">
          <MetricCard
            style={{ flex: '1 1 150px', minWidth: 150 }}
            title="通过率"
            value={fmtPercent(report.pass_rate)}
            suffix="%"
            tone={passTone}
            hint={`${report.passed_cases}/${report.total_cases} 通过`}
          />
          <MetricCard style={{ flex: '1 1 120px', minWidth: 120 }} title="总用例" value={report.total_cases} />
          <MetricCard
            style={{ flex: '1 1 120px', minWidth: 120 }}
            title="通过"
            value={report.passed_cases}
            tone="success"
          />
          <MetricCard
            style={{ flex: '1 1 120px', minWidth: 120 }}
            title="失败"
            value={report.failed_cases}
            tone="error"
          />
          <MetricCard
            style={{ flex: '1 1 120px', minWidth: 120 }}
            title="错误"
            value={report.error_cases}
            tone="warning"
          />
          <MetricCard style={{ flex: '1 1 120px', minWidth: 120 }} title="跳过" value={report.skipped_cases} />
          <MetricCard
            style={{ flex: '1 1 140px', minWidth: 140 }}
            title="执行耗时"
            value={fmtDuration(report.duration_ms)}
          />
        </Flex>
        <Progress
          percent={report.pass_rate}
          strokeColor={passColor}
          style={{ marginTop: token.margin, marginBottom: 0 }}
        />
        <Typography.Text
          type="secondary"
          style={{ fontSize: token.fontSizeSM, display: 'block', marginTop: token.marginXXS }}
        >
          统计字段由系统代码计算且不可变，AI 只负责总结、风险解释与失败聚类。
        </Typography.Text>
      </Card>

      {/* C. 执行摘要 + 执行环境 */}
      <Row gutter={[token.margin, token.margin]} style={{ marginBottom: token.margin }}>
        <Col xs={24} lg={14}>
          <Card size="small" title="执行摘要">
            <Typography.Text strong>状态分布</Typography.Text>
            {statusCounts.size === 0 ? (
              <Typography.Text type="secondary" style={{ display: 'block', margin: `${token.marginXS}px 0` }}>
                无用例执行数据
              </Typography.Text>
            ) : (
              <Flex wrap gap="small" style={{ margin: `${token.marginXS}px 0 ${token.marginSM}px` }}>
                {[...statusCounts.entries()].map(([status, count]) => (
                  <Flex key={status} align="center" gap={4}>
                    <StatusBadge
                      value={status}
                      labels={{ ...CASE_EXECUTION_STATUS_LABEL }}
                      colors={{ ...CASE_EXECUTION_STATUS_COLOR }}
                    />
                    <Typography.Text strong>{count}</Typography.Text>
                  </Flex>
                ))}
              </Flex>
            )}
            <Divider style={{ margin: `${token.marginSM}px 0` }} />
            <Typography.Text strong>主要失败原因</Typography.Text>
            {clusterGrid}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title="执行环境">
            <Descriptions
              size="small"
              column={1}
              items={[
                { key: 'project', label: '所属项目', children: projectName ?? `#${report.project_id}` },
                { key: 'env', label: '环境', children: envName ?? (envId != null ? `#${envId}` : '-') },
                { key: 'run', label: '关联执行', children: test_run ? `#${test_run.id}` : '关联执行记录已删除' },
                {
                  key: 'runStatus',
                  label: '执行状态',
                  children: test_run ? (
                    <StatusBadge
                      value={test_run.status}
                      colors={TEST_RUN_STATUS_COLOR}
                      label={labelOf(TEST_RUN_STATUS_OPTIONS, test_run.status)}
                    />
                  ) : (
                    '-'
                  ),
                },
                { key: 'start', label: '执行开始', children: fmtTimeSec(test_run?.started_at) },
                { key: 'end', label: '执行结束', children: fmtTimeSec(test_run?.finished_at) },
                { key: 'duration', label: '执行耗时', children: fmtDuration(report.duration_ms) },
                { key: 'generated', label: '报告生成于', children: fmtTime(report.created_at) },
              ]}
            />
          </Card>
          {security && <SecuritySummaryCard summary={security} />}
        </Col>
      </Row>

    </>
  );
}
