// 测试报告列表页：按项目分页列出正式测试报告，支持环境 / 风险等级 / 状态筛选。
//
// 数据：GET /projects/{project_id}/reports 返回分页信封 {items,total,page,page_size}。
// 权限（服务端为准）：读 = 项目可见（viewer+）；越权 404，前端不展示。
// 报告统计字段全部由后端代码计算，本页只展示，不做二次计算。
// 筛选走 FilterToolbar（服务端筛选，无关键词搜索），状态与风险颜色由 reports feature 提供。
import { useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Checkbox, Progress, Space, Table, theme } from 'antd';
import { DeleteOutlined, EyeOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import type { TableColumnsType } from 'antd';
import { reportsApi } from '@/features/reports/api/reports';
import { getErrorMessage } from '@/shared/api/client';
import { projectsApi } from '@/features/projects/api/projects';
import { FilterToolbar } from '@/shared/ui/FilterToolbar';
import { EmptyState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { fmtDuration, fmtTime } from '@/shared/lib/format';
import { REPORT_RISK_COLOR, REPORT_STATUS_COLOR } from '@/features/reports/status';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { REPORT_RISK_OPTIONS, REPORT_STATUS_OPTIONS } from './constants';
import type { ReportRiskLevel, ReportStatus, TestReportListItem } from '@/features/reports/contracts';
import type { BatchLifecycleReceipt } from '@/features/data-lifecycle/api';


interface Filters {
  environment_id?: number;
  risk_level?: ReportRiskLevel;
  status?: ReportStatus;
}

/** 测试报告列表页。 */
export function ConsoleReportListPage() {
  const { currentProjectId } = useConsoleScope();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const [filters, setFilters] = useState<Filters>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedReportIds, setSelectedReportIds] = useState<number[]>([]);

  useEffect(() => setSelectedReportIds([]), [currentProjectId]);

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

  const removeMutation = useMutation({
    mutationFn: (id: number) => reportsApi.remove(id),
    onSuccess: () => {
      message.success('测试报告已移入回收站');
      queryClient.invalidateQueries({ queryKey: ['test-reports'] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '删除报告失败')),
  });
  const { isPending: isRemovingReport, mutateAsync: removeReport } = removeMutation;
  const batchRemoveMutation = useMutation({
    mutationFn: (ids: number[]) => reportsApi.removeMany(currentProjectId!, ids),
    onSuccess: (receipt: BatchLifecycleReceipt) => {
      setSelectedReportIds([]);
      queryClient.invalidateQueries({ queryKey: ['test-reports'] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
      if (receipt.failed === 0) message.success(`已删除 ${receipt.succeeded} 份报告，记录已移入回收站`);
      else {
        message.warning(`已删除 ${receipt.succeeded} 份报告，${receipt.failed} 份未删除`);
        modal.info({
          title: '批量删除结果',
          width: 620,
          content: <Space direction="vertical" style={{ width: '100%' }}>
            {receipt.items.filter((item) => !item.succeeded).map((item) => (
              <Alert key={item.id} type="error" showIcon message={`报告 #${item.id}`} description={item.error ?? '删除失败'} />
            ))}
          </Space>,
        });
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '批量删除报告失败')),
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
        width: 190,
        fixed: 'right',
        render: (_, row) => (
          <Space size={4}>
            <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/console/test-reports/${row.id}`)}>查看详情</Button>
            <Button size="small" danger icon={<DeleteOutlined />} loading={isRemovingReport}
              onClick={() => modal.confirm({
                title: `删除报告「${row.title}」？`,
                content: '报告将移入项目回收站；测试运行和执行证据保留。',
                okText: '删除并移入回收站', cancelText: '取消', okButtonProps: { danger: true },
                onOk: () => removeReport(row.id),
              })} />
          </Space>
        ),
      },
    ],
    [navigate, token, modal, isRemovingReport, removeReport],
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

      <Space style={{ margin: '12px 0' }} wrap>
        <Checkbox
          checked={rows.length > 0 && rows.every((report) => selectedReportIds.includes(report.id))}
          indeterminate={rows.some((report) => selectedReportIds.includes(report.id)) && !rows.every((report) => selectedReportIds.includes(report.id))}
          onChange={(event) => setSelectedReportIds((current) => event.target.checked
            ? [...new Set([...current, ...rows.map((report) => report.id)])]
            : current.filter((id) => !rows.some((report) => report.id === id)))}
        >
          全选当前页（{rows.length}）
        </Checkbox>
        <Button danger disabled={selectedReportIds.length === 0 || batchRemoveMutation.isPending}
          loading={batchRemoveMutation.isPending}
          onClick={() => modal.confirm({
            title: `删除选中的 ${selectedReportIds.length} 份报告？`,
            content: '报告逐条移入项目回收站；测试运行和执行证据保留。',
            okText: '删除并移入回收站', cancelText: '取消', okButtonProps: { danger: true },
            onOk: () => batchRemoveMutation.mutateAsync(selectedReportIds),
          })}>
          批量删除（{selectedReportIds.length}）
        </Button>
      </Space>

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
          rowSelection={{
            selectedRowKeys: selectedReportIds,
            preserveSelectedRowKeys: true,
            onChange: (keys) => setSelectedReportIds(keys.map(Number)),
          }}
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
