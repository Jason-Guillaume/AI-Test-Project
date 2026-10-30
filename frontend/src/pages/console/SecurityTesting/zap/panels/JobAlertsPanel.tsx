// OWASP ZAP Job Alerts Panel 面板。
// 安全扫描 · 任务详情与结果页共用的四个面板：事件时间线 / 告警 / 覆盖率 / 报告。
// 另加「关联 Finding」面板，用于把扫描命中的疑似问题接回 Phase 1 的疑似问题状态流。
//
// 告警表的两条硬约定：
//   - rule_id 与 risk 显示 ZAP 原文，不做翻译不做映射；
//   - Confidence 与 Severity 是两个独立维度，必须分列展示，不能合并。
import { useState } from 'react';
import { Button, Card, Descriptions, Drawer, Empty, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { zapApi } from '@/features/security-testing/zap/api';
import type { ScanAlert } from '@/features/security-testing/zap/contracts';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { severityColor, severityLabel } from '../../constants';
import { confidenceColor, CONFIDENCE_TIP } from "../constants";
import { PAGE_SIZE, POLL_MS } from './constants';

export function JobAlertsPanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const [page, setPage] = useState(1);
  const [severity, setSeverity] = useState<string | undefined>(undefined);
  const [ruleId, setRuleId] = useState<string | undefined>(undefined);
  const [detail, setDetail] = useState<ScanAlert | null>(null);

  const query = useQuery({
    queryKey: ['zap-alerts', projectId, jobId, { severity, ruleId, page }],
    queryFn: () =>
      zapApi.listScanAlerts(projectId, jobId, {
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

      <Table<ScanAlert> scroll={{ x: 'max-content' }}
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
