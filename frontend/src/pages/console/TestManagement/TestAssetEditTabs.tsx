// 测试资产前置条件与数据编辑 Tab。
// 测试资产页（用户视角）。
// 左右布局：左侧 策略→测试点→用例 三级树；右侧选中用例的聚合详情编辑器
// （基本信息 + 前置条件 / 测试数据 / 步骤 / 断言 四 Tab，子实体就地 CRUD）。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写 = 项目成员（member+）；跨项目越权 404，前端不展示。
// §26：用例编辑携带 revision 乐观锁；并发冲突返回 409，前端提示「当前测试用例已被其他用户修改」并重载详情。
// 返回形态：listStrategies/listPoints/listCases/getCaseDetail 及子实体列表均为裸数组/对象（无分页信封）。
import { useMemo, useState } from 'react';
import { App, Button, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag } from 'antd';
import type { TableColumnsType } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { getErrorMessage } from '@/shared/api/client';
import { TEST_DATA_SOURCE_OPTIONS, TEST_FAKER_GENERATOR_OPTIONS, TEST_FAKER_LOCALE_OPTIONS, TEST_OPERATOR_OPTIONS, TEST_PRECONDITION_TYPE_OPTIONS, TEST_VALUE_TYPE_OPTIONS } from './constants';
import type { TestCaseData, TestCaseDataCreate, TestCaseDataUpdate, TestCaseFixture, TestCasePrecondition, TestCasePreconditionCreate, TestCasePreconditionUpdate } from '@/features/test-management/contracts';

// ============================================================ 前置条件 Tab

interface PreconditionFormValues {
  type: 'VARIABLE' | 'TEXT' | 'FIXTURE' | 'API' | 'BUSINESS_ACTION' | 'BUSINESS_FLOW';
  target?: string;
  operator: 'EQ' | 'NE' | 'GT' | 'GE' | 'LT' | 'LE' | 'IN' | 'CONTAINS' | 'EXISTS' | 'NOT_EXISTS';
  expected_value?: string;
  description?: string;
  sort: number;
}

export function PreconditionsTab({ caseId, items }: { caseId: number; items: TestCasePrecondition[] }) {
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
  /** FIXTURE 模式：来自本用例「所需 Fixture」的 fixture_key。 */
  fixture_key?: string;
  /** FIXTURE 模式：该 Fixture 输出契约里的名称。 */
  output?: string;
  /** FAKER 模式：后端白名单生成器名。 */
  generator?: string;
  /** FAKER 模式：生成语言。 */
  locale?: string;
  /** FAKER 模式：random_choice 候选值。 */
  choices?: string[];
}

export function DataTab({ caseId, items, fixtures }: { caseId: number; items: TestCaseData[]; fixtures: TestCaseFixture[] }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<TestCaseData | null>(null);
  const [form] = Form.useForm<DataFormValues>();

  const watchedSource = Form.useWatch('source_type', form);
  const watchedFixtureKey = Form.useWatch('fixture_key', form);
  const watchedGenerator = Form.useWatch('generator', form);

  // FIXTURE 模式只能绑定本用例已声明的 Fixture（未声明的 key 后端拒绝）。
  const fixtureOptions = useMemo(
    () =>
      fixtures.map((f) => ({
        value: f.fixture_key,
        label: `${f.fixture_key} — ${f.name}`,
        outputs: f.outputs ?? [],
      })),
    [fixtures],
  );
  const outputOptions = (watchedFixtureKey ? fixtureOptions.find((o) => o.value === watchedFixtureKey) : undefined)
    ?.outputs.map((n) => ({ value: n, label: n })) ?? [];

  const sourceValueLabel =
    watchedSource === 'VARIABLE'
      ? '变量名（如 ${fixture.SUCCESS_TASK.task_id} 或输出名）'
      : watchedSource === 'RUNTIME'
        ? '运行时变量名（如 task_id）'
        : watchedSource === 'ENVIRONMENT'
          ? '环境变量名'
          : '值';
  const sourceHint =
    watchedSource === 'FAKER'
      ? '值在每次执行时现造，不需要填「值」。'
      : watchedSource === 'FIXTURE'
        ? '值在执行前由平台注入，无需填写。'
        : undefined;

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
    const cfg = row.config_json ?? {};
    form.setFieldsValue({
      name: row.name,
      value_type: row.value_type as DataFormValues['value_type'],
      source_type: row.source_type as DataFormValues['source_type'],
      required: row.required,
      description: row.description ?? undefined,
      sort: row.sort,
      // STATIC/ENVIRONMENT/VARIABLE/RUNTIME 直接复用 value 列；FIXTURE/FAKER 的 value 不展示。
      value: (row.source_type === 'FIXTURE' || row.source_type === 'FAKER') ? undefined : row.value ?? undefined,
      fixture_key: typeof cfg.fixture_key === 'string' ? cfg.fixture_key : undefined,
      output: typeof cfg.output === 'string' ? cfg.output : undefined,
      generator: typeof cfg.generator === 'string' ? cfg.generator : undefined,
      locale: typeof cfg.locale === 'string' ? cfg.locale : undefined,
      choices: Array.isArray(cfg.choices) ? cfg.choices.map(String) : undefined,
    });
    setOpen(true);
  };
  const submit = async () => {
    const v = await form.validateFields();
    // FIXTURE / FAKER 走 config_json，value 列不适用（FIXTURE 由后端回写表达式）。
    let config_json: Record<string, unknown> | null = null;
    if (v.source_type === 'FIXTURE') {
      if (!v.fixture_key || !v.output) { message.error('请选择 Fixture 与输出'); return; }
      config_json = { fixture_key: v.fixture_key, output: v.output, variable: v.name };
    } else if (v.source_type === 'FAKER') {
      if (!v.generator) { message.error('请选择 FAKER 生成器'); return; }
      config_json = { generator: v.generator, locale: v.locale || 'zh_CN' };
      if (v.generator === 'random_choice') {
        const choices = (v.choices ?? []).map((c) => c.trim()).filter(Boolean);
        if (!choices.length) { message.error('random_choice 需要至少 1 个候选值'); return; }
        config_json.choices = choices;
      }
    }
    const value = v.source_type === 'FIXTURE' || v.source_type === 'FAKER' ? null : v.value ?? null;
    if (editing) {
      // 不传 name（不可改）。
      await updateMut.mutateAsync({ id: editing.id, body: { value_type: v.value_type, value, source_type: v.source_type, config_json, required: v.required, description: v.description ?? null, sort: v.sort } });
    } else {
      await createMut.mutateAsync({ name: v.name, value_type: v.value_type, value, source_type: v.source_type, config_json, required: v.required, description: v.description ?? null, sort: v.sort });
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
          <Form.Item name="source_type" label="来源" extra={sourceHint}>
            <Select options={TEST_DATA_SOURCE_OPTIONS} />
          </Form.Item>
          <Form.Item name="name" label="数据项名" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={100} disabled={editing != null} />
          </Form.Item>
          {watchedSource !== 'FIXTURE' && watchedSource !== 'FAKER' && (
            <Form.Item name="value_type" label="值类型"><Select options={TEST_VALUE_TYPE_OPTIONS} /></Form.Item>
          )}
          <Form.Item
            name="value"
            label={sourceValueLabel}
            dependencies={['source_type']}
            rules={[
              {
                validator: async (_rule, value) => {
                  const src = form.getFieldValue('source_type');
                  if (src === 'FIXTURE' || src === 'FAKER') return;
                  if (value === undefined || value === null || String(value).trim() === '') {
                    throw new Error('该来源需要填写值');
                  }
                },
              },
            ]}
          >
            <Input />
          </Form.Item>
          {watchedSource === 'FIXTURE' && (
            <>
              <Form.Item
                name="fixture_key"
                label="所需 Fixture"
                rules={[{ required: true, message: '请选择 Fixture' }]}
                extra={fixtureOptions.length ? undefined : '本用例还没有声明所需 Fixture，请到「所需 Fixture」页签添加'}
              >
                <Select options={fixtureOptions} showSearch optionFilterProp="label" placeholder="选择本用例所需的 Fixture" />
              </Form.Item>
              <Form.Item name="output" label="输出名" rules={[{ required: true, message: '请选择输出名' }]}>
                <Select
                  options={outputOptions}
                  placeholder={watchedFixtureKey ? '选择该 Fixture 的输出' : '先选择 Fixture'}
                  disabled={!watchedFixtureKey || outputOptions.length === 0}
                />
              </Form.Item>
            </>
          )}
          {watchedSource === 'FAKER' && (
            <>
              <Form.Item name="generator" label="生成器" rules={[{ required: true, message: '请选择生成器' }]}>
                <Select options={TEST_FAKER_GENERATOR_OPTIONS} />
              </Form.Item>
              <Form.Item name="locale" label="语言" initialValue="zh_CN">
                <Select options={TEST_FAKER_LOCALE_OPTIONS} />
              </Form.Item>
              {watchedGenerator === 'random_choice' && (
                <Form.Item name="choices" label="候选值" extra="运行时从这些候选中随机取一个">
                  <Select mode="tags" open={false} tokenSeparators={[',']} />
                </Form.Item>
              )}
            </>
          )}
          <Form.Item name="required" label="必需" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="description" label="说明"><Input maxLength={500} /></Form.Item>
          <Form.Item name="sort" label="排序"><InputNumber min={0} /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}

