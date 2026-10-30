// 安全扫描 · 任务详情抽屉。
//
// 展示：任务基本信息、当前阶段与进度、事件时间线、告警、覆盖率、关联疑似问题、报告。
// 进度通过 GET /scan-jobs/{id}/progress 轮询，任务结束后停止轮询。
// progress = -1 时后端不给精确百分比，只展示阶段与计数，不能编一个 0% 出来。
import type { ReactNode } from 'react';
import { Drawer, Progress, Space, Spin, Tabs, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { zapApi } from '@/features/security-testing/zap/api';
import type { ScanJob } from '@/features/security-testing/zap/contracts';
import { ErrorState } from '@/shared/ui/PageState';
import { TaskSourceLinks } from '@/features/tasks/components/TaskSourceLinks';
import { authModeLabel, authResultColor, authResultLabel, BROWSER_AUTH_MODES, isRunningJob, jobStatusLabel, scanModeLabel } from './constants';
import { JobAlertsPanel } from './panels/JobAlertsPanel';
import { JobCoveragePanel } from './panels/JobCoveragePanel';
import { JobEventsPanel } from './panels/JobEventsPanel';
import { JobFindingsPanel } from './panels/JobFindingsPanel';
import { JobReportPanel } from './panels/JobReportPanel';
import { ScanJobStatusBadge } from './panels/ScanJobStatusBadge';

/** 任务详情抽屉。job 由调用方传入（已加载好的任务对象）。 */
export function ScanJobDetailDrawer({
  projectId,
  job,
  onClose,
}: {
  projectId: number;
  job: ScanJob;
  onClose: () => void;
}) {
  // 运行中才轮询进度；结束后一次即可（仍拉一次拿到最终计数）。
  const progressQuery = useQuery({
    queryKey: ['zap-progress', projectId, job.id],
    queryFn: () => zapApi.getScanProgress(projectId, job.id),
    refetchInterval: (query) => isRunningJob(query.state.data?.status ?? job.status) ? 5000 : false,
  });
  const running = isRunningJob(progressQuery.data?.status ?? job.status);

  const progress = progressQuery.data ?? {
    progress: job.progress,
    stage: job.stage,
    status: job.status,
    urls_discovered: job.urls_discovered,
    requests_made: job.requests_made,
    total_alerts: job.total_alerts,
    high_count: job.high_count,
    medium_count: job.medium_count,
    low_count: job.low_count,
    info_count: job.info_count,
    cancel_requested: job.cancel_requested,
    duration_ms: job.duration_ms,
  };

  const browserMode =
    job.authentication_mode != null && BROWSER_AUTH_MODES.has(job.authentication_mode);

  return (
    <Drawer
      title={
        <Space>
          <Typography.Text strong>扫描任务 #{job.id}</Typography.Text>
          <ScanJobStatusBadge status={progress.status} />
          {progress.cancel_requested && <Tag color="orange">已请求取消</Tag>}
        </Space>
      }
      open
      onClose={onClose}
      width={920}
      destroyOnClose
    >
      <div style={{ marginBottom: 16 }}>
        {progressQuery.isLoading ? (
          <div style={{ padding: 24, textAlign: 'center' }}>
            <Spin />
          </div>
        ) : progressQuery.isError ? (
          <ErrorState error={progressQuery.error} onRetry={progressQuery.refetch} />
        ) : (
          <div>
            <Progress
              percent={progress.progress >= 0 ? progress.progress : 0}
              showInfo={progress.progress >= 0}
              status={
                progress.status === 'FAILED' || progress.status === 'TIMED_OUT'
                  ? 'exception'
                  : isRunningJob(progress.status)
                    ? 'active'
                    : undefined
              }
              format={() =>
                progress.progress >= 0 ? undefined : '进度无法精确计算，以下方阶段与计数为准'
              }
            />
            <Space size="large" wrap style={{ marginTop: 4 }}>
              <Typography.Text>
                阶段：<Typography.Text strong>{progress.stage ?? '-'}</Typography.Text>
              </Typography.Text>
              <Typography.Text type="secondary">
                已发现 {progress.urls_discovered} 个地址 · 已发 {progress.requests_made} 次请求
              </Typography.Text>
              <Typography.Text type="secondary">
                告警 {progress.total_alerts}（高 {progress.high_count} · 中 {progress.medium_count} · 低{' '}
                {progress.low_count} · 提示 {progress.info_count}）
              </Typography.Text>
              {progress.duration_ms != null && (
                <Typography.Text type="secondary">耗时 {progress.duration_ms} 毫秒</Typography.Text>
              )}
            </Space>
          </div>
        )}
      </div>

      <Tabs
        size="small"
        defaultActiveKey="events"
        items={[
          {
            key: 'events',
            label: '事件时间线',
            children: <JobEventsPanel projectId={projectId} jobId={job.id} running={running} />,
          },
          {
            key: 'alerts',
            label: '告警',
            children: <JobAlertsPanel projectId={projectId} jobId={job.id} running={running} />,
          },
          {
            key: 'coverage',
            label: '覆盖率',
            children: <JobCoveragePanel projectId={projectId} jobId={job.id} running={running} />,
          },
          {
            key: 'findings',
            label: '关联疑似问题',
            children: <JobFindingsPanel projectId={projectId} jobId={job.id} running={running} />,
          },
          {
            key: 'report',
            label: '报告',
            children: <JobReportPanel projectId={projectId} jobId={job.id} running={running} />,
          },
        ]}
      />

      <div style={{ marginTop: 16 }}>
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          任务基本信息
        </Typography.Title>
        <BasicInfo job={job} browserMode={browserMode} />
        <div style={{ marginTop: 12 }}>
          <TaskSourceLinks resourceType="SECURITY_SCAN_JOB" resourceId={job.id} />
        </div>
      </div>
    </Drawer>
  );
}

/** 任务基本信息块。 */
function BasicInfo({
  job,
  browserMode,
}: {
  job: ScanJob;
  browserMode: boolean;
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '8px 24px',
        fontSize: 13,
      }}
    >
      <InfoRow label="目标" value={`${job.target_name ?? '-'}（#${job.target_id}）`} />
      <InfoRow
        label="扫描策略"
        value={`${job.scan_profile_name ?? '-'}（#${job.scan_profile_id}）`}
      />
      <InfoRow label="扫描模式" value={scanModeLabel(job.scan_mode)} />
      <InfoRow
        label="认证模式"
        value={
          <Space>
            <span>{authModeLabel(job.authentication_mode ?? 'NONE')}</span>
            {browserMode && !job.browser_session_established && (
              <Tag color="orange">浏览器会话未建立</Tag>
            )}
            {job.authentication_status && (
              <Tag color={authResultColor(job.authentication_status)}>
                {authResultLabel(job.authentication_status)}
              </Tag>
            )}
          </Space>
        }
      />
      <InfoRow label="环境" value={job.environment_name ?? `#${job.environment_id ?? '未指定'}`} />
      <InfoRow label="ZAP 扫描引用" value={job.zap_scan_reference ?? '-'} />
      <InfoRow label="关联测试执行" value={job.test_run_id != null ? `TestRun #${job.test_run_id}` : '-'} />
      <InfoRow label="执行 Worker" value={job.worker_owner ?? '-'} />
      <InfoRow label="发起人" value={job.initiated_by != null ? `用户 #${job.initiated_by}` : '-'} />
      <InfoRow
        label="批准人"
        value={job.approved_by != null ? `用户 #${job.approved_by}` : '未记录批准（被动扫描）'}
      />
      <InfoRow label="开始时间" value={job.started_at ?? '-'} />
      <InfoRow label="结束时间" value={job.finished_at ?? '-'} />
      <InfoRow label="耗时" value={job.duration_ms != null ? `${job.duration_ms} 毫秒` : '-'} />
      <InfoRow label="心跳时间" value={job.heartbeat_at ?? '-'} />
      <InfoRow
        label="告警统计"
        value={`共 ${job.total_alerts}（高 ${job.high_count} · 中 ${job.medium_count} · 低 ${job.low_count} · 提示 ${job.info_count}）`}
      />
      <InfoRow
        label="Finding 统计"
        value={`新增 ${job.new_findings_count} · 重复 ${job.duplicate_findings_count}`}
      />
      {job.error_code && <InfoRow label="错误码" value={job.error_code} />}
      {job.error_message && <InfoRow label="错误说明" value={job.error_message} />}
      <InfoRow label="最终状态" value={jobStatusLabel(job.status)} />
    </div>
  );
}

/** 一行「标签 + 值」。 */
function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <Typography.Text type="secondary">{label}</Typography.Text>
      <div style={{ marginTop: 2, wordBreak: 'break-all' }}>{value}</div>
    </div>
  );
}
