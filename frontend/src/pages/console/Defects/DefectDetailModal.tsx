// 缺陷详情弹窗：聚合事实字段、接口证据、附件、关联来源、修复验证、外部反馈与分享历史、活动时间线。
// 状态只能通过队列动作变更；归档/撤销归档需 editor+，归档会撤销全部有效分享。
import { ExclamationCircleOutlined, InboxOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, App, Button, Input, Modal, Select, Space, Tag, Timeline, Typography, Upload,
} from 'antd';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { bugsApi } from '@/features/defects/api/defects';
import { DefectShareHistory } from '@/features/defects/components/DefectShareHistory';
import type { Bug, BugAction } from '@/features/defects/contracts';
import { projectsApi } from '@/features/projects/api/projects';
import { tasksApi } from '@/features/tasks/api/tasks';
import { clearTaskCreateUncertainty, readTaskCreateUncertainty, rememberTaskCreateUncertainty, type TaskCreateUncertainty } from '@/features/tasks/createUncertainty';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { DefectOrigins } from '@/widgets/execution-detail/DefectOrigins';
import { isAxiosError } from 'axios';
import { DefectActionModal } from './DefectActionModal';
import { ACTION_LABELS, CATEGORY_COLOR, PRIORITY_COLOR, PRIORITY_LABELS, SEVERITY_COLOR, STATUS_COLOR } from './constants';

const ACTIONS_BY_STATUS: Record<string, BugAction[]> = {
  待确认: ['confirm', 'reject', 'mark_duplicate'],
  处理中: ['ready_for_regression'],
  已修复: ['regression_pass', 'regression_fail'],
  已关闭: ['reopen'],
  已拒绝: ['reopen'],
};

/**
 * 缺陷详情弹窗：按 bugId 拉详情与活动时间线，按当前状态给出队列动作入口。
 * 会发请求：['bug-detail'] / ['bug-activities'] / 草稿提交 / 归档 / 撤销归档；
 * 成功后统一失效列表、详情、队列与分享缓存。失败用 message.error 呈现。
 */
export function DefectDetailModal({
  bugId, canManage, canArchive, onClose, onEdit, onShare,
}: {
  bugId: number;
  canManage: (projectId: number) => boolean;
  canArchive: (projectId: number) => boolean;
  onClose: () => void;
  onEdit: (bug: Bug) => void;
  onShare: (bug: Bug) => void;
}) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ['bug-detail', bugId], queryFn: () => bugsApi.get(bugId) });
  const activities = useQuery({
    queryKey: ['bug-activities', bugId],
    queryFn: () => bugsApi.activities(bugId),
  });
  const [action, setAction] = useState<BugAction | null>(null);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiveReason, setArchiveReason] = useState('');

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['bugs'] });
    queryClient.invalidateQueries({ queryKey: ['bug-detail', bugId] });
    queryClient.invalidateQueries({ queryKey: ['bug-activities', bugId] });
    queryClient.invalidateQueries({ queryKey: ['defect-queues'] });
    queryClient.invalidateQueries({ queryKey: ['bug-shares'] });
  };

  const submitDraft = useMutation({
    mutationFn: () => bugsApi.submitDraft(bugId),
    onSuccess: () => { message.success('草稿已提交，进入待确认队列'); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '提交失败')),
  });
  const archive = useMutation({
    mutationFn: () => bugsApi.archive(bugId, archiveReason),
    onSuccess: () => {
      message.success('缺陷已归档，全部有效分享已撤销');
      setArchiveOpen(false);
      setArchiveReason('');
      refresh();
    },
    onError: (error) => message.error(getErrorMessage(error, '归档失败')),
  });
  const restore = useMutation({
    mutationFn: () => bugsApi.restore(bugId),
    onSuccess: () => { message.success('已撤销归档'); refresh(); },
    onError: (error) => message.error(getErrorMessage(error, '撤销归档失败')),
  });

  const bug = detail.data;
  const writable = bug ? canManage(bug.project_id) : false;
  const archivable = bug ? canArchive(bug.project_id) : false;

  return (
    <Modal
      open
      width={820}
      title={bug ? `缺陷 #${bug.id}：${bug.title}` : '缺陷详情'}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
    >
      {detail.isPending ? <LoadingState /> : detail.isError || !bug ? <ErrorState error={detail.error} onRetry={detail.refetch} /> : (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space wrap>
            {bug.category ? <Tag color={CATEGORY_COLOR[bug.category]}>{bug.category}</Tag> : <Tag>未划分</Tag>}
            <Tag color={SEVERITY_COLOR[bug.severity]}>严重度 {bug.severity}</Tag>
            <Tag color={PRIORITY_COLOR[bug.priority]}>优先级 {PRIORITY_LABELS[bug.priority]}</Tag>
            <Tag color={STATUS_COLOR[bug.status]}>{bug.status_display}</Tag>
            {bug.environment && <Tag>{bug.environment}</Tag>}
            {bug.affected_version && <Tag>影响版本 {bug.affected_version}</Tag>}
            {bug.fix_version && <Tag color="cyan">可回归 {bug.fix_version}</Tag>}
            {bug.is_draft && <Tag color="default">草稿</Tag>}
            {bug.archived_at && <Tag color="default">已归档</Tag>}
            {bug.duplicate_of_bug_id && <Tag color="red">重复于 #{bug.duplicate_of_bug_id}</Tag>}
          </Space>
          {bug.archived_at && bug.archive_reason && (
            <Alert type="info" showIcon message={`归档原因：${bug.archive_reason}`} />
          )}
          {writable && !bug.archived_at && (
            <Space wrap>
              {bug.is_draft ? (
                <Button type="primary" loading={submitDraft.isPending} onClick={() => submitDraft.mutate()}>提交草稿</Button>
              ) : (ACTIONS_BY_STATUS[bug.status] ?? []).map((item) => (
                <Button
                  key={item}
                  type={item === 'confirm' || item === 'regression_pass' ? 'primary' : 'default'}
                  danger={item === 'regression_fail' || item === 'reject'}
                  onClick={() => setAction(item)}
                >
                  {ACTION_LABELS[item]}
                </Button>
              ))}
              <Button onClick={() => onEdit(bug)}>编辑</Button>
              <Button onClick={() => onShare(bug)}>推送到飞书</Button>
              {archivable && <Button onClick={() => setArchiveOpen(true)}>归档</Button>}
            </Space>
          )}
          {writable && bug.archived_at && archivable && (
            <Button loading={restore.isPending} onClick={() => modal.confirm({
              title: '撤销归档？',
              icon: <ExclamationCircleOutlined />,
              content: '缺陷将恢复列表可见并可继续队列操作；已撤销的分享不会自动恢复。',
              onOk: () => restore.mutateAsync(),
            })}>撤销归档</Button>
          )}
          <Typography.Text>{bug.description || '暂无描述'}</Typography.Text>
          <Typography.Text strong>复现步骤</Typography.Text>
          <pre className="bug-api-pre">{bug.steps_to_reproduce || '未填写'}</pre>
          <Typography.Text strong>实际结果</Typography.Text>
          <pre className="bug-api-pre">{bug.actual_result || '未填写'}</pre>
          <Typography.Text strong>预期结果</Typography.Text>
          <pre className="bug-api-pre">{bug.expected_result || '未填写'}</pre>
          {(bug.api_url || bug.api_method || bug.api_request_headers || bug.api_request_body || bug.api_response) && (
            <>
              <Typography.Text strong>接口信息</Typography.Text>
              <Typography.Paragraph style={{ marginBottom: 0 }}>
                {bug.api_method && <Tag color="geekblue">{bug.api_method}</Tag>}
                <Typography.Text code>{bug.api_url || '未填写请求地址'}</Typography.Text>
              </Typography.Paragraph>
              {bug.api_request_headers && (<><Typography.Text type="secondary">请求头</Typography.Text><pre className="bug-api-pre">{bug.api_request_headers}</pre></>)}
              {bug.api_request_body && (<><Typography.Text type="secondary">请求体</Typography.Text><pre className="bug-api-pre">{bug.api_request_body}</pre></>)}
              {bug.api_response && (<><Typography.Text type="secondary">实际响应</Typography.Text><pre className="bug-api-pre">{bug.api_response}</pre></>)}
            </>
          )}
          <BugAttachments bugId={bug.id} />
          <Typography.Text strong>关联来源</Typography.Text>
          <DefectOrigins bugId={bug.id} />
          <BugVerificationPanel bug={bug} />
          <DefectShareHistory bug={bug} canManage={writable} />
          <Typography.Text strong>活动时间线</Typography.Text>
          {activities.isError ? <Typography.Text type="danger">活动读取失败</Typography.Text> : (
            <Timeline
              items={(activities.data ?? []).map((item) => ({
                key: item.id,
                color: item.actor_type === 'EXTERNAL_SHARE' ? 'orange' : item.action === 'regression_fail' ? 'red' : 'blue',
                children: (
                  <Space direction="vertical" size={0}>
                    <Typography.Text>
                      {item.action_label || item.action}
                      {item.old_status && item.new_status && (
                        <Typography.Text type="secondary">（{item.old_status} → {item.new_status === '已修复' ? '待验证' : item.new_status}）</Typography.Text>
                      )}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      {item.actor_type === 'EXTERNAL_SHARE' ? '外部反馈' : item.actor_name ?? '系统'} · {new Date(item.created_at).toLocaleString()}
                    </Typography.Text>
                    {item.note && <Typography.Text>{item.note}</Typography.Text>}
                  </Space>
                ),
              }))}
            />
          )}
        </Space>
      )}
      {action && bug && (
        <DefectActionModal bug={bug} action={action} onClose={() => setAction(null)} onDone={() => setAction(null)} />
      )}
      <Modal
        open={archiveOpen}
        title="归档缺陷"
        onCancel={() => setArchiveOpen(false)}
        onOk={() => {
          if (!archiveReason.trim()) { message.warning('请填写归档原因'); return; }
          archive.mutate();
        }}
        confirmLoading={archive.isPending}
        okText="确认归档"
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert type="warning" showIcon message="归档会撤销该缺陷全部有效分享（含批次入口与附件公开访问），缺陷默认从列表隐藏。" />
          <Input.TextArea
            rows={3}
            maxLength={500}
            placeholder="归档原因（必填），如：长期挂起 / 版本已下线"
            value={archiveReason}
            onChange={(event) => setArchiveReason(event.target.value)}
          />
        </Space>
      </Modal>
    </Modal>
  );
}

/** 修复验证面板：待验证状态下选择原失败执行与环境创建验证任务；结果未知时保留重试意图，防止重复建任务。 */
function BugVerificationPanel({ bug }: { bug: Bug }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [environmentId, setEnvironmentId] = useState<number>();
  const [sourceExecutionId, setSourceExecutionId] = useState<number>();
  const intent = useRef<{ fingerprint: string; requestKey: string } | null>(null);
  const currentBugId = useRef(bug.id);
  const currentFingerprint = JSON.stringify({ bug_id: bug.id, sourceExecutionId, environmentId });
  currentBugId.current = bug.id;
  const currentFingerprintRef = useRef(currentFingerprint);
  currentFingerprintRef.current = currentFingerprint;
  const [unknownCreate, setUnknownCreate] = useState<TaskCreateUncertainty | null>(null);
  useEffect(() => {
    intent.current = null;
    setSourceExecutionId(undefined);
    setEnvironmentId(undefined);
    setUnknownCreate(null);
  }, [bug.id]);
  const sourcesQuery = useQuery({
    queryKey: ['bug-sources', bug.id],
    queryFn: () => bugsApi.bugSources(bug.id),
  });
  const environmentsQuery = useQuery({
    queryKey: ['project-environments', bug.project_id],
    queryFn: () => projectsApi.listEnvironments(bug.project_id),
  });
  const taskRefsQuery = useQuery({
    queryKey: ['task-resource-sources', 'BUG', bug.id, bug.project_id],
    queryFn: () => tasksApi.sources('BUG', String(bug.id), bug.project_id),
  });
  const verifyMutation = useMutation({
    mutationFn: (submission: { bugId: number; sourceExecutionId: number; environmentId: number; requestKey: string; fingerprint: string }) => tasksApi.verifyBug(submission.bugId, {
      source_case_execution_id: submission.sourceExecutionId,
      environment_id: submission.environmentId,
      request_key: submission.requestKey,
    }),
    onSuccess: async (task, submission) => {
      clearTaskCreateUncertainty(submission.requestKey);
      if (intent.current?.requestKey === submission.requestKey) intent.current = null;
      setUnknownCreate((previous) => previous?.request_key === submission.requestKey ? null : previous);
      message.success('验证任务已创建；任务结果不会自动关闭缺陷');
      await queryClient.invalidateQueries({ queryKey: ['task-resource-sources', 'BUG', submission.bugId] });
      if (currentBugId.current === submission.bugId && currentFingerprintRef.current === submission.fingerprint) {
        navigate(`/console/tasks/${task.id}`);
      }
    },
    onError: (error, submission) => {
      message.error(getErrorMessage(error, '验证任务创建失败'));
      if (!isAxiosError(error) || !error.response || error.response.status >= 500) {
        const marker = { kind: 'verification' as const, project_id: bug.project_id, request_key: submission.requestKey, recorded_at: Date.now() };
        rememberTaskCreateUncertainty(marker);
        setUnknownCreate(marker);
      } else clearTaskCreateUncertainty(submission.requestKey);
    },
  });
  const failedSources = (sourcesQuery.data ?? []).filter((source) => source.case_execution_id != null);
  const environments = (environmentsQuery.data?.items ?? []).filter((environment) => environment.is_active && environment.id != null);

  return (
    <div>
      <Typography.Text strong>修复验证</Typography.Text>
      {bug.status !== '已修复' ? <Typography.Paragraph type="secondary">登记可回归（待验证）后，可以选择原失败用例创建新的验证任务。</Typography.Paragraph> : (
        <Space direction="vertical" style={{ width: '100%', marginTop: 8 }}>
          {sourcesQuery.isError || environmentsQuery.isError ? <Typography.Text type="danger">来源或执行环境读取失败，无法创建验证任务。</Typography.Text> : null}
          <Select
            aria-label="原失败执行"
            value={sourceExecutionId}
            onChange={(value) => { setSourceExecutionId(value); setUnknownCreate(null); }}
            loading={sourcesQuery.isLoading}
            options={failedSources.map((source) => ({ value: source.case_execution_id!, label: `原失败用例执行 #${source.case_execution_id}` }))}
            placeholder={failedSources.length ? '选择关联的原失败执行' : '缺陷没有可用的用例失败来源'}
          />
          <Select
            aria-label="验证环境"
            value={environmentId}
            onChange={(value) => { setEnvironmentId(value); setUnknownCreate(null); }}
            loading={environmentsQuery.isLoading}
            options={environments.map((environment) => ({ value: environment.id!, label: environment.display_name || environment.name }))}
            placeholder={environments.length ? '重新确认验证环境' : '当前项目没有可用环境'}
          />
          <Button
            type="primary"
            loading={verifyMutation.isPending}
            disabled={sourceExecutionId == null || environmentId == null || sourcesQuery.isError || environmentsQuery.isError}
            onClick={() => {
              if (verifyMutation.isPending) return;
              if (sourceExecutionId == null || environmentId == null) return;
              const fingerprint = JSON.stringify({ bug_id: bug.id, sourceExecutionId, environmentId });
              const retryingIntent = intent.current?.fingerprint === fingerprint ? intent.current : null;
              const previousUnknown = readTaskCreateUncertainty();
              if (previousUnknown && retryingIntent?.requestKey !== previousUnknown.request_key) {
                message.warning('请先到任务列表核对上一条结果未知的请求，再提交新的验证配置');
                return;
              }
              const submissionIntent = retryingIntent ?? { fingerprint, requestKey: `bug-verify-${crypto.randomUUID()}` };
              intent.current = submissionIntent;
              rememberTaskCreateUncertainty({ kind: 'verification', project_id: bug.project_id, request_key: submissionIntent.requestKey, recorded_at: Date.now() });
              verifyMutation.mutate({ bugId: bug.id, sourceExecutionId, environmentId, ...submissionIntent });
            }}
          >创建新的验证任务</Button>
          {unknownCreate && <Alert type="warning" showIcon message="验证任务创建结果未知" description="请检查关联任务记录后再决定是否重试；切换环境或来源会建立新的提交意图。" action={<Button size="small" onClick={() => navigate('/console/tasks')}>查看任务列表</Button>} />}
          {taskRefsQuery.isError ? <Typography.Text type="secondary">无法读取相关任务结果。</Typography.Text> : taskRefsQuery.data?.map((ref) => (
            <Typography.Link key={`${ref.task_run_id}-${ref.id}`} onClick={() => navigate(`/console/tasks/${ref.task_id}?runId=${ref.task_run_id}`)}>
              {ref.task_title ?? `验证任务 #${ref.task_id}`} · 运行 #{ref.run_number}
            </Typography.Link>
          ))}
        </Space>
      )}
    </div>
  );
}

/** 附件面板：列表 / 下载 / 删除 / 拖拽上传（单文件 ≤10MB），操作后失效附件缓存。 */
function BugAttachments({ bugId }: { bugId: number }) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['bug-attachments', bugId], queryFn: () => bugsApi.attachments(bugId) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['bug-attachments', bugId] });
  return <Space direction="vertical" style={{ width: '100%' }}><Typography.Text strong>附件</Typography.Text>
    {query.isError ? <Typography.Text type="danger">附件读取失败</Typography.Text> : query.data?.map((attachment) => <Space key={attachment.id}>
      <Button type="link" onClick={() => bugsApi.downloadAttachment(bugId, attachment).catch((error) => message.error(getErrorMessage(error, '下载失败')))}>{attachment.filename}</Button><Typography.Text type="secondary">{(attachment.size / 1024).toFixed(1)} KB</Typography.Text>
      <Button size="small" danger onClick={() => modal.confirm({ title: '删除此附件？', onOk: async () => { try { await bugsApi.deleteAttachment(bugId, attachment.id); await refresh(); } catch (error) { message.error(getErrorMessage(error, '删除失败')); } } })}>删除</Button></Space>)}
    <Upload.Dragger multiple showUploadList={false} customRequest={async ({ file, onSuccess, onError }) => { try { await bugsApi.uploadAttachment(bugId, file as File); await refresh(); onSuccess?.({}); message.success('附件已上传'); } catch (error) { onError?.(error as Error); message.error(getErrorMessage(error, '上传失败')); } }} beforeUpload={(file) => { if (!file.size || file.size > 10 * 1024 * 1024) { message.error('附件不能为空且不能超过 10 MB'); return Upload.LIST_IGNORE; } return true; }}>
      <p className="ant-upload-drag-icon"><InboxOutlined /></p>
      <p className="ant-upload-text">点击或拖拽文件到此处上传</p>
      <p className="ant-upload-hint">支持多个文件，单个文件不超过 10 MB</p>
    </Upload.Dragger></Space>;
}