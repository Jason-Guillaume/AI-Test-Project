import type { ReactNode } from 'react';
import { Alert, Button, Card, Divider, Empty, Flex, Table, Tabs, theme, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { ErrorState } from '@/shared/ui/PageState';
import { FilterToolbar } from '@/shared/ui/FilterToolbar';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { fmtTime } from '@/shared/lib/format';
import { CASE_EXECUTION_STATUS_OPTIONS, TEST_PRIORITY_OPTIONS } from '@/pages/console/TestManagement/constants';
import { SendOutlined } from '@ant-design/icons';
import { AiSummaryPanel } from './ReportSummaryPanels';
import { NOTIFY_STATUS_COLOR, NOTIFY_STATUS_OPTIONS } from '@/features/notifications/constants';
import type { NotificationChannel, NotificationRecord } from '@/features/notifications/contracts';
import type { CaseExecutionSummary, TestReport } from '@/features/reports/contracts';

interface ReportWorkspaceProps {
  report: TestReport;
  workspaceTab: string;
  onWorkspaceTabChange: (key: string) => void;
  visibleCases: CaseExecutionSummary[];
  caseExecutions: CaseExecutionSummary[];
  failedRows: CaseExecutionSummary[];
  caseColumns: TableColumnsType<CaseExecutionSummary>;
  failedColumns: TableColumnsType<CaseExecutionSummary>;
  clusterGrid: ReactNode;
  clusterFocus: number[] | null;
  caseKeyword: string;
  caseStatus?: string;
  casePriority?: string;
  onCaseKeywordChange: (value: string) => void;
  onCaseFilterChange: (key: string, value: string | undefined) => void;
  onResetCaseFilters: () => void;
  onSelectCase: (row: CaseExecutionSummary) => void;
  isFetching: boolean;
  records: NotificationRecord[];
  recordsQuery: { data?: { total?: number }; isError: boolean; error: unknown; isFetching: boolean; refetch: () => unknown };
  channelsQuery: { isError: boolean; error: unknown; isPending: boolean; refetch: () => unknown };
  channels: NotificationChannel[];
  canNotify: boolean;
  onNotify: () => void;
}

export function ReportWorkspace({
  report,
  workspaceTab,
  onWorkspaceTabChange,
  visibleCases,
  caseExecutions,
  failedRows,
  caseColumns,
  failedColumns,
  clusterGrid,
  clusterFocus,
  caseKeyword,
  caseStatus,
  casePriority,
  onCaseKeywordChange,
  onCaseFilterChange,
  onResetCaseFilters,
  onSelectCase,
  isFetching,
  records,
  recordsQuery,
  channelsQuery,
  channels,
  canNotify,
  onNotify,
}: ReportWorkspaceProps) {
  const { token } = theme.useToken();

  return (
      <Card size="small" style={{ marginBottom: token.margin }}>
        <Tabs
          activeKey={workspaceTab}
          onChange={onWorkspaceTabChange}
          items={[
            {
              key: 'cases',
              label: `用例结果（${visibleCases.length}/${caseExecutions.length}）`,
              children: (
                <Flex vertical gap={token.marginSM}>
                  <FilterToolbar
                    search={caseKeyword}
                    searchPlaceholder="搜索用例名称或错误码"
                    selects={[
                      { key: 'status', label: '状态', options: CASE_EXECUTION_STATUS_OPTIONS, allowClear: true },
                      { key: 'priority', label: '优先级', options: TEST_PRIORITY_OPTIONS, allowClear: true },
                    ]}
                    values={{ status: caseStatus, priority: casePriority }}
                    onSearch={onCaseKeywordChange}
                    onFilterChange={(key, value) => {
                      if (key === 'status') onCaseFilterChange('status', value);
                      else if (key === 'priority') onCaseFilterChange('priority', value);
                    }}
                    onReset={onResetCaseFilters}
                  />
                  {clusterFocus && (
                    <Alert
                      type="info"
                      showIcon
                      message={`已聚焦失败聚类：${clusterFocus.length} 条用例执行`}
                      action={
                        <Button size="small" type="link" onClick={onResetCaseFilters}>
                          取消聚焦
                        </Button>
                      }
                    />
                  )}
                  <Table
                    rowKey="id"
                    size="small"
                    columns={caseColumns}
                    dataSource={visibleCases}
                    loading={isFetching}
                    scroll={{ x: 1100 }}
                    pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true }}
                    onRow={(row) => ({ onClick: () => onSelectCase(row), style: { cursor: 'pointer' } })}
                    locale={{ emptyText: <Empty description="没有匹配当前筛选条件的用例执行" /> }}
                  />
                </Flex>
              ),
            },
            {
              key: 'failures',
              label: `失败分析${failedRows.length > 0 ? `（${failedRows.length}）` : ''}`,
              children: (
                <Flex vertical gap={token.marginSM}>
                  {clusterGrid}
                  <Divider style={{ margin: 0 }} />
                  {failedRows.length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无失败用例" />
                  ) : (
                    <Table
                      rowKey="id"
                      size="small"
                      columns={failedColumns}
                      dataSource={failedRows}
                      scroll={{ x: 1300 }}
                      pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
                      onRow={(row) => ({ onClick: () => onSelectCase(row), style: { cursor: 'pointer' } })}
                    />
                  )}
                </Flex>
              ),
            },
            {
              key: 'ai',
              label: `AI 总结${report.ai_summary_version ? `（${report.ai_summary_version}）` : ''}`,
              children: <AiSummaryPanel summary={report.ai_summary} />,
            },
            {
              key: 'notify',
              label: `通知记录${records.length > 0 ? `（${recordsQuery.data?.total ?? records.length}）` : ''}`,
              children: (
                <Flex vertical gap={token.marginSM}>
                  <Flex justify="space-between" align="center" wrap="wrap" gap="small">
                    <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
                      发送审计记录。Webhook 地址与签名密钥不会显示、也不会写入报告或通知记录。
                    </Typography.Text>
                    <Button
                      type="primary"
                      icon={<SendOutlined />}
                      disabled={!canNotify}
                      onClick={onNotify}
                    >
                      发送飞书通知
                    </Button>
                  </Flex>
                  {/* 三态分开：接口失败要报错误并给重试，不能显示「去配置渠道」的提示 */}
                  {channelsQuery.isError ? (
                    <ErrorState error={channelsQuery.error} onRetry={channelsQuery.refetch} />
                  ) : !channelsQuery.isPending && channels.length === 0 ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="没有可用的通知渠道"
                      description="请在「项目配置 · 通知渠道」配置启用且连通测试通过的渠道后重试。"
                    />
                  ) : null}
                  {recordsQuery.isError ? (
                    <ErrorState error={recordsQuery.error} onRetry={recordsQuery.refetch} />
                  ) : records.length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未发送过飞书通知" />
                  ) : (
                    <Table
                      rowKey="id"
                      size="small"
                      columns={[
                        { title: '记录ID', dataIndex: 'id', width: 90 },
                        { title: '渠道ID', dataIndex: 'channel_id', width: 100 },
                        {
                          title: '状态',
                          dataIndex: 'status',
                          width: 120,
                          render: (v: string) => (
                            <StatusBadge
                              value={v}
                              options={NOTIFY_STATUS_OPTIONS}
                              colors={{ ...NOTIFY_STATUS_COLOR }}
                            />
                          ),
                        },
                        { title: '错误信息', dataIndex: 'error_message', render: (v: string | null) => v ?? '-' },
                        { title: '发送时间', dataIndex: 'sent_at', width: 170, render: (v: string | null) => fmtTime(v) },
                        { title: '记录时间', dataIndex: 'created_at', width: 170, render: (v: string | null) => fmtTime(v) },
                      ]}
                      dataSource={records}
                      loading={recordsQuery.isFetching}
                      pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
                    />
                  )}
                </Flex>
              ),
            },
          ]}
        />
      </Card>

  );
}
