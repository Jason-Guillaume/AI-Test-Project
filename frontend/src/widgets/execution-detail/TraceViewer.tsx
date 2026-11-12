// 可搜索的 Playwright 动作时间线。
//
// 后端 `safe_trace` 显式丢弃 frame-snapshot / screencast-frame / resource-snapshot，
// 因此这里做的是「动作时序」而不是 DOM 回放。标题必须如实说明这一点。
//
// 数据来自 webUIApi.trace(id) 返回 { events: Record<string, unknown>[] }，
// 每行是 Playwright trace 事件：wallTime / startTime / endTime / apiName / callId /
// method / type / params。本组件把这些字段安全收窄成 TraceEvent，避免整行 JSON dump。

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Empty, Input, Select, Space, Table, Tag, theme, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { webUIApi } from '@/features/web-testing/api/webUI';
import { fmtDuration, fmtTimeSec } from '@/shared/lib/format';
import { JsonView } from '@/shared/ui/JsonView';
import type { WebArtifactRef } from '@/features/web-testing/lib/webSnapshot';

/** Playwright 动作事件的最小字段集（严格与后端 safe_trace 输出对齐）。 */
export interface TraceEvent {
  /** 事件类型，如 console / request / response / consoleText / beginAriaSnapshot ... */
  type?: string;
  /** 方法名，如 page.click / locator.fill ... */
  method?: string;
  /** API 名称，如 Page / Locator / BrowserContext */
  apiName?: string;
  /** 调用 ID（后端保留，便于关联 trace 的 start / end） */
  callId?: string;
  /** 事件墙钟时间（ISO 8601） */
  wallTime?: string;
  /** 内部开始时间（ms 或 ISO 8601，视事件而定） */
  startTime?: string | number;
  /** 内部结束时间 */
  endTime?: string | number;
  /** 调用参数（脱敏后的） */
  params?: unknown;
  /** 返回结果（脱敏后的） */
  result?: unknown;
  /** 错误对象（若失败） */
  error?: unknown;
}

/** 表格行结构：TraceEvent + 行内计算的耗时 + 原始事件索引。 */
type TraceRow = TraceEvent & { __i: number; durationMs: number | null };

type SortMode = 'time' | 'duration';

interface TraceViewerProps {
  /** TRACE 类附件；为空时不发起请求 */
  artifact: WebArtifactRef | undefined | null;
  /** 空态文案 */
  emptyText?: string;
}

/** 从原始事件里安全收窄出 TraceEvent。
 *
 * 后端可能写入未知字段（如 metadata / frameId），全部透传到 [key: string]: unknown。
 */
function narrowTraceEvent(raw: Record<string, unknown>): TraceEvent {
  const r = raw as Record<string, unknown>;
  const str = (v: unknown): string | undefined => (typeof v === 'string' ? v : undefined);
  const time = (v: unknown): string | number | undefined =>
    typeof v === 'string' || typeof v === 'number' ? v : undefined;

  return {
    type: str(r.type),
    method: str(r.method),
    apiName: str(r.apiName),
    callId: str(r.callId),
    wallTime: str(r.wallTime),
    startTime: time(r.startTime),
    endTime: time(r.endTime),
    params: r.params,
    result: r.result,
    error: r.error,
  };
}

/** 用起止时间计算行耗时；类型可能不一致（ISO 字符串 vs ms 数字），统一按 Number 差值。 */
function rowDurationMs(start: string | number | undefined, end: string | number | undefined): number | null {
  if (start == null || end == null) return null;
  const s = typeof start === 'number' ? start : Date.parse(start);
  const e = typeof end === 'number' ? end : Date.parse(end);
  if (Number.isNaN(s) || Number.isNaN(e)) return null;
  const d = e - s;
  return d > 0 ? d : null;
}

/**
 * 可搜索动作时间线。
 *
 * 布局：顶部事件类型分布 Tag 组 + 排序与方法筛选栏 + 表格。
 * 事件类型分布只是统计提示，不隐藏原始事件；搜索框支持对方法/名称/参数全文匹配。
 */
export function TraceViewer({ artifact, emptyText = '无 Trace' }: TraceViewerProps) {
  const { token } = theme.useToken();
  const [query, setQuery] = useState('');
  const [sortMode, setSortMode] = useState<SortMode>('time');
  const [methodFilter, setMethodFilter] = useState<string>('');

  const traceQuery = useQuery({
    queryKey: ['web-trace', artifact?.id ?? null],
    queryFn: () => webUIApi.trace(artifact!.id),
    enabled: !!artifact,
  });

  const events = useMemo(() => (traceQuery.data?.events ?? []).map(narrowTraceEvent), [traceQuery.data]);

  // 事件类型分布：按 type 分组计数
  const typeCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const ev of events) {
      const key = ev.type ?? '(unknown)';
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
  }, [events]);

  // 方法下拉选项：只列出实际出现过的方法名，按出现次数倒序
  const methodOptions = useMemo(() => {
    const map = new Map<string, number>();
    for (const ev of events) {
      if (ev.method) map.set(ev.method, (map.get(ev.method) ?? 0) + 1);
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([value, count]) => ({ value, label: `${value} (${count})` }));
  }, [events]);

  // 每行预计算耗时，供表格列渲染与排序使用；__i 是原始事件在全部 events 里的索引
  const rows: TraceRow[] = useMemo(() => {
    const list: TraceRow[] = events.map((ev, i) => ({
      ...ev,
      __i: i,
      durationMs: rowDurationMs(ev.startTime, ev.endTime),
    }));
    const q = query.trim().toLowerCase();
    let filtered = list;
    if (q) {
      filtered = filtered.filter((ev) => {
        const text = `${ev.type ?? ''} ${ev.method ?? ''} ${ev.apiName ?? ''} ${
          typeof ev.params === 'string' ? ev.params : JSON.stringify(ev.params ?? null)
        }`.toLowerCase();
        return text.includes(q);
      });
    }
    if (methodFilter) {
      filtered = filtered.filter((ev) => ev.method === methodFilter);
    }
    return [...filtered].sort((a, b) => {
      if (sortMode === 'duration') {
        return (b.durationMs ?? -1) - (a.durationMs ?? -1);
      }
      return (a.wallTime ?? '').localeCompare(b.wallTime ?? '');
    });
  }, [events, query, methodFilter, sortMode]);

  const columns: TableColumnsType<TraceRow> = [
    {
      title: '#',
      dataIndex: '__i',
      width: 56,
      render: (v: number) => <span style={{ color: token.colorTextTertiary }}>{v + 1}</span>,
    },
    {
      title: '时间',
      dataIndex: 'wallTime',
      width: 168,
      render: (v: string | undefined) =>
        v ? <Typography.Text style={{ fontSize: token.fontSizeSM }}>{fmtTimeSec(v)}</Typography.Text> : '-',
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 120,
      render: (v: string | undefined) => (v ? <Tag bordered={false}>{v}</Tag> : '-'),
    },
    {
      title: '方法',
      dataIndex: 'method',
      width: 220,
      render: (v: string | undefined) =>
        v ? <Typography.Text code style={{ fontSize: token.fontSizeSM }}>{v}</Typography.Text> : '-',
    },
    {
      title: 'API',
      dataIndex: 'apiName',
      width: 140,
      render: (v: string | undefined) =>
        v ? <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{v}</Typography.Text> : '-',
    },
    {
      title: '耗时',
      dataIndex: 'durationMs',
      width: 90,
      render: (v: number | null) =>
        v != null ? (
          <Typography.Text style={{ fontSize: token.fontSizeSM }}>{fmtDuration(v)}</Typography.Text>
        ) : (
          '-'
        ),
    },
    {
      title: '参数',
      dataIndex: 'params',
      render: (v: unknown) => <JsonView value={v} maxHeight={120} emptyText="无参数" copyable={false} />,
    },
  ];

  // 无附件：给出静态提示，不发起请求
  if (!artifact) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>{emptyText}</Typography.Text>
    );
  }

  if (traceQuery.isError) {
    return (
      <div style={{ color: token.colorError, fontSize: token.fontSizeSM }}>
        Trace 加载失败：{(traceQuery.error as Error)?.message ?? '未知错误'}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: token.marginXS }}>
      {/* 事件类型分布 */}
      <Space size={4} wrap>
        <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
          事件类型分布：
        </Typography.Text>
        {typeCounts.length === 0 ? (
          <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
            Trace 为空
          </Typography.Text>
        ) : (
          typeCounts.map(([type, count]) => (
            <Tag key={type} bordered={false} color="default" style={{ fontSize: token.fontSizeSM }}>
              {type} {count}
            </Tag>
          ))
        )}
      </Space>

      {/* 筛选栏 */}
      <div style={{ display: 'flex', gap: token.marginXS, alignItems: 'center', flexWrap: 'wrap' }}>
        <Input
          size="small"
          prefix={<SearchOutlined />}
          placeholder="搜索方法 / 名称 / 参数"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          allowClear
          style={{ width: 240 }}
        />
        <Space size={4}>
          <Button
            type={sortMode === 'time' ? 'primary' : 'default'}
            size="small"
            onClick={() => setSortMode('time')}
          >
            按时间
          </Button>
          <Button
            type={sortMode === 'duration' ? 'primary' : 'default'}
            size="small"
            onClick={() => setSortMode('duration')}
          >
            按耗时
          </Button>
        </Space>
        <Select
          size="small"
          style={{ width: 260 }}
          allowClear
          placeholder="按方法过滤"
          value={methodFilter || undefined}
          onChange={(v) => setMethodFilter(v ?? '')}
          options={methodOptions}
          showSearch
          optionFilterProp="label"
        />
      </div>

      {events.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Trace 为空" />
      ) : (
        <Table
          rowKey={(r) => String(r.__i)}
          size="small"
          loading={traceQuery.isFetching}
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 20, size: 'small' }}
          scroll={{ x: 900 }}
        />
      )}
    </div>
  );
}
