// 测试报告列表页：按项目分页列出正式测试报告，支持环境 / 风险等级 / 状态筛选。
//
// 数据：GET /projects/{project_id}/reports 返回分页信封 {items,total,page,page_size}。
// 权限（服务端为准）：读 = 项目可见（viewer+）；越权 404，前端不展示。
// 报告统计字段全部由后端代码计算，本页只展示，不做二次计算。
// 筛选走 FilterToolbar（服务端筛选，无关键词搜索），状态与风险走 StatusBadge + shared/status 色板。
import { useMemo, useState } from 'react';
import { Button, Progress, Table, theme } from 'antd';
import { EyeOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import type { TableColumnsType } from 'antd';
import { reportsApi } from '@/api/reports';
import { projectsApi } from '@/api/projects';
import { FilterToolbar } from '@/components/FilterToolbar';
import { EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { PageHeader } from '@/components/PageHeader';
import { StatusBadge } from '@/components/StatusBadge';
import { fmtDuration, fmtTime } from '@/shared/format';
import { REPORT_RISK_COLOR, REPORT_STATUS_COLOR } from '@/shared/status';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import { REPORT_RISK_OPTIONS, REPORT_STATUS_OPTIONS } from './constants';
import type { ReportRiskLevel, ReportStatus, TestReportListItem } from '@/types';

interface Filters {
  environment_id?: number;
  risk_level?: ReportRiskLevel;
  status?: ReportStatus;
}

/** 测试报告列表页。 */
export function ConsoleReportListPage() {
  const { currentProjectId } = useConsoleScope();
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const [filters, setFilters] = useState<Filters>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const envsQuery = useQuery({
    queryKey: ['project-environments', currentProjectId],
    queryFn: () => projectsApi.listEnvironments(currentProjectId!),
    enabled: currentProjectId != null,
    staleTime: 60_000,
  });
  const envs = envsQuery.data?.items ?? [];

  const reportsQuery = useQuery({
    queryKey: ['test-reports', currentProjectId, page, pageSize, filters],
    queryFn: () => reportsApi.list(currentProjectId!, { page, page_size: pageSize, ...filters }),
    enabled: currentProjectId != null,
  });

  // 服务端筛选：改动任一筛选器即回到第一页并重新拉取
  const onFilterChange = (key: string, value: string | undefined) => {
    setFilters((prev) => {
      const next: Filters = { ...prev };
      if (key === 'environment_id') {
        next.environment_id = value == null ? undefined : Number(value);
      } else if (key === 'risk_level') {
        next.risk_level = value == null ? undefined : (value as ReportRiskLevel);
      } else if (key === 'status') {
        next.status = value == null ? undefined : (value as ReportStatus);
      }
      return next;
    });
    setPage(1);
  };

  const rows: TestReportListItem[] = reportsQuery.data?.items ?? [];
  const total = reportsQuery.data?.total ?? 0;
  const currentPage = reportsQuery.data?.page ?? page;

  const columns: TableColumnsType<TestReportListItem> = useMemo(
    () => [
      { title: '报告编号', dataIndex: 'report_no', width: 170 },
      { title: '标题', dataIndex: 'title', ellipsis: true },
      {
        title: '风险',
        dataIndex: 'risk_level',
        width: 110,
        render: (v: ReportRiskLevel) => (
          <StatusBadge value={v} options={REPORT_RISK_OPTIONS} color={REPORT_RISK_COLOR[v]} />
        ),
      },
      {
        title: '通过率',
        dataIndex: 'pass_rate',
        width: 150,
        render: (v: number) => (
          <Progress
            percent={v}
            size="small"
            strokeColor={v >= 90 ? token.colorSuccess : v >= 60 ? token.colorWarning : token.colorError}
          />
        ),
      },
      {
        title: '总数',
        width: 190,
        render: (_, r) => (
          <span style={{ whiteSpace: 'nowrap' }}>
            <b>{r.total_cases}</b>
            <span style={{ color: token.colorTextTertiary, fontSize: token.fontSizeSM, marginLeft: token.marginXXS }}>
              通过 {r.passed_cases} / 失败 {r.failed_cases} / 错误 {r.error_cases}
            </span>
          </span>
        ),
      },
      {
        title: '耗时',
        dataIndex: 'duration_ms',
        width: 100,
        align: 'right',
        render: (v: number | null) => fmtDuration(v),
      },
      {
        title: '状态',
        dataIndex: 'status',
        width: 130,
        render: (v: ReportStatus) => (
          <StatusBadge value={v} options={REPORT_STATUS_OPTIONS} color={REPORT_STATUS_COLOR[v]} />
        ),
      },
      { title: '生成时间', dataIndex: 'created_at', width: 160, render: (v: string) => fmtTime(v) },
      {
        title: '操作',
        width: 110,
        fixed: 'right',
        render: (_, row) => (
          <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/console/test-reports/${row.id}`)}>
            查看详情
          </Button>
        ),
      },
    ],
    [navigate, token],
  );

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="测试报告"
        subtitle="报告由测试执行结果自动生成；统计数据不可变，AI 仅负责总结与风险解释。"
      />

      <FilterToolbar
        showSearch={false}
        selects={[
          {
            key: 'environment_id',
            label: '环境',
            placeholder: '全部环境',
            options: envs.map((e) => ({
              label: e.display_name || e.name,
              value: e.id == null ? '' : String(e.id),
            })).filter((o) => o.value !== ''),
          },
          { key: 'risk_level', label: '风险等级', placeholder: '全部风险', options: REPORT_RISK_OPTIONS },
          { key: 'status', label: '状态', placeholder: '全部状态', options: REPORT_STATUS_OPTIONS },
        ]}
        values={
          filters.environment_id == null
            ? { risk_level: filters.risk_level, status: filters.status }
            : { environment_id: String(filters.environment_id), risk_level: filters.risk_level, status: filters.status }
        }
        onFilterChange={onFilterChange}
        onReset={() => {
          setFilters({});
          setPage(1);
        }}
      />

      {reportsQuery.isLoading ? (
        <LoadingState />
      ) : rows.length === 0 ? (
        <EmptyState description="暂无测试报告，可先在「执行历史」中执行测试用例生成报告" />
      ) : (
        <Table<TestReportListItem>
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={rows}
          scroll={{ x: 1160 }}
          loading={reportsQuery.isFetching}
          pagination={{
            current: currentPage,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            pageSizeOptions: [10, 20, 50],
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      )}
    </PageContainer>
  );
}
