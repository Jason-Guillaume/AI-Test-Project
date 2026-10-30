import { Button, Card, Col, Row, Skeleton, Tag } from 'antd';
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { dashboardApi } from '@/features/dashboard/api/dashboard';
import type { DashboardCharts as DashboardChartsData, DashboardDailyCount, DashboardDefectSeverityItem, DashboardExecutionTrendItem } from '@/features/dashboard/contracts';


const SEVERITY_COLORS: Record<number, string> = {
  1: 'var(--chart-severity-low)',
  2: 'var(--chart-severity-medium)',
  3: 'var(--chart-severity-high)',
  4: 'var(--chart-severity-critical)',
};

const CHART_WIDTH = 520;
const CHART_HEIGHT = 220;
const PLOT = { left: 38, right: 12, top: 14, bottom: 36 };

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
  const plotWidth = CHART_WIDTH - PLOT.left - PLOT.right;
  const plotHeight = CHART_HEIGHT - PLOT.top - PLOT.bottom;
  const maxValue = Math.max(0, ...data.map((point) => point.total));
  const maxY = Math.max(5, Math.ceil(maxValue / 5) * 5);
  const x = (index: number) =>
    PLOT.left + (data.length <= 1 ? plotWidth / 2 : (index / (data.length - 1)) * plotWidth);
  const y = (value: number) => PLOT.top + plotHeight - (value / maxY) * plotHeight;
  const series = [
    { key: 'total', label: '执行总数', color: 'var(--chart-blue)' },
    { key: 'passed', label: '通过', color: 'var(--chart-green)' },
    { key: 'failed', label: '失败 / 异常', color: 'var(--chart-red)' },
  ] as const;

  return (
    <div className="dashboard-chart-content">
      <svg
        className="dashboard-chart-svg"
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        role="img"
        aria-label="最近七天用例执行总数、通过数和失败异常数折线图"
      >
        {Array.from({ length: 5 }, (_, index) => {
          const value = (maxY / 4) * (4 - index);
          const lineY = y(value);
          return (
            <g key={index}>
              <line className="dashboard-chart-gridline" x1={PLOT.left} x2={CHART_WIDTH - PLOT.right} y1={lineY} y2={lineY} />
              <text className="dashboard-chart-axis-label" x={PLOT.left - 9} y={lineY + 4} textAnchor="end">{Math.round(value)}</text>
            </g>
          );
        })}
        {data.map((point, index) => (
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
          <text className="dashboard-chart-empty-label" x={PLOT.left + plotWidth / 2} y={PLOT.top + plotHeight / 2} textAnchor="middle">暂无执行记录</text>
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
  const plotWidth = CHART_WIDTH - PLOT.left - PLOT.right;
  const plotHeight = CHART_HEIGHT - PLOT.top - PLOT.bottom;
  const maxValue = Math.max(0, ...data.map((point) => point.count));
  const maxY = Math.max(5, Math.ceil(maxValue / 5) * 5);
  const slotWidth = data.length ? plotWidth / data.length : plotWidth;
  const barWidth = Math.min(34, slotWidth * 0.56);
  const y = (value: number) => PLOT.top + plotHeight - (value / maxY) * plotHeight;

  return (
    <div className="dashboard-chart-content">
      <svg
        className="dashboard-chart-svg"
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        role="img"
        aria-label="最近七天 AI 生成并保存的用例数量柱状图"
      >
        {Array.from({ length: 5 }, (_, index) => {
          const value = (maxY / 4) * (4 - index);
          const lineY = y(value);
          return (
            <g key={index}>
              <line className="dashboard-chart-gridline" x1={PLOT.left} x2={CHART_WIDTH - PLOT.right} y1={lineY} y2={lineY} />
              <text className="dashboard-chart-axis-label" x={PLOT.left - 9} y={lineY + 4} textAnchor="end">{Math.round(value)}</text>
            </g>
          );
        })}
        {data.map((point, index) => {
          const barHeight = (point.count / maxY) * plotHeight;
          const barX = PLOT.left + slotWidth * index + (slotWidth - barWidth) / 2;
          return (
            <g key={point.date}>
              <rect className="dashboard-chart-bar" x={barX} y={y(point.count)} width={barWidth} height={Math.max(0, barHeight)} rx="5">
                <title>{`${dayLabel(point.date)} AI 生成用例：${point.count}`}</title>
              </rect>
              <text className="dashboard-chart-axis-label" x={barX + barWidth / 2} y={CHART_HEIGHT - 10} textAnchor="middle">{dayLabel(point.date)}</text>
            </g>
          );
        })}
        {maxValue === 0 && (
          <text className="dashboard-chart-empty-label" x={PLOT.left + plotWidth / 2} y={PLOT.top + plotHeight / 2} textAnchor="middle">暂无 AI 生成记录</text>
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
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={8}>
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
        </Col>
        <Col xs={24} xl={8}>
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
        </Col>
        <Col xs={24} xl={8}>
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
        </Col>
      </Row>
    </section>
  );
}
