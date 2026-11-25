import { collectArrayPages } from '@/shared/api/pagination';
// 执行中心页（用户视角）。
// 列出项目内测试计划，逐行「执行」触发同步执行（POST /test-plans/{id}/runs），
// 返回完成的 TestRun，弹窗展示结果汇总并支持跳转执行历史。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写/执行 = 项目成员（member+）；越权 404，前端不展示。
// §32：执行同步返回完成态 TestRun（status/total/passed/failed/skipped/error）。
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  App,
  Button,
  Descriptions,
  Form,
  Modal,
  Select,
  Space,
  Statistic,
  Table,
  theme,
  Typography,
} from 'antd';
import { CaretRightOutlined } from '@ant-design/icons';
import { useMutation, useQuery } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { projectsApi } from '@/features/projects/api/projects';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { fmtTimeSec } from '@/shared/lib/format';
import { TEST_RUN_STATUS_COLOR } from '@/features/test-management/status';
import { TEST_RUN_STATUS_OPTIONS } from './constants';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { useAuth } from '@/app/providers/AuthProvider';
import type { Environment } from '@/features/environments/contracts';
import type { TestPlan, TestRun } from '@/features/test-management/contracts';


interface RunFormValues {
  environment_id?: number | null;
}

/** 执行中心页。 */
export function ConsoleExecutionCenterPage() {
  const { message } = App.useApp();
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const { currentProjectId } = useConsoleScope();
  const { user } = useAuth();
  const storageKey = useCallback((projectId: number) => `run-intent-${user?.id ?? 0}-${projectId}`, [user?.id]);

  const [runPlanId, setRunPlanId] = useState<number | null>(null);
  const [resultRun, setResultRun] = useState<TestRun | null>(null);
  const [form] = Form.useForm<RunFormValues>();
  const projectRef = useRef(currentProjectId);
  projectRef.current = currentProjectId;
  type Intent = { projectId: number; planId: number; environmentId: number | null; key: string };
  const [intent, setIntent] = useState<Intent | null>(null);
  useEffect(() => {
    setRunPlanId(null);
    setResultRun(null);
    form.resetFields();
    try { setIntent(currentProjectId == null ? null : JSON.parse(localStorage.getItem(storageKey(currentProjectId)) || 'null')); }
    catch { setIntent(null); }
  }, [currentProjectId, storageKey, form]);
  const saveIntent = (value: Intent) => {
    localStorage.setItem(storageKey(value.projectId), JSON.stringify(value));
    setIntent(value);
  };
  const lookup = async () => {
    if (!intent) return;
    try {
      const run = await testManagementApi.getRunByRequest(intent.projectId, intent.key);
      if (projectRef.current === intent.projectId) setResultRun(run);
    } catch (e) { if (projectRef.current === intent.projectId) message.warning(getErrorMessage(e, '尚未找到运行，可使用同一请求重试')); }
  };

  const plansQuery = useQuery({
    queryKey: ['test-plans', currentProjectId, 'exec-center'],
    queryFn: () => collectArrayPages((page) => testManagementApi.listPlans(currentProjectId!, { page, page_size: 100 }), 100),
    enabled: currentProjectId != null,
  });
  const envsQuery = useQuery({
    queryKey: ['project-environments', currentProjectId],
    queryFn: () => projectsApi.listEnvironments(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const environments: Environment[] = envsQuery.data?.items ?? [];

  const runMutation = useMutation({
    mutationFn: (submission: Intent) => testManagementApi.createRun(submission.planId, { environment_id: submission.environmentId, request_key: submission.key }),
    onSuccess: (run, submission) => {
      if (projectRef.current !== submission.projectId) return;
      message.success(run.status === 'RUNNING' ? '执行中，可稍后核对结果' : '已取得执行结果');
      setRunPlanId(null);
      setResultRun(run);
    },
    onError: (e, submission) => {
      if (projectRef.current === submission.projectId) message.warning(getErrorMessage(e, '提交结果待确认，请核对或使用相同请求重试'));
    },
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const plans = plansQuery.data ?? [];
  const activePlan = plans.find((p) => p.id === runPlanId) ?? null;
  const envName = (eid: number | null) =>
    eid == null ? '使用计划环境' : environments.find((e) => e.id === eid)?.display_name ?? `环境#${eid}`;

  const columns: TableColumnsType<TestPlan> = [
    { title: 'ID', dataIndex: 'id', width: 64 },
    { title: '名称', dataIndex: 'name', className: 'table-record-name' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => <StatusBadge value={v} color={v === 'ACTIVE' ? 'green' : 'default'} />,
    },
    { title: '执行模式', dataIndex: 'execution_mode', width: 100 },
    {
      title: '环境',
      dataIndex: 'environment_id',
      width: 130,
      render: (eid: number | null) => envName(eid),
    },
    {
      title: '操作',
      width: 110,
      render: (_, row) => (
        <Button
          type="primary"
          size="small"
          icon={<CaretRightOutlined />}
          disabled={row.status === 'DISABLED' || intent != null}
          onClick={() => {
            setRunPlanId(row.id);
            form.resetFields();
            form.setFieldsValue({ environment_id: row.environment_id ?? null });
          }}
        >
          执行
        </Button>
      ),
    },
  ];

  return (
    <PageContainer>
      <PageHeader title="执行中心" subtitle="选择一个测试计划并触发执行，完成后即可查看结果。" />

      {intent && <Space style={{ marginBottom: 16 }}>
        <Typography.Text>上次请求：计划 #{intent.planId}，环境 #{intent.environmentId ?? '计划默认'}（结果可核对）</Typography.Text>
        <Button onClick={() => void lookup()}>核对运行</Button>
        <Button disabled={runMutation.isPending} onClick={() => runMutation.mutate(intent)}>使用相同请求重试</Button>
        {resultRun && !['RUNNING', 'PENDING'].includes(resultRun.status) && <Button onClick={() => { localStorage.removeItem(storageKey(intent.projectId)); setIntent(null); setResultRun(null); }}>主动再次运行</Button>}
      </Space>}
      {plansQuery.isLoading ? (
        <LoadingState />
      ) : plansQuery.isError ? (
        /* 接口失败必须报错：否则 500 会提示「去测试计划页创建」，把服务端错误指向错误方向 */
        <ErrorState error={plansQuery.error} onRetry={plansQuery.refetch} />
      ) : plans.length === 0 ? (
        <EmptyState description="暂无测试计划，请先在「测试计划」页创建" />
      ) : (
        <Table rowKey="id" columns={columns} dataSource={plans} tableLayout="fixed" scroll={{ x: 710 }} pagination={false} size="middle" />
      )}

      {/* 执行参数弹窗 */}
      <Modal
        title={activePlan ? `执行计划：${activePlan.name}` : '执行计划'}
        open={runPlanId != null}
        onCancel={() => setRunPlanId(null)}
        onOk={async () => {
          const values = await form.validateFields();
          if (!activePlan || currentProjectId == null || projectRef.current !== currentProjectId) return;
          const submission = { projectId: currentProjectId, planId: activePlan.id, environmentId: values.environment_id ?? null, key: crypto.randomUUID() };
          saveIntent(submission);
          runMutation.mutate(submission);
        }}
        confirmLoading={runMutation.isPending}
        okText="执行"
        cancelText="取消"
        destroyOnHidden
        width={460}
      >
        <Typography.Text>项目 #{currentProjectId} · 计划 {activePlan?.name}</Typography.Text>
        <Form<RunFormValues> form={form} layout="vertical">
          <Form.Item name="environment_id" label="执行环境（覆盖计划环境；留空使用计划环境）">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="使用计划环境"
              options={environments.map((e) => ({ value: e.id!, label: e.display_name }))}
            />
          </Form.Item>
          <Typography.Text type="secondary">
            该计划含的套件下全部启用用例将依次执行（§32 同步执行）。
          </Typography.Text>
        </Form>
      </Modal>

      {/* 执行结果弹窗 */}
      <Modal
        title="执行结果"
        open={resultRun != null}
        onCancel={() => setResultRun(null)}
        footer={[
          <Button key="history" onClick={() => { setResultRun(null); navigate('/console/execution-history'); }}>
            查看执行历史
          </Button>,
          <Button key="close" type="primary" onClick={() => setResultRun(null)}>
            关闭
          </Button>,
        ]}
        width={560}
      >
        {resultRun && (
          <>
            <Space style={{ marginBottom: 12 }}>
              <StatusBadge
                value={resultRun.status}
                options={TEST_RUN_STATUS_OPTIONS}
                colors={TEST_RUN_STATUS_COLOR}
              />
              <Typography.Text type="secondary">执行 #{resultRun.id}</Typography.Text>
            </Space>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="计划ID">{resultRun.plan_id ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="环境ID">{resultRun.environment_id ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="开始">{fmtTimeSec(resultRun.started_at)}</Descriptions.Item>
              <Descriptions.Item label="结束">{fmtTimeSec(resultRun.finished_at)}</Descriptions.Item>
            </Descriptions>
            <Space style={{ marginTop: 16, width: '100%', justifyContent: 'space-around' }} wrap>
              <Statistic title="总数" value={resultRun.total} />
              <Statistic title="通过" value={resultRun.passed} valueStyle={{ color: token.colorSuccess }} />
              <Statistic title="失败" value={resultRun.failed} valueStyle={{ color: token.colorError }} />
              <Statistic title="跳过" value={resultRun.skipped} />
              <Statistic title="错误" value={resultRun.error} valueStyle={{ color: token.colorWarning }} />
            </Space>
          </>
        )}
      </Modal>
    </PageContainer>
  );
}
