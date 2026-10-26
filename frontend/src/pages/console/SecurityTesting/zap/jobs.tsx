// 安全扫描 · 子 Tab 3：扫描任务。
//
// 任务列表 + 发起扫描四步向导 + 取消任务。
// 有运行中任务时 10 秒轮询一次列表；全部结束后停止轮询，避免空转。
// 取消只置持久化取消位，由 Worker 在下一个检查点真正停止（不是立即中断）。
import { useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Popconfirm,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { securityApi } from '@/api/securityTesting';
import type { ScanJob } from '@/api/securityTesting';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState } from '@/components/PageState';
import {
  authModeLabel,
  isRunningJob,
  JOB_STATUS_OPTIONS,
  scanModeLabel,
} from './constants';
import { ScanJobDetailDrawer } from './jobDetail';
import { ScanJobStatusBadge } from './jobPanels';
import { ScanWizardModal } from './wizard';

const PAGE_SIZE = 10;

/** 扫描任务子 Tab。projectId 由父页传入（已确保非空）。 */
export function JobsSubTab({ projectId, initialJobId }: { projectId: number; initialJobId?: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [detailJob, setDetailJob] = useState<ScanJob | null>(null);
  const initialJobQuery = useQuery({
    queryKey: ['zap-job-from-task', projectId, initialJobId],
    queryFn: () => securityApi.getScanJob(projectId, initialJobId!),
    enabled: initialJobId != null,
  });
  useEffect(() => {
    if (initialJobQuery.data) setDetailJob(initialJobQuery.data);
  }, [initialJobQuery.data]);

  const listQuery = useQuery({
    queryKey: ['zap-jobs', projectId, { status: statusFilter, page }],
    queryFn: () =>
      securityApi.listScanJobs(projectId, {
        page,
        page_size: PAGE_SIZE,
        status: statusFilter,
      }),
    // 只有当前页里还有未结束的任务才轮询，避免列表空转。
    refetchInterval: (query) =>
      query.state.data?.items.some((j) => isRunningJob(j.status)) ? 10000 : false,
  });

  const items = listQuery.data?.items ?? [];
  const hasRunning = items.some((j) => isRunningJob(j.status));

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['zap-jobs', projectId] });
  };

  const cancelMutation = useMutation({
    mutationFn: (id: number) => securityApi.cancelScanJob(projectId, id),
    onSuccess: () => {
      message.success('已请求取消，Worker 将在下一个检查点停止');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '取消失败')),
  });

  const columns: TableColumnsType<ScanJob> = [
    {
      title: '任务',
      width: 90,
      render: (_, r) => (
        <Button type="link" style={{ padding: 0, height: 'auto' }} onClick={() => setDetailJob(r)}>
          <Typography.Text strong>#{r.id}</Typography.Text>
        </Button>
      ),
    },
    {
      title: '目标',
      dataIndex: 'target_name',
      render: (v: string | null, r) =>
        v ?? <Typography.Text type="secondary">#{r.target_id}</Typography.Text>,
    },
    {
      title: '策略',
      dataIndex: 'scan_profile_name',
      render: (v: string | null, r) =>
        v ?? <Typography.Text type="secondary">#{r.scan_profile_id}</Typography.Text>,
    },
    {
      title: '扫描模式',
      dataIndex: 'scan_mode',
      width: 130,
      render: (v: string) => <Tag color={v.includes('ACTIVE') || v === 'FULL_AUTHORIZED' ? 'volcano' : 'cyan'}>{scanModeLabel(v)}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      render: (v: string, r) => (
        <Space direction="vertical" size={0}>
          <ScanJobStatusBadge status={v} />
          {r.cancel_requested && <Tag color="orange">已请求取消</Tag>}
        </Space>
      ),
    },
    {
      title: '进度',
      width: 170,
      render: (_, r) =>
        r.progress >= 0 ? (
          <Progress
            percent={r.progress}
            size="small"
            status={r.status === 'FAILED' || r.status === 'TIMED_OUT' ? 'exception' : undefined}
          />
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.stage ?? '阶段未知'}
          </Typography.Text>
        ),
    },
    {
      title: '认证',
      dataIndex: 'authentication_mode',
      width: 110,
      render: (v: string | null) => authModeLabel(v ?? 'NONE'),
    },
    {
      title: '告警',
      width: 110,
      render: (_, r) =>
        r.total_alerts > 0 ? (
          <Tag color={r.high_count > 0 ? 'red' : r.medium_count > 0 ? 'orange' : 'default'}>
            {r.total_alerts}（高 {r.high_count}）
          </Tag>
        ) : (
          <Typography.Text type="secondary">{r.total_alerts}</Typography.Text>
        ),
    },
    {
      title: '地址 / 请求',
      width: 120,
      render: (_, r) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {r.urls_discovered} / {r.requests_made}
        </Typography.Text>
      ),
    },
    {
      title: '耗时',
      width: 100,
      render: (_, r) =>
        r.duration_ms != null ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.duration_ms < 60_000 ? `${r.duration_ms}ms` : `${Math.round(r.duration_ms / 60_000)}分${Math.round((r.duration_ms % 60_000) / 1000)}秒`}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary">-</Typography.Text>
        ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: string | null) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {v ?? '-'}
        </Typography.Text>
      ),
    },
    {
      title: '操作',
      width: 150,
      render: (_, r) => (
        <Space size="small">
          <Button size="small" onClick={() => setDetailJob(r)}>
            详情
          </Button>
          {isRunningJob(r.status) ? (
            <Popconfirm
              title="确认取消该扫描任务？"
              description="取消只置取消标记，Worker 会在下一个检查点真正停止。"
              onConfirm={() => cancelMutation.mutate(r.id)}
            >
              <Button size="small" danger loading={cancelMutation.isPending}>
                取消
              </Button>
            </Popconfirm>
          ) : (
            <Typography.Text type="secondary">-</Typography.Text>
          )}
        </Space>
      ),
    },
  ];

  if (listQuery.isLoading) return <LoadingState />;
  if (listQuery.isError) return <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />;

  const total = listQuery.data?.total ?? items.length;

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap>
          <Select
            allowClear
            placeholder="任务状态"
            style={{ width: 160 }}
            value={statusFilter}
            onChange={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
            options={JOB_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
          />
          <Button type="primary" danger onClick={() => setWizardOpen(true)}>
            发起扫描
          </Button>
        </Space>
      </Card>

      {hasRunning && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="有任务正在执行"
          description="列表每 10 秒自动刷新一次；取消只置取消标记，Worker 会在下一个检查点真正停止。"
        />
      )}

      <Table<ScanJob>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
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

      {wizardOpen && (
        <ScanWizardModal
          projectId={projectId}
          onCancel={() => setWizardOpen(false)}
          onSubmitted={invalidate}
        />
      )}

      {detailJob && (
        <ScanJobDetailDrawer
          projectId={projectId}
          job={detailJob}
          onClose={() => setDetailJob(null)}
        />
      )}
    </div>
  );
}
