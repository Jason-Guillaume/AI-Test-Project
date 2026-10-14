// 测试资产页（用户视角）。
// 左右布局：左侧 策略→测试点→用例 三级树；右侧选中用例的聚合详情编辑器
// （基本信息 + 前置条件 / 测试数据 / 步骤 / 断言 四 Tab，子实体就地 CRUD）。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写 = 项目成员（member+）；跨项目越权 404，前端不展示。
// §26：用例编辑携带 revision 乐观锁；并发冲突返回 409，前端提示「当前测试用例已被其他用户修改」并重载详情。
// 返回形态：listStrategies/listPoints/listCases/getCaseDetail 及子实体列表均为裸数组/对象（无分页信封）。
import { useMemo, useState } from 'react';
import {
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tree,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { testManagementApi } from '@/api/testManagement';
import { getErrorMessage } from '@/api/client';
import { EmptyState, LoadingState, PageContainer } from '@/components/PageState';
import { useConsoleScope } from '@/hooks/useConsoleScope';
import {
  TEST_ASSERTION_TYPE_OPTIONS,
  TEST_CASE_TYPE_OPTIONS,
  TEST_DATA_SOURCE_OPTIONS,
  TEST_OPERATOR_OPTIONS,
  TEST_PRECONDITION_TYPE_OPTIONS,
  TEST_PRIORITY_OPTIONS,
  TEST_STATUS_OPTIONS,
  TEST_STEP_TYPE_OPTIONS,
  TEST_STRATEGY_CATEGORY_OPTIONS,
  TEST_TARGET_TYPE_OPTIONS,
  TEST_VALUE_TYPE_OPTIONS,
} from './constants';
import type {
  TestAssertion,
  TestAssertionCreate,
  TestAssertionUpdate,
  TestCaseCreate,
  TestCaseData,
  TestCaseDataCreate,
  TestCaseDataUpdate,
  TestCasePrecondition,
  TestCasePreconditionCreate,
  TestCasePreconditionUpdate,
  TestCaseUpdate,
  TestPointCreate,
  TestStep,
  TestStepCreate,
  TestStepUpdate,
  TestStrategyCreate,
} from '@/types';

const STATUS_COLOR: Record<string, string> = {
  DRAFT: 'blue',
  ACTIVE: 'green',
  DEPRECATED: 'default',
};

/** 左侧树节点（结构兼容 antd Tree 的 DataNode，后者字段全可选）。 */
interface TreeNode {
  key: string;
  title: string;
  children?: TreeNode[];
  isLeaf?: boolean;
}

/** 测试资产页。 */
export function ConsoleTestAssetPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();

  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(null);
  const [selectedPointId, setSelectedPointId] = useState<number | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<number | null>(null);
  const [selectedKey, setSelectedKey] = useState<string>();

  const [strategyOpen, setStrategyOpen] = useState(false);
  const [pointOpen, setPointOpen] = useState(false);
  const [caseOpen, setCaseOpen] = useState(false);
  const [caseEditOpen, setCaseEditOpen] = useState(false);
  const [strategyForm] = Form.useForm<StrategyFormValues>();
  const [pointForm] = Form.useForm<PointFormValues>();
  const [caseForm] = Form.useForm<CaseFormValues>();
  const [caseEditForm] = Form.useForm<CaseFormValues>();

  const strategiesQuery = useQuery({
    queryKey: ['test-strategies', currentProjectId],
    queryFn: () => testManagementApi.listStrategies(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const pointsQuery = useQuery({
    queryKey: ['test-points', currentProjectId],
    queryFn: () => testManagementApi.listPoints(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const casesQuery = useQuery({
    queryKey: ['test-cases', currentProjectId],
    queryFn: () => testManagementApi.listCases(currentProjectId!),
    enabled: currentProjectId != null,
  });
  const detailQuery = useQuery({
    queryKey: ['test-case-detail', selectedCaseId],
    queryFn: () => testManagementApi.getCaseDetail(selectedCaseId!),
    enabled: selectedCaseId != null,
  });

  const strategies = strategiesQuery.data ?? [];
  const points = pointsQuery.data ?? [];
  const cases = casesQuery.data ?? [];
  const detail = detailQuery.data;

  const treeData = useMemo<TreeNode[]>(() => {
    const buildPoints = (parentId: number | null) =>
      points
        .filter((p) => (p.strategy_id ?? null) === parentId)
        .map((p) => ({
          key: `p:${p.id}`,
          title: p.name,
          children: cases
            .filter((c) => c.test_point_id === p.id)
            .map((c) => ({ key: `c:${c.id}`, title: c.name, isLeaf: true })),
        }));
    const nodes: TreeNode[] = strategies.map((s) => ({
      key: `s:${s.id}`,
      title: s.name,
      children: buildPoints(s.id),
    }));
    const ungrouped = buildPoints(null);
    if (ungrouped.length > 0) {
      nodes.push({ key: 's:0', title: '未归属策略', children: ungrouped });
    }
    return nodes;
  }, [strategies, points, cases]);

  const onSelect = (keys: React.Key[]) => {
    const key = keys[0] as string | undefined;
    if (!key) return;
    setSelectedKey(key);
    const [type, idStr] = key.split(':');
    const id = Number(idStr);
    if (type === 's') {
      setSelectedStrategyId(id || null);
      setSelectedPointId(null);
      setSelectedCaseId(null);
    } else if (type === 'p') {
      setSelectedPointId(id);
      const p = points.find((x) => x.id === id);
      setSelectedStrategyId(p?.strategy_id ?? null);
      setSelectedCaseId(null);
    } else if (type === 'c') {
      setSelectedCaseId(id);
      const c = cases.find((x) => x.id === id);
      const pid = c?.test_point_id ?? null;
      setSelectedPointId(pid);
      const p = points.find((x) => x.id === pid);
      setSelectedStrategyId(p?.strategy_id ?? null);
    }
  };

  // ---- 创建策略 / 点 / 用例 ----
  const createStrategyMut = useMutation({
    mutationFn: (body: TestStrategyCreate) => testManagementApi.createStrategy(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('测试策略已创建');
      queryClient.invalidateQueries({ queryKey: ['test-strategies'] });
      setStrategyOpen(false);
      setSelectedStrategyId(data.id);
      setSelectedKey(`s:${data.id}`);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });
  const createPointMut = useMutation({
    mutationFn: (body: TestPointCreate) => testManagementApi.createPoint(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('测试点已创建');
      queryClient.invalidateQueries({ queryKey: ['test-points'] });
      setPointOpen(false);
      setSelectedPointId(data.id);
      setSelectedKey(`p:${data.id}`);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });
  const createCaseMut = useMutation({
    mutationFn: (body: TestCaseCreate) => testManagementApi.createCase(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('测试用例已创建');
      queryClient.invalidateQueries({ queryKey: ['test-cases'] });
      setCaseOpen(false);
      setSelectedCaseId(data.id);
      setSelectedKey(`c:${data.id}`);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  // ---- 编辑用例基本信息（§26 乐观锁）----
  const updateCaseMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: TestCaseUpdate }) =>
      testManagementApi.updateCase(id, body),
    onSuccess: () => {
      message.success('用例已更新');
      queryClient.invalidateQueries({ queryKey: ['test-cases'] });
      queryClient.invalidateQueries({ queryKey: ['test-case-detail', selectedCaseId] });
      setCaseEditOpen(false);
    },
    onError: (e) => {
      // §26：并发冲突 → 后端返回 409「当前测试用例已被其他用户修改，请刷新后重试」。
      message.error(getErrorMessage(e, '更新失败'));
      queryClient.invalidateQueries({ queryKey: ['test-case-detail', selectedCaseId] });
    },
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  const openCaseEdit = () => {
    if (!detail) return;
    caseEditForm.setFieldsValue({
      name: detail.name,
      priority: detail.priority as CaseFormValues['priority'],
      case_type: detail.case_type as CaseFormValues['case_type'],
      target_type: detail.target_type as CaseFormValues['target_type'],
      status: detail.status as CaseFormValues['status'],
      enabled: detail.enabled,
      description: detail.description ?? undefined,
    });
    setCaseEditOpen(true);
  };

  const submitCaseEdit = async () => {
    if (!detail) return;
    const values = await caseEditForm.validateFields();
    // §26：携带当前 revision；不匹配时后端返回 409。
    await updateCaseMut.mutateAsync({
      id: detail.id,
      body: {
        name: values.name,
        priority: values.priority,
        case_type: values.case_type,
        target_type: values.target_type,
        status: values.status,
        enabled: values.enabled,
        description: values.description || null,
        revision: detail.revision,
      },
    });
  };

  return (
    <PageContainer>
      <Row gutter={16}>
        {/* 左侧树 */}
        <Col flex="300px">
          <div
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 8,
              height: 'calc(100vh - 200px)',
              minHeight: 400,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }} wrap>
              <span style={{ fontWeight: 600 }}>策略 / 点 / 用例</span>
              <Button size="small" icon={<PlusOutlined />} onClick={() => { strategyForm.resetFields(); strategyForm.setFieldsValue({ category: 'FUNCTIONAL', enabled: true }); setStrategyOpen(true); }}>
                新建策略
              </Button>
            </Space>
            <Space size={4} style={{ marginBottom: 8 }}>
              <Button size="small" type="primary" disabled={selectedStrategyId == null} onClick={() => { pointForm.resetFields(); pointForm.setFieldsValue({ priority: 'P1', target_type: 'API', status: 'DRAFT' }); setPointOpen(true); }}>
                新建测试点
              </Button>
              <Button size="small" disabled={selectedPointId == null} onClick={() => { caseForm.resetFields(); caseForm.setFieldsValue({ priority: 'P1', case_type: 'FUNCTIONAL', target_type: 'API', status: 'DRAFT', enabled: true }); setCaseOpen(true); }}>
                新建用例
              </Button>
            </Space>
            <div style={{ flex: 1, overflow: 'auto' }}>
              {strategiesQuery.isLoading || pointsQuery.isLoading || casesQuery.isLoading ? (
                <LoadingState />
              ) : treeData.length === 0 ? (
                <EmptyState description="暂无策略，请新建" />
              ) : (
                <Tree
                  treeData={treeData}
                  selectedKeys={selectedKey ? [selectedKey] : []}
                  onSelect={onSelect}
                  blockNode
                />
              )}
            </div>
          </div>
        </Col>

        {/* 右侧用例详情编辑器 */}
        <Col flex="auto">
          <div
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 16,
              height: 'calc(100vh - 200px)',
              minHeight: 400,
              overflow: 'auto',
            }}
          >
            {selectedCaseId == null ? (
              <EmptyState description="请在左侧选择一个测试用例，或新建一个用例" />
            ) : detailQuery.isLoading ? (
              <LoadingState />
            ) : !detail ? (
              <EmptyState description="用例不存在或无访问权限" />
            ) : (
              <>
                <Card
                  size="small"
                  title={<Space><Typography.Text strong>{detail.name}</Typography.Text><Tag>rev {detail.revision}</Tag></Space>}
                  extra={<Button size="small" icon={<EditOutlined />} onClick={openCaseEdit}>编辑用例</Button>}
                  style={{ marginBottom: 12 }}
                >
                  <Descriptions size="small" column={3}>
                    <Descriptions.Item label="优先级"><Tag>{detail.priority}</Tag></Descriptions.Item>
                    <Descriptions.Item label="类型">{detail.case_type}</Descriptions.Item>
                    <Descriptions.Item label="被测对象">{detail.target_type}</Descriptions.Item>
                    <Descriptions.Item label="状态"><Tag color={STATUS_COLOR[detail.status] ?? 'default'}>{detail.status}</Tag></Descriptions.Item>
                    <Descriptions.Item label="启用">{detail.enabled ? <Tag color="green">是</Tag> : <Tag>否</Tag>}</Descriptions.Item>
                    <Descriptions.Item label="测试点">{detail.test_point_id ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="描述" span={3}>{detail.description || '-'}</Descriptions.Item>
                  </Descriptions>
                </Card>

                <Tabs
                  items={[
                    { key: 'preconditions', label: '前置条件', children: <PreconditionsTab caseId={detail.id} items={detail.preconditions} /> },
                    { key: 'data', label: '测试数据', children: <DataTab caseId={detail.id} items={detail.test_data} /> },
                    { key: 'steps', label: '步骤', children: <StepsTab caseId={detail.id} items={detail.steps} /> },
                    { key: 'assertions', label: '断言', children: <AssertionsTab caseId={detail.id} items={detail.assertions} /> },
                  ]}
                />
              </>
            )}
          </div>
        </Col>
      </Row>

      {/* 新建策略 */}
      <Modal
        title="新建测试策略"
        open={strategyOpen}
        onCancel={() => setStrategyOpen(false)}
        onOk={async () => {
          const v = await strategyForm.validateFields();
          await createStrategyMut.mutateAsync({
            name: v.name,
            category: v.category,
            enabled: v.enabled,
            description: v.description || null,
          });
        }}
        confirmLoading={createStrategyMut.isPending}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<StrategyFormValues> form={strategyForm} layout="vertical" initialValues={{ category: 'FUNCTIONAL', enabled: true }}>
          <Form.Item name="name" label="策略名称" rules={[{ required: true, message: '请输入策略名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="category" label="类别">
            <Select options={TEST_STRATEGY_CATEGORY_OPTIONS} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建测试点 */}
      <Modal
        title="新建测试点"
        open={pointOpen}
        onCancel={() => setPointOpen(false)}
        onOk={async () => {
          const v = await pointForm.validateFields();
          await createPointMut.mutateAsync({
            name: v.name,
            priority: v.priority,
            target_type: v.target_type,
            status: v.status,
            strategy_id: selectedStrategyId || null,
            description: v.description || null,
          });
        }}
        confirmLoading={createPointMut.isPending}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<PointFormValues> form={pointForm} layout="vertical" initialValues={{ priority: 'P1', target_type: 'API', status: 'DRAFT' }}>
          <Form.Item name="name" label="测试点名称" rules={[{ required: true, message: '请输入测试点名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select options={TEST_PRIORITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="target_type" label="被测对象类型">
            <Select options={TEST_TARGET_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={TEST_STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建用例 */}
      <Modal
        title="新建测试用例"
        open={caseOpen}
        onCancel={() => setCaseOpen(false)}
        onOk={async () => {
          const v = await caseForm.validateFields();
          await createCaseMut.mutateAsync({
            name: v.name,
            priority: v.priority,
            case_type: v.case_type,
            target_type: v.target_type,
            status: v.status,
            enabled: v.enabled,
            test_point_id: selectedPointId,
            description: v.description || null,
          });
        }}
        confirmLoading={createCaseMut.isPending}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<CaseFormValues> form={caseForm} layout="vertical" initialValues={{ priority: 'P1', case_type: 'FUNCTIONAL', target_type: 'API', status: 'DRAFT', enabled: true }}>
          <Form.Item name="name" label="用例名称" rules={[{ required: true, message: '请输入用例名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select options={TEST_PRIORITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="case_type" label="用例类型">
            <Select options={TEST_CASE_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="target_type" label="被测对象类型">
            <Select options={TEST_TARGET_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={TEST_STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑用例基本信息（乐观锁）*/}
      <Modal
        title="编辑测试用例"
        open={caseEditOpen}
        onCancel={() => setCaseEditOpen(false)}
        onOk={submitCaseEdit}
        confirmLoading={updateCaseMut.isPending}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<CaseFormValues> form={caseEditForm} layout="vertical">
          <Form.Item name="name" label="用例名称" rules={[{ required: true, message: '请输入用例名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select options={TEST_PRIORITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="case_type" label="用例类型">
            <Select options={TEST_CASE_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="target_type" label="被测对象类型">
            <Select options={TEST_TARGET_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={TEST_STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}

// ---- 表单值类型 ----
interface StrategyFormValues {
  name: string;
  category: 'FUNCTIONAL' | 'PARAMETER' | 'BOUNDARY' | 'AUTH' | 'PERMISSION' | 'BUSINESS' | 'EXCEPTION' | 'IDEMPOTENCY' | 'SECURITY' | 'DATA_CONSISTENCY';
  enabled: boolean;
  description?: string;
}
interface PointFormValues {
  name: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  target_type: 'API' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION';
  status: 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
  description?: string;
}
interface CaseFormValues {
  name: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  case_type: 'FUNCTIONAL' | 'BUSINESS' | 'NEGATIVE' | 'BOUNDARY' | 'PERMISSION' | 'SECURITY' | 'EXCEPTION';
  target_type: 'API' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION';
  status: 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
  enabled: boolean;
  description?: string;
}

// ============================================================ 前置条件 Tab

interface PreconditionFormValues {
  type: 'VARIABLE' | 'TEXT' | 'FIXTURE' | 'API' | 'BUSINESS_ACTION' | 'BUSINESS_FLOW';
  target?: string;
  operator: 'EQ' | 'NE' | 'GT' | 'GE' | 'LT' | 'LE' | 'IN' | 'CONTAINS' | 'EXISTS' | 'NOT_EXISTS';
  expected_value?: string;
  description?: string;
  sort: number;
}

function PreconditionsTab({ caseId, items }: { caseId: number; items: TestCasePrecondition[] }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<TestCasePrecondition | null>(null);
  const [form] = Form.useForm<PreconditionFormValues>();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['test-case-detail', caseId] });

  const createMut = useMutation({
    mutationFn: (body: TestCasePreconditionCreate) => testManagementApi.createPrecondition(caseId, body),
    onSuccess: () => { message.success('前置条件已新增'); invalidate(); setOpen(false); },
    onError: (e) => message.error(getErrorMessage(e, '新增失败')),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: TestCasePreconditionUpdate }) => testManagementApi.updatePrecondition(id, body),
    onSuccess: () => { message.success('前置条件已更新'); invalidate(); setOpen(false); },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });
  const removeMut = useMutation({
    mutationFn: (id: number) => testManagementApi.removePrecondition(id),
    onSuccess: () => { message.success('前置条件已删除'); invalidate(); },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const openCreate = () => { setEditing(null); form.resetFields(); form.setFieldsValue({ type: 'VARIABLE', operator: 'EQ', sort: 0 }); setOpen(true); };
  const openEdit = (row: TestCasePrecondition) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({ type: row.type as PreconditionFormValues['type'], target: row.target ?? undefined, operator: row.operator as PreconditionFormValues['operator'], expected_value: row.expected_value ?? undefined, description: row.description ?? undefined, sort: row.sort });
    setOpen(true);
  };
  const submit = async () => {
    const v = await form.validateFields();
    const body = { type: v.type, target: v.target ?? null, operator: v.operator, expected_value: v.expected_value ?? null, description: v.description ?? null, sort: v.sort };
    if (editing) await updateMut.mutateAsync({ id: editing.id, body });
    else await createMut.mutateAsync(body);
  };

  const columns: TableColumnsType<TestCasePrecondition> = [
    { title: '类型', dataIndex: 'type', width: 120 },
    { title: '目标', dataIndex: 'target', ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: '操作符', dataIndex: 'operator', width: 90 },
    { title: '期望值', dataIndex: 'expected_value', ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: '说明', dataIndex: 'description', ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: '排序', dataIndex: 'sort', width: 60 },
    {
      title: '操作', width: 120,
      render: (_, row) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => removeMut.mutate(row.id)}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Space style={{ marginBottom: 8 }}><Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增前置条件</Button></Space>
      <Table rowKey="id" size="small" columns={columns} dataSource={items} pagination={false} />
      <Modal title={editing ? '编辑前置条件' : '新增前置条件'} open={open} onCancel={() => setOpen(false)} onOk={submit} confirmLoading={createMut.isPending || updateMut.isPending} okText="保存" cancelText="取消" destroyOnClose width={480}>
        <Form<PreconditionFormValues> form={form} layout="vertical" initialValues={{ type: 'VARIABLE', operator: 'EQ', sort: 0 }}>
          <Form.Item name="type" label="类型"><Select options={TEST_PRECONDITION_TYPE_OPTIONS} /></Form.Item>
          <Form.Item name="target" label="目标"><Input maxLength={200} /></Form.Item>
          <Form.Item name="operator" label="操作符"><Select options={TEST_OPERATOR_OPTIONS} /></Form.Item>
          <Form.Item name="expected_value" label="期望值"><Input /></Form.Item>
          <Form.Item name="description" label="说明"><Input maxLength={500} /></Form.Item>
          <Form.Item name="sort" label="排序"><InputNumber min={0} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ============================================================ 测试数据 Tab

interface DataFormValues {
  name: string;
  value_type: 'STRING' | 'INTEGER' | 'NUMBER' | 'BOOLEAN' | 'OBJECT' | 'ARRAY';
  value?: string;
  source_type: 'STATIC' | 'ENVIRONMENT' | 'VARIABLE' | 'RUNTIME' | 'FAKER' | 'FIXTURE';
  required: boolean;
  description?: string;
  sort: number;
}

function DataTab({ caseId, items }: { caseId: number; items: TestCaseData[] }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<TestCaseData | null>(null);
  const [form] = Form.useForm<DataFormValues>();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['test-case-detail', caseId] });

  const createMut = useMutation({
    mutationFn: (body: TestCaseDataCreate) => testManagementApi.createData(caseId, body),
    onSuccess: () => { message.success('测试数据已新增'); invalidate(); setOpen(false); },
    onError: (e) => message.error(getErrorMessage(e, '新增失败')), // 同名 → 409，展示后端消息
  });
  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: TestCaseDataUpdate }) => testManagementApi.updateData(id, body),
    onSuccess: () => { message.success('测试数据已更新'); invalidate(); setOpen(false); },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });
  const removeMut = useMutation({
    mutationFn: (id: number) => testManagementApi.removeData(id),
    onSuccess: () => { message.success('测试数据已删除'); invalidate(); },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const openCreate = () => { setEditing(null); form.resetFields(); form.setFieldsValue({ value_type: 'STRING', source_type: 'STATIC', required: false, sort: 0 }); setOpen(true); };
  const openEdit = (row: TestCaseData) => {
    setEditing(row);
    form.resetFields();
    // 编辑模式不提供 name（TestCaseDataUpdate 无 name 字段）。
    form.setFieldsValue({ name: row.name, value_type: row.value_type as DataFormValues['value_type'], value: row.value ?? undefined, source_type: row.source_type as DataFormValues['source_type'], required: row.required, description: row.description ?? undefined, sort: row.sort });
    setOpen(true);
  };
  const submit = async () => {
    const v = await form.validateFields();
    if (editing) {
      // 不传 name（不可改）。
      await updateMut.mutateAsync({ id: editing.id, body: { value_type: v.value_type, value: v.value ?? null, source_type: v.source_type, required: v.required, description: v.description ?? null, sort: v.sort } });
    } else {
      await createMut.mutateAsync({ name: v.name, value_type: v.value_type, value: v.value ?? null, source_type: v.source_type, required: v.required, description: v.description ?? null, sort: v.sort });
    }
  };

  const columns: TableColumnsType<TestCaseData> = [
    { title: '名称', dataIndex: 'name' },
    { title: '值类型', dataIndex: 'value_type', width: 100 },
    { title: '值', dataIndex: 'value', ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: '来源', dataIndex: 'source_type', width: 110 },
    { title: '必需', dataIndex: 'required', width: 70, render: (v: boolean) => (v ? <Tag color="green">是</Tag> : <Tag>否</Tag>) },
    { title: '排序', dataIndex: 'sort', width: 60 },
    {
      title: '操作', width: 120,
      render: (_, row) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => removeMut.mutate(row.id)}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Space style={{ marginBottom: 8 }}><Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增测试数据</Button></Space>
      <Table rowKey="id" size="small" columns={columns} dataSource={items} pagination={false} />
      <Modal title={editing ? '编辑测试数据' : '新增测试数据'} open={open} onCancel={() => setOpen(false)} onOk={submit} confirmLoading={createMut.isPending || updateMut.isPending} okText="保存" cancelText="取消" destroyOnClose width={480}>
        <Form<DataFormValues> form={form} layout="vertical" initialValues={{ value_type: 'STRING', source_type: 'STATIC', required: false, sort: 0 }}>
          <Form.Item name="name" label="数据项名" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={100} disabled={editing != null} />
          </Form.Item>
          <Form.Item name="value_type" label="值类型"><Select options={TEST_VALUE_TYPE_OPTIONS} /></Form.Item>
          <Form.Item name="value" label="值"><Input /></Form.Item>
          <Form.Item name="source_type" label="来源"><Select options={TEST_DATA_SOURCE_OPTIONS} /></Form.Item>
          <Form.Item name="required" label="必需" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="description" label="说明"><Input maxLength={500} /></Form.Item>
          <Form.Item name="sort" label="排序"><InputNumber min={0} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ============================================================ 步骤 Tab

interface StepFormValues {
  name: string;
  step_type: 'SETUP' | 'ACTION' | 'ASSERT' | 'CLEANUP';
  target_type?: 'API' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION';
  target_id?: number;
  sort: number;
}

function StepsTab({ caseId, items }: { caseId: number; items: TestStep[] }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<TestStep | null>(null);
  const [form] = Form.useForm<StepFormValues>();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['test-case-detail', caseId] });

  const createMut = useMutation({
    mutationFn: (body: TestStepCreate) => testManagementApi.createStep(caseId, body),
    onSuccess: () => { message.success('步骤已新增'); invalidate(); setOpen(false); },
    onError: (e) => message.error(getErrorMessage(e, '新增失败')),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: TestStepUpdate }) => testManagementApi.updateStep(id, body),
    onSuccess: () => { message.success('步骤已更新'); invalidate(); setOpen(false); },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });
  const removeMut = useMutation({
    mutationFn: (id: number) => testManagementApi.removeStep(id),
    onSuccess: () => { message.success('步骤已删除'); invalidate(); },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const openCreate = () => { setEditing(null); form.resetFields(); form.setFieldsValue({ step_type: 'ACTION', sort: 0 }); setOpen(true); };
  const openEdit = (row: TestStep) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({ name: row.name, step_type: row.step_type as StepFormValues['step_type'], target_type: (row.target_type ?? undefined) as StepFormValues['target_type'], target_id: row.target_id ?? undefined, sort: row.sort });
    setOpen(true);
  };
  const submit = async () => {
    const v = await form.validateFields();
    const body = { name: v.name, step_type: v.step_type, target_type: v.target_type ?? null, target_id: v.target_id ?? null, sort: v.sort };
    if (editing) await updateMut.mutateAsync({ id: editing.id, body });
    else await createMut.mutateAsync(body);
  };

  const columns: TableColumnsType<TestStep> = [
    { title: '名称', dataIndex: 'name' },
    { title: '类型', dataIndex: 'step_type', width: 100 },
    { title: '被测对象', dataIndex: 'target_type', width: 130, render: (v: string | null) => v ?? '-' },
    { title: '对象ID', dataIndex: 'target_id', width: 90, render: (v: number | null) => v ?? '-' },
    { title: '排序', dataIndex: 'sort', width: 60 },
    {
      title: '操作', width: 120,
      render: (_, row) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => removeMut.mutate(row.id)}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Space style={{ marginBottom: 8 }}><Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增步骤</Button></Space>
      <Table rowKey="id" size="small" columns={columns} dataSource={items} pagination={false} />
      <Modal title={editing ? '编辑步骤' : '新增步骤'} open={open} onCancel={() => setOpen(false)} onOk={submit} confirmLoading={createMut.isPending || updateMut.isPending} okText="保存" cancelText="取消" destroyOnClose width={480}>
        <Form<StepFormValues> form={form} layout="vertical" initialValues={{ step_type: 'ACTION', sort: 0 }}>
          <Form.Item name="name" label="步骤名" rules={[{ required: true, message: '请输入步骤名' }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="step_type" label="步骤类型"><Select options={TEST_STEP_TYPE_OPTIONS} /></Form.Item>
          <Form.Item name="target_type" label="被测对象类型"><Select options={TEST_TARGET_TYPE_OPTIONS} allowClear /></Form.Item>
          <Form.Item name="target_id" label="被测对象ID"><InputNumber min={1} /></Form.Item>
          <Form.Item name="sort" label="排序"><InputNumber min={0} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ============================================================ 断言 Tab

interface AssertionFormValues {
  assertion_type: 'STATUS_CODE' | 'JSON_PATH' | 'HEADER' | 'RESPONSE_TIME' | 'CONTAINS' | 'NOT_CONTAINS';
  source?: string;
  path?: string;
  operator: 'EQ' | 'NE' | 'GT' | 'GE' | 'LT' | 'LE' | 'IN' | 'CONTAINS' | 'EXISTS' | 'NOT_EXISTS';
  expected_value?: string;
  required: boolean;
  step_id?: number;
  sort: number;
}

function AssertionsTab({ caseId, items }: { caseId: number; items: TestAssertion[] }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<TestAssertion | null>(null);
  const [form] = Form.useForm<AssertionFormValues>();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['test-case-detail', caseId] });

  const createMut = useMutation({
    mutationFn: (body: TestAssertionCreate) => testManagementApi.createAssertion(caseId, body),
    onSuccess: () => { message.success('断言已新增'); invalidate(); setOpen(false); },
    onError: (e) => message.error(getErrorMessage(e, '新增失败')),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: TestAssertionUpdate }) => testManagementApi.updateAssertion(id, body),
    onSuccess: () => { message.success('断言已更新'); invalidate(); setOpen(false); },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });
  const removeMut = useMutation({
    mutationFn: (id: number) => testManagementApi.removeAssertion(id),
    onSuccess: () => { message.success('断言已删除'); invalidate(); },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const openCreate = () => { setEditing(null); form.resetFields(); form.setFieldsValue({ assertion_type: 'STATUS_CODE', operator: 'EQ', required: true, sort: 0 }); setOpen(true); };
  const openEdit = (row: TestAssertion) => {
    setEditing(row);
    form.resetFields();
    form.setFieldsValue({ assertion_type: row.assertion_type as AssertionFormValues['assertion_type'], source: row.source ?? undefined, path: row.path ?? undefined, operator: row.operator as AssertionFormValues['operator'], expected_value: row.expected_value ?? undefined, required: row.required, step_id: row.step_id ?? undefined, sort: row.sort });
    setOpen(true);
  };
  const submit = async () => {
    const v = await form.validateFields();
    const body = { assertion_type: v.assertion_type, source: v.source ?? null, path: v.path ?? null, operator: v.operator, expected_value: v.expected_value ?? null, required: v.required, step_id: v.step_id ?? null, sort: v.sort };
    if (editing) await updateMut.mutateAsync({ id: editing.id, body });
    else await createMut.mutateAsync(body);
  };

  const columns: TableColumnsType<TestAssertion> = [
    { title: '类型', dataIndex: 'assertion_type', width: 130 },
    { title: '来源', dataIndex: 'source', width: 110, render: (v: string | null) => v ?? '-' },
    { title: '路径', dataIndex: 'path', ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: '操作符', dataIndex: 'operator', width: 90 },
    { title: '期望值', dataIndex: 'expected_value', ellipsis: true, render: (v: string | null) => v ?? '-' },
    { title: '必需', dataIndex: 'required', width: 70, render: (v: boolean) => (v ? <Tag color="green">是</Tag> : <Tag>否</Tag>) },
    { title: '排序', dataIndex: 'sort', width: 60 },
    {
      title: '操作', width: 120,
      render: (_, row) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => removeMut.mutate(row.id)}><Button size="small" danger icon={<DeleteOutlined />} /></Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Space style={{ marginBottom: 8 }}><Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreate}>新増断言</Button></Space>
      <Table rowKey="id" size="small" columns={columns} dataSource={items} pagination={false} />
      <Modal title={editing ? '编辑断言' : '新增断言'} open={open} onCancel={() => setOpen(false)} onOk={submit} confirmLoading={createMut.isPending || updateMut.isPending} okText="保存" cancelText="取消" destroyOnClose width={520}>
        <Form<AssertionFormValues> form={form} layout="vertical" initialValues={{ assertion_type: 'STATUS_CODE', operator: 'EQ', required: true, sort: 0 }}>
          <Form.Item name="assertion_type" label="断言类型"><Select options={TEST_ASSERTION_TYPE_OPTIONS} /></Form.Item>
          <Form.Item name="source" label="来源（HEADER 名 / CONTEXT 作用域）"><Input maxLength={100} /></Form.Item>
          <Form.Item name="path" label="路径（JSONPath 或字段路径）"><Input maxLength={500} placeholder="如 $.code 或 status_code" /></Form.Item>
          <Form.Item name="operator" label="操作符"><Select options={TEST_OPERATOR_OPTIONS} /></Form.Item>
          <Form.Item name="expected_value" label="期望值"><Input placeholder="如 0 或 200" /></Form.Item>
          <Form.Item name="required" label="必需（软断言=否）" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="step_id" label="关联步骤ID"><InputNumber min={1} /></Form.Item>
          <Form.Item name="sort" label="排序"><InputNumber min={0} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}
