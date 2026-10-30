// OWASP ZAP Job Events Panel 面板。
// 安全扫描 · 任务详情与结果页共用的四个面板：事件时间线 / 告警 / 覆盖率 / 报告。
// 另加「关联 Finding」面板，用于把扫描命中的疑似问题接回 Phase 1 的疑似问题状态流。
//
// 告警表的两条硬约定：
//   - rule_id 与 risk 显示 ZAP 原文，不做翻译不做映射；
//   - Confidence 与 Severity 是两个独立维度，必须分列展示，不能合并。
import { useState } from 'react';
import { Card, Select, Space, Table, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { JsonView } from '@/shared/ui/JsonView';
import { zapApi } from '@/features/security-testing/zap/api';
import type { ScanEvent } from '@/features/security-testing/zap/contracts';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { PAGE_SIZE, POLL_MS } from './constants';

export function JobEventsPanel({ projectId, jobId, running = false }: { projectId: number; jobId: number; running?: boolean }) {
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState<string | undefined>(undefined);

  const query = useQuery({
    queryKey: ['zap-events', projectId, jobId, { eventType, page }],
    queryFn: () =>
      zapApi.listScanEvents(projectId, jobId, { page, page_size: PAGE_SIZE, event_type: eventType }),
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
        <Space wrap className="ui-list-toolbar">
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
      <Table<ScanEvent> scroll={{ x: 'max-content' }}
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
