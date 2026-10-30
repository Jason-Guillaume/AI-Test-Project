import { collectArrayPages } from '@/shared/api/pagination';
// 测试计划页（用户视角）。
// 单页表格：计划 CRUD + 每行「管理套件」抽屉（计划↔套件关联的增删）。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写 = 项目成员（member+）；跨项目越权 404，前端不展示。
// 返回形态：listPlans / listPlanSuites / listSuites 均返回裸数组；environment_id 关联 platform 级 Environment（按数字 id）。
import { useState } from 'react';
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { projectsApi } from '@/features/projects/api/projects';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { TEST_EXECUTION_MODE_OPTIONS, TEST_PLAN_STATUS_OPTIONS } from './constants';
import type { Environment } from '@/features/environments/contracts';
import type { TestPlan, TestPlanCreate, TestPlanStatus, TestPlanSuiteResponse, TestPlanUpdate, TestSuite } from '@/features/test-management/contracts';


interface PlanFormValues {
  name: string;
  status: TestPlanStatus;
  execution_mode: 'MANUAL' | 'SCHEDULED' | 'CI';
  environment_id?: number | null;
  description?: string;
}

const PLAN_STATUS_COLOR: Record<string, string> = {
  DRAFT: 'blue',
  ACTIVE: 'green',
  DISABLED: 'default',
};

/** 测试计划页。 */
export function ConsoleTestPlansPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<TestPlan | null>(null);
  const [planDrawerId, setPlanDrawerId] = useState<number | null>(null);
  const [addSuiteId, setAddSuiteId] = useState<number | null>(null);
  const [addSuiteSort, setAddSuiteSort] = useState(0);
  const [form] = Form.useForm<PlanFormValues>();

  const plansQuery = useQuery({
    queryKey: ['test-plans', currentProjectId],
    queryFn: () => collectArrayPages((page) => testManagementApi.listPlans(currentProjectId!, { page, page_size: 100 }), 100),
    enabled: currentProjectId != null,
  });
  const envsQuery = useQuery({
    queryKey: ['project-environments', currentProjectId],
    queryFn: () => projectsApi.listEnvironments(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const environments: Environment[] = envsQuery.data?.items ?? [];
  const envName = (eid: number | null) =>
    eid == null ? '-' : environments.find((e) => e.id === eid)?.display_name ?? `环境#${eid}`;

  const createMutation = useMutation({
    mutationFn: (body: TestPlanCreate) =>
      testManagementApi.createPlan(currentProjectId!, body),
    onSuccess: () => {
      message.success('测试计划已创建');
      queryClient.invalidateQueries({ queryKey: ['test-plans'] });
      setModalOpen(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: TestPlanUpdate }) =>
      testManagementApi.updatePlan(id, body),
    onSuccess: () => {
      message.success('测试计划已更新');
      queryClient.invalidateQueries({ queryKey: ['test-plans'] });
      setModalOpen(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });
  const removeMutation = useMutation({
    mutationFn: (id: number) => testManagementApi.removePlan(id),
    onSuccess: () => {
      message.success('测试计划已删除');
      queryClient.invalidateQueries({ queryKey: ['test-plans'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ status: 'DRAFT', execution_mode: 'MANUAL', environment_id: null });
    setModalOpen(true);
  };
  const openEdit = (plan: TestPlan) => {
    setEditing(plan);
    form.resetFields();
    form.setFieldsValue({
      name: plan.name,
      status: plan.status as TestPlanStatus,
      execution_mode: plan.execution_mode as PlanFormValues['execution_mode'],
      environment_id: plan.environment_id,
      description: plan.description ?? undefined,
    });
    setModalOpen(true);
  };
  const submit = async () => {
    const values = await form.validateFields();
    const body = {
      name: values.name,
      status: values.status,
      execution_mode: values.execution_mode,
      environment_id: values.environment_id ?? null,
      description: values.description || null,
    };
    if (editing) {
      await updateMutation.mutateAsync({ id: editing.id, body });
    } else {
      await createMutation.mutateAsync(body);
    }
  };

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const plans = plansQuery.data ?? [];

  const columns: TableColumnsType<TestPlan> = [
    { title: 'ID', dataIndex: 'id', width: 64 },
    { title: '名称', dataIndex: 'name' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => <Tag color={PLAN_STATUS_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '执行模式', dataIndex: 'execution_mode', width: 100 },
    {
      title: '环境',
      dataIndex: 'environment_id',
      width: 130,
      render: (eid: number | null) => envName(eid),
    },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v: string | null) => v || '-' },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v: string) => v?.slice(0, 16).replace('T', ' '),
    },
    {
      title: '操作',
      width: 240,
      render: (_, row) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            编辑
          </Button>
          <Button size="small" onClick={() => setPlanDrawerId(row.id)}>
            管理套件
          </Button>
          <Popconfirm title="确认删除该计划？" onConfirm={() => removeMutation.mutate(row.id)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Typography.Title level={5} style={{ margin: 0 }}>
          测试计划
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建计划
        </Button>
      </Space>

      {plansQuery.isLoading ? (
        <LoadingState />
      ) : plansQuery.isError ? (
        <ErrorState error={plansQuery.error} onRetry={plansQuery.refetch} />
      ) : plans.length === 0 ? (
        <EmptyState description="暂无测试计划" />
      ) : (
        <Table rowKey="id" columns={columns} dataSource={plans} pagination={false} size="middle" />
      )}

      <Modal
        title={editing ? '编辑测试计划' : '新建测试计划'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submit}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form<PlanFormValues> form={form} layout="vertical" initialValues={{ status: 'DRAFT', execution_mode: 'MANUAL' }}>
          <Form.Item name="name" label="计划名称" rules={[{ required: true, message: '请输入计划名称' }]}>
            <Input maxLength={200} placeholder="如 登录接口回归计划" />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={TEST_PLAN_STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item name="execution_mode" label="执行模式">
            <Select options={TEST_EXECUTION_MODE_OPTIONS} />
          </Form.Item>
          <Form.Item name="environment_id" label="执行环境">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="使用计划环境"
              options={environments.map((e) => ({ value: e.id!, label: e.display_name }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      <PlanSuitesDrawer
        planId={planDrawerId}
        onClose={() => setPlanDrawerId(null)}
        addSuiteId={addSuiteId}
        setAddSuiteId={setAddSuiteId}
        addSuiteSort={addSuiteSort}
        setAddSuiteSort={setAddSuiteSort}
      />
    </PageContainer>
  );
}

/** 计划↔套件关联管理抽屉。 */
function PlanSuitesDrawer({
  planId,
  onClose,
  addSuiteId,
  setAddSuiteId,
  addSuiteSort,
  setAddSuiteSort,
}: {
  planId: number | null;
  onClose: () => void;
  addSuiteId: number | null;
  setAddSuiteId: (v: number | null) => void;
  addSuiteSort: number;
  setAddSuiteSort: (v: number) => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();

  const planSuitesQuery = useQuery({
    queryKey: ['plan-suites', planId],
    queryFn: () => testManagementApi.listPlanSuites(planId!),
    enabled: planId != null,
  });
  const allSuitesQuery = useQuery({
    queryKey: ['test-suites', currentProjectId, 'for-plan'],
    queryFn: () => collectArrayPages((page) => testManagementApi.listSuites(currentProjectId!, { page, page_size: 100 }), 100),
    enabled: planId != null && currentProjectId != null,
  });

  const addMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { suite_id: number; sort: number } }) =>
      testManagementApi.addPlanSuite(id, body),
    onSuccess: () => {
      message.success('套件已加入计划');
      queryClient.invalidateQueries({ queryKey: ['plan-suites', planId] });
      setAddSuiteId(null);
      setAddSuiteSort(0);
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });
  const removeMutation = useMutation({
    mutationFn: (planSuiteId: number) => testManagementApi.removePlanSuite(planSuiteId),
    onSuccess: () => {
      message.success('套件已移除');
      queryClient.invalidateQueries({ queryKey: ['plan-suites', planId] });
    },
    onError: (e) => message.error(getErrorMessage(e, '移除失败')),
  });

  const planSuites = planSuitesQuery.data ?? [];
  const allSuites: TestSuite[] = allSuitesQuery.data ?? [];
  const suiteName = (sid: number) =>
    allSuites.find((s) => s.id === sid)?.name ?? `套件#${sid}`;

  const columns: TableColumnsType<TestPlanSuiteResponse> = [
    { title: '套件ID', dataIndex: 'suite_id', width: 80 },
    { title: '套件名称', dataIndex: 'suite_id', render: (sid: number) => suiteName(sid) },
    { title: '排序', dataIndex: 'sort', width: 80 },
    {
      title: '操作',
      width: 100,
      render: (_, row) => (
        <Popconfirm title="确认从计划移除该套件？" onConfirm={() => removeMutation.mutate(row.id)}>
          <Button size="small" danger icon={<DeleteOutlined />}>
            移除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Drawer title="管理计划套件" width={640} open={planId != null} onClose={onClose} destroyOnClose>
      <div className="member-add-row">
        <Select
          className="member-add-row__select"
          showSearch
          optionFilterProp="label"
          placeholder="选择要加入的套件"
          value={addSuiteId ?? undefined}
          onChange={setAddSuiteId}
          options={allSuites.map((s) => ({ value: s.id, label: s.name }))}
        />
        <InputNumber
          min={0}
          value={addSuiteSort}
          onChange={(v) => setAddSuiteSort(v ?? 0)}
          placeholder="排序"
          style={{ width: 90 }}
        />
        <Button
          type="primary"
          disabled={addSuiteId == null}
          onClick={() =>
            addMutation.mutate({ id: planId!, body: { suite_id: addSuiteId!, sort: addSuiteSort } })
          }
        >
          添加
        </Button>
      </div>
      <Table
        rowKey="id"
        size="small"
        columns={columns}
        scroll={{ x: 'max-content' }}
        dataSource={planSuites}
        pagination={false}
        loading={planSuitesQuery.isLoading}
      />
    </Drawer>
  );
}
