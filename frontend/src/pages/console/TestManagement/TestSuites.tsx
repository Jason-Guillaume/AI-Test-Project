import { collectArrayPages } from '@/shared/api/pagination';
// 测试套件页（用户视角）。
// 单页表格：套件 CRUD + 每行「管理用例」抽屉（套件↔用例关联的增删）。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写 = 项目成员（member+）；跨项目越权 404，前端不展示。
// 返回形态：listSuites / listSuiteCases / listCases 均返回裸数组（无分页信封）。
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
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { TEST_SUITE_TYPE_OPTIONS } from './constants';
import type { TestSuite, TestSuiteCaseResponse, TestSuiteCreate, TestSuiteType, TestSuiteUpdate } from '@/features/test-management/contracts';


interface SuiteFormValues {
  name: string;
  suite_type: TestSuiteType;
  enabled: boolean;
  description?: string;
}

const SUITE_TYPE_COLOR: Record<string, string> = {
  SMOKE: 'magenta',
  REGRESSION: 'blue',
  BUSINESS: 'geekblue',
  CUSTOM: 'default',
};

/** 测试套件页。 */
export function ConsoleTestSuitesPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<TestSuite | null>(null);
  const [suiteDrawerId, setSuiteDrawerId] = useState<number | null>(null);
  const [addCaseId, setAddCaseId] = useState<number | null>(null);
  const [addCaseSort, setAddCaseSort] = useState(0);
  const [form] = Form.useForm<SuiteFormValues>();

  const suitesQuery = useQuery({
    queryKey: ['test-suites', currentProjectId],
    queryFn: () => collectArrayPages((page) => testManagementApi.listSuites(currentProjectId!, { page, page_size: 100 }), 100),
    enabled: currentProjectId != null,
  });

  const createMutation = useMutation({
    mutationFn: (body: TestSuiteCreate) =>
      testManagementApi.createSuite(currentProjectId!, body),
    onSuccess: () => {
      message.success('测试套件已创建');
      queryClient.invalidateQueries({ queryKey: ['test-suites'] });
      setModalOpen(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: TestSuiteUpdate }) =>
      testManagementApi.updateSuite(id, body),
    onSuccess: () => {
      message.success('测试套件已更新');
      queryClient.invalidateQueries({ queryKey: ['test-suites'] });
      setModalOpen(false);
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => testManagementApi.removeSuite(id),
    onSuccess: () => {
      message.success('测试套件已删除');
      queryClient.invalidateQueries({ queryKey: ['test-suites'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ suite_type: 'REGRESSION', enabled: true });
    setModalOpen(true);
  };

  const openEdit = (suite: TestSuite) => {
    setEditing(suite);
    form.resetFields();
    form.setFieldsValue({
      name: suite.name,
      suite_type: suite.suite_type as TestSuiteType,
      enabled: suite.enabled,
      description: suite.description ?? undefined,
    });
    setModalOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    const body = {
      name: values.name,
      suite_type: values.suite_type,
      enabled: values.enabled,
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

  const suites = suitesQuery.data ?? [];

  const columns: TableColumnsType<TestSuite> = [
    { title: 'ID', dataIndex: 'id', width: 64 },
    { title: '名称', dataIndex: 'name' },
    {
      title: '类型',
      dataIndex: 'suite_type',
      width: 110,
      render: (v: string) => <Tag color={SUITE_TYPE_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 70,
      render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '描述',
      dataIndex: 'description',
      ellipsis: true,
      render: (v: string | null) => v || '-',
    },
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
          <Button size="small" onClick={() => setSuiteDrawerId(row.id)}>
            管理用例
          </Button>
          <Popconfirm
            title="确认删除该套件？"
            onConfirm={() => removeMutation.mutate(row.id)}
          >
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
          测试套件
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建套件
        </Button>
      </Space>

      {suitesQuery.isLoading ? (
        <LoadingState />
      ) : suitesQuery.isError ? (
        <ErrorState error={suitesQuery.error} onRetry={suitesQuery.refetch} />
      ) : suites.length === 0 ? (
        <EmptyState description="暂无测试套件" />
      ) : (
        <Table rowKey="id" columns={columns} dataSource={suites} pagination={false} size="middle" />
      )}

      {/* 新建/编辑套件弹窗 */}
      <Modal
        title={editing ? '编辑测试套件' : '新建测试套件'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submit}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<SuiteFormValues> form={form} layout="vertical" initialValues={{ suite_type: 'REGRESSION', enabled: true }}>
          <Form.Item
            name="name"
            label="套件名称"
            rules={[{ required: true, message: '请输入套件名称' }]}
          >
            <Input maxLength={200} placeholder="如 登录接口回归套件" />
          </Form.Item>
          <Form.Item name="suite_type" label="类型">
            <Select options={TEST_SUITE_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 管理套件用例 */}
      <SuiteCasesDrawer
        suiteId={suiteDrawerId}
        onClose={() => setSuiteDrawerId(null)}
        addCaseId={addCaseId}
        setAddCaseId={setAddCaseId}
        addCaseSort={addCaseSort}
        setAddCaseSort={setAddCaseSort}
      />
    </PageContainer>
  );
}

/** 套件↔用例关联管理抽屉。 */
function SuiteCasesDrawer({
  suiteId,
  onClose,
  addCaseId,
  setAddCaseId,
  addCaseSort,
  setAddCaseSort,
}: {
  suiteId: number | null;
  onClose: () => void;
  addCaseId: number | null;
  setAddCaseId: (v: number | null) => void;
  addCaseSort: number;
  setAddCaseSort: (v: number) => void;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();

  const suiteCasesQuery = useQuery({
    queryKey: ['suite-cases', suiteId],
    queryFn: () => testManagementApi.listSuiteCases(suiteId!),
    enabled: suiteId != null,
  });
  const allCasesQuery = useQuery({
    queryKey: ['test-cases', currentProjectId, 'for-suite'],
    queryFn: () => collectArrayPages((page) => testManagementApi.listCases(currentProjectId!, { page, page_size: 100 }), 100),
    enabled: suiteId != null && currentProjectId != null,
  });

  const addMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { test_case_id: number; sort: number } }) =>
      testManagementApi.addSuiteCase(id, body),
    onSuccess: () => {
      message.success('用例已加入套件');
      queryClient.invalidateQueries({ queryKey: ['suite-cases', suiteId] });
      setAddCaseId(null);
      setAddCaseSort(0);
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });
  const removeMutation = useMutation({
    mutationFn: (suiteCaseId: number) => testManagementApi.removeSuiteCase(suiteCaseId),
    onSuccess: () => {
      message.success('用例已移除');
      queryClient.invalidateQueries({ queryKey: ['suite-cases', suiteId] });
    },
    onError: (e) => message.error(getErrorMessage(e, '移除失败')),
  });

  const suiteCases = suiteCasesQuery.data ?? [];
  const allCases = allCasesQuery.data ?? [];
  const caseName = (cid: number) =>
    allCases.find((c) => c.id === cid)?.name ?? `用例#${cid}`;

  const columns: TableColumnsType<TestSuiteCaseResponse> = [
    { title: '用例ID', dataIndex: 'test_case_id', width: 80 },
    {
      title: '用例名称',
      dataIndex: 'test_case_id',
      render: (cid: number) => caseName(cid),
    },
    { title: '排序', dataIndex: 'sort', width: 80 },
    {
      title: '启用',
      dataIndex: 'enabled',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">是</Tag> : <Tag>否</Tag>),
    },
    {
      title: '操作',
      width: 100,
      render: (_, row) => (
        <Popconfirm title="确认从套件移除该用例？" onConfirm={() => removeMutation.mutate(row.id)}>
          <Button size="small" danger icon={<DeleteOutlined />}>
            移除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Drawer title="管理套件用例" width={640} open={suiteId != null} onClose={onClose} destroyOnClose>
      <div className="member-add-row">
        <Select
          className="member-add-row__select"
          showSearch
          optionFilterProp="label"
          placeholder="选择要加入的用例"
          value={addCaseId ?? undefined}
          onChange={setAddCaseId}
          options={allCases.map((c) => ({ value: c.id, label: c.name }))}
        />
        <InputNumber
          min={0}
          value={addCaseSort}
          onChange={(v) => setAddCaseSort(v ?? 0)}
          placeholder="排序"
          style={{ width: 90 }}
        />
        <Button
          type="primary"
          disabled={addCaseId == null}
          onClick={() =>
            addMutation.mutate({
              id: suiteId!,
              body: { test_case_id: addCaseId!, sort: addCaseSort },
            })
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
        dataSource={suiteCases}
        pagination={false}
        loading={suiteCasesQuery.isLoading}
      />
    </Drawer>
  );
}
