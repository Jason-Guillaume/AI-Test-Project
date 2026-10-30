import { collectPages } from '@/shared/api/pagination';
// 安全测试 · 安全用例 Tab。
//
// 新建安全计划（预览 Modal）→ 确认生成 → 高风险确认 → 执行（测试环境）→ 变异详情抽屉。
// confirm-risk / execute 都只能由人在本页触发，不会自动执行。
//
// 安全红线：
//   - 执行只能选非生产环境（allow_production 恒不生效，生产由后端 gate 拒绝）；
//   - 变异详情抽屉展示的 mutation_trace / evidence 均为后端脱敏后的结构化数据，
//     本页不展示基线 Authorization 头明文，也不在任何 Agent brief 里暴露证据；
//   - 缺 Fixture（blocked_reason 非空）的预览项整行标黄，确认时不强制勾选。
import { useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { securityApi } from '@/features/security-testing/api/securityTesting';
import { projectsApi } from '@/features/projects/api/projects';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import { PlanPreviewModal } from './PlanPreviewModal';
import {
  RESULT_OPTIONS,
  resultColor,
  resultLabel,
  severityColor,
  severityLabel,
} from './constants';
import type { SecurityCaseDetail, SecurityExecution } from '@/features/security-testing/contracts';


/** 安全用例 Tab。projectId 由父页传入（已确保非空）。 */
export function CasesTab({ projectId }: { projectId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [apiFilter, setApiFilter] = useState<number | undefined>(undefined);
  const [enabledFilter, setEnabledFilter] = useState<boolean | undefined>(undefined);
  const [selectedCases, setSelectedCases] = useState<SecurityCaseDetail[]>([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [executeOpen, setExecuteOpen] = useState(false);
  const [drawerExec, setDrawerExec] = useState<SecurityExecution | null>(null);

  const listQuery = useQuery({
    queryKey: ['security-cases', projectId, { api_id: apiFilter, enabled: enabledFilter }],
    queryFn: () =>
      collectPages((page) => securityApi.listCases(projectId, {
        page,
        page_size: 100,
        api_id: apiFilter,
        enabled: enabledFilter,
      })),
  });

  const allCasesQuery = useQuery({
    queryKey: ['security-cases', projectId, 'filter-options'],
    queryFn: () => collectPages((page) => securityApi.listCases(projectId, { page, page_size: 100 })),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['security-cases'] });
    queryClient.invalidateQueries({ queryKey: ['security-findings'] });
    queryClient.invalidateQueries({ queryKey: ['security-overview', projectId] });
  };

  const toggleEnabledMutation = useMutation({
    mutationFn: ({ c, next }: { c: SecurityCaseDetail; next: boolean }) =>
      securityApi.updateCase(c.id, { enabled: next }),
    onSuccess: () => {
      message.success('已切换启用状态');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '切换失败')),
  });

  const confirmRiskMutation = useMutation({
    mutationFn: (caseId: number) => securityApi.confirmRisk(caseId),
    onSuccess: () => {
      message.success('已确认高风险用例');
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '确认失败')),
  });

  const runMutation = useMutation({
    mutationFn: (body: { security_case_ids: number[]; environment_id?: number | null }) =>
      securityApi.runSecurity(projectId, body),
    onSuccess: (run) => {
      message.success(`已提交执行（TestRun #${run.id}）`);
      setExecuteOpen(false);
      setSelectedCases([]);
      invalidate();
    },
    onError: (e) => message.error(getErrorMessage(e, '执行失败')),
  });

  const confirmStatus = (c: SecurityCaseDetail): 'READY' | 'PENDING_CONFIRM' | 'CONFIRMED' => {
    if (!c.confirmation_required) return 'READY';
    return c.confirmed_at ? 'CONFIRMED' : 'PENDING_CONFIRM';
  };

  const columns: TableColumnsType<SecurityCaseDetail> = [
    {
      title: '用例',
      dataIndex: 'case_name',
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{r.case_name ?? `安全用例 #${r.id}`}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.mutation_type}
            {r.api_name ? ` · ${r.api_name}` : ''}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '风险级别',
      dataIndex: 'risk_level',
      width: 90,
      render: (v: string | null) => (v ? <Tag color={severityColor(v)}>{severityLabel(v)}</Tag> : '-'),
    },
    {
      title: '高风险确认',
      width: 130,
      render: (_, r) => {
        const st = confirmStatus(r);
        if (st === 'READY') return <Tag color="green">无需确认</Tag>;
        if (st === 'CONFIRMED') return <Tag color="blue">已确认</Tag>;
        return (
          <Space size="small">
            <Tag color="orange">待确认</Tag>
            <Button
              size="small"
              type="link"
              onClick={() => confirmRiskMutation.mutate(r.id)}
              loading={confirmRiskMutation.isPending}
            >
              确认
            </Button>
          </Space>
        );
      },
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 70,
      render: (v: boolean, r) => (
        <Switch checked={v} size="small" onChange={(next) => toggleEnabledMutation.mutate({ c: r, next })} />
      ),
    },
    {
      title: '最近执行',
      width: 160,
      render: (_, r) => {
        const ex = r.latest_execution;
        if (!ex) return <Typography.Text type="secondary">未执行</Typography.Text>;
        return (
          <Button
            size="small"
            type="link"
            onClick={() => setDrawerExec(ex)}
            style={{ padding: 0 }}
          >
            <Tag color={resultColor(ex.security_result)}>{resultLabel(ex.security_result)}</Tag>
            {ex.actual_status_codes.length > 0 && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {ex.actual_status_codes.join(',')}
              </Typography.Text>
            )}
          </Button>
        );
      },
    },
  ];

  if (listQuery.isLoading) return <LoadingState />;
  if (listQuery.isError) return <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />;

  const items = listQuery.data?.items ?? [];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space wrap className="ui-list-toolbar">
          <Select
            allowClear
            placeholder="按接口过滤"
            style={{ width: 200 }}
            value={apiFilter}
            onChange={setApiFilter}
            options={Array.from(
              new Map(
                (allCasesQuery.data?.items ?? [])
                  .filter((c) => c.api_id != null)
                  .map((c) => [c.api_id as number, c.api_name ?? '未知接口']),
              ).entries(),
            ).map(([id, name]) => ({ value: id, label: name }))}
          />
          <Select
            allowClear
            placeholder="启用状态"
            style={{ width: 140 }}
            value={enabledFilter}
            onChange={setEnabledFilter}
            options={[
              { value: true, label: '已启用' },
              { value: false, label: '已停用' },
            ]}
          />
          <Button type="primary" onClick={() => setPreviewOpen(true)}>
            新建安全计划
          </Button>
          <Button
            disabled={selectedCases.length === 0}
            onClick={() => setExecuteOpen(true)}
          >
            执行选中（{selectedCases.length}）
          </Button>
        </Space>
      </Card>

      <Table<SecurityCaseDetail> scroll={{ x: 'max-content' }}
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={false}
        rowSelection={{
          selectedRowKeys: selectedCases.map((c) => c.id),
          onChange: (_, rows) => setSelectedCases(rows),
        }}
      />

      {previewOpen && (
        <PlanPreviewModal
          projectId={projectId}
          onCancel={() => setPreviewOpen(false)}
          onConfirmed={() => {
            setPreviewOpen(false);
            invalidate();
          }}
        />
      )}

      {executeOpen && (
        <ExecuteModal
          projectId={projectId}
          cases={selectedCases}
          submitting={runMutation.isPending}
          onCancel={() => setExecuteOpen(false)}
          onSubmit={(environmentId) =>
            runMutation.mutate({
              security_case_ids: selectedCases.map((c) => c.id),
              environment_id: environmentId,
            })
          }
        />
      )}

      <MutationDetailDrawer execution={drawerExec} onClose={() => setDrawerExec(null)} />
    </div>
  );
}

/** 执行 Modal：选择非生产环境后批量执行选中用例。 */
function ExecuteModal({
  projectId,
  cases,
  submitting,
  onCancel,
  onSubmit,
}: {
  projectId: number;
  cases: SecurityCaseDetail[];
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (environmentId: number | null) => void;
}) {
  const [envId, setEnvId] = useState<number | undefined>(undefined);
  const envsQuery = useQuery({
    queryKey: ['security-execute', projectId, 'envs'],
    queryFn: () => projectsApi.listEnvironments(projectId),
  });
  const envs = (envsQuery.data?.items ?? []).filter((e) => e.id != null);

  const pendingConfirm = cases.filter((c) => c.confirmation_required && !c.confirmed_at);

  return (
    <Modal
      title={`执行安全用例（${cases.length} 条）`}
      open
      onCancel={onCancel}
      confirmLoading={submitting}
      okText="执行"
      cancelText="取消"
      okButtonProps={{ disabled: envId == null }}
      onOk={() => onSubmit(envId ?? null)}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {pendingConfirm.length > 0 && (
          <Alert
            type="warning"
            showIcon
            message={`${pendingConfirm.length} 条高风险用例尚未确认`}
            description="未确认的高风险用例会被服务端跳过（SECURITY_CONFIRMATION_REQUIRED）。请先在用例列表点「确认」。"
          />
        )}
        <Form layout="vertical">
          <Form.Item label="执行环境" required>
            <Select
              placeholder="选择环境（生产会被服务端拒绝）"
              value={envId}
              onChange={setEnvId}
              options={envs.map((e) => ({ value: e.id, label: `${e.display_name}（${e.name}）` }))}
            />
          </Form.Item>
        </Form>
        <Alert
          type="info"
          showIcon
          message="安全变异请求只会发送到所选环境；生产环境恒为拒绝。"
        />
      </Space>
    </Modal>
  );
}

/** 变异详情抽屉：展示一次安全执行的脱敏 trace / 结论。 */
function MutationDetailDrawer({
  execution,
  onClose,
}: {
  execution: SecurityExecution | null;
  onClose: () => void;
}) {
  return (
    <Drawer
      title={execution ? `变异详情 #${execution.id}` : '变异详情'}
      open={execution != null}
      onClose={onClose}
      width={560}
      destroyOnClose
    >
      {execution && (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="安全结论">
              <Tag color={resultColor(execution.security_result)}>
                {resultLabel(execution.security_result)}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="分类">{execution.classification ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="基线结论">
              {execution.baseline_status ? (
                <Tag color={execution.baseline_status === 'PASSED' ? 'green' : 'red'}>
                  {execution.baseline_status}
                </Tag>
              ) : (
                '-'
              )}
            </Descriptions.Item>
            <Descriptions.Item label="基线状态码">
              {execution.baseline_http_status ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label="实际状态码">
              {execution.actual_status_codes.length ? execution.actual_status_codes.join(',') : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="重放次数">{execution.replay_count}</Descriptions.Item>
            {execution.error_code && (
              <Descriptions.Item label="错误码" span={2}>
                <Typography.Text type="danger">{execution.error_code}</Typography.Text>
              </Descriptions.Item>
            )}
          </Descriptions>

          <Card size="small" title="变异轨迹（已脱敏）">
            {execution.mutation_trace.length === 0 ? (
              <Empty description="无变异轨迹" />
            ) : (
              <pre
                style={{
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  maxHeight: 240,
                  overflow: 'auto',
                  background: '#fafafa',
                  padding: 8,
                  borderRadius: 6,
                  fontSize: 12,
                  margin: 0,
                }}
              >
                {JSON.stringify(execution.mutation_trace, null, 2)}
              </pre>
            )}
          </Card>

          <Alert
            type="info"
            showIcon
            message="基线请求头（如 Authorization）与响应正文已在后端脱敏，本页不展示明文。"
          />

          {RESULT_OPTIONS.find((o) => o.value === execution.security_result)?.value ===
            'POTENTIAL_ISSUE' && (
            <Alert
              type="warning"
              showIcon
              message="该次执行产生疑似问题"
              description="疑似问题需人工确认，不等于已发现漏洞。可在「疑似问题」Tab 查看与处置。"
            />
          )}
        </Space>
      )}
    </Drawer>
  );
}
