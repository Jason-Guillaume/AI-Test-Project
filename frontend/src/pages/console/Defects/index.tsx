// 缺陷工作台（测试团队视角，无处理人）。
// 路由 /console/defects 挂载 ConsoleDefectsPage。
//
// 功能：
//   - 队列工作台：顶部当前项目「未关闭」，快捷队列计数与列表 total 同口径；
//   - 过滤：前后端划分 / 严重度 / 优先级 / 关键字（项目由顶栏统一选择，处理人筛选已停用）；
//   - 新建 / 编辑：禅道式弹窗（DefectFormModal），批量创建（BatchCreateBugsModal）；
//   - 批量治理：调优先级 / 归档 / 撤销归档 / 删除 / 飞书推送，逐项回执；
//   - 详情：DefectDetailModal 聚合证据、验证、外部反馈与活动时间线；
//   - 质量统计与项目设置（灰度开关、提醒、模板）。
//
// 权限（服务端为准）：读 = viewer+；写 = member+；归档/设置/模板 = editor+。
import { collectPages } from '@/shared/api/pagination';
import {
  App, Alert, Button, Checkbox, Input, Modal, Select, Space, Statistic, Tabs, Tag, Typography,
} from 'antd';
import { ExclamationCircleOutlined, SettingOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '@/app/providers/AuthProvider';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { bugsApi } from '@/features/defects/api/defects';
import { DefectShareModal } from '@/features/defects/components/DefectShareModal';
import type {
  Bug, BugBatchActionRequest, BugBatchActionReceipt, BugCategory, BugCategoryFilter,
  BugListQuery, BugPriority, BugSeverity, BugStatus,
} from '@/features/defects/contracts';
import { projectsApi } from '@/features/projects/api/projects';
import { EmptyState, ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { ResourceTable, type PaginationState } from '@/shared/ui/ResourceTable';
import { sequenceColumn } from '@/shared/lib/sequence';
import { getErrorMessage } from '@/shared/api/client';
import type { BatchLifecycleReceipt } from '@/features/data-lifecycle/api';
import type { Paginated } from '@/shared/api/contracts';
import { BatchCreateBugsModal } from './BatchCreateBugsModal';
import { DefectDetailModal } from './DefectDetailModal';
import { DefectFormModal } from './DefectFormModal';
import { DefectSettingsDrawer } from './DefectSettingsDrawer';
import {
  CATEGORY_COLOR, PRIORITY_COLOR, PRIORITY_LABELS, PRIORITY_OPTIONS,
  SEVERITY_COLOR, SEVERITY_OPTIONS, STATUS_COLOR, STATUS_DISPLAY, STATUS_OPTIONS,
} from './constants';

type ShareTarget = Pick<Bug, 'id' | 'project_id'>;
type QueueKey = 'unclosed' | 'pending_confirm' | 'in_progress' | 'pending_verify'
  | 'reported_by_me' | 'closed' | 'rejected' | 'archived' | 'drafts' | 'all';

const QUEUE_LABELS: Record<QueueKey, string> = {
  unclosed: '未关闭', pending_confirm: '待确认', in_progress: '处理中', pending_verify: '待验证',
  reported_by_me: '我提交的', closed: '已关闭', rejected: '已拒绝', archived: '已归档', drafts: '我的草稿', all: '全部',
};
const QUEUE_QUERY: Record<QueueKey, Partial<BugListQuery>> = {
  unclosed: { status_group: 'unclosed' },
  pending_confirm: { status: '待确认' },
  in_progress: { status: '处理中' },
  pending_verify: { status: '已修复' },
  reported_by_me: { mine: true },
  closed: { status: '已关闭' },
  rejected: { status: '已拒绝' },
  archived: { view: 'archived' },
  drafts: { view: 'drafts' },
  all: {},
};
const QUEUE_COUNT_KEY: Partial<Record<QueueKey, keyof import('@/features/defects/contracts').BugQueueCounts>> = {
  unclosed: 'unclosed', pending_confirm: 'pending_confirm', in_progress: 'in_progress',
  pending_verify: 'pending_verify', reported_by_me: 'reported_by_me', closed: 'closed',
  rejected: 'rejected', archived: 'archived', drafts: 'drafts',
};

/**
 * 缺陷工作台页面。
 * 会发请求：['bugs', query] 列表、['projects'] 项目下拉、['defect-queues'] 队列计数、
 * ['defect-stats'] 质量统计、['defect-project-setting'] 灰度开关（均按项目惰性启用）。
 * mutation：删除 / 批量删除 / 批量治理，成功后统一失效列表与队列统计。
 * 失败呈现：列表失败整页 ErrorState；mutation 失败 message.error，部分失败弹逐项回执。
 */
export function ConsoleDefectsPage() {
  const { message, modal } = App.useApp();
  const { isPlatformAdmin } = useAuth();
  const { currentProjectId } = useConsoleScope();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedBugId = Number(searchParams.get('bugId'));
  const detailOpen = Number.isSafeInteger(requestedBugId) && requestedBugId > 0;

  const [pagination, setPagination] = useState<PaginationState>({ page: 1, page_size: 10 });
  const projectId = currentProjectId ?? undefined;
  const [queue, setQueue] = useState<QueueKey>('unclosed');
  const [categoryFilter, setCategoryFilter] = useState<BugCategoryFilter | undefined>(undefined);
  const [status, setStatus] = useState<BugStatus | undefined>(undefined);
  const [severity, setSeverity] = useState<BugSeverity | undefined>(undefined);
  const [priority, setPriority] = useState<BugPriority | undefined>(undefined);
  const [keyword, setKeyword] = useState('');
  const [selectedBugIds, setSelectedBugIds] = useState<number[]>([]);
  const [selectAllLoading, setSelectAllLoading] = useState(false);
  const [shareBugs, setShareBugs] = useState<ShareTarget[] | null>(null);
  const [formModal, setFormModal] = useState<{ mode: 'create' } | { mode: 'edit'; bugId: number } | null>(null);
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [batchPriority, setBatchPriority] = useState<BugPriority | undefined>(undefined);
  const [batchArchiveOpen, setBatchArchiveOpen] = useState(false);
  const [batchArchiveReason, setBatchArchiveReason] = useState('');

  const projectsQuery = useQuery({
    queryKey: ['projects', { page: 1, page_size: 100 }],
    queryFn: () => collectPages((page) => projectsApi.list({ page, page_size: 100 })),
  });
  const projectOptions = (projectsQuery.data?.items ?? []).map((p) => ({ label: p.name, value: p.id }));

  const settingQuery = useQuery({
    queryKey: ['defect-project-setting', projectId],
    queryFn: () => bugsApi.projectSetting(projectId!),
    enabled: projectId != null,
  });
  const queueMode = projectId != null && (settingQuery.data?.queue_enabled ?? true);
  const queuesQuery = useQuery({
    queryKey: ['defect-queues', projectId],
    queryFn: () => bugsApi.queues(projectId!),
    enabled: queueMode,
  });
  const statsQuery = useQuery({
    queryKey: ['defect-stats', projectId],
    queryFn: () => bugsApi.stats(projectId!),
    enabled: queueMode,
  });

  const query = useMemo<BugListQuery>(() => ({
    page: pagination.page,
    page_size: pagination.page_size,
    project_id: projectId,
    category: categoryFilter,
    severity,
    priority,
    keyword: keyword || undefined,
    ...(queueMode
      ? { ...QUEUE_QUERY[queue], sort: 'updated' as const, ...(queue === 'all' ? { status } : {}) }
      : { status }),
  }), [pagination, projectId, categoryFilter, severity, priority, keyword, queueMode, queue, status]);

  const listQuery = useQuery<Paginated<Bug>>({
    queryKey: ['bugs', query],
    queryFn: () => bugsApi.list(query),
    enabled: projectId != null,
  });

  const projectRole = (id: number) => (projectsQuery.data?.items ?? []).find((item) => item.id === id)?.my_role;
  const canManage = (id: number) => isPlatformAdmin || ['member', 'editor', 'owner'].includes(projectRole(id) || '');
  const canPermanent = (id: number) => isPlatformAdmin || ['editor', 'owner'].includes(projectRole(id) || '');

  const refreshLists = () => {
    queryClient.invalidateQueries({ queryKey: ['bugs'] });
    queryClient.invalidateQueries({ queryKey: ['defect-queues'] });
    queryClient.invalidateQueries({ queryKey: ['defect-stats'] });
  };

  async function selectAllFilteredResults() {
    setSelectAllLoading(true);
    try {
      const result = await collectPages((page) => bugsApi.list({ ...query, page, page_size: 200 }));
      setSelectedBugIds(result.items.map((bug) => bug.id));
      message.success(`已选中当前筛选结果 ${result.items.length} 条`);
    } catch (error) {
      message.error(getErrorMessage(error, '加载全部筛选结果失败'));
    } finally {
      setSelectAllLoading(false);
    }
  }

  const removeMutation = useMutation({
    mutationFn: (id: number) => bugsApi.remove(id),
    onSuccess: () => {
      message.success('缺陷已删除');
      refreshLists();
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const showReceipt = (title: string, succeeded: number, failed: number, items: Array<{ id: number; succeeded: boolean; error?: string | null }>, okText: string) => {
    if (failed === 0) { message.success(`${okText} ${succeeded} 个缺陷`); return; }
    message.warning(`${okText} ${succeeded} 个缺陷，${failed} 个未处理`);
    modal.info({
      title,
      width: 620,
      content: <Space direction="vertical" style={{ width: '100%' }}>
        {items.filter((item) => !item.succeeded).map((item) => (
          <Alert key={item.id} type="error" showIcon message={`缺陷 #${item.id}`} description={item.error ?? '处理失败'} />
        ))}
      </Space>,
    });
  };

  const batchRemoveMutation = useMutation({
    mutationFn: (ids: number[]) => bugsApi.removeMany(projectId!, ids),
    onSuccess: (receipt: BatchLifecycleReceipt) => {
      setSelectedBugIds([]);
      refreshLists();
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
      showReceipt('批量删除结果', receipt.succeeded, receipt.failed, receipt.items, '已删除');
    },
    onError: (error) => message.error(getErrorMessage(error, '批量删除失败')),
  });

  const batchActionMutation = useMutation({
    mutationFn: (body: BugBatchActionRequest) => bugsApi.batchAction(body),
    onSuccess: (receipt: BugBatchActionReceipt, body) => {
      setSelectedBugIds([]);
      setBatchArchiveOpen(false);
      setBatchArchiveReason('');
      refreshLists();
      queryClient.invalidateQueries({ queryKey: ['bug-detail'] });
      const label = body.action === 'set_priority' ? '已调整优先级' : body.action === 'archive' ? '已归档' : '已撤销归档';
      showReceipt('批量处理结果', receipt.succeeded, receipt.failed, receipt.items, label);
    },
    onError: (error) => message.error(getErrorMessage(error, '批量处理失败')),
  });

  const confirmDelete = (bug: Bug) => {
    modal.confirm({
      title: '确认删除该缺陷？',
      icon: <ExclamationCircleOutlined />,
      content: `「${bug.title}」将移入项目回收站，可由授权成员恢复。`,
      okText: '删除并移入回收站',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => removeMutation.mutateAsync(bug.id),
    });
  };

  if (currentProjectId == null) {
    return <PageContainer><EmptyState description="请先在顶部选择一个项目" /></PageContainer>;
  }

  if (listQuery.isPending) return <LoadingState />;
  if (listQuery.isError) {
    return <PageContainer><ErrorState error={listQuery.error} onRetry={listQuery.refetch} /></PageContainer>;
  }
  const data = listQuery.data;
  const counts = queuesQuery.data;
  const stats = statsQuery.data;
  const resetPage = () => setPagination((p) => ({ ...p, page: 1 }));
  const batchDisabled = projectId == null || selectedBugIds.length === 0 || !canManage(projectId);

  return (
    <PageContainer>
      {queueMode && (
        <Tabs
          activeKey={queue}
          onChange={(key) => { setQueue(key as QueueKey); setSelectedBugIds([]); setStatus(undefined); resetPage(); }}
          items={(Object.keys(QUEUE_LABELS) as QueueKey[]).map((key) => {
            const countKey = QUEUE_COUNT_KEY[key];
            const count = countKey && counts ? counts[countKey] : undefined;
            return { key, label: count != null ? `${QUEUE_LABELS[key]}（${count}）` : QUEUE_LABELS[key] };
          })}
        />
      )}

      {queueMode && stats && (
        <Space wrap size="large" style={{ marginBottom: 12 }}>
          <Statistic title="未关闭积压" value={Object.entries(stats.backlog).filter(([s]) => !['已关闭', '已拒绝'].includes(s)).reduce((sum, [, n]) => sum + n, 0)} />
          <Statistic title="平均首次确认耗时（小时）" value={stats.first_confirm_hours_avg ?? '-'} precision={1} suffix={<Typography.Text type="secondary">样本 {stats.first_confirm_sample}</Typography.Text>} />
          <Statistic title="平均待验证时长（小时）" value={stats.pending_verify_hours_avg ?? '-'} precision={1} suffix={<Typography.Text type="secondary">样本 {stats.pending_verify_sample}</Typography.Text>} />
          <Statistic
            title="回归失败率"
            value={stats.regression_failure_rate != null ? stats.regression_failure_rate * 100 : '-'}
            precision={1}
            suffix={stats.regression_failure_rate != null ? `%（${stats.regression_failed}/${stats.regression_total}）` : `样本 ${stats.regression_total}`}
          />
          <Typography.Text type="secondary">统计窗口 {stats.period_days} 天</Typography.Text>
        </Space>
      )}

      <div className="console-toolbar">
        <Input.Search
          placeholder="按标题搜索"
          allowClear
          enterButton
          style={{ maxWidth: 240 }}
          onSearch={(v) => { setKeyword(v); resetPage(); }}
        />
        <Select
          placeholder="全部划分"
          allowClear
          options={[{ label: '前端', value: '前端' }, { label: '前后端', value: '前后端' }, { label: '接口', value: '接口' }, { label: '未划分', value: '未划分' }]}
          value={categoryFilter}
          onChange={(v) => { setCategoryFilter(v); setSelectedBugIds([]); resetPage(); }}
          style={{ minWidth: 120 }}
        />
        {(!queueMode || queue === 'all') && (
          <Select
            placeholder="全部状态"
            allowClear
            options={STATUS_OPTIONS}
            value={status}
            onChange={(v) => { setStatus(v); resetPage(); }}
            style={{ minWidth: 120 }}
          />
        )}
        <Select placeholder="全部严重度" allowClear options={SEVERITY_OPTIONS} value={severity} onChange={(v) => { setSeverity(v); resetPage(); }} style={{ minWidth: 120 }} />
        <Select placeholder="全部优先级" allowClear options={PRIORITY_OPTIONS} value={priority} onChange={(v) => { setPriority(v); resetPage(); }} style={{ minWidth: 120 }} />
        <Button type="primary" onClick={() => setFormModal({ mode: 'create' })}>新建缺陷</Button>
        <Button onClick={() => setBatchModalOpen(true)} disabled={projectOptions.length === 0}>批量创建</Button>
        {projectId != null && (
          <Button icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>缺陷设置</Button>
        )}
      </div>

      <div className="console-toolbar">
        <Checkbox
          checked={data.items.length > 0 && data.items.every((bug) => selectedBugIds.includes(bug.id))}
          indeterminate={data.items.some((bug) => selectedBugIds.includes(bug.id)) && !data.items.every((bug) => selectedBugIds.includes(bug.id))}
          disabled={projectId == null}
          onChange={(event) => {
            const pageIds = new Set(data.items.map((bug) => bug.id));
            setSelectedBugIds((current) => event.target.checked
              ? [...new Set([...current, ...pageIds])]
              : current.filter((id) => !pageIds.has(id)));
          }}
        >
          全选当前页（{data.items.length}）
        </Checkbox>
        <Button loading={selectAllLoading} disabled={projectId == null || data.total === 0 || !canManage(projectId)} onClick={selectAllFilteredResults}>
          全选全部筛选结果（{data.total}）
        </Button>
        {selectedBugIds.length > 0 && <Button onClick={() => setSelectedBugIds([])}>清空选择（{selectedBugIds.length}）</Button>}
        <Select
          placeholder="批量优先级"
          allowClear
          options={PRIORITY_OPTIONS}
          value={batchPriority}
          onChange={setBatchPriority}
          style={{ minWidth: 120 }}
          disabled={batchDisabled}
        />
        <Button
          disabled={batchDisabled || batchPriority == null || batchActionMutation.isPending}
          onClick={() => modal.confirm({
            title: `将选中的 ${selectedBugIds.length} 个缺陷优先级调整为「${PRIORITY_LABELS[batchPriority!]}」？`,
            content: '逐个校验并返回处理结果；不影响缺陷状态。',
            onOk: () => batchActionMutation.mutateAsync({ project_id: projectId!, ids: selectedBugIds, action: 'set_priority', priority: batchPriority }),
          })}
        >调整优先级</Button>
        <Button
          disabled={batchDisabled || !canPermanent(projectId!) || batchActionMutation.isPending}
          onClick={() => setBatchArchiveOpen(true)}
        >批量归档</Button>
        {queueMode && queue === 'archived' && (
          <Button
            disabled={batchDisabled || !canPermanent(projectId!) || batchActionMutation.isPending}
            onClick={() => modal.confirm({
              title: `撤销选中 ${selectedBugIds.length} 个缺陷的归档？`,
              content: '缺陷恢复列表可见；已撤销的分享不会自动恢复。',
              onOk: () => batchActionMutation.mutateAsync({ project_id: projectId!, ids: selectedBugIds, action: 'restore' }),
            })}
          >撤销归档</Button>
        )}
        <Button danger disabled={batchDisabled || batchRemoveMutation.isPending}
          loading={batchRemoveMutation.isPending}
          onClick={() => modal.confirm({
            title: `删除选中的 ${selectedBugIds.length} 个缺陷？`,
            content: '删除会保留来源追溯关系并移入项目回收站；每个缺陷独立校验并返回处理结果。',
            okText: '删除并移入回收站', cancelText: '取消', okButtonProps: { danger: true },
            onOk: () => batchRemoveMutation.mutateAsync(selectedBugIds),
          })}>
          批量删除（{selectedBugIds.length}）
        </Button>
        <Button
          disabled={batchDisabled}
          onClick={() => setShareBugs([...new Set(selectedBugIds)].map((id) => ({ id, project_id: projectId! })))}
        >
          批量推送到飞书（{selectedBugIds.length}）
        </Button>
      </div>

      <ResourceTable
        rowKey={(r) => r.id}
        scroll={{ x: 1360 }}
        columns={[
          sequenceColumn<Bug>({ page: pagination.page, pageSize: pagination.page_size }),
          { title: '项目', dataIndex: 'project_name', render: (v: string | null) => v ?? '-' },
          {
            title: '前后端', dataIndex: 'category', width: 96,
            render: (v: BugCategory | null) => v ? <Tag color={CATEGORY_COLOR[v]}>{v}</Tag> : <Tag>未划分</Tag>,
          },
          { title: '标题', dataIndex: 'title' },
          { title: '严重度', dataIndex: 'severity', width: 80, render: (v: BugSeverity) => <Tag color={SEVERITY_COLOR[v]}>{v}</Tag> },
          { title: '优先级', dataIndex: 'priority', width: 90, render: (v: BugPriority) => <Tag color={PRIORITY_COLOR[v]}>{PRIORITY_LABELS[v]}</Tag> },
          {
            title: '状态', dataIndex: 'status', width: 100,
            render: (v: BugStatus, row: Bug) => (
              <Space size={4}>
                <Tag color={STATUS_COLOR[v]}>{row.status_display ?? STATUS_DISPLAY[v]}</Tag>
                {row.is_draft && <Tag>草稿</Tag>}
                {row.archived_at && <Tag>归档</Tag>}
              </Space>
            ),
          },
          {
            title: '推送', dataIndex: 'active_share_count', width: 90,
            render: (value: number | undefined) => (value && value > 0 ? <Tag color="green">已推送</Tag> : <Tag>未推送</Tag>),
          },
          { title: '报告人', dataIndex: 'reporter_username', width: 110, render: (v: string | null) => v ?? '-' },
          { title: '更新时间', dataIndex: 'updated_at', width: 170, render: (v: string) => new Date(v).toLocaleString() },
          {
            title: '操作', key: 'actions', width: 210,
            render: (_: unknown, row: Bug) => (
              <Space size={4} wrap={false}>
                <Button size="small" onClick={() => setSearchParams({ bugId: String(row.id) })}>详情</Button>
                {canManage(row.project_id) && <Button size="small" onClick={() => setShareBugs([row])}>推送到飞书</Button>}
                {canManage(row.project_id) && <Button size="small" onClick={() => setFormModal({ mode: 'edit', bugId: row.id })}>编辑</Button>}
                {canManage(row.project_id) && (
                  <Button size="small" danger disabled={removeMutation.isPending} onClick={() => confirmDelete(row)}>删除</Button>
                )}
              </Space>
            ),
          },
        ]}
        dataSource={data.items}
        loading={listQuery.isFetching}
        total={data.total}
        pagination={pagination}
        onPaginationChange={setPagination}
        rowSelection={{
          selectedRowKeys: selectedBugIds,
          preserveSelectedRowKeys: true,
          onChange: (keys) => setSelectedBugIds(keys.map(Number)),
          getCheckboxProps: (row) => ({ disabled: projectId == null || row.project_id !== projectId }),
        }}
      />

      {detailOpen && (
        <DefectDetailModal
          bugId={requestedBugId}
          canManage={canManage}
          canArchive={canPermanent}
          onClose={() => setSearchParams({})}
          onEdit={(bug) => setFormModal({ mode: 'edit', bugId: bug.id })}
          onShare={(bug) => setShareBugs([bug])}
        />
      )}

      {formModal && (
        <DefectFormModal
          mode={formModal.mode}
          bugId={formModal.mode === 'edit' ? formModal.bugId : undefined}
          initialProjectId={projectId ?? projectOptions[0]?.value}
          initialCategory={categoryFilter && categoryFilter !== '未划分' ? categoryFilter as BugCategory : undefined}
          projectOptions={projectOptions}
          onClose={() => setFormModal(null)}
          onSaved={(_bug, continueCreating) => {
            if (!continueCreating) setFormModal(null);
            resetPage();
            refreshLists();
          }}
        />
      )}

      {shareBugs && shareBugs.length > 0 && (
        <DefectShareModal bugs={shareBugs} canPermanent={canPermanent(shareBugs[0].project_id)} onClose={() => { setShareBugs(null); queryClient.invalidateQueries({ queryKey: ['bugs'] }); queryClient.invalidateQueries({ queryKey: ['bug-shares'] }); }} />
      )}

      {batchModalOpen && (
        <BatchCreateBugsModal
          initialProjectId={projectId ?? projectOptions[0]?.value}
          initialCategory={categoryFilter && categoryFilter !== '未划分' ? categoryFilter as BugCategory : undefined}
          projectOptions={projectOptions}
          onClose={() => setBatchModalOpen(false)}
          onCreated={() => { setBatchModalOpen(false); resetPage(); refreshLists(); }}
        />
      )}

      {settingsOpen && projectId != null && (
        <DefectSettingsDrawer
          projectId={projectId}
          projectName={projectOptions.find((p) => p.value === projectId)?.label}
          canEdit={canPermanent(projectId)}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      <Modal
        open={batchArchiveOpen}
        title={`归档选中的 ${selectedBugIds.length} 个缺陷`}
        onCancel={() => setBatchArchiveOpen(false)}
        onOk={() => {
          if (!batchArchiveReason.trim()) { message.warning('请填写归档原因'); return; }
          batchActionMutation.mutate({ project_id: projectId!, ids: selectedBugIds, action: 'archive', reason: batchArchiveReason.trim() });
        }}
        confirmLoading={batchActionMutation.isPending}
        okText="确认归档"
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert type="warning" showIcon message="归档会撤销每个缺陷的全部有效分享，并从默认列表隐藏；逐个校验并返回处理结果。" />
          <Input.TextArea rows={3} maxLength={500} placeholder="归档原因（必填）" value={batchArchiveReason} onChange={(event) => setBatchArchiveReason(event.target.value)} />
        </Space>
      </Modal>
    </PageContainer>
  );
}