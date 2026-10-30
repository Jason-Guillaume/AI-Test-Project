import { Card, Col, Empty, Flex, Row, Typography, theme } from 'antd';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { REPORT_FAILURE_TYPE_COLOR } from '@/features/reports/status';
import { FAILURE_TYPE_OPTIONS } from './constants';
import type { FailureClusterRow } from './ReportSummaryPanels';

export function ReportFailureClusterGrid({ clusters, onFocusCluster }: {
  clusters: FailureClusterRow[];
  onFocusCluster: (ids: number[]) => void;
}) {
  const { token } = theme.useToken();
  return (
clusters.length === 0 ? (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有失败或错误的用例" />
  ) : (
    <Row gutter={[12, 12]} style={{ marginTop: token.marginXS }}>
      {clusters.map((c, i) => {
        const ft = c.failure_type ?? 'UNKNOWN';
        const focusable = c.case_execution_ids.length > 0;
        return (
          <Col key={i} xs={24} sm={12} md={8}>
            <Card
              size="small"
              hoverable={focusable}
              onClick={focusable ? () => onFocusCluster(c.case_execution_ids) : undefined}
              styles={{ body: { padding: token.paddingSM } }}
            >
              <Flex justify="space-between" align="center" gap="small">
                <StatusBadge value={ft} options={FAILURE_TYPE_OPTIONS} color={REPORT_FAILURE_TYPE_COLOR[ft]} />
                <Typography.Text strong>{c.count} 条</Typography.Text>
              </Flex>
              {focusable && (
                <Typography.Text
                  type="secondary"
                  style={{ fontSize: token.fontSizeSM, display: 'block', marginTop: token.marginXXS }}
                >
                  点击聚焦这 {c.case_execution_ids.length} 条用例执行
                </Typography.Text>
              )}
            </Card>
          </Col>
        );
      })}
    </Row>
  ));
}
