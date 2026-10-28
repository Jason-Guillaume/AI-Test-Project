import { collectPages } from '@/api/pagination';
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
  Card,
  Col,
  Descriptions,
  Divider,
  Empty,
  Flex,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Statistic,
  Table,
  Tabs,
  Tag,
  theme,
  Typography,
} from 'antd';
import { DeleteOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import type { TableColumnsType } from 'antd';

import { getErrorMessage } from '@/api/client';
import { notificationChannelsApi } from '@/api/notificationChannels';
import { projectsApi } from '@/api/projects';
import { reportsApi } from '@/api/reports';
import { CaseExecutionDetail } from '@/components/exec/CaseExecutionDetail';
import { FilterToolbar } from '@/components/FilterToolbar';
import { MetricCard, type MetricTone } from '@/components/MetricCard';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { PageHeader } from '@/components/PageHeader';
import { StatusBadge } from '@/components/StatusBadge';
import { TaskSourceLinks } from '@/components/tasks/TaskSourceLinks';
import { fmtDuration, fmtPercent, fmtTime, fmtTimeSec } from '@/shared/format';
import { labelOf } from '@/shared/options';
import {
  CASE_EXECUTION_STATUS_COLOR,
  CASE_EXECUTION_STATUS_LABEL,
  REPORT_FAILURE_TYPE_COLOR,
  REPORT_RISK_COLOR,
  REPORT_STATUS_COLOR,
  TEST_RUN_STATUS_COLOR,
} from '@/shared/status';
import {
  CASE_EXECUTION_STATUS_OPTIONS,
  TEST_CASE_TYPE_OPTIONS,
  TEST_PRIORITY_OPTIONS,
  TEST_RUN_STATUS_OPTIONS,
} from '@/pages/console/TestManagement/constants';
import {
  NOTIFY_CONDITION_OPTIONS,
  NOTIFY_STATUS_COLOR,
  NOTIFY_STATUS_OPTIONS,
} from '@/shared/notify';
import {
  FAILURE_TYPE_OPTIONS,
  REPORT_RISK_OPTIONS,
  REPORT_STATUS_OPTIONS,
} from './constants';
import type { CaseExecutionSummary, ReportFailureType, SecuritySummary } from '@/types';

// 失败聚类条目：后端返回 Record<string, unknown>，这里做一次结构校验再渲染。
interface FailureClusterRow {
  failure_type: ReportFailureType | null;
  count: number;
  case_execution_ids: number[];
}

const KNOWN_FAILURE_TYPES = new Set(FAILURE_TYPE_OPTIONS.map((o) => o.value));

/** 收窄失败聚类数组，字段缺失时按空值兜底，不把原始 Record 直接摊进渲染。 */
function readFailureClusters(raw: Array<Record<string, unknown>> | undefined): FailureClusterRow[] {
  if (!raw) return [];
  const rows: FailureClusterRow[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue;
    const ft =
      typeof item.failure_type === 'string' && KNOWN_FAILURE_TYPES.has(item.failure_type as ReportFailureType)
        ? (item.failure_type as ReportFailureType)
        : null;
    rows.push({
      failure_type: ft,
      count: typeof item.count === 'number' ? item.count : 0,
      case_execution_ids: Array.isArray(item.case_execution_ids)
        ? item.case_execution_ids.filter((v): v is number => typeof v === 'number')
        : [],
    });
  }
  return rows;
}

/** 收窄安全摘要：字段口径由后端 features/reports/schemas.py 的 SecuritySummary 保证。 */
function readSecuritySummary(summary: Record<string, unknown> | null): SecuritySummary | null {
  const sec = summary?.security;
  return sec && typeof sec === 'object' ? (sec as SecuritySummary) : null;
}

/** AI 总结区块：只展示 LLM 结构化字段，不参与统计计算。 */
function AiSummaryPanel({ summary }: { summary: Record<string, unknown> | null }) {
  const { token } = theme.useToken();

  if (!summary) {
    return (
      <Alert
        type="info"
        showIcon
        message="暂无 AI 总结"
        description="AI 总结生成失败或已被跳过。报告统计与风险等级由代码计算，不受影响；可点击「重新生成 AI 总结」重试。"
      />
    );
  }

  const text = (k: string) => (summary[k] as string | undefined) ?? '';
  const list = (k: string) => ((summary[k] as string[] | undefined) ?? []).filter((v) => typeof v === 'string');

  const listBlock = (title: string, items: string[], tone: 'normal' | 'warn' | 'danger' = 'normal') => {
    if (items.length === 0) return null;
    const color = tone === 'danger' ? token.colorError : tone === 'warn' ? token.colorWarning : token.colorText;
    return (
      <div style={{ marginBottom: token.margin }}>
        <Typography.Text strong>{title}</Typography.Text>
        <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
          {items.map((t, i) => (
            <li key={i} style={{ color, lineHeight: 1.7 }}>
              {t}
            </li>
          ))}
        </ul>
      </div>
    );
  };

  return (
    <div>
      {text('overview') && (
        <Alert
          type="success"
          showIcon
          message="总体结论"
          description={<div style={{ lineHeight: 1.8 }}>{text('overview')}</div>}
          style={{ marginBottom: token.margin }}
        />
      )}
      {listBlock('主要发现', list('key_findings'))}
      {listBlock('疑似产品问题（需人工确认，不是已确认缺陷）', list('potential_issues'), 'warn')}
      {listBlock('测试数据问题', list('test_data_issues'))}
      {listBlock('环境问题', list('environment_issues'))}
      {listBlock('改进建议', list('recommendations'))}
      {text('risk_summary') && (
        <div style={{ marginBottom: token.margin }}>
          <Typography.Text strong>风险解释</Typography.Text>
          <div style={{ marginTop: 4, lineHeight: 1.8 }}>{text('risk_summary')}</div>
        </div>
      )}
    </div>
  );
}

/**
 * 安全摘要卡片。
 *
 * 文案统一「疑似问题」，不写「已发现漏洞」；top_findings 不含 evidence 正文。
 */
function SecuritySummaryCard({ summary }: { summary: SecuritySummary }) {
  const { token } = theme.useToken();
  const sec = summary;

  const severityLabel: Record<string, string> = {
    INFO: '提示',
    LOW: '低',
    MEDIUM: '中',
    HIGH: '高',
    CRITICAL: '严重',
  };
  const severityColor: Record<string, string> = {
    INFO: 'default',
    LOW: 'blue',
    MEDIUM: 'orange',
    HIGH: 'red',
    CRITICAL: 'volcano',
  };

  return (
    <Card size="small" title="安全摘要（疑似问题）" style={{ marginTop: token.margin }}>
      <Row gutter={12}>
        <Col span={4}>
          <Statistic title="安全用例" value={sec.cases} />
        </Col>
        <Col span={4}>
          <Statistic title="通过" value={sec.pass} valueStyle={{ color: token.colorSuccess }} />
        </Col>
        <Col span={4}>
          <Statistic title="疑似问题" value={sec.potential_issues} valueStyle={{ color: token.colorError }} />
        </Col>
        <Col span={4}>
          <Statistic title="不确定" value={sec.inconclusive} />
        </Col>
        <Col span={4}>
          <Statistic title="执行失败" value={sec.failed_execution} valueStyle={{ color: token.colorWarning }} />
        </Col>
        <Col span={4}>
          <Statistic title="跳过" value={sec.skipped} />
        </Col>
      </Row>
      <Divider style={{ margin: `${token.marginSM}px 0` }} />
      <Flex gap="small" wrap>
        {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] as const).map((lv) => (
          <Tag key={lv} color={severityColor[lv] ?? 'default'}>
            {severityLabel[lv] ?? lv}：{sec.findings?.[lv] ?? 0}
          </Tag>
        ))}
      </Flex>
      {sec.top_findings && sec.top_findings.length > 0 && (
        <>
          <Typography.Text strong style={{ display: 'block', marginTop: token.marginSM }}>
            疑似问题 Top（不含证据正文）
          </Typography.Text>
          <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
            {sec.top_findings.map((f) => (
              <li key={f.id} style={{ lineHeight: 1.7 }}>
                <Tag color={severityColor[f.severity] ?? 'default'}>{severityLabel[f.severity] ?? f.severity}</Tag>
                <Typography.Text>{f.title}</Typography.Text>
                <Typography.Text type="secondary" style={{ marginLeft: token.marginXXS, fontSize: token.fontSizeSM }}>
                  {f.mutation_type}
                </Typography.Text>
              </li>
            ))}
          </ul>
        </>
      )}
      <Alert
        type="info"
        showIcon
        style={{ marginTop: token.marginSM }}
        message="疑似问题需人工确认，不等于已发现漏洞；证据请到「安全测试 · 疑似问题」查看。"
      />
    </Card>
  );
}

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

  const clusterGrid = clusters.length === 0 ? (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有失败或错误的用例" />
  ) : (
    <Row gutter={[12, 12]} style={{ marginTop: token.marginXS }}>
      {clusters.map((c, i) => {
        const ft = c.failure_type ?? 'UNKNOWN';
        const focusable = c.case_execution_ids.length > 0;
        return (
          <Col key={i} xs={24} sm={12} md={8}>
            <Card
              size="small"
              hoverable={focusable}
              onClick={focusable ? () => focusCluster(c.case_execution_ids) : undefined}
              styles={{ body: { padding: token.paddingSM } }}
            >
              <Flex justify="space-between" align="center" gap="small">
                <StatusBadge value={ft} options={FAILURE_TYPE_OPTIONS} color={REPORT_FAILURE_TYPE_COLOR[ft]} />
                <Typography.Text strong>{c.count} 条</Typography.Text>
              </Flex>
              {focusable && (
                <Typography.Text
                  type="secondary"
                  style={{ fontSize: token.fontSizeSM, display: 'block', marginTop: token.marginXXS }}
                >
                  点击聚焦这 {c.case_execution_ids.length} 条用例执行
                </Typography.Text>
              )}
            </Card>
          </Col>
        );
      })}
    </Row>
  );

  return (
    <PageContainer>
      {/* A. 报告头部 */}
      <PageHeader
        back
        onBack={() => navigate('/console/test-reports')}
        title={report.title}
        titleExtra={
          <>
            <StatusBadge
              value={report.status}
              options={REPORT_STATUS_OPTIONS}
              color={REPORT_STATUS_COLOR[report.status]}
            />
            <Tag color={REPORT_RISK_COLOR[report.risk_level]}>
              风险：{labelOf(REPORT_RISK_OPTIONS, report.risk_level)}
            </Tag>
          </>
        }
        subtitle={`${report.report_no} · 生成于 ${fmtTime(report.created_at)}`}
        meta={[
          { label: '所属项目', value: projectName ?? `#${report.project_id}` },
          { label: '环境', value: envName ?? (envId != null ? `#${envId}` : '-') },
          { label: '关联执行', value: test_run ? `#${test_run.id}` : '关联执行记录已删除' },
          {
            label: '执行时间',
            value: test_run?.started_at
              ? `${fmtTimeSec(test_run.started_at)} → ${fmtTimeSec(test_run.finished_at)}`
              : '-',
          },
          { label: '执行耗时', value: fmtDuration(report.duration_ms) },
          { label: '用例数', value: report.total_cases },
        ]}
        extra={
          <>
            <Button
              icon={<ReloadOutlined />}
              loading={regenerateMutation.isPending}
              onClick={() =>
                modal.confirm({
                  title: '重新生成 AI 总结？',
                  content: '报告统计字段不可变，仅重新生成 AI 总结（风险等级仍由代码规则决定）。',
                  onOk: () => regenerateMutation.mutateAsync(),
                })
              }
            >
              重新生成 AI 总结
            </Button>
            <Button
              type="primary"
              icon={<SendOutlined />}
              disabled={!canNotify}
              onClick={openNotifyModal}
            >
              发送飞书通知
            </Button>
            <Popconfirm
              title="确认删除该报告？"
              description="仅删除报告记录，不会删除执行记录与用例执行结果。"
              onConfirm={() => deleteMutation.mutate()}
            >
              <Button danger icon={<DeleteOutlined />} loading={deleteMutation.isPending}>
                删除报告
              </Button>
            </Popconfirm>
          </>
        }
      />

      <Flex vertical gap={8} style={{ marginBottom: token.margin }}>
        <TaskSourceLinks resourceType="REPORT" resourceId={report.id} />
        <TaskSourceLinks resourceType="TEST_RUN" resourceId={test_run?.id} />
      </Flex>

      {/* C. 风险提示：只在真的有风险时出现 */}
      {riskAlerts.length > 0 && (
        <Flex vertical gap={token.marginXS} style={{ marginBottom: token.margin }}>
          {riskAlerts.map((a, i) => (
            <Alert key={i} type={a.type} showIcon message={a.message} description={a.description} />
          ))}
        </Flex>
      )}

      {/* B. 概览统计 */}
      <Card size="small" style={{ marginBottom: token.margin }}>
        <Flex gap={token.marginXS} wrap="wrap">
          <MetricCard
            style={{ flex: '1 1 150px', minWidth: 150 }}
            title="通过率"
            value={fmtPercent(report.pass_rate)}
            suffix="%"
            tone={passTone}
            hint={`${report.passed_cases}/${report.total_cases} 通过`}
          />
          <MetricCard style={{ flex: '1 1 120px', minWidth: 120 }} title="总用例" value={report.total_cases} />
          <MetricCard
            style={{ flex: '1 1 120px', minWidth: 120 }}
            title="通过"
            value={report.passed_cases}
            tone="success"
          />
          <MetricCard
            style={{ flex: '1 1 120px', minWidth: 120 }}
            title="失败"
            value={report.failed_cases}
            tone="error"
          />
          <MetricCard
            style={{ flex: '1 1 120px', minWidth: 120 }}
            title="错误"
            value={report.error_cases}
            tone="warning"
          />
          <MetricCard style={{ flex: '1 1 120px', minWidth: 120 }} title="跳过" value={report.skipped_cases} />
          <MetricCard
            style={{ flex: '1 1 140px', minWidth: 140 }}
            title="执行耗时"
            value={fmtDuration(report.duration_ms)}
          />
        </Flex>
        <Progress
          percent={report.pass_rate}
          strokeColor={passColor}
          style={{ marginTop: token.margin, marginBottom: 0 }}
        />
        <Typography.Text
          type="secondary"
          style={{ fontSize: token.fontSizeSM, display: 'block', marginTop: token.marginXXS }}
        >
          统计字段由系统代码计算且不可变，AI 只负责总结、风险解释与失败聚类。
        </Typography.Text>
      </Card>

      {/* C. 执行摘要 + 执行环境 */}
      <Row gutter={[token.margin, token.margin]} style={{ marginBottom: token.margin }}>
        <Col xs={24} lg={14}>
          <Card size="small" title="执行摘要">
            <Typography.Text strong>状态分布</Typography.Text>
            {statusCounts.size === 0 ? (
              <Typography.Text type="secondary" style={{ display: 'block', margin: `${token.marginXS}px 0` }}>
                无用例执行数据
              </Typography.Text>
            ) : (
              <Flex wrap gap="small" style={{ margin: `${token.marginXS}px 0 ${token.marginSM}px` }}>
                {[...statusCounts.entries()].map(([status, count]) => (
                  <Flex key={status} align="center" gap={4}>
                    <StatusBadge
                      value={status}
                      labels={{ ...CASE_EXECUTION_STATUS_LABEL }}
                      colors={{ ...CASE_EXECUTION_STATUS_COLOR }}
                    />
                    <Typography.Text strong>{count}</Typography.Text>
                  </Flex>
                ))}
              </Flex>
            )}
            <Divider style={{ margin: `${token.marginSM}px 0` }} />
            <Typography.Text strong>主要失败原因</Typography.Text>
            {clusterGrid}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title="执行环境">
            <Descriptions
              size="small"
              column={1}
              items={[
                { key: 'project', label: '所属项目', children: projectName ?? `#${report.project_id}` },
                { key: 'env', label: '环境', children: envName ?? (envId != null ? `#${envId}` : '-') },
                { key: 'run', label: '关联执行', children: test_run ? `#${test_run.id}` : '关联执行记录已删除' },
                {
                  key: 'runStatus',
                  label: '执行状态',
                  children: test_run ? (
                    <StatusBadge
                      value={test_run.status}
                      colors={TEST_RUN_STATUS_COLOR}
                      label={labelOf(TEST_RUN_STATUS_OPTIONS, test_run.status)}
                    />
                  ) : (
                    '-'
                  ),
                },
                { key: 'start', label: '执行开始', children: fmtTimeSec(test_run?.started_at) },
                { key: 'end', label: '执行结束', children: fmtTimeSec(test_run?.finished_at) },
                { key: 'duration', label: '执行耗时', children: fmtDuration(report.duration_ms) },
                { key: 'generated', label: '报告生成于', children: fmtTime(report.created_at) },
              ]}
            />
          </Card>
          {security && <SecuritySummaryCard summary={security} />}
        </Col>
      </Row>

      {/* D. 结果工作台 */}
      <Card size="small" style={{ marginBottom: token.margin }}>
        <Tabs
          activeKey={workspaceTab}
          onChange={setWorkspaceTab}
          items={[
            {
              key: 'cases',
              label: `用例结果（${visibleCases.length}/${caseExecutions.length}）`,
              children: (
                <Flex vertical gap={token.marginSM}>
                  <FilterToolbar
                    search={caseKeyword}
                    searchPlaceholder="搜索用例名称或错误码"
                    selects={[
                      { key: 'status', label: '状态', options: CASE_EXECUTION_STATUS_OPTIONS, allowClear: true },
                      { key: 'priority', label: '优先级', options: TEST_PRIORITY_OPTIONS, allowClear: true },
                    ]}
                    values={{ status: caseStatus, priority: casePriority }}
                    onSearch={setCaseKeyword}
                    onFilterChange={(key, value) => {
                      if (key === 'status') setCaseStatus(value);
                      else if (key === 'priority') setCasePriority(value);
                    }}
                    onReset={resetCaseFilters}
                  />
                  {clusterFocus && (
                    <Alert
                      type="info"
                      showIcon
                      message={`已聚焦失败聚类：${clusterFocus.length} 条用例执行`}
                      action={
                        <Button size="small" type="link" onClick={resetCaseFilters}>
                          取消聚焦
                        </Button>
                      }
                    />
                  )}
                  <Table
                    rowKey="id"
                    size="small"
                    columns={caseColumns}
                    dataSource={visibleCases}
                    loading={detailQuery.isFetching}
                    scroll={{ x: 1100 }}
                    pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true }}
                    onRow={(row) => ({ onClick: () => setSelectedRow(row), style: { cursor: 'pointer' } })}
                    locale={{ emptyText: <Empty description="没有匹配当前筛选条件的用例执行" /> }}
                  />
                </Flex>
              ),
            },
            {
              key: 'failures',
              label: `失败分析${failedRows.length > 0 ? `（${failedRows.length}）` : ''}`,
              children: (
                <Flex vertical gap={token.marginSM}>
                  {clusterGrid}
                  <Divider style={{ margin: 0 }} />
                  {failedRows.length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无失败用例" />
                  ) : (
                    <Table
                      rowKey="id"
                      size="small"
                      columns={failedColumns}
                      dataSource={failedRows}
                      scroll={{ x: 1300 }}
                      pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
                      onRow={(row) => ({ onClick: () => setSelectedRow(row), style: { cursor: 'pointer' } })}
                    />
                  )}
                </Flex>
              ),
            },
            {
              key: 'ai',
              label: `AI 总结${report.ai_summary_version ? `（${report.ai_summary_version}）` : ''}`,
              children: <AiSummaryPanel summary={report.ai_summary} />,
            },
            {
              key: 'notify',
              label: `通知记录${records.length > 0 ? `（${recordsQuery.data?.total ?? records.length}）` : ''}`,
              children: (
                <Flex vertical gap={token.marginSM}>
                  <Flex justify="space-between" align="center" wrap="wrap" gap="small">
                    <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
                      发送审计记录。Webhook 地址与签名密钥不会显示、也不会写入报告或通知记录。
                    </Typography.Text>
                    <Button
                      type="primary"
                      icon={<SendOutlined />}
                      disabled={!canNotify}
                      onClick={openNotifyModal}
                    >
                      发送飞书通知
                    </Button>
                  </Flex>
                  {/* 三态分开：接口失败要报错误并给重试，不能显示「去配置渠道」的提示 */}
                  {channelsQuery.isError ? (
                    <ErrorState error={channelsQuery.error} onRetry={channelsQuery.refetch} />
                  ) : !channelsQuery.isPending && channels.length === 0 ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="没有可用的通知渠道"
                      description="请在「项目配置 · 通知渠道」配置启用且连通测试通过的渠道后重试。"
                    />
                  ) : null}
                  {recordsQuery.isError ? (
                    <ErrorState error={recordsQuery.error} onRetry={recordsQuery.refetch} />
                  ) : records.length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未发送过飞书通知" />
                  ) : (
                    <Table
                      rowKey="id"
                      size="small"
                      columns={[
                        { title: '记录ID', dataIndex: 'id', width: 90 },
                        { title: '渠道ID', dataIndex: 'channel_id', width: 100 },
                        {
                          title: '状态',
                          dataIndex: 'status',
                          width: 120,
                          render: (v: string) => (
                            <StatusBadge
                              value={v}
                              options={NOTIFY_STATUS_OPTIONS}
                              colors={{ ...NOTIFY_STATUS_COLOR }}
                            />
                          ),
                        },
                        { title: '错误信息', dataIndex: 'error_message', render: (v: string | null) => v ?? '-' },
                        { title: '发送时间', dataIndex: 'sent_at', width: 170, render: (v: string | null) => fmtTime(v) },
                        { title: '记录时间', dataIndex: 'created_at', width: 170, render: (v: string | null) => fmtTime(v) },
                      ]}
                      dataSource={records}
                      loading={recordsQuery.isFetching}
                      pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
                    />
                  )}
                </Flex>
              ),
            },
          ]}
        />
      </Card>

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
