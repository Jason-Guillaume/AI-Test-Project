// 测试资产 Fixture、步骤与断言编辑 Tab。
// 测试资产页（用户视角）。
// 左右布局：左侧 策略→测试点→用例 三级树；右侧选中用例的聚合详情编辑器
// （基本信息 + 前置条件 / 测试数据 / 步骤 / 断言 四 Tab，子实体就地 CRUD）。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写 = 项目成员（member+）；跨项目越权 404，前端不展示。
// §26：用例编辑携带 revision 乐观锁；并发冲突返回 409，前端提示「当前测试用例已被其他用户修改」并重载详情。
// 返回形态：listStrategies/listPoints/listCases/getCaseDetail 及子实体列表均为裸数组/对象（无分页信封）。
import { useEffect, useMemo, useRef, useState } from 'react';
import { App, Alert, Button, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography } from 'antd';
import type { TableColumnsType } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { testDataApi } from '@/features/test-data/api/testData';
import { getErrorMessage } from '@/shared/api/client';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { TEST_ASSERTION_TYPE_OPTIONS, TEST_OPERATOR_OPTIONS, TEST_STEP_TYPE_OPTIONS, TEST_TARGET_TYPE_OPTIONS } from './constants';
import type { TestAssertion, TestAssertionCreate, TestAssertionUpdate, TestCaseFixture, TestStep, TestStepCreate, TestStepUpdate } from '@/features/test-management/contracts';

// ============================================================ 所需 Fixture Tab
//
// 执行本用例前，平台按这里的顺序（含各自依赖）执行这些 Fixture 生成运行时数据；
// 清理按各 Fixture 自身的 cleanup_policy 决定。只能引用本用例已声明的 fixture_key，
// 因此「测试数据」页签的 FIXTURE 来源只能从下拉里选，不用手填表达式。
// 后端接口是整体替换（PUT 全量），这里在本地暂存选择，点「保存 Fixture」一次性提交。

interface FixtureRow {
  /** 行内唯一序号（Table rowKey，避免排序 / 换选时整行重建）。 */
  _row: number;
  fixture_key?: string;
}

export function FixturesTab({ caseId, items }: { caseId: number; items: TestCaseFixture[] }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();
  const nextRowId = useRef(0);

  const [rows, setRows] = useState<FixtureRow[]>(() =>
    items.map((f) => ({ _row: nextRowId.current++, fixture_key: f.fixture_key })),
  );
  const [dirty, setDirty] = useState(false);

  // 切换用例 / 后端刷新详情时回到服务端状态。
  useEffect(() => {
    setRows(items.map((f) => ({ _row: nextRowId.current++, fixture_key: f.fixture_key })));
    setDirty(false);
  }, [items]);

  const activeQuery = useQuery({
    queryKey: ['fixtures', currentProjectId, 'active'],
    queryFn: () => testDataApi.listFixtures(currentProjectId!, { status: 'ACTIVE' }),
    enabled: currentProjectId != null,
  });
  const available = useMemo(() => activeQuery.data?.items ?? [], [activeQuery.data]);
  const keyName = useMemo(() => {
    const m = new Map<string, string>();
    available.forEach((f) => m.set(f.fixture_key, f.name));
    return m;
  }, [available]);

  const saveMut = useMutation({
    mutationFn: () =>
      testManagementApi.replaceCaseFixtures(
        caseId,
        rows.filter((r) => r.fixture_key).map((r) => ({ fixture_key: r.fixture_key! })),
      ),
    onSuccess: () => {
      message.success('所需 Fixture 已保存');
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ['test-case-detail', caseId] });
    },
    onError: (e) => message.error(getErrorMessage(e, '保存失败')),
  });

  const commit = (next: FixtureRow[]) => { setRows(next); setDirty(true); };
  const move = (idx: number, delta: number) => {
    const to = idx + delta;
    if (to < 0 || to >= rows.length) return;
    const next = [...rows];
    [next[idx], next[to]] = [next[to], next[idx]];
    commit(next);
  };

  const columns: TableColumnsType<FixtureRow> = [
    { title: '执行顺序', width: 90, render: (_v, _row, idx) => `第 ${idx + 1} 位` },
    {
      title: 'Fixture',
      render: (_v, _row, idx) => {
        const used = new Set(rows.filter((r) => r.fixture_key && r.fixture_key !== rows[idx].fixture_key).map((r) => r.fixture_key as string));
        return (
          <Select
            size="small"
            style={{ minWidth: 240 }}
            showSearch
            optionFilterProp="label"
            placeholder="选择 Fixture"
            value={rows[idx].fixture_key}
            onChange={(key: string) => commit(rows.map((r, i) => (i === idx ? { ...r, fixture_key: key } : r)))}
            options={available.map((f) => ({
              value: f.fixture_key,
              label: `${f.fixture_key} — ${f.name}`,
              disabled: used.has(f.fixture_key),
            }))}
          />
        );
      },
    },
    { title: '名称', width: 180, render: (_v, row) => (row.fixture_key ? keyName.get(row.fixture_key) ?? '-' : '-') },
    {
      title: '输出契约',
      width: 240,
      render: (_v, _row, idx) => {
        const outputs = items[idx]?.outputs ?? [];
        return outputs.length ? <Space size={[0, 2]} wrap>{outputs.map((o) => <Tag key={o}>{o}</Tag>)}</Space> : '-';
      },
    },
    {
      title: '操作',
      width: 140,
      render: (_v, _row, idx) => (
        <Space size={4}>
          <Button size="small" disabled={idx === 0} onClick={() => move(idx, -1)}>上移</Button>
          <Button size="small" disabled={idx === rows.length - 1} onClick={() => move(idx, 1)}>下移</Button>
          <Popconfirm title="移除此 Fixture？" onConfirm={() => commit(rows.filter((_r, i) => i !== idx))}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Typography.Text type="secondary">
        执行本用例前，平台按依赖顺序执行这里声明的 Fixture，输出可被「测试数据」的 FIXTURE 来源引用；清理按各 Fixture 自身的 cleanup_policy 执行。
      </Typography.Text>
      {activeQuery.error && (
        <Alert
          type="warning"
          showIcon
          message="无法加载 Fixture 列表"
          description={getErrorMessage(activeQuery.error, '请到「测试数据中心」确认权限与配置')}
        />
      )}
      <Table
        rowKey={(row) => row._row}
        size="small"
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: '本用例还没有声明所需 Fixture' }}
      />
      <Space>
        <Button
          size="small"
          icon={<PlusOutlined />}
          disabled={available.length === 0}
          onClick={() => commit([...rows, { _row: nextRowId.current++, fixture_key: undefined }])}
        >
          新增 Fixture
        </Button>
        <Button
          size="small"
          type="primary"
          loading={saveMut.isPending}
          disabled={!dirty}
          onClick={() => saveMut.mutate()}
        >
          保存 Fixture
        </Button>
      </Space>
    </Space>
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

export function StepsTab({ caseId, items }: { caseId: number; items: TestStep[] }) {
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

export function AssertionsTab({ caseId, items }: { caseId: number; items: TestAssertion[] }) {
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
