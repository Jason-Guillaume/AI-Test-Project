// OWASP ZAP Job Findings Panel 面板。
// 安全扫描 · 任务详情与结果页共用的四个面板：事件时间线 / 告警 / 覆盖率 / 报告。
// 另加「关联 Finding」面板，用于把扫描命中的疑似问题接回 Phase 1 的疑似问题状态流。
//
// 告警表的两条硬约定：
//   - rule_id 与 risk 显示 ZAP 原文，不做翻译不做映射；
//   - Confidence 与 Severity 是两个独立维度，必须分列展示，不能合并。
import { useState } from 'react';
import { App, Card, Empty, Select, Space, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { zapApi } from '@/features/security-testing/zap/api';
import { securityApi } from '@/features/security-testing/api/securityTesting';
import type { ScanFindingLink } from '@/features/security-testing/zap/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { FINDING_STATUS_OPTIONS, FINDING_STATUS_TRANSITIONS, findingStatusColor, findingStatusLabel } from '../../constants';
import type { SecurityFindingStatus } from '@/features/security-testing/contracts';
import { confidenceColor } from "../constants";
import { PAGE_SIZE, POLL_MS } from './constants';

export function JobFindingsPanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);

  const findingsQuery = useQuery({
    queryKey: ['zap-findings', projectId, jobId, page],
    queryFn: () => zapApi.listScanFindings(projectId, jobId, { page, page_size: PAGE_SIZE }),
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
        <Space wrap className="ui-list-toolbar">
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
      <Table<ScanFindingLink> scroll={{ x: 'max-content' }}
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
