// OWASP ZAP Job Coverage Panel 面板。
// 安全扫描 · 任务详情与结果页共用的四个面板：事件时间线 / 告警 / 覆盖率 / 报告。
// 另加「关联 Finding」面板，用于把扫描命中的疑似问题接回 Phase 1 的疑似问题状态流。
//
// 告警表的两条硬约定：
//   - rule_id 与 risk 显示 ZAP 原文，不做翻译不做映射；
//   - Confidence 与 Severity 是两个独立维度，必须分列展示，不能合并。
import { useState } from 'react';
import { Card, Col, Empty, Row, Statistic, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { zapApi } from '@/features/security-testing/zap/api';
import type { ScanCoverageRow } from '@/features/security-testing/zap/contracts';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { coverageStageColor, coverageStageLabel } from "../constants";
import { PAGE_SIZE, POLL_MS } from './constants';

export function JobCoveragePanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ['zap-coverage', projectId, jobId, page],
    queryFn: () => zapApi.getScanCoverage(projectId, jobId, page, PAGE_SIZE),
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

      <Table<ScanCoverageRow> scroll={{ x: 'max-content' }}
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
