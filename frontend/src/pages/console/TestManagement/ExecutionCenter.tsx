import { collectArrayPages } from '@/shared/api/pagination';
// 执行中心页（用户视角）。
// 列出项目内测试计划，逐行「执行」触发同步执行（POST /test-plans/{id}/runs），
// 返回完成的 TestRun，弹窗展示结果汇总并支持跳转执行历史。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写/执行 = 项目成员（member+）；越权 404，前端不展示。
// §32：执行同步返回完成态 TestRun（status/total/passed/failed/skipped/error）。
import { useState } from 'react';
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
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { fmtTimeSec } from '@/shared/lib/format';
import { TEST_RUN_STATUS_COLOR } from '@/features/test-management/status';
import { TEST_RUN_STATUS_OPTIONS } from './constants';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
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

  const [runPlanId, setRunPlanId] = useState<number | null>(null);
  const [resultRun, setResultRun] = useState<TestRun | null>(null);
  const [form] = Form.useForm<RunFormValues>();

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
    mutationFn: ({ planId, body }: { planId: number; body: RunFormValues }) =>
      testManagementApi.createRun(planId, { environment_id: body.environment_id ?? null }),
    onSuccess: (run) => {
      message.success('执行完成');
      setRunPlanId(null);
      setResultRun(run);
    },
    onError: (e) => message.error(getErrorMessage(e, '执行失败')),
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
    { title: '名称', dataIndex: 'name' },
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
          disabled={row.status === 'DISABLED'}
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
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Typography.Title level={5} style={{ margin: 0 }}>
          执行中心
        </Typography.Title>
        <Typography.Text type="secondary">选择一个测试计划并触发执行；执行同步返回结果。</Typography.Text>
      </Space>

      {plansQuery.isLoading ? (
        <LoadingState />
      ) : plansQuery.isError ? (
        /* 接口失败必须报错：否则 500 会提示「去测试计划页创建」，把服务端错误指向错误方向 */
        <ErrorState error={plansQuery.error} onRetry={plansQuery.refetch} />
      ) : plans.length === 0 ? (
        <EmptyState description="暂无测试计划，请先在「测试计划」页创建" />
      ) : (
        <Table rowKey="id" columns={columns} dataSource={plans} pagination={false} size="middle" />
      )}

      {/* 执行参数弹窗 */}
      <Modal
        title={activePlan ? `执行计划：${activePlan.name}` : '执行计划'}
        open={runPlanId != null}
        onCancel={() => setRunPlanId(null)}
        onOk={async () => {
          const values = await form.validateFields().catch(() => ({}) as RunFormValues);
          runMutation.mutate({ planId: runPlanId!, body: values });
        }}
        confirmLoading={runMutation.isPending}
        okText="执行"
        cancelText="取消"
        destroyOnClose
        width={460}
      >
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
