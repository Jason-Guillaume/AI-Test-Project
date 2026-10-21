// 安全扫描 · 任务详情与结果页共用的四个面板：事件时间线 / 告警 / 覆盖率 / 报告。
// 另加「关联 Finding」面板，用于把扫描命中的疑似问题接回 Phase 1 的疑似问题状态流。
//
// 告警表的两条硬约定：
//   - rule_id 与 risk 显示 ZAP 原文，不做翻译不做映射；
//   - Confidence 与 Severity 是两个独立维度，必须分列展示，不能合并。
import { useState } from 'react';
import {
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { JsonView } from '@/components/JsonView';
import { StatusBadge } from '@/components/StatusBadge';
import { securityApi } from '@/api/securityTesting';
import type {
  ScanAlert,
  ScanCoverageRow,
  ScanEvent,
  ScanFindingLink,
  ScanReport,
} from '@/api/securityTesting';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState } from '@/components/PageState';
import {
  FINDING_STATUS_OPTIONS,
  FINDING_STATUS_TRANSITIONS,
  findingStatusColor,
  findingStatusLabel,
  severityColor,
  severityLabel,
} from '../constants';
import type { SecurityFindingStatus } from '@/types';
import {
  confidenceColor,
  CONFIDENCE_TIP,
  coverageStageColor,
  coverageStageLabel,
  JOB_STATUS_OPTIONS,
} from './constants';

/** 状态徽标专用选项（复用 constants 里的标签与色）。 */
const JOB_STATUS_BADGE_OPTIONS = JOB_STATUS_OPTIONS;

const PAGE_SIZE = 20;

/** 任务未结束时的列表轮询间隔。 */
const POLL_MS = 10000;

// --------------------------------------------------------------------------- 事件时间线

/** 事件时间线：按 seq 顺序展示扫描过程事件。 */
export function JobEventsPanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState<string | undefined>(undefined);

  const query = useQuery({
    queryKey: ['zap-events', projectId, jobId, { eventType, page }],
    queryFn: () =>
      securityApi.listScanEvents(projectId, jobId, { page, page_size: PAGE_SIZE, event_type: eventType }),
    refetchInterval: running ? POLL_MS : false,
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const { items, total } = query.data ?? { items: [], total: 0 };

  const columns: TableColumnsType<ScanEvent> = [
    { title: '#', dataIndex: 'seq', width: 60 },
    { title: '事件类型', dataIndex: 'event_type', width: 190 },
    { title: '阶段', dataIndex: 'stage', width: 130, render: (v: string | null) => v ?? '-' },
    {
      title: '说明',
      dataIndex: 'message',
      render: (v: string | null) => v ?? '-',
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string | null) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {v ?? '-'}
        </Typography.Text>
      ),
    },
  ];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Select
            allowClear
            placeholder="事件类型"
            style={{ width: 200 }}
            value={eventType}
            onChange={(v) => {
              setEventType(v);
              setPage(1);
            }}
          />
          <Typography.Text type="secondary">{items.length} 条事件</Typography.Text>
        </Space>
      </Card>
      <Table<ScanEvent>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        expandable={{
          expandedRowRender: (r) => (
            <JsonView value={r.payload_json} maxHeight={240} emptyText="该事件无附加数据" />
          ),
          rowExpandable: (r) => r.payload_json != null,
        }}
        pagination={
          total > PAGE_SIZE
            ? {
                current: page,
                pageSize: PAGE_SIZE,
                total,
                showSizeChanger: false,
                onChange: setPage,
              }
            : { pageSize: PAGE_SIZE, showSizeChanger: false }
        }
      />
    </div>
  );
}

// --------------------------------------------------------------------------- 告警

/** 告警列表：severity 筛选 + Confidence / Severity 分列。 */
export function JobAlertsPanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const [page, setPage] = useState(1);
  const [severity, setSeverity] = useState<string | undefined>(undefined);
  const [ruleId, setRuleId] = useState<string | undefined>(undefined);
  const [detail, setDetail] = useState<ScanAlert | null>(null);

  const query = useQuery({
    queryKey: ['zap-alerts', projectId, jobId, { severity, ruleId, page }],
    queryFn: () =>
      securityApi.listScanAlerts(projectId, jobId, {
        page,
        page_size: PAGE_SIZE,
        severity,
        rule_id: ruleId,
      }),
    refetchInterval: running ? POLL_MS : false,
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const data = query.data ?? { items: [], total: 0, counts: { total: 0, high: 0, medium: 0, low: 0, info: 0 } };
  const { items, total, counts } = data;

  const columns: TableColumnsType<ScanAlert> = [
    {
      title: '规则 ID',
      dataIndex: 'rule_id',
      width: 90,
      render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
    },
    {
      title: '告警',
      dataIndex: 'name',
      render: (_, r) => (
        <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => setDetail(r)}>
          <Typography.Text strong>{r.name}</Typography.Text>
        </Button>
      ),
    },
    {
      title: 'risk（ZAP 原文）',
      dataIndex: 'risk',
      width: 120,
      render: (v: string) => v || '-',
    },
    {
      title: 'Severity（平台）',
      dataIndex: 'severity',
      width: 120,
      render: (v: string) => <Tag color={severityColor(v)}>{severityLabel(v)}</Tag>,
    },
    {
      title: (
        <Tooltip title={CONFIDENCE_TIP}>
          <span>Confidence</span>
        </Tooltip>
      ),
      dataIndex: 'confidence',
      width: 100,
      render: (v: number) => <Tag color={confidenceColor(v)}>{v}</Tag>,
    },
    { title: '方法', dataIndex: 'method', width: 80, render: (v: string) => v || '-' },
    { title: '参数', dataIndex: 'parameter', width: 120, render: (v: string) => v || '-' },
    {
      title: '命中地址',
      dataIndex: 'url',
      render: (v: string) => <Typography.Text style={{ fontSize: 12 }}>{v}</Typography.Text>,
    },
  ];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select
            allowClear
            placeholder="Severity"
            style={{ width: 150 }}
            value={severity}
            onChange={(v) => {
              setSeverity(v);
              setPage(1);
            }}
            options={['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((s) => ({
              value: s,
              label: severityLabel(s),
            }))}
          />
          <Select
            allowClear
            placeholder="规则 ID"
            style={{ width: 170 }}
            value={ruleId}
            onChange={(v) => {
              setRuleId(v);
              setPage(1);
            }}
            options={items.map((a) => ({ value: a.rule_id, label: `${a.rule_id} · ${a.name}` }))}
          />
          <Typography.Text type="secondary">
            共 {counts.total} 条 · 高 {counts.high} · 中 {counts.medium} · 低 {counts.low} · 提示 {counts.info}
          </Typography.Text>
        </Space>
      </Card>

      <Table<ScanAlert>
        rowKey={(r) => `${r.rule_id}|${r.url}|${r.method}|${r.parameter}`}
        size="small"
        columns={columns}
        dataSource={items}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该任务没有告警" /> }}
        pagination={
          total > PAGE_SIZE
            ? {
                current: page,
                pageSize: PAGE_SIZE,
                total,
                showSizeChanger: false,
                onChange: setPage,
              }
            : { pageSize: PAGE_SIZE, showSizeChanger: false }
        }
      />

      {detail && <AlertDrawer alert={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

/** 单条告警详情抽屉。 */
function AlertDrawer({ alert, onClose }: { alert: ScanAlert; onClose: () => void }) {
  return (
    <Drawer
      title={`告警 ${alert.rule_id} · ${alert.name}`}
      open
      onClose={onClose}
      width={560}
      destroyOnClose
    >
      <Descriptions
        size="small"
        column={2}
        bordered
        items={[
          { key: 'rule', label: '规则 ID', children: <Typography.Text code>{alert.rule_id}</Typography.Text> },
          { key: 'risk', label: 'risk（ZAP 原文）', children: alert.risk || '-' },
          { key: 'severity', label: 'Severity（平台）', children: <Tag color={severityColor(alert.severity)}>{severityLabel(alert.severity)}</Tag> },
          {
            key: 'confidence',
            label: 'Confidence（ZAP）',
            children: (
              <Tooltip title={CONFIDENCE_TIP}>
                <Tag color={confidenceColor(alert.confidence)}>{alert.confidence}</Tag>
              </Tooltip>
            ),
          },
          { key: 'method', label: '方法', children: alert.method || '-' },
          { key: 'parameter', label: '参数', children: alert.parameter || '-' },
          { key: 'url', label: '命中地址', children: <Typography.Text code>{alert.url}</Typography.Text>, span: 2 },
          { key: 'description', label: '描述', children: alert.description || '-', span: 2 },
          { key: 'remediation', label: '修复建议', children: alert.remediation || '-', span: 2 },
          { key: 'evidence', label: '证据（已脱敏）', children: alert.evidence || '-', span: 2 },
          {
            key: 'refs',
            label: '参考',
            span: 2,
            children: (
              <Space wrap>
                {alert.cwe_id != null && <Tag>CWE-{alert.cwe_id}</Tag>}
                {alert.wasc_id != null && <Tag>WASC-{alert.wasc_id}</Tag>}
                {alert.reference ? <Typography.Text code>{alert.reference}</Typography.Text> : null}
              </Space>
            ),
          },
        ]}
      />
    </Drawer>
  );
}

// --------------------------------------------------------------------------- 覆盖率

/** 覆盖率：阶段分布摘要 + 每个扫描对象的覆盖阶段。 */
export function JobCoveragePanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ['zap-coverage', projectId, jobId, page],
    queryFn: () => securityApi.getScanCoverage(projectId, jobId, page, PAGE_SIZE),
    refetchInterval: running ? POLL_MS : false,
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const { items, total, summary } = query.data ?? { items: [], total: 0, summary: {} as Record<string, number> };

  const columns: TableColumnsType<ScanCoverageRow> = [
    {
      title: '扫描对象',
      dataIndex: 'identifier',
      render: (v: string) => <Typography.Text style={{ fontSize: 12 }}>{v}</Typography.Text>,
    },
    {
      title: '覆盖阶段',
      dataIndex: 'stage',
      width: 130,
      render: (v: string) => <Tag color={coverageStageColor(v)}>{coverageStageLabel(v)}</Tag>,
    },
    { title: '方法', dataIndex: 'method', width: 80, render: (v: string) => v || '-' },
    { title: '状态码', dataIndex: 'status_code', width: 90, render: (v: number | null) => v ?? '-' },
    {
      title: '被动分析',
      dataIndex: 'passive_analyzed',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="cyan">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '主动扫描',
      dataIndex: 'active_scanned',
      width: 90,
      render: (v: boolean) => (v ? <Tag color="volcano">是</Tag> : <Tag>否</Tag>),
    },
  ];

  return (
    <div>
      {Object.keys(summary).length > 0 ? (
        <Row gutter={16} style={{ marginBottom: 12 }}>
          {Object.entries(summary).map(([stage, count]) => (
            <Col key={stage} xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title={coverageStageLabel(stage)} value={count} />
              </Card>
            </Col>
          ))}
        </Row>
      ) : null}

      <Table<ScanCoverageRow>
        rowKey={(r) => `${r.identifier}|${r.method}`}
        size="small"
        columns={columns}
        dataSource={items}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无覆盖率数据" /> }}
        pagination={
          total > PAGE_SIZE
            ? {
                current: page,
                pageSize: PAGE_SIZE,
                total,
                showSizeChanger: false,
                onChange: setPage,
              }
            : { pageSize: PAGE_SIZE, showSizeChanger: false }
        }
      />
    </div>
  );
}

// --------------------------------------------------------------------------- 关联 Finding

/**
 * 关联 Finding：扫描命中的疑似问题本体在 Phase 1 的 security_finding 上，
 * 状态流转（确认 / 误报 / 已修复）走 Phase 1 的 PATCH /security-findings/{id}。
 * 重新扫描不会重置人工确认或误报状态（§十九）。
 */
export function JobFindingsPanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);

  const findingsQuery = useQuery({
    queryKey: ['zap-findings', projectId, jobId, page],
    queryFn: () => securityApi.listScanFindings(projectId, jobId, { page, page_size: PAGE_SIZE }),
    refetchInterval: running ? POLL_MS : false,
  });

  // 关联的疑似问题本体（Phase 1），用来拿到 status 并做状态流转。
  const findingIds = (findingsQuery.data?.items ?? []).map((f) => f.finding_id);
  const findingDetailsQuery = useQuery({
    queryKey: ['security-findings', projectId, 'by-ids', findingIds],
    queryFn: async () => {
      const results = await Promise.all(
        findingIds.map((id) => securityApi.getFinding(id).catch(() => null)),
      );
      return results.filter((f): f is NonNullable<typeof f> => f != null);
    },
    enabled: findingIds.length > 0,
  });
  const statusOf = new Map(
    (findingDetailsQuery.data ?? []).map((f) => [f.id, f.status] as const),
  );

  const updateStatusMutation = useMutation({
    mutationFn: ({ id, next }: { id: number; next: SecurityFindingStatus }) =>
      securityApi.updateFinding(id, { status: next }),
    onSuccess: () => {
      message.success('状态已更新');
      queryClient.invalidateQueries({ queryKey: ['security-findings'] });
      queryClient.invalidateQueries({ queryKey: ['zap-findings'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '状态更新失败（可能是不允许的迁移）')),
  });

  if (findingsQuery.isLoading) return <LoadingState />;
  if (findingsQuery.isError) return <ErrorState error={findingsQuery.error} onRetry={findingsQuery.refetch} />;

  const all = findingsQuery.data?.items ?? [];
  const items = all.filter((f) => {
    if (!statusFilter) return true;
    return (statusOf.get(f.finding_id) ?? '') === statusFilter;
  });

  const columns: TableColumnsType<ScanFindingLink> = [
    {
      title: '疑似问题',
      width: 150,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>#{r.finding_id}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.source_alert_name ?? '-'}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '状态',
      width: 110,
      render: (_, r) => {
        const s = statusOf.get(r.finding_id);
        return s ? <Tag color={findingStatusColor(s)}>{findingStatusLabel(s)}</Tag> : <Tag>加载中</Tag>;
      },
    },
    { title: '规则 ID', dataIndex: 'source_rule_id', width: 90, render: (v: string | null) => v ?? '-' },
    { title: 'risk', dataIndex: 'risk', width: 90, render: (v: string | null) => v ?? '-' },
    {
      title: 'Confidence',
      dataIndex: 'confidence',
      width: 100,
      render: (v: number | null) =>
        v == null ? '-' : <Tag color={confidenceColor(v)}>{v}</Tag>,
    },
    {
      title: '命中',
      width: 200,
      render: (_, r) => (
        <Typography.Text style={{ fontSize: 12 }}>
          {r.method ?? ''} {r.url ?? ''}
        </Typography.Text>
      ),
    },
    {
      title: '首次 / 重复',
      width: 120,
      render: (_, r) =>
        r.first_seen_in_job ? <Tag color="volcano">首次命中</Tag> : <Tag>重复命中 ×{r.repeat_count}</Tag>,
    },
    {
      title: '处置',
      width: 160,
      render: (_, r) => {
        const s = statusOf.get(r.finding_id);
        return s ? (
          <Select
            size="small"
            style={{ width: 130 }}
            placeholder="变更状态"
            value={undefined}
            onChange={(next: SecurityFindingStatus) => updateStatusMutation.mutate({ id: r.finding_id, next })}
            options={(FINDING_STATUS_TRANSITIONS[s] ?? []).map((v) => {
              const o = FINDING_STATUS_OPTIONS.find((x) => x.value === v);
              return o ? { value: v, label: o.label } : { value: v, label: v };
            })}
          />
        ) : null;
      },
    },
  ];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space>
          <Select
            allowClear
            placeholder="疑似问题状态"
            style={{ width: 160 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={FINDING_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          />
          <Typography.Text type="secondary">
            共关联 {findingsQuery.data?.total ?? all.length} 条疑似问题
          </Typography.Text>
        </Space>
      </Card>
      <Table<ScanFindingLink>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该任务没有关联疑似问题" /> }}
        pagination={
          (findingsQuery.data?.total ?? 0) > PAGE_SIZE
            ? {
                current: page,
                pageSize: PAGE_SIZE,
                total: findingsQuery.data?.total,
                showSizeChanger: false,
                onChange: setPage,
              }
            : { pageSize: PAGE_SIZE, showSizeChanger: false }
        }
      />
    </div>
  );
}

// --------------------------------------------------------------------------- 报告

/** 报告：数字全部来自任务记录本身，不接受前端传入（§二十五）。 */
export function JobReportPanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const query = useQuery({
    queryKey: ['zap-report', projectId, jobId],
    queryFn: () => securityApi.getScanReport(projectId, jobId),
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
          <Table<ScanAlert>
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
export function ScanJobStatusBadge({ status }: { status: string }) {
  return <StatusBadge value={status} options={JOB_STATUS_BADGE_OPTIONS} />;
}
