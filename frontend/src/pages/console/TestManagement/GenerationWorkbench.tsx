// 用例生成审核工作台：批次生成、历史批次、逐条审核与批量操作。
// 草稿接受后才写入正式用例（DRAFT 态）；AI 审阅与质量标记只是建议，人工判断才是审核依据。
import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Collapse,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ButtonProps } from 'antd';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import type {
  CaseDraft,
  DraftQualityIssue,
  GenerationAgentOption,
  GenerationBatch,
  GenerationBatchListItem,
} from '@/features/test-management/contracts';
import { getErrorMessage, userStore } from '@/shared/api/client';
import { buildReviewBody, formatMetric, hasFailedModule, isGenerationActive, generationStorageKey, pendingModules } from '@/pages/console/TestManagement/generationReview.mjs';

const DRAFT_STATUS: Record<string, { label: string; color: string }> = {
  PENDING: { label: '待审核', color: 'gold' },
  ACCEPTED: { label: '已入库', color: 'green' },
  REJECTED: { label: '已拒绝', color: 'red' },
};

const BATCH_STATUS: Record<string, { label: string; color: string }> = {
  QUEUED: { label: '等待执行', color: 'blue' },
  RUNNING: { label: '后台生成中', color: 'processing' },
  CANCEL_REQUESTED: { label: '正在安全停止', color: 'orange' },
  CANCELLED: { label: '已取消', color: 'default' },
  COMPLETED: { label: '生成成功', color: 'green' },
  PARTIAL_FAILED: { label: '部分失败', color: 'orange' },
  FAILED: { label: '生成失败', color: 'red' },
};

const QUALITY_LEVEL_COLOR: Record<string, string> = { error: 'red', warning: 'orange', info: 'blue' };

const QUALITY_RULE_LABEL: Record<string, string> = {
  TITLE_EMPTY: '标题为空',
  TITLE_DUPLICATE_IN_BATCH: '批内重名',
  TITLE_SIMILAR_TO_EXISTING: '疑似重复',
  STEPS_EMPTY: '步骤为空',
  EXPECTED_EMPTY: '预期为空',
  STEP_EXPECTED_MISMATCH: '步骤预期不匹配',
  PRECONDITION_MISSING: '缺前置条件',
  EXPECTED_VAGUE: '预期模糊',
  BOUNDARY_MISSING: '缺边界场景',
};

const AUDIT_ACTION_LABEL: Record<string, string> = {
  CREATE: '创建批次',
  EDIT: '编辑草稿',
  APPROVE: '接受入库',
  REJECT: '拒绝',
  REOPEN: '恢复待审核',
  BATCH_REVIEW: '批量审核',
  REGENERATE: '重新生成失败模块',
};

/** 质量标记：级别颜色 + 规则中文名，悬停看说明与相似用例。 */
function QualityTags({ quality }: { quality: DraftQualityIssue[] }) {
  if (!quality?.length) return null;
  return (
    <>
      {quality.map((issue, index) => (
        <Tooltip
          key={`${issue.rule}-${index}`}
          title={
            <span>
              {issue.message}
              {issue.similar_cases?.length
                ? `；相似用例：${issue.similar_cases.map((item) => `#${item.test_case_id} ${item.name}`).join('；')}`
                : ''}
            </span>
          }
        >
          <Tag color={QUALITY_LEVEL_COLOR[issue.level] ?? 'default'}>{QUALITY_RULE_LABEL[issue.rule] ?? issue.rule}</Tag>
        </Tooltip>
      ))}
    </>
  );
}

/** 模块耗时与 token 指标；只有数值，不含提示词与密钥。 */
function MetricsLine({ batch }: { batch: GenerationBatch }) {
  if (!batch.module_metrics?.length) return null;
  return (
    <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
      {batch.module_metrics.map((item, index) => <div key={index}>{formatMetric(item)}</div>)}
    </Typography.Paragraph>
  );
}

/** 单条草稿卡片：结构化展示 + 编辑/接受/拒绝/恢复。 */
function DraftCard({ draft, onChanged }: { draft: CaseDraft; onChanged: () => void }) {
  const { message, modal } = App.useApp();
  const [editOpen, setEditOpen] = useState(false);
  const [form] = Form.useForm();
  const status = DRAFT_STATUS[draft.status] ?? { label: draft.status, color: 'default' };
  const edited = JSON.stringify(draft.original_payload ?? {}) !== JSON.stringify({ ...draft.payload });

  const submitEdit = async () => {
    const values = await form.validateFields();
    const lines = (text?: string) => (text ?? '').split('\n').map((item) => item.trim()).filter(Boolean);
    try {
      await testManagementApi.updateDraft(draft.id, {
        title: values.title,
        priority: values.priority,
        requirement: values.requirement,
        preconditions: lines(values.preconditions),
        test_data: lines(values.test_data),
        steps: lines(values.steps),
        expected_results: lines(values.expected_results),
      });
      message.success('草稿已保存');
      setEditOpen(false);
      onChanged();
    } catch (error) {
      message.error(getErrorMessage(error, '保存草稿失败'));
    }
  };

  const reject = () => {
    let comment = '';
    modal.confirm({
      title: '拒绝该草稿？',
      content: <Input.TextArea rows={3} maxLength={500} placeholder="拒绝原因（可选）" onChange={(event) => { comment = event.target.value; }} />,
      onOk: async () => {
        try {
          await testManagementApi.rejectDraft(draft.id, comment ? { comment } : {});
          onChanged();
        } catch (error) {
          message.error(getErrorMessage(error, '拒绝失败'));
        }
      },
    });
  };

  return (
    <div data-testid={`gen-draft-${draft.id}`} style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 12, marginBottom: 8 }}>
      <Space wrap>
        <Typography.Text strong>{draft.title}</Typography.Text>
        <Tag>{draft.priority}</Tag>
        <Tag data-testid={`gen-draft-status-${draft.id}`} color={status.color}>{status.label}</Tag>
        {edited && draft.status === 'PENDING' ? <Tag color="purple">已人工修改</Tag> : null}
        <QualityTags quality={draft.quality} />
      </Space>
      <Typography.Paragraph style={{ marginTop: 8, marginBottom: 4 }}>{draft.payload.requirement}</Typography.Paragraph>
      <Collapse
        size="small"
        items={[{
          key: 'detail',
          label: '步骤与预期',
          children: (
            <div>
              <Typography.Text type="secondary">前置条件：{(draft.payload.preconditions ?? []).join('；') || '无'}</Typography.Text>
              <ol style={{ marginBottom: 4 }}>
                {(draft.payload.steps ?? []).map((step, index) => (
                  <li key={index}>
                    {step}
                    {draft.payload.expected_results?.[index] ? (
                      <Typography.Text type="secondary">{` → ${draft.payload.expected_results[index]}`}</Typography.Text>
                    ) : null}
                  </li>
                ))}
              </ol>
              <Typography.Text type="secondary">测试数据：{(draft.payload.test_data ?? []).join('；') || '无'}</Typography.Text>
            </div>
          ),
        }]}
      />
      <div style={{ marginTop: 8 }}>
        <Typography.Text type="secondary">
          子 Agent {draft.child_name} v{draft.child_version} · 模型 {draft.model_name || '-'} · Skill {draft.skill_versions.map((item) => `${item.key}@${item.version}`).join('、') || '无'}
        </Typography.Text>
      </div>
      {draft.import_error ? <Alert data-testid={`gen-import-error-${draft.id}`} style={{ marginTop: 8 }} type="error" showIcon message={`入库失败：${draft.import_error}`} /> : null}
      {draft.review_comment ? <Alert style={{ marginTop: 8 }} type="warning" showIcon message={`审核意见：${draft.review_comment}`} /> : null}
      {draft.status === 'PENDING' ? (
        <Space style={{ marginTop: 8 }}>
          <Button size="small" data-testid={`gen-draft-edit-${draft.id}`} onClick={() => { form.setFieldsValue({
            title: draft.title,
            priority: draft.priority,
            requirement: draft.payload.requirement,
            preconditions: (draft.payload.preconditions ?? []).join('\n'),
            test_data: (draft.payload.test_data ?? []).join('\n'),
            steps: (draft.payload.steps ?? []).join('\n'),
            expected_results: (draft.payload.expected_results ?? []).join('\n'),
          }); setEditOpen(true); }}>编辑</Button>
          <Popconfirm title="接受该草稿并写入正式用例？" onConfirm={async () => {
            try {
              await testManagementApi.acceptDraft(draft.id);
              message.success('已入库');
              onChanged();
            } catch (error) {
              message.error(getErrorMessage(error, '入库失败'));
            }
          }}>
            <Button size="small" type="primary" data-testid={`gen-draft-accept-${draft.id}`}>接受入库</Button>
          </Popconfirm>
          <Button size="small" danger data-testid={`gen-draft-reject-${draft.id}`} onClick={reject}>拒绝</Button>
        </Space>
      ) : null}
      {draft.status === 'REJECTED' ? (
        <Space style={{ marginTop: 8 }}>
          <Button size="small" data-testid={`gen-draft-reopen-${draft.id}`} onClick={async () => {
            try {
              await testManagementApi.reopenDraft(draft.id);
              onChanged();
            } catch (error) {
              message.error(getErrorMessage(error, '恢复失败'));
            }
          }}>恢复待审核</Button>
        </Space>
      ) : null}
      {draft.status === 'ACCEPTED' && draft.test_case_id ? (
        <div style={{ marginTop: 8 }}><Typography.Text type="success">已入库为用例 #{draft.test_case_id}</Typography.Text></div>
      ) : null}
      <Modal title="编辑草稿" open={editOpen} width={640} onCancel={() => setEditOpen(false)} onOk={submitEdit} destroyOnClose okButtonProps={{ 'data-testid': 'gen-edit-save' } as ButtonProps}>
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="用例标题" rules={[{ required: true, whitespace: true, max: 200 }]}><Input /></Form.Item>
          <Form.Item name="priority" label="优先级" rules={[{ required: true }]}>
            <Select options={['P0', 'P1', 'P2', 'P3'].map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item name="requirement" label="测试需求" rules={[{ required: true, whitespace: true, max: 2000 }]}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="preconditions" label="前置条件（每行一条）"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="test_data" label="测试数据（每行一条）"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="steps" label="测试步骤（每行一条）" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="expected_results" label="预期结果（每行一条）" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

/** 批次级操作：全部接受、全部拒绝、按模块接受、失败模块重新生成。全部二次确认。 */
function BatchActionBar({ batch, onChanged }: { batch: GenerationBatch; onChanged: () => void }) {
  const { message, modal } = App.useApp();
  const [module, setModule] = useState<string | undefined>(undefined);
  const pending = batch.drafts.filter((draft) => draft.status === 'PENDING');
  const modules = pendingModules(batch.drafts);
  const hasFailed = hasFailedModule(batch.module_errors);

  const review = (action: 'accept' | 'reject', scope: 'all' | 'module', moduleName?: string) => {
    const count = scope === 'all' ? pending.length : pending.filter((draft) => draft.module === moduleName).length;
    modal.confirm({
      title: action === 'accept' ? '批量接受并入库' : '批量拒绝',
      content: `将对 ${count} 条待审核草稿执行「${action === 'accept' ? '接受并写入正式用例' : '拒绝'}」，重名草稿会单条失败并标明原因。确认继续？`,
      okButtonProps: { 'data-testid': 'gen-batch-review-confirm' } as ButtonProps,
      onOk: async () => {
        try {
          const result = await testManagementApi.reviewGenerationBatch(batch.id, buildReviewBody({ action, scope, module: moduleName }));
          const failed = result.items.filter((item) => !item.ok);
          if (failed.length) {
            message.warning(`已处理 ${result.affected} 条，${failed.length} 条失败：${failed[0].error ?? ''}`);
          } else {
            message.success(`已处理 ${result.affected} 条`);
          }
          onChanged();
        } catch (error) {
          message.error(getErrorMessage(error, '批量操作失败'));
        }
      },
    });
  };

  const regenerate = async () => {
    try {
      if (batch.task_run_id) {
        await testManagementApi.retryGenerationTask(batch.id);
        message.success('失败模块已排队重试');
      } else {
        await testManagementApi.regenerateGenerationBatch(batch.id, {});
        message.success('失败模块已重新生成');
      }
      onChanged();
    } catch (error) {
      message.error(getErrorMessage(error, '重新生成失败'));
    }
  };

  return (
    <Space wrap style={{ marginBottom: 12 }}>
      <Button data-testid="gen-review-all-accept" type="primary" disabled={!pending.length} onClick={() => review('accept', 'all')}>全部接受入库（{pending.length}）</Button>
      <Button data-testid="gen-review-all-reject" danger disabled={!pending.length} onClick={() => review('reject', 'all')}>全部拒绝</Button>
      <Select
        data-testid="gen-module-select"
        placeholder="按模块接受"
        style={{ width: 160 }}
        value={module}
        onChange={setModule}
        options={modules.map((item) => ({ value: item, label: item }))}
      />
      <Button data-testid="gen-review-module-accept" disabled={!module} onClick={() => module && review('accept', 'module', module)}>接受该模块</Button>
      {hasFailed && !isGenerationActive(batch.status) ? (
        <Popconfirm title="只重新生成失败模块，已审核草稿不受影响。确认？" onConfirm={regenerate}>
          <Button data-testid="gen-regenerate">重新生成失败模块</Button>
        </Popconfirm>
      ) : null}
    </Space>
  );
}

/** 批次审计时间线。 */
function AuditPanel({ batchId }: { batchId: number }) {
  const query = useQuery({
    queryKey: ['generation-audits', batchId],
    queryFn: () => testManagementApi.listGenerationAudits(batchId),
  });
  if (!query.data?.length) return <Typography.Text type="secondary">暂无审计记录</Typography.Text>;
  return (
    <div>
      {query.data.map((row) => (
        <div key={row.id} style={{ marginBottom: 4 }}>
          <Typography.Text type="secondary">
            {row.created_at?.replace('T', ' ').slice(0, 19)} · {AUDIT_ACTION_LABEL[row.action] ?? row.action}
            {row.draft_id ? ` · 草稿 #${row.draft_id}` : ''}
            {row.detail && Object.keys(row.detail).length ? ` · ${JSON.stringify(row.detail)}` : ''}
          </Typography.Text>
        </div>
      ))}
    </div>
  );
}

/** 批次详情：审阅建议、模块错误、批量操作、按模块分组的草稿、审计。 */
export function BatchDetail({ batch: initialBatch, onChanged }: { batch: GenerationBatch; onChanged: (updated?: GenerationBatch) => void }) {
  const queryClient = useQueryClient();
  const batchQuery = useQuery({
    queryKey: ['generation-batch', initialBatch.id],
    queryFn: () => testManagementApi.getGenerationBatch(initialBatch.id),
    initialData: initialBatch,
    refetchInterval: (query) => isGenerationActive(query.state.data?.status) ? 1500 : false,
    refetchIntervalInBackground: true,
  });
  const batch = batchQuery.data;
  const taskQuery = useQuery({
    queryKey: ['generation-task', batch.id],
    queryFn: () => testManagementApi.getGenerationTask(batch.id),
    enabled: Boolean(batch.task_run_id),
    refetchInterval: (query) => isGenerationActive(query.state.data?.status ?? batch.status) ? 1500 : false,
    refetchIntervalInBackground: true,
  });
  const { message } = App.useApp();
  const reload = async () => {
    const updated = await testManagementApi.getGenerationBatch(batch.id);
    queryClient.setQueryData(['generation-batch', batch.id], updated);
    queryClient.invalidateQueries({ queryKey: ['generation-task', batch.id] });
    queryClient.invalidateQueries({ queryKey: ['generation-audits', batch.id] });
    onChanged(updated);
  };
  const status = BATCH_STATUS[batch.status] ?? { label: batch.status, color: 'default' };
  const modules = Array.from(new Set(batch.drafts.map((draft) => draft.module)));
  return (
    <div style={{ marginTop: 16 }}>
      <Space wrap>
        <Typography.Text strong>批次 #{batch.id}</Typography.Text>
        <Tag color={status.color}>{status.label}</Tag>
        <Typography.Text type="secondary">主 Agent {batch.supervisor_name} v{batch.supervisor_version} · {batch.created_at?.replace('T', ' ').slice(0, 19)}</Typography.Text>
      </Space>
      {batch.review_summary ? (
        <Alert style={{ marginTop: 8 }} type="info" showIcon message={`AI 审阅建议（仅供参考，不构成审核依据）：${batch.review_summary}`} />
      ) : null}
      {batch.review_gaps.length ? (
        <Alert style={{ marginTop: 8 }} type="warning" showIcon message={`待确认事项：${batch.review_gaps.join('；')}`} />
      ) : null}
      {batch.task_run_id ? (
        <div data-testid="gen-task-progress">
          <Typography.Paragraph>任务 #{batch.task_id} · Run #{batch.task_run_id} · {taskQuery.data?.completed ?? 0}/{taskQuery.data?.total ?? 0}</Typography.Paragraph>
          {taskQuery.data?.trace_id ? (
            <Typography.Paragraph type="secondary">
              Trace <Typography.Text copyable code>{taskQuery.data.trace_id}</Typography.Text>
              {taskQuery.data.observability_status === 'DISABLED' ? ' · 追踪上报未启用' : ' · 追踪投影待核验'}
            </Typography.Paragraph>
          ) : null}
          <Progress percent={taskQuery.data?.total ? Math.round(100 * taskQuery.data.completed / taskQuery.data.total) : 0} />
          {taskQuery.error || batchQuery.error ? <Alert type="error" message="读取任务状态失败，请刷新重试" /> : null}
          {taskQuery.data?.modules.map((item) => (
            <div key={item.work_item_id} data-testid={`gen-task-module-${item.module}`}>
              <Tag>{item.module}</Tag>{item.status} · Agent #{item.agent_id} v{item.agent_version} · 尝试 {item.attempts}
              {item.agent_run_id ? ` · 实例 #${item.agent_run_id}` : ''}
              {item.started_at ? ` · 开始 ${item.started_at.replace('T', ' ').slice(0, 19)}` : ''}
              {item.finished_at ? ` · 结束 ${item.finished_at.replace('T', ' ').slice(0, 19)}` : ''}
              {item.duration_ms != null ? ` · ${(item.duration_ms / 1000).toFixed(1)} 秒` : ''}
              {item.error_code ? ` · ${item.error_code}：${item.error}` : ''}
            </div>
          ))}
          {isGenerationActive(batch.status) ? <Button data-testid="gen-cancel" danger disabled={batch.status === 'CANCEL_REQUESTED'} onClick={async () => {
            try { await testManagementApi.cancelGenerationTask(batch.id); await reload(); }
            catch (error) { message.error(getErrorMessage(error, '取消失败')); }
          }}>取消生成任务</Button> : null}
          <Collapse items={[{ key: 'task-events', label: '任务执行时间线', children: taskQuery.data?.events.map((event) => (
            <div key={event.id}>{event.created_at.replace('T', ' ').slice(0, 19)} · {event.type} · {String(event.detail.module ?? '')} {String(event.detail.status ?? '')}</div>
          )) }]} />
        </div>
      ) : null}
      <MetricsLine batch={batch} />
      {batch.module_errors.map((item, index) => (
        <Alert key={index} data-testid={`gen-module-error-${item.module ?? index}`} type={item.status === 'SKIPPED' ? 'warning' : 'error'} showIcon style={{ marginBottom: 8 }} message={`${item.module ?? '模块'}：${item.error}`} />
      ))}
      <BatchActionBar batch={batch} onChanged={reload} />
      <Tabs
        size="small"
        items={modules.map((name) => ({
          key: name,
          label: `${name}（${batch.drafts.filter((draft) => draft.module === name).length}）`,
          children: batch.drafts.filter((draft) => draft.module === name).map((draft) => (
            <DraftCard key={draft.id} draft={draft} onChanged={reload} />
          )),
        }))}
      />
      <Collapse
        size="small"
        style={{ marginTop: 8 }}
        items={[{ key: 'audits', label: <span data-testid="gen-audits">审计记录</span>, children: <AuditPanel batchId={batch.id} /> }]}
      />
    </div>
  );
}

/** 历史批次列表：状态/模块/关键字筛选 + 分页。 */
export function BatchHistory({ projectId, onSelect }: { projectId: number; onSelect: (batch: GenerationBatch) => void }) {
  const { message } = App.useApp();
  const [pagination, setPagination] = useState({ page: 1, page_size: 10 });
  const [filters, setFilters] = useState<{ status?: string; module?: string; keyword?: string }>({});
  const query = useQuery({
    queryKey: ['generation-batches', projectId, pagination, filters],
    queryFn: () => testManagementApi.listGenerationBatches(projectId, {
      page: pagination.page, page_size: pagination.page_size, ...filters,
    }),
  });
  const open = async (batchId: number) => {
    try {
      onSelect(await testManagementApi.getGenerationBatch(batchId));
    } catch (error) {
      message.error(getErrorMessage(error, '读取批次失败'));
    }
  };
  const status = query.data;
  return (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          allowClear placeholder="状态" style={{ width: 130 }}
          options={Object.entries(BATCH_STATUS).map(([value, item]) => ({ value, label: item.label }))}
          onChange={(value) => { setFilters((prev) => ({ ...prev, status: value })); setPagination((prev) => ({ ...prev, page: 1 })); }}
        />
        <Select
          allowClear placeholder="模块" style={{ width: 130 }}
          options={['api', 'web', 'security', 'asr', 'ai'].map((value) => ({ value, label: value }))}
          onChange={(value) => { setFilters((prev) => ({ ...prev, module: value })); setPagination((prev) => ({ ...prev, page: 1 })); }}
        />
        <Input.Search
          allowClear placeholder="需求关键字" style={{ width: 200 }}
          onSearch={(value) => { setFilters((prev) => ({ ...prev, keyword: value || undefined })); setPagination((prev) => ({ ...prev, page: 1 })); }}
        />
        {status ? (
          <Typography.Text type="secondary">
            成功 {status.completed_count} · 部分失败 {status.partial_failed_count} · 失败 {status.failed_count}
          </Typography.Text>
        ) : null}
      </Space>
      <Table<GenerationBatchListItem>
        rowKey="id"
        size="small"
        loading={query.isFetching}
        dataSource={query.data?.items ?? []}
        pagination={{
          current: pagination.page,
          pageSize: pagination.page_size,
          total: query.data?.total ?? 0,
          onChange: (page, pageSize) => setPagination({ page, page_size: pageSize }),
        }}
        columns={[
          { title: '批次', dataIndex: 'id', width: 70, render: (value: number) => `#${value}` },
          { title: '方向', dataIndex: 'direction', width: 70 },
          {
            title: '状态', dataIndex: 'status', width: 100,
            render: (value: string) => {
              const item = BATCH_STATUS[value] ?? { label: value, color: 'default' };
              return <Tag color={item.color}>{item.label}</Tag>;
            },
          },
          { title: '主 Agent', dataIndex: 'supervisor_name' },
          {
            title: '草稿', width: 170,
            render: (_, row) => `共 ${row.draft_total} · 待审 ${row.pending_count} · 入库 ${row.accepted_count} · 拒绝 ${row.rejected_count}`,
          },
          {
            title: '失败模块', dataIndex: 'module_error_count', width: 90,
            render: (value: number) => (value ? <Tag color="red">{value}</Tag> : '-'),
          },
          { title: '创建时间', dataIndex: 'created_at', width: 160, render: (value: string) => value?.replace('T', ' ').slice(0, 19) },
          { title: '操作', width: 80, render: (_, row) => <Button size="small" type="link" data-testid={`gen-batch-open-${row.id}`} onClick={() => open(row.id)}>审核</Button> },
        ]}
      />
    </div>
  );
}

/** 生成抽屉主体：新建生成 + 历史批次两个页签。 */
export function GenerationWorkbench({ projectId, direction, scopeNodeId, agents, batch, onBatch, onChanged }: {
  projectId: number;
  direction: string;
  scopeNodeId?: number;
  agents: GenerationAgentOption[];
  batch: GenerationBatch | null;
  onBatch: (batch: GenerationBatch | null) => void;
  onChanged: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<'generate' | 'history'>('generate');
  const userId = String(userStore.get<{ id: number }>()?.id ?? '');
  const storageKey = generationStorageKey(userId, projectId, direction);
  const requestRef = useRef<{ payload: string; key: string } | null>(null);
  useEffect(() => {
    let disposed = false;
    const saved = localStorage.getItem(storageKey);
    if (saved) testManagementApi.getGenerationBatch(Number(saved)).then((result) => {
      if (!disposed && result.project_id === projectId && result.direction === direction) onBatch(result);
    }).catch(() => { if (!disposed) message.error('恢复生成任务失败，可从历史批次重新打开'); });
    return () => { disposed = true; };
  // onBatch is supplied by the parent; restore only when the scope changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);
  const rememberBatch = (result: GenerationBatch) => {
    localStorage.setItem(storageKey, String(result.id));
    onBatch(result);
  };
  const run = async () => {
    const values = await form.validateFields();
    if (busy) return;
    const payload = JSON.stringify({ projectId, direction, scopeNodeId, values });
    if (requestRef.current?.payload !== payload) requestRef.current = { payload, key: crypto.randomUUID() };
    setBusy(true);
    try {
      const created = await testManagementApi.submitGenerationTask(projectId, {
        request_key: requestRef.current!.key,
        agent_id: values.agent_id,
        direction,
        scope_node_id: scopeNodeId,
        requirements: values.requirements,
        include_security: Boolean(values.include_security),
        cases_per_module: values.cases_per_module,
      });
      rememberBatch(created);
      message.success(`任务 #${created.task_id} 已提交，可离开页面后查看进度`);
    } catch (error) {
      message.error(getErrorMessage(error, '生成失败'));
    } finally {
      setBusy(false);
    }
  };
  const tabs = [
    {
      key: 'generate',
      label: '生成草稿',
      children: (
        <>
          <Form form={form} layout="vertical" initialValues={{ cases_per_module: 5, include_security: false }}>
            <Form.Item name="agent_id" label="主 Agent" rules={[{ required: true }]}>
              <Select data-testid="gen-agent-select" options={agents.map((agent) => ({ value: agent.id, label: `${agent.name} v${agent.version}（${agent.modules.join('、')}）` }))} placeholder={agents.length ? '选择用例生成主 Agent' : '还没有启用的用例生成主 Agent'} />
            </Form.Item>
            <Form.Item name="cases_per_module" label="每模块条数"><InputNumber min={1} max={20} data-testid="gen-cases-per-module" /></Form.Item>
            <Form.Item name="include_security" valuePropName="checked"><Checkbox data-testid="gen-include-security">同时生成安全专项（主 Agent 已绑定安全子 Agent 时）</Checkbox></Form.Item>
            <Form.Item name="requirements" label="需求" rules={[{ required: true, whitespace: true }]}><Input.TextArea data-testid="gen-requirements" rows={5} maxLength={20000} /></Form.Item>
            <Space>
              <Button data-testid="gen-submit" type="primary" loading={busy} onClick={run}>生成草稿</Button>
              {batch && !isGenerationActive(batch.status) ? <Button onClick={() => {
                requestRef.current = null;
                localStorage.removeItem(storageKey);
                onBatch(null);
              }}>新建生成任务</Button> : null}
            </Space>
          </Form>
          {batch ? <BatchDetail batch={batch} onChanged={(updated) => { if (updated) onBatch(updated); onChanged(); }} /> : null}
        </>
      ),
    },
    {
      key: 'history',
      label: '历史批次',
      children: (
        <BatchHistory projectId={projectId} onSelect={(selected) => { rememberBatch(selected); setTab('generate'); }} />
      ),
    },
  ];
  return (
    <>
      <Alert type="info" showIcon style={{ marginBottom: 12 }} message="草稿不会自动成为正式用例，也不能直接执行。接受后才进入用例库（DRAFT 态）。" />
      <Tabs activeKey={tab} onChange={(key) => setTab(key as 'generate' | 'history')} items={tabs} />
    </>
  );
}

