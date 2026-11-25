import { Button, Card, Skeleton, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { type ReactNode, useLayoutEffect, useRef, useState } from 'react';
import { dashboardApi } from '@/features/dashboard/api/dashboard';
import type { DashboardCharts as DashboardChartsData, DashboardDailyCount, DashboardDefectSeverityItem, DashboardExecutionTrendItem } from '@/features/dashboard/contracts';


const SEVERITY_COLORS: Record<number, string> = {
  1: 'var(--chart-severity-low)',
  2: 'var(--chart-severity-medium)',
  3: 'var(--chart-severity-high)',
  4: 'var(--chart-severity-critical)',
};

const CHART_HEIGHT = 220;
const PLOT = { right: 20, top: 14, bottom: 36 };
const PLOT_HEIGHT = CHART_HEIGHT - PLOT.top - PLOT.bottom;

function useCountChart(maxValue: number) {
  const ref = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(320);
  useLayoutEffect(() => {
    const svg = ref.current;
    if (!svg) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setWidth(entry.contentRect.width);
    });
    observer.observe(svg);
    return () => observer.disconnect();
  }, []);
  const maxY = Math.max(5, Math.ceil(maxValue / 5) * 5);
  const left = Math.max(38, String(maxY).length * 8 + 12);
  const plotWidth = Math.max(1, width - left - PLOT.right);
  const y = (value: number) => PLOT.top + PLOT_HEIGHT * (1 - value / maxY);
  return { ref, width, left, plotWidth, maxY, y };
}

function CountGrid({ maxY, left, width }: { maxY: number; left: number; width: number }) {
  return Array.from({ length: 6 }, (_, index) => {
    const value = (maxY / 5) * (5 - index);
    const lineY = PLOT.top + PLOT_HEIGHT * index / 5;
    return (
      <g key={value}>
        <line className="dashboard-chart-gridline" x1={left} x2={width - PLOT.right} y1={lineY} y2={lineY} />
        <text className="dashboard-chart-axis-label" x={left - 9} y={lineY + 4} textAnchor="end">{value}</text>
      </g>
    );
  });
}

function dateTickIndices(count: number, plotWidth: number) {
  if (count < 2) return new Set(count ? [0] : []);
  const last = count - 1;
  const pointGap = plotWidth / last;
  const minStep = Math.max(1, Math.ceil(40 / Math.max(1, pointGap)));
  const intervals = Math.max(1, Math.floor(last / minStep));
  return new Set(Array.from({ length: intervals + 1 }, (_, i) => Math.round(i * last / intervals)));
}

function dayLabel(value: string) {
  return value.slice(5).replace('-', '/');
}

function ChartLoading() {
  return <Skeleton active title={false} paragraph={{ rows: 5 }} />;
}

function ChartError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="dashboard-chart-error">
      <span>统计数据暂时无法加载</span>
      <Button size="small" onClick={onRetry}>重试</Button>
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  extra,
  children,
}: {
  title: string;
  subtitle: string;
  extra: string;
  children: ReactNode;
}) {
  return (
    <Card
      className="dashboard-chart-card"
      title={
        <div className="dashboard-chart-heading">
          <strong>{title}</strong>
          <span>{subtitle}</span>
        </div>
      }
      extra={<Tag bordered={false}>{extra}</Tag>}
    >
      {children}
    </Card>
  );
}

function LineChart({ data }: { data: DashboardExecutionTrendItem[] }) {
  const maxValue = Math.max(0, ...data.map((point) => point.total));
  const { ref, width, left, plotWidth, maxY, y } = useCountChart(maxValue);
  const dateTicks = dateTickIndices(data.length, plotWidth);
  const x = (index: number) =>
    left + (data.length <= 1 ? plotWidth / 2 : (index / (data.length - 1)) * plotWidth);
  const series = [
    { key: 'total', label: '执行总数', color: 'var(--chart-blue)' },
    { key: 'passed', label: '通过', color: 'var(--chart-green)' },
    { key: 'failed', label: '失败 / 异常', color: 'var(--chart-red)' },
  ] as const;

  return (
    <div className="dashboard-chart-content">
      <svg
        ref={ref}
        className="dashboard-chart-svg"
        height={CHART_HEIGHT}
        viewBox={`0 0 ${width} ${CHART_HEIGHT}`}
        role="img"
        aria-label="最近七天用例执行总数、通过数和失败异常数折线图"
      >
        <CountGrid maxY={maxY} left={left} width={width} />
        {data.map((point, index) => dateTicks.has(index) && (
          <text key={point.date} className="dashboard-chart-axis-label" x={x(index)} y={CHART_HEIGHT - 10} textAnchor="middle">
            {dayLabel(point.date)}
          </text>
        ))}
        {series.map((line) => {
          const points = data.map((point, index) => `${x(index)},${y(point[line.key])}`).join(' ');
          return (
            <g key={line.key}>
              <polyline className="dashboard-chart-line" points={points} stroke={line.color} />
              {data.map((point, index) => (
                <circle key={point.date} className="dashboard-chart-point" cx={x(index)} cy={y(point[line.key])} r="3.5" fill={line.color}>
                  <title>{`${dayLabel(point.date)} ${line.label}：${point[line.key]}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
        {maxValue === 0 && (
          <text className="dashboard-chart-empty-label" x={left + plotWidth / 2} y={PLOT.top + PLOT_HEIGHT / 2} textAnchor="middle">暂无执行记录</text>
        )}
      </svg>
      <div className="dashboard-chart-legend">
        {series.map((line) => (
          <span key={line.key}><i style={{ backgroundColor: line.color }} />{line.label}</span>
        ))}
      </div>
    </div>
  );
}

function DefectDonut({ data }: { data: DashboardDefectSeverityItem[] }) {
  const orderedData = [...data].sort((a, b) => b.severity - a.severity);
  const total = data.reduce((sum, item) => sum + item.value, 0);
  const circumference = 2 * Math.PI * 56;
  let offset = 0;

  return (
    <div className="dashboard-donut-layout">
      <svg className="dashboard-donut-svg" viewBox="0 0 180 180" role="img" aria-label={`缺陷严重程度分布，共 ${total} 个缺陷`}>
        <circle className="dashboard-donut-track" cx="90" cy="90" r="56" />
        {total > 0 && orderedData.map((item) => {
          const length = (item.value / total) * circumference;
          const dash = Math.max(0, length - 3);
          const dashOffset = offset;
          offset += length;
          if (!item.value) return null;
          return (
            <circle
              key={item.severity}
              className="dashboard-donut-segment"
              cx="90"
              cy="90"
              r="56"
              transform="rotate(-90 90 90)"
              stroke={SEVERITY_COLORS[item.severity]}
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-dashOffset}
            >
              <title>{`${item.label}：${item.value}`}</title>
            </circle>
          );
        })}
        <text className="dashboard-donut-total" x="90" y="87" textAnchor="middle">{total}</text>
        <text className="dashboard-donut-caption" x="90" y="108" textAnchor="middle">缺陷总数</text>
      </svg>
      <div className="dashboard-severity-legend">
        {orderedData.map((item) => (
          <div className="dashboard-severity-row" key={item.severity}>
            <span className="dashboard-severity-label">
              <i style={{ backgroundColor: SEVERITY_COLORS[item.severity] }} />{item.label}
            </span>
            <strong>{item.value}</strong>
            <small>{total ? `${Math.round((item.value / total) * 100)}%` : '0%'}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

function BarChart({ data }: { data: DashboardDailyCount[] }) {
  const maxValue = Math.max(0, ...data.map((point) => point.count));
  const { ref, width, left, plotWidth, maxY, y } = useCountChart(maxValue);
  const slotWidth = data.length ? plotWidth / data.length : plotWidth;
  const dateTicks = dateTickIndices(data.length, plotWidth - slotWidth);
  const barWidth = Math.min(34, slotWidth * 0.56);

  return (
    <div className="dashboard-chart-content">
      <svg
        ref={ref}
        className="dashboard-chart-svg"
        height={CHART_HEIGHT}
        viewBox={`0 0 ${width} ${CHART_HEIGHT}`}
        role="img"
        aria-label="最近七天 AI 生成并保存的用例数量柱状图"
      >
        <CountGrid maxY={maxY} left={left} width={width} />
        {data.map((point, index) => {
          const barHeight = (point.count / maxY) * PLOT_HEIGHT;
          const barX = left + slotWidth * index + (slotWidth - barWidth) / 2;
          return (
            <g key={point.date}>
              <rect className="dashboard-chart-bar" x={barX} y={y(point.count)} width={barWidth} height={Math.max(0, barHeight)} rx="5">
                <title>{`${dayLabel(point.date)} AI 生成用例：${point.count}`}</title>
              </rect>
              {dateTicks.has(index) && <text className="dashboard-chart-axis-label" x={barX + barWidth / 2} y={CHART_HEIGHT - 10} textAnchor="middle">{dayLabel(point.date)}</text>}
            </g>
          );
        })}
        {maxValue === 0 && (
          <text className="dashboard-chart-empty-label" x={left + plotWidth / 2} y={PLOT.top + PLOT_HEIGHT / 2} textAnchor="middle">暂无 AI 生成记录</text>
        )}
      </svg>
      <div className="dashboard-chart-legend">
        <span><i className="dashboard-chart-legend-bar" />AI 生成并保存的用例</span>
      </div>
    </div>
  );
}

function ChartPanel({
  title,
  subtitle,
  extra,
  loading,
  error,
  retry,
  children,
}: {
  title: string;
  subtitle: string;
  extra: string;
  loading: boolean;
  error: boolean;
  retry: () => void;
  children: ReactNode;
}) {
  return (
    <ChartCard title={title} subtitle={subtitle} extra={extra}>
      {loading ? <ChartLoading /> : error ? <ChartError onRetry={retry} /> : children}
    </ChartCard>
  );
}

export function DashboardCharts({
  organizationId,
  projectId,
}: {
  organizationId: number | null;
  projectId: number | null;
}) {
  const params = {
    days: 7,
    organization_id: organizationId ?? undefined,
    project_id: projectId ?? undefined,
  };
  const query = useQuery({
    queryKey: ['dashboard', 'charts', params],
    queryFn: () => dashboardApi.charts(params),
    staleTime: 0,
  });
  const data: DashboardChartsData | undefined = query.data;

  return (
    <section className="dashboard-charts" aria-label="测试质量统计图表">
      <ChartPanel
        title="用例执行趋势"
        subtitle="执行数、通过数与失败异常数"
        extra="最近 7 天"
        loading={query.isPending}
        error={query.isError}
        retry={query.refetch}
      >
        <LineChart data={data?.execution_trend ?? []} />
      </ChartPanel>
      <ChartPanel
        title="缺陷严重程度"
        subtitle="按当前工作范围内的缺陷等级统计"
        extra="全部缺陷"
        loading={query.isPending}
        error={query.isError}
        retry={query.refetch}
      >
        <DefectDonut data={data?.defect_severity ?? []} />
      </ChartPanel>
      <ChartPanel
        title="用例生成趋势"
        subtitle="AI 生成并保存的用例数量"
        extra="最近 7 天"
        loading={query.isPending}
        error={query.isError}
        retry={query.refetch}
      >
        <BarChart data={data?.case_generation ?? []} />
      </ChartPanel>
    </section>
  );
}
