import { collectPages } from '@/shared/api/pagination';
// 测试报告详情页：概览统计 + 执行摘要 + 结果工作台 + 证据抽屉。
//
// 信息架构对应重构计划 §3：
//   A 报告头部   —— PageHeader：名称 / 编号 / 项目 / 环境 / 执行时间 / 状态 / 主操作
//   B 概览统计   —— 紧凑 MetricCard 组 + 通过率进度条
//   C 执行摘要   —— 状态分布 / 主要失败原因（可钻取到用例）/ 风险提示 / 安全摘要
//   D 结果工作台 —— 用例结果（搜索 + 状态 + 优先级筛选）/ 失败分析 / AI 总结 / 通知记录
//   E 证据       —— CaseExecutionDetail 宽屏抽屉（步骤时间线 + 断言 + 截图 + Trace + 请求响应）
//
// 接口（只读为主，不新增语义）：
//   GET    /reports/{report_id}                         报告详情
//   POST   /reports/{report_id}/regenerate-ai-summary   重生成 AI 总结（统计字段不可变）
//   POST   /reports/{report_id}/notify                  手动触发飞书通知
//   GET    /reports/{report_id}/notifications            发送审计记录
//   DELETE /reports/{report_id}                         删除报告（不删 TestRun / CaseExecution）
//
// 安全边界：报告与通知记录不含 webhook URL / secret；POTENTIAL_BUG 与安全疑似问题
// 均只表示「需人工确认」，文案不写「已确认缺陷」；快照已脱敏，前端不做二次增强。
// 颜色一律走 theme token，禁止裸 hex。

import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Flex,
  Modal,
  Select,
  Tag,
  theme,
  Typography,
} from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import type { TableColumnsType } from 'antd';

import { getErrorMessage } from '@/shared/api/client';
import { notificationChannelsApi } from '@/features/notifications/api/notificationChannels';
import { projectsApi } from '@/features/projects/api/projects';
import { reportsApi } from '@/features/reports/api/reports';
import { CaseExecutionDetail } from '@/widgets/execution-detail/CaseExecutionDetail';
import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { fmtDuration, fmtPercent, fmtTimeSec } from '@/shared/lib/format';
import { labelOf } from '@/shared/lib/options';
import { CASE_EXECUTION_STATUS_COLOR, CASE_EXECUTION_STATUS_LABEL } from '@/features/test-management/status';
import { REPORT_FAILURE_TYPE_COLOR } from '@/features/reports/status';
import { TEST_CASE_TYPE_OPTIONS } from '@/pages/console/TestManagement/constants';
import { NOTIFY_CONDITION_OPTIONS } from '@/features/notifications/constants';
import { FAILURE_TYPE_OPTIONS } from './constants';
import { readFailureClusters, readSecuritySummary } from './ReportSummaryPanels';
import { ReportWorkspace } from './ReportWorkspace';
import { ReportOverview } from './ReportOverview';
import { ReportFailureClusterGrid } from './ReportFailureClusterGrid';
import type { MetricTone } from '@/shared/ui/MetricCard';
import type { CaseExecutionSummary, ReportFailureType } from '@/features/reports/contracts';


/**
 * 测试报告详情页。
 */
export function ConsoleReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const id = reportId ? Number(reportId) : null;
  const navigate = useNavigate();
  const { message: msg, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { token } = theme.useToken();

  // 结果工作台的状态：抽屉选中行、失败聚类钻取、用例筛选、当前 Tab
  const [selectedRow, setSelectedRow] = useState<CaseExecutionSummary | null>(null);
  const [clusterFocus, setClusterFocus] = useState<number[] | null>(null);
  const [caseKeyword, setCaseKeyword] = useState('');
  const [caseStatus, setCaseStatus] = useState<string | undefined>(undefined);
  const [casePriority, setCasePriority] = useState<string | undefined>(undefined);
  const [workspaceTab, setWorkspaceTab] = useState('cases');
  const [notifyOpen, setNotifyOpen] = useState(false);
  const [notifyChannelId, setNotifyChannelId] = useState<number | undefined>(undefined);

  const detailQuery = useQuery({
    queryKey: ['test-report-detail', id],
    queryFn: () => reportsApi.get(id!),
    enabled: id != null,
  });

  // 项目名与环境名：复用列表页/项目详情页的既有缓存键，不新增接口形态
  const reportProjectId = detailQuery.data?.report.project_id ?? null;
  const projectQuery = useQuery({
    queryKey: ['project', reportProjectId, 'detail'],
    queryFn: () => projectsApi.get(reportProjectId!),
    enabled: reportProjectId != null,
    staleTime: 60_000,
  });
  const envsQuery = useQuery({
    queryKey: ['project-environments', reportProjectId],
    queryFn: () => projectsApi.listEnvironments(reportProjectId!),
    enabled: reportProjectId != null,
    staleTime: 60_000,
  });

  // 通知渠道按项目作用域取，避免跨项目串用（与渠道管理页同键）
  const channelsQuery = useQuery({
    queryKey: ['notification-channels', reportProjectId],
    queryFn: () => collectPages((page) => notificationChannelsApi.list(reportProjectId!, { page, page_size: 100 })),
    enabled: reportProjectId != null,
    staleTime: 60_000,
  });
  // 显式传分页：后端默认 page_size=20，不传会在 Tab 标题显示 total 而表格只出 20 条
  const recordsQuery = useQuery({
    queryKey: ['report-notifications', id],
    queryFn: () => collectPages((page) => notificationChannelsApi.listReportNotifications(id!, { page, page_size: 100 })),
    enabled: id != null,
  });

  const channels = (channelsQuery.data?.items ?? []).filter((c) => c.enabled && c.webhook_configured);
  const records = recordsQuery.data?.items ?? [];

  // 渠道查询失败时 channels 同样为空，但不能当成「没配置渠道」：
  // 那样会把 403/404/500 伪装成配置缺失——按钮永久禁用，还提示用户「去通知中心配置渠道」。
  const canNotify = !channelsQuery.isPending && !channelsQuery.isError && channels.length > 0;

  const openNotifyModal = () => {
    if (channelsQuery.isError) return;
    if (channels.length === 0) {
      msg.warning('请先在「项目配置 · 通知渠道」配置启用且连通测试通过的渠道');
      return;
    }
    if (channels.length === 1) setNotifyChannelId(channels[0].id);
    setNotifyOpen(true);
  };

  const regenerateMutation = useMutation({
    mutationFn: () => reportsApi.regenerateAiSummary(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['test-report-detail', id] });
      msg.success('AI 总结已重新生成');
    },
    onError: (e) => msg.error(getErrorMessage(e, 'AI 总结重生成失败')),
  });

  const notifyMutation = useMutation({
    mutationFn: () => notificationChannelsApi.notifyReport(id!, { channel_id: notifyChannelId! }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['report-notifications', id] });
      setNotifyOpen(false);
      setNotifyChannelId(undefined);
      if (data.skipped) {
        msg.warning('已跳过：通知条件不满足或渠道禁用');
      } else if (data.status === 'SUCCESS') {
        msg.success('飞书通知发送成功');
      } else {
        msg.error(`飞书通知发送失败：${data.error_message ?? '未知错误'}`);
      }
    },
    onError: (e) => msg.error(getErrorMessage(e, '通知发送失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: () => reportsApi.remove(id!),
    onSuccess: () => {
      // 列表页与详情页都要刷新，否则已删报告在缓存过期前仍可见
      queryClient.invalidateQueries({ queryKey: ['test-reports'] });
      queryClient.invalidateQueries({ queryKey: ['test-report-detail', id] });
      msg.success('报告已删除（执行记录与用例执行结果保留）');
      navigate('/console/test-reports');
    },
    onError: (e) => msg.error(getErrorMessage(e, '删除报告失败')),
  });

  // 切换报告时清空所有工作台本地状态，避免上一份报告的筛选条件泄漏
  useEffect(() => {
    setSelectedRow(null);
    setClusterFocus(null);
    setCaseKeyword('');
    setCaseStatus(undefined);
    setCasePriority(undefined);
    setWorkspaceTab('cases');
  }, [id]);

  // ⚠️ 下面三个 useMemo 必须位于所有提前 return 之前：React Router 在同一 route pattern
  // （/console/test-reports/:reportId）下复用组件实例，直接跳到另一份报告会让 detailQuery
  // 重新进入 loading，此时若 hook 数量比上一次渲染少，React 18 直接抛
  // "Rendered fewer hooks than expected."，整页白屏。
  const detail = detailQuery.data;
  const caseExecutions = useMemo(() => detail?.case_executions ?? [], [detail?.case_executions]);

  const failedRows = useMemo(
    () => caseExecutions.filter((c) => c.status === 'FAILED' || c.status === 'ERROR'),
    [caseExecutions],
  );

  // 状态分布：按执行状态聚合计数
  const statusCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of caseExecutions) m.set(c.status, (m.get(c.status) ?? 0) + 1);
    return m;
  }, [caseExecutions]);

  // 用例筛选：聚类钻取 + 状态 + 优先级 + 关键词，全部在前端过滤（数据已随详情一次取回）
  const visibleCases = useMemo(() => {
    const kw = caseKeyword.trim().toLowerCase();
    return caseExecutions.filter((c) => {
      if (clusterFocus && !clusterFocus.includes(c.id)) return false;
      if (caseStatus && c.status !== caseStatus) return false;
      if (casePriority && c.priority !== casePriority) return false;
      if (kw && !`${c.case_name} ${c.error_code ?? ''}`.toLowerCase().includes(kw)) return false;
      return true;
    });
  }, [caseExecutions, clusterFocus, caseKeyword, caseStatus, casePriority]);

  if (id == null) {
    return (
      <PageContainer>
        <Alert type="error" showIcon message="无效的报告编号" />
      </PageContainer>
    );
  }
  if (detailQuery.isLoading) return <LoadingState />;
  if (detailQuery.isError) {
    return (
      <PageContainer>
        <ErrorState error={detailQuery.error} onRetry={detailQuery.refetch} />
      </PageContainer>
    );
  }
  if (!detail) return null;

  const { report, test_run, failure_clusters } = detail;

  const clusters = readFailureClusters(failure_clusters);
  const security = readSecuritySummary(report.summary);

  const resetCaseFilters = () => {
    setClusterFocus(null);
    setCaseKeyword('');
    setCaseStatus(undefined);
    setCasePriority(undefined);
  };

  const focusCluster = (ids: number[]) => {
    setClusterFocus(ids);
    setCaseStatus(undefined);
    setCasePriority(undefined);
    setCaseKeyword('');
    setWorkspaceTab('cases');
  };

  // 通过率口径：< 90% 提示，< 60% 视为不可接受
  const passTone: MetricTone = report.pass_rate >= 90 ? 'success' : report.pass_rate >= 60 ? 'warning' : 'error';
  const passColor =
    passTone === 'success' ? token.colorSuccess : passTone === 'warning' ? token.colorWarning : token.colorError;

  const envId = report.environment_id ?? test_run?.environment_id ?? null;
  const envName =
    (envsQuery.data?.items ?? []).find((e) => e.id != null && e.id === envId)?.display_name ?? null;
  const projectName = projectQuery.data?.name ?? null;

  // 风险提示：只在该真的有事时出现，避免用占位文字填充版面
  const riskAlerts: { type: 'error' | 'warning'; message: string; description: string }[] = [];
  if (report.status === 'FAILED') {
    riskAlerts.push({
      type: 'error',
      message: '报告生成失败',
      description: 'AI 总结不可用；统计字段与失败聚类仍由代码计算，可尝试「重新生成 AI 总结」。',
    });
  }
  if (test_run?.status === 'FAILED') {
    riskAlerts.push({
      type: 'error',
      message: `关联执行 #${test_run.id} 状态为失败`,
      description: '执行过程中出现中断或异常，建议从失败分析进入首个失败用例定位。',
    });
  }
  if (report.total_cases > 0 && report.pass_rate < 90) {
    riskAlerts.push({
      type: 'warning',
      message: `通过率 ${fmtPercent(report.pass_rate)}% 低于 90%`,
      description: `失败 ${report.failed_cases} 条、错误 ${report.error_cases} 条、跳过 ${report.skipped_cases} 条。`,
    });
  }
  if (security && security.potential_issues > 0) {
    riskAlerts.push({
      type: 'warning',
      message: `安全用例存在 ${security.potential_issues} 条疑似问题`,
      description: '疑似问题需人工确认，不等于已确认缺陷；证据请到「安全测试 · 疑似问题」查看。',
    });
  }

  const caseColumns: TableColumnsType<CaseExecutionSummary> = [
    {
      title: '用例',
      dataIndex: 'case_name',
      ellipsis: true,
      render: (v: string) => <Typography.Text strong>{v}</Typography.Text>,
    },
    { title: '优先级', dataIndex: 'priority', width: 90, render: (v: string) => <Tag color="blue">{v}</Tag> },
    {
      title: '类型',
      dataIndex: 'case_type',
      width: 110,
      render: (v: string | null) => (v ? (TEST_CASE_TYPE_OPTIONS.find((o) => o.value === v)?.label ?? v) : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v: string) => (
        <StatusBadge
          value={v}
          labels={{ ...CASE_EXECUTION_STATUS_LABEL }}
          colors={{ ...CASE_EXECUTION_STATUS_COLOR }}
        />
      ),
    },
    {
      title: '失败分类',
      dataIndex: 'failure_type',
      width: 210,
      render: (v: ReportFailureType | null) =>
        v ? <StatusBadge value={v} options={FAILURE_TYPE_OPTIONS} color={REPORT_FAILURE_TYPE_COLOR[v]} /> : '-',
    },
    { title: '开始时间', dataIndex: 'started_at', width: 160, render: (v: string | null) => fmtTimeSec(v) },
    { title: '耗时', dataIndex: 'duration_ms', width: 90, align: 'right', render: (v: number | null) => fmtDuration(v) },
    {
      title: '错误码',
      dataIndex: 'error_code',
      width: 130,
      render: (v: string | null) => (v ? <Typography.Text code>{v}</Typography.Text> : '-'),
    },
    {
      title: '操作',
      width: 76,
      render: (_, row) => (
        <Button
          size="small"
          type="link"
          onClick={(e) => {
            e.stopPropagation();
            setSelectedRow(row);
          }}
        >
          详情
        </Button>
      ),
    },
  ];

  // 失败分析表：同一套列 + 内联错误信息，不用再点进抽屉才能看到原因
  const failedColumns: TableColumnsType<CaseExecutionSummary> = [
    ...caseColumns.slice(0, -1),
    {
      title: '错误信息',
      dataIndex: 'error_message',
      render: (v: string | null) =>
        v ? <Typography.Text type="danger" style={{ whiteSpace: 'pre-wrap' }}>{v}</Typography.Text> : '-',
    },
    caseColumns[caseColumns.length - 1],
  ];

  const clusterGrid = <ReportFailureClusterGrid clusters={clusters} onFocusCluster={focusCluster} />;

  return (
    <PageContainer>
      <ReportOverview
        report={report}
        testRun={test_run}
        projectName={projectName}
        envName={envName}
        envId={envId}
        riskAlerts={riskAlerts}
        passTone={passTone}
        passColor={passColor}
        statusCounts={statusCounts}
        clusterGrid={clusterGrid}
        security={security}
        onBack={() => navigate('/console/test-reports')}
        regenerateLoading={regenerateMutation.isPending}
        onRegenerate={() => modal.confirm({
          title: '重新生成 AI 总结？',
          content: '报告统计字段不可变，仅重新生成 AI 总结（风险等级仍由代码规则决定）。',
          onOk: () => regenerateMutation.mutateAsync(),
        })}
        canNotify={canNotify}
        onNotify={openNotifyModal}
        deleteLoading={deleteMutation.isPending}
        onDelete={() => deleteMutation.mutate()}
      />

      <ReportWorkspace
        report={report}
        workspaceTab={workspaceTab}
        onWorkspaceTabChange={setWorkspaceTab}
        visibleCases={visibleCases}
        caseExecutions={caseExecutions}
        failedRows={failedRows}
        caseColumns={caseColumns}
        failedColumns={failedColumns}
        clusterGrid={clusterGrid}
        clusterFocus={clusterFocus}
        caseKeyword={caseKeyword}
        caseStatus={caseStatus}
        casePriority={casePriority}
        onCaseKeywordChange={setCaseKeyword}
        onCaseFilterChange={(key, value) => {
          if (key === 'status') setCaseStatus(value);
          else if (key === 'priority') setCasePriority(value);
        }}
        onResetCaseFilters={resetCaseFilters}
        onSelectCase={setSelectedRow}
        isFetching={detailQuery.isFetching}
        records={records}
        recordsQuery={recordsQuery}
        channelsQuery={channelsQuery}
        channels={channels}
        canNotify={canNotify}
        onNotify={openNotifyModal}
      />

      {/* E. 证据：宽屏抽屉，替代原来的多 Tab Modal */}
      <CaseExecutionDetail open={selectedRow !== null} execution={selectedRow} onClose={() => setSelectedRow(null)} />

      <Modal
        title="发送飞书通知"
        open={notifyOpen}
        onCancel={() => setNotifyOpen(false)}
        confirmLoading={notifyMutation.isPending}
        onOk={() => {
          if (notifyChannelId == null) {
            msg.warning('请选择一个通知渠道');
            return;
          }
          notifyMutation.mutate();
        }}
      >
        <Flex vertical gap="middle">
          <Typography.Text>
            即将把报告 <b>{report.report_no}</b> 的风险等级、通过率与 AI 总结发送到飞书群。
            发送失败不影响报告与执行记录状态。
          </Typography.Text>
          <Select
            placeholder="选择通知渠道"
            style={{ width: '100%' }}
            value={notifyChannelId}
            onChange={setNotifyChannelId}
            options={channels.map((c) => ({
              label: `${c.name}（${labelOf(NOTIFY_CONDITION_OPTIONS, c.notify_condition)}） ${c.webhook_masked}`,
              value: c.id,
            }))}
          />
          <Alert
            type="info"
            showIcon
            message="提示"
            description="Webhook 地址与签名密钥不会显示、也不会写入报告或通知记录。"
          />
        </Flex>
      </Modal>
    </PageContainer>
  );
}
