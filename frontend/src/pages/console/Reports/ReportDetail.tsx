// 测试报告详情页：概览 + AI 总结 + 失败聚类 + 逐用例执行 + 通知记录。
//
// 数据：
//   - GET /reports/{report_id} 报告详情（报告本体 + TestRun 摘要 + 逐用例执行 + 失败聚类）
//   - POST /reports/{report_id}/regenerate-ai-summary 重生成 AI 总结（统计字段不可变）
//   - POST /reports/{report_id}/notify 手动触发飞书通知（选择渠道）
//   - GET /reports/{report_id}/notifications 报告的发送审计记录
//   - DELETE /reports/{report_id} 删除报告（不删 TestRun / CaseExecution）
//
// 安全边界：报告与通知记录中均不含 webhook URL / secret；POTENTIAL_BUG 只表示
// 「疑似产品问题，需人工确认」，页面文案不写「已发现 Bug」。
import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Flex,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  EyeOutlined,
  LeftOutlined,
  ReloadOutlined,
  SendOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import type { TableColumnsType } from 'antd';
import { WebArtifacts } from '@/pages/console/WebUI/Artifacts';
import { reportsApi } from '@/api/reports';
import { notificationChannelsApi } from '@/api/notificationChannels';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import {
  CASE_STATUS_COLOR,
  CASE_STATUS_LABEL,
  fmtTime,
  FAILURE_TYPE_COLOR,
  FAILURE_TYPE_OPTIONS,
  NOTIFY_STATUS_COLOR,
  NOTIFY_STATUS_OPTIONS,
  REPORT_RISK_OPTIONS,
  REPORT_STATUS_COLOR,
  REPORT_STATUS_OPTIONS,
  RISK_COLOR,
} from './constants';
import type {
  CaseExecutionSummary,
  ReportFailureType,
  ReportRiskLevel,
  ReportStatus,
  SecuritySummary,
} from '@/types';

const riskLabel = (v: ReportRiskLevel) =>
  REPORT_RISK_OPTIONS.find((o) => o.value === v)?.label ?? v;
const statusLabel = (v: ReportStatus) =>
  REPORT_STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v;
const failureLabel = (v: ReportFailureType) =>
  FAILURE_TYPE_OPTIONS.find((o) => o.value === v)?.label ?? v;
const notifyStatusLabel = (v: string) =>
  NOTIFY_STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v;

/** 只读 JSON 视图（快照已脱敏，仍做兜底展示）。 */
function JsonView({ value }: { value: unknown }) {
  if (value == null) return <Empty description="无数据" />;
  return (
    <pre
      style={{
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
        maxHeight: 320,
        overflow: 'auto',
        background: '#fafafa',
        padding: 8,
        borderRadius: 6,
        fontSize: 12,
      }}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/** AI 总结区块：只展示 LLM 结构化字段，不参与统计计算。 */
function AiSummaryPanel({ summary }: { summary: Record<string, unknown> | null }) {
  if (!summary) {
    return (
      <Alert
        type="info"
        showIcon
        message="暂无 AI 总结"
        description="AI 总结生成失败或已被跳过。报告统计与风险等级由代码计算，不受影响；可点击「重新生成 AI 总结」重试。"
      />
    );
  }
  const text = (k: string) => (summary[k] as string | undefined) ?? '';
  const list = (k: string) => ((summary[k] as string[] | undefined) ?? []);

  const listBlock = (title: string, items: string[], tone: 'normal' | 'warn' | 'danger' = 'normal') => {
    if (items.length === 0) return null;
    const color = tone === 'danger' ? '#cf1322' : tone === 'warn' ? '#d46b08' : undefined;
    return (
      <div style={{ marginBottom: 16 }}>
        <Typography.Text strong>{title}</Typography.Text>
        <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
          {items.map((t, i) => (
            <li key={i} style={{ color, lineHeight: 1.7 }}>
              {t}
            </li>
          ))}
        </ul>
      </div>
    );
  };

  return (
    <div>
      {text('overview') && (
        <Card size="small" style={{ marginBottom: 16, background: '#f6ffed' }}>
          <Typography.Text strong>总体结论</Typography.Text>
          <div style={{ marginTop: 4, lineHeight: 1.8 }}>{text('overview')}</div>
        </Card>
      )}
      {listBlock('主要发现', list('key_findings'))}
      {listBlock('疑似产品问题（需人工确认，不是已确认缺陷）', list('potential_issues'), 'warn')}
      {listBlock('测试数据问题', list('test_data_issues'))}
      {listBlock('环境问题', list('environment_issues'))}
      {listBlock('改进建议', list('recommendations'))}
      {text('risk_summary') && (
        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong>风险解释</Typography.Text>
          <div style={{ marginTop: 4, lineHeight: 1.8 }}>{text('risk_summary')}</div>
        </div>
      )}
    </div>
  );
}

/**
 * 安全摘要卡片：仅在 summary.security 存在时渲染。
 * 文案统一「疑似问题」，不写「已发现漏洞」；top_findings 不含 evidence 正文。
 */
function SecuritySummaryCard({ summary }: { summary: Record<string, unknown> | null }) {
  const sec = (summary?.security as SecuritySummary | undefined) ?? null;
  if (!sec) return null; // 无安全用例的旧报告不渲染该卡片。

  const severityLabel: Record<string, string> = {
    INFO: '提示',
    LOW: '低',
    MEDIUM: '中',
    HIGH: '高',
    CRITICAL: '严重',
  };
  const severityColor: Record<string, string> = {
    INFO: 'default',
    LOW: 'blue',
    MEDIUM: 'orange',
    HIGH: 'red',
    CRITICAL: 'volcano',
  };

  return (
    <Card size="small" style={{ marginBottom: 16, background: '#fff1f0' }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 8 }}>
        <Typography.Text strong>安全摘要（疑似问题）</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          统计由代码从安全执行与未关闭疑似问题计算，不经 AI。
        </Typography.Text>
      </Flex>
      <Row gutter={16}>
        <Col span={4}>
          <Statistic title="安全用例" value={sec.cases} />
        </Col>
        <Col span={4}>
          <Statistic title="通过" value={sec.pass} valueStyle={{ color: '#52c41a' }} />
        </Col>
        <Col span={4}>
          <Statistic
            title="疑似问题"
            value={sec.potential_issues}
            valueStyle={{ color: '#cf1322' }}
          />
        </Col>
        <Col span={4}>
          <Statistic title="不确定" value={sec.inconclusive} />
        </Col>
        <Col span={4}>
          <Statistic title="执行失败" value={sec.failed_execution} />
        </Col>
        <Col span={4}>
          <Statistic title="跳过" value={sec.skipped} />
        </Col>
      </Row>
      <Divider style={{ margin: '12px 0' }} />
      <Flex gap="small" wrap>
        {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] as const).map((lv) => (
          <Tag key={lv} color={severityColor[lv] ?? 'default'}>
            {severityLabel[lv] ?? lv}：{sec.findings?.[lv] ?? 0}
          </Tag>
        ))}
      </Flex>
      {sec.top_findings && sec.top_findings.length > 0 && (
        <>
          <Typography.Text strong style={{ display: 'block', marginTop: 12 }}>
            疑似问题 Top（不含证据正文）
          </Typography.Text>
          <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
            {sec.top_findings.map((f) => (
              <li key={f.id} style={{ lineHeight: 1.7 }}>
                <Tag color={severityColor[f.severity] ?? 'default'}>{severityLabel[f.severity] ?? f.severity}</Tag>
                <Typography.Text>{f.title}</Typography.Text>
                <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                  {f.mutation_type}
                </Typography.Text>
              </li>
            ))}
          </ul>
        </>
      )}
      <Alert
        type="info"
        showIcon
        style={{ marginTop: 12 }}
        message="疑似问题需人工确认，不等于已发现漏洞；证据请到「安全测试 · 疑似问题」查看。"
      />
    </Card>
  );
}

/** 用例执行详情弹窗：断言结果 + 请求/响应/上下文快照。 */
function CaseModal({ ce, onClose }: { ce: CaseExecutionSummary | null; onClose: () => void }) {
  const assertionRows = ce?.assertion_results ?? [];
  const columns: TableColumnsType<Record<string, unknown>> = [
    { title: '断言', dataIndex: 'path', render: (v) => String(v ?? '-') },
    { title: '操作符', dataIndex: 'operator', width: 90, render: (v) => String(v ?? '-') },
    { title: '期望', dataIndex: 'expected', ellipsis: true, render: (v) => String(v ?? '-') },
    { title: '实际', dataIndex: 'actual', ellipsis: true, render: (v) => String(v ?? '-') },
    {
      title: '结果',
      dataIndex: 'passed',
      width: 80,
      render: (v: unknown) => (v ? <Tag color="green">通过</Tag> : <Tag color="red">失败</Tag>),
    },
  ];

  return (
    <Modal
      title={ce != null ? `用例执行 #${ce.id} · ${ce.case_name}` : '用例执行'}
      open={ce != null}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
      width={760}
    >
      {ce?.error_message && (
        <Alert
          type="error"
          showIcon
          message={`错误码：${ce.error_code ?? '-'}`}
          description={ce.error_message}
          style={{ marginBottom: 12 }}
        />
      )}
      <Tabs
        items={[
          {
            key: 'assertions',
            label: '断言结果',
            children:
              assertionRows.length === 0 ? (
                <Empty description="无断言结果" />
              ) : (
                <Table
                  rowKey={(_, idx) => String(idx)}
                  size="small"
                  columns={columns}
                  dataSource={assertionRows as Record<string, unknown>[]}
                  pagination={false}
                />
              ),
          },
          { key: 'request', label: '请求快照', children: <JsonView value={ce?.request_snapshot} /> },
          { key: 'web', label: 'Web 步骤与附件', children: <WebArtifacts snapshot={ce?.response_snapshot} /> },
          { key: 'response', label: '响应快照', children: <JsonView value={ce?.response_snapshot} /> },
          { key: 'context', label: '上下文', children: <JsonView value={ce?.context_json} /> },
        ]}
      />
    </Modal>
  );
}

/** 测试报告详情页。 */
export function ConsoleReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const id = reportId ? Number(reportId) : null;
  const navigate = useNavigate();
  const { message: msg, modal } = App.useApp();
  const queryClient = useQueryClient();

  const [selectedCe, setSelectedCe] = useState<CaseExecutionSummary | null>(null);
  const [notifyOpen, setNotifyOpen] = useState(false);
  const [notifyChannelId, setNotifyChannelId] = useState<number | undefined>(undefined);

  const detailQuery = useQuery({
    queryKey: ['test-report-detail', id],
    queryFn: () => reportsApi.get(id!),
    enabled: id != null,
  });

  const channelsQuery = useQuery({
    queryKey: ['notification-channels', 'all', 'for-notify'],
    queryFn: () =>
      detailQuery.data
        ? notificationChannelsApi.list(detailQuery.data.report.project_id, { page: 1, page_size: 100 })
        : Promise.resolve(undefined),
    enabled: !!detailQuery.data,
    staleTime: 60_000,
  });
  const channels = (channelsQuery.data?.items ?? []).filter((c) => c.enabled && c.webhook_configured);

  const recordsQuery = useQuery({
    queryKey: ['report-notifications', id],
    queryFn: () => notificationChannelsApi.listReportNotifications(id!),
    enabled: id != null,
  });

  const regenerateMutation = useMutation({
    mutationFn: () => reportsApi.regenerateAiSummary(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['test-report-detail', id] });
      msg.success('AI 总结已重新生成');
    },
    onError: (e) => msg.error(getErrorMessage(e, 'AI 总结重生成失败')),
  });

  const notifyMutation = useMutation({
    mutationFn: () => notificationChannelsApi.notifyReport(id!, { channel_id: notifyChannelId! }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['report-notifications', id] });
      setNotifyOpen(false);
      setNotifyChannelId(undefined);
      if (data.skipped) {
        msg.warning('已跳过：通知条件不满足或渠道禁用');
      } else if (data.status === 'SUCCESS') {
        msg.success('飞书通知发送成功');
      } else {
        msg.error(`飞书通知发送失败：${data.error_message ?? '未知错误'}`);
      }
    },
    onError: (e) => msg.error(getErrorMessage(e, '通知发送失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: () => reportsApi.remove(id!),
    onSuccess: () => {
      msg.success('报告已删除（执行记录与用例执行结果保留）');
      navigate('/console/test-reports');
    },
    onError: (e) => msg.error(getErrorMessage(e, '删除报告失败')),
  });

  useEffect(() => {
    setSelectedCe(null);
  }, [id]);

  const detail = detailQuery.data;
  const clusters = useMemo<Record<string, unknown>[]>(() => detail?.failure_clusters ?? [], [detail]);

  if (id == null) {
    return (
      <PageContainer>
        <Alert type="error" showIcon message="无效的报告编号" />
      </PageContainer>
    );
  }
  if (detailQuery.isLoading) return <LoadingState />;
  if (detailQuery.isError) {
    return (
      <PageContainer>
        <ErrorState error={detailQuery.error} onRetry={detailQuery.refetch} />
      </PageContainer>
    );
  }
  if (!detail) return null;

  const { report, test_run, case_executions } = detail;
  const failedRows = case_executions.filter((c) => c.status === 'FAILED' || c.status === 'ERROR');

  const caseColumns: TableColumnsType<CaseExecutionSummary> = [
    { title: '用例', dataIndex: 'case_name', ellipsis: true },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 80,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    { title: '类型', dataIndex: 'case_type', width: 110, render: (v: string | null) => v ?? '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => (
        <Tag color={CASE_STATUS_COLOR[v as keyof typeof CASE_STATUS_COLOR] ?? 'default'}>
          {CASE_STATUS_LABEL[v as keyof typeof CASE_STATUS_LABEL] ?? v}
        </Tag>
      ),
    },
    {
      title: '失败分类',
      dataIndex: 'failure_type',
      width: 180,
      render: (v: ReportFailureType | null) =>
        v ? <Tag color={FAILURE_TYPE_COLOR[v] ?? 'default'}>{failureLabel(v)}</Tag> : '-',
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      width: 100,
      align: 'right',
      render: (v: number | null) => (v == null ? '-' : `${(v / 1000).toFixed(2)} s`),
    },
    { title: '错误码', dataIndex: 'error_code', width: 130, render: (v: string | null) => v ?? '-' },
    {
      title: '操作',
      width: 90,
      render: (_, row) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => setSelectedCe(row)}>
          查看
        </Button>
      ),
    },
  ];

  return (
    <PageContainer>
      <Flex align="center" gap="small" style={{ marginBottom: 16 }}>
        <Button icon={<LeftOutlined />} type="text" onClick={() => navigate('/console/test-reports')} />
        <Typography.Title level={5} style={{ margin: 0 }}>
          {report.report_no}
        </Typography.Title>
        <Tag color={REPORT_STATUS_COLOR[report.status] ?? 'default'}>{statusLabel(report.status)}</Tag>
        <Tag color={RISK_COLOR[report.risk_level] ?? 'default'}>风险 {riskLabel(report.risk_level)}</Tag>
      </Flex>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Flex justify="space-between" align="center">
          <Flex vertical gap="2">
            <Typography.Text strong style={{ fontSize: 15 }}>
              {report.title}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              生成于 {fmtTime(report.created_at)}
              {test_run ? ` · 执行 #${test_run.id}` : ' · 关联执行记录已删除'}
            </Typography.Text>
          </Flex>
          <Flex gap="small">
            <Button
              icon={<ReloadOutlined />}
              loading={regenerateMutation.isPending}
              onClick={() =>
                modal.confirm({
                  title: '重新生成 AI 总结？',
                  content: '报告统计字段不可变，仅重新生成 AI 总结（风险等级仍由代码规则决定）。',
                  onOk: () => regenerateMutation.mutateAsync(),
                })
              }
            >
              重新生成 AI 总结
            </Button>
            <Button
              type="primary"
              icon={<SendOutlined />}
              disabled={channels.length === 0}
              onClick={() => {
                if (channels.length === 0) {
                  msg.warning('请先在「飞书通知」中配置启用的通知渠道');
                  return;
                }
                if (channels.length === 1) setNotifyChannelId(channels[0].id);
                setNotifyOpen(true);
              }}
            >
              发送飞书通知
            </Button>
            <Popconfirm
              title="确认删除该报告？"
              description="仅删除报告记录，不会删除执行记录与用例执行结果。"
              onConfirm={() => deleteMutation.mutate()}
            >
              <Button danger icon={<DeleteOutlined />} loading={deleteMutation.isPending}>
                删除报告
              </Button>
            </Popconfirm>
          </Flex>
        </Flex>
        <Divider style={{ margin: '12px 0' }} />
        <Row gutter={16}>
          <Col span={4}>
            <Statistic title="通过率" value={report.pass_rate} precision={2} suffix="%" />
          </Col>
          <Col span={2}>
            <Statistic title="总数" value={report.total_cases} />
          </Col>
          <Col span={2}>
            <Statistic title="通过" value={report.passed_cases} valueStyle={{ color: '#52c41a' }} />
          </Col>
          <Col span={2}>
            <Statistic title="失败" value={report.failed_cases} valueStyle={{ color: '#cf1322' }} />
          </Col>
          <Col span={2}>
            <Statistic title="错误" value={report.error_cases} valueStyle={{ color: '#faad14' }} />
          </Col>
          <Col span={2}>
            <Statistic title="跳过" value={report.skipped_cases} />
          </Col>
          <Col span={6}>
            <Statistic
              title="执行耗时"
              value={report.duration_ms == null ? '-' : (report.duration_ms / 1000).toFixed(2)}
              suffix={report.duration_ms == null ? '' : ' s'}
            />
          </Col>
        </Row>
        <Progress
          style={{ marginTop: 16, marginBottom: 0 }}
          percent={report.pass_rate}
          strokeColor={report.pass_rate >= 90 ? '#52c41a' : report.pass_rate >= 60 ? '#faad14' : '#ff4d4f'}
        />
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 12 }}
          message="统计字段由系统代码计算且不可变，AI 只负责总结、风险解释与失败聚类。"
        />
      </Card>

      <SecuritySummaryCard summary={report.summary} />

      <Tabs
        items={[
          {
            key: 'ai',
            label: `AI 总结${report.ai_summary_version ? `（${report.ai_summary_version}）` : ''}`,
            children: <AiSummaryPanel summary={report.ai_summary} />,
          },
          {
            key: 'failures',
            label: `失败分析${failedRows.length > 0 ? `（${failedRows.length}）` : ''}`,
            children: (
              <div>
                {clusters.length === 0 ? (
                  <Empty description="没有失败或错误的用例" />
                ) : (
                  <Row gutter={[12, 12]}>
                    {clusters.map((c, i) => (
                      <Col key={i} xs={24} sm={12} lg={8}>
                        <Card size="small">
                          <Flex justify="space-between" align="center">
                            <Tag
                              color={FAILURE_TYPE_COLOR[(c.failure_type as ReportFailureType) ?? 'UNKNOWN'] ?? 'default'}
                            >
                              {failureLabel((c.failure_type as ReportFailureType) ?? 'UNKNOWN')}
                            </Tag>
                            <Typography.Text strong>{String(c.count ?? 0)} 条</Typography.Text>
                          </Flex>
                        </Card>
                      </Col>
                    ))}
                  </Row>
                )}
                <Divider />
                {failedRows.length === 0 ? (
                  <Empty description="无失败用例" />
                ) : (
                  <Table
                    rowKey="id"
                    size="small"
                    columns={caseColumns}
                    dataSource={failedRows}
                    pagination={false}
                    expandable={{
                      expandedRowRender: (row) => <JsonView value={row.error_message} />,
                    }}
                  />
                )}
              </div>
            ),
          },
          {
            key: 'cases',
            label: `逐用例执行（${case_executions.length}）`,
            children:
              case_executions.length === 0 ? (
                <Empty description="无逐用例执行数据" />
              ) : (
                <Table
                  rowKey="id"
                  size="small"
                  columns={caseColumns}
                  dataSource={case_executions}
                  pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
                />
              ),
          },
          {
            key: 'notifications',
            label: `通知记录${(recordsQuery.data?.items ?? []).length > 0 ? `（${recordsQuery.data?.total ?? 0}）` : ''}`,
            children: <NotificationRecords records={recordsQuery.data?.items ?? []} loading={recordsQuery.isFetching} />,
          },
        ]}
      />

      <CaseModal ce={selectedCe} onClose={() => setSelectedCe(null)} />

      <Modal
        title="发送飞书通知"
        open={notifyOpen}
        onCancel={() => setNotifyOpen(false)}
        confirmLoading={notifyMutation.isPending}
        onOk={() => {
          if (notifyChannelId == null) {
            msg.warning('请选择一个通知渠道');
            return;
          }
          notifyMutation.mutate();
        }}
      >
        <Flex vertical gap="12">
          <Typography.Text>
            即将把报告 <b>{report.report_no}</b> 的风险等级、通过率与 AI 总结发送到飞书群。
            发送失败不影响报告与执行记录状态。
          </Typography.Text>
          <Select
            placeholder="选择通知渠道"
            style={{ width: '100%' }}
            value={notifyChannelId}
            onChange={setNotifyChannelId}
            options={channels.map((c) => ({
              label: `${c.name}（${c.notify_condition}） ${c.webhook_masked}`,
              value: c.id,
            }))}
          />
          <Alert
            type="info"
            showIcon
            message="提示"
            description="Webhook 地址与签名密钥不会显示、也不会写入报告或通知记录。"
          />
        </Flex>
      </Modal>
    </PageContainer>
  );
}

/** 报告的通知发送审计列表。 */
function NotificationRecords({
  records,
  loading,
}: {
  records: import('@/types').NotificationRecord[];
  loading: boolean;
}) {
  const columns: TableColumnsType<import('@/types').NotificationRecord> = [
    { title: '记录ID', dataIndex: 'id', width: 80 },
    { title: '渠道ID', dataIndex: 'channel_id', width: 90 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (v: string) => (
        <Tag color={NOTIFY_STATUS_COLOR[v as keyof typeof NOTIFY_STATUS_COLOR] ?? 'default'}>
          {notifyStatusLabel(v)}
        </Tag>
      ),
    },
    { title: '错误信息', dataIndex: 'error_message', render: (v: string | null) => v ?? '-' },
    { title: '发送时间', dataIndex: 'sent_at', width: 170, render: (v: string | null) => fmtTime(v) },
    { title: '记录时间', dataIndex: 'created_at', width: 170, render: (v: string) => fmtTime(v) },
  ];
  if (records.length === 0 && !loading) return <Empty description="尚未发送过飞书通知" />;
  return (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      columns={columns}
      dataSource={records}
      pagination={false}
    />
  );
}
