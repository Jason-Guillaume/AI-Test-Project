import { collectArrayPages } from '@/shared/api/pagination';
// 测试套件页（用户视角）。
// 单页表格：套件 CRUD + 每行「管理用例」抽屉（套件↔用例关联的增删）。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写 = 项目成员（member+）；跨项目越权 404，前端不展示。
// 返回形态：listSuites / listSuiteCases / listCases 均返回裸数组（无分页信封）。
import { useEffect, useState } from 'react';
import {
  App,
  Alert,
  Button,
  Checkbox,
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
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { TableColumnsType } from 'antd';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { getErrorMessage } from '@/shared/api/client';
import { ErrorState, EmptyState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { sequenceColumn } from '@/shared/lib/sequence';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { TEST_SUITE_TYPE_OPTIONS } from './constants';
import { ManagementRowActions } from './ManagementRowActions';
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
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<TestSuite | null>(null);
  const [suiteDrawerId, setSuiteDrawerId] = useState<number | null>(null);
  const [selectedSuiteIds, setSelectedSuiteIds] = useState<number[]>([]);
  const [addCaseId, setAddCaseId] = useState<number | null>(null);
  const [addCaseSort, setAddCaseSort] = useState(0);
  const [form] = Form.useForm<SuiteFormValues>();
  useEffect(() => {
    setModalOpen(false); setEditing(null); setSuiteDrawerId(null); setSelectedSuiteIds([]);
    setAddCaseId(null); form.resetFields();
  }, [currentProjectId, form]);

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

  const batchRemoveMutation = useMutation({
    mutationFn: (ids: number[]) => testManagementApi.removeSuites(currentProjectId!, ids),
    onSuccess: (receipt) => {
      setSelectedSuiteIds([]);
      queryClient.invalidateQueries({ queryKey: ['test-suites'] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
      if (receipt.failed === 0) message.success(`已删除 ${receipt.succeeded} 个测试套件，记录已移入回收站`);
      else {
        message.warning(`已删除 ${receipt.succeeded} 个测试套件，${receipt.failed} 个未删除`);
        modal.info({
          title: '批量删除结果',
          width: 620,
          content: <Space direction="vertical" style={{ width: '100%' }}>
            {receipt.items.filter((item) => !item.succeeded).map((item) => (
              <Alert key={item.id} type="error" showIcon message={`测试套件 #${item.id}`} description={item.error ?? '删除失败'} />
            ))}
          </Space>,
        });
      }
    },
    onError: (error) => message.error(getErrorMessage(error, '批量删除失败')),
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
    sequenceColumn<TestSuite>(),
    { title: '名称', dataIndex: 'name', width: 200, className: 'table-record-name' },
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
      width: 160,
      render: (_, row) => (
        <ManagementRowActions
          onEdit={() => openEdit(row)}
          manageLabel="管理用例"
          onManage={() => setSuiteDrawerId(row.id)}
          deleteTitle={`删除套件「${row.name}」？仍被启用计划或执行任务引用时会拒绝删除。`}
          onDelete={() => removeMutation.mutateAsync(row.id)}
        />
      ),
    },
  ];

  return (
    <PageContainer>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }} wrap>
        <Typography.Title level={5} style={{ margin: 0 }}>
          测试套件
        </Typography.Title>
        <Space wrap>
          <Checkbox
            checked={suites.length > 0 && selectedSuiteIds.length === suites.length}
            indeterminate={selectedSuiteIds.length > 0 && selectedSuiteIds.length < suites.length}
            onChange={(event) => setSelectedSuiteIds(event.target.checked ? suites.map((suite) => suite.id) : [])}
          >
            全选当前列表（{suites.length}）
          </Checkbox>
          <Button danger disabled={selectedSuiteIds.length === 0 || batchRemoveMutation.isPending}
            loading={batchRemoveMutation.isPending}
            onClick={() => modal.confirm({
              title: `删除选中的 ${selectedSuiteIds.length} 个测试套件？`,
              content: '仍被启用测试计划或执行任务引用的套件会逐条拒绝；成功删除的套件可在回收站恢复。',
              okText: '删除并移入回收站', cancelText: '取消', okButtonProps: { danger: true },
              onOk: () => batchRemoveMutation.mutateAsync(selectedSuiteIds),
            })}>
            批量删除（{selectedSuiteIds.length}）
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建套件</Button>
        </Space>
      </Space>

      {suitesQuery.isLoading ? (
        <LoadingState />
      ) : suitesQuery.isError ? (
        <ErrorState error={suitesQuery.error} onRetry={suitesQuery.refetch} />
      ) : suites.length === 0 ? (
        <EmptyState description="暂无测试套件" />
      ) : (
        <Table rowKey="id" columns={columns} dataSource={suites} scroll={{ x: 970 }} pagination={false} size="middle"
          rowSelection={{ selectedRowKeys: selectedSuiteIds, onChange: (keys) => setSelectedSuiteIds(keys.map(Number)) }} />
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
        destroyOnHidden
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
  const [keyword, setKeyword] = useState('');
  const [candidatePage, setCandidatePage] = useState(1);
  useEffect(() => { setKeyword(''); setCandidatePage(1); }, [suiteId, currentProjectId]);
  const allCasesQuery = useQuery({
    queryKey: ['test-cases', currentProjectId, 'for-suite', keyword, candidatePage],
    queryFn: () => testManagementApi.listCases(currentProjectId!, { page: candidatePage, page_size: 20, keyword }),
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

  const columns: TableColumnsType<TestSuiteCaseResponse> = [
    sequenceColumn<TestSuiteCaseResponse>(),
    {
      title: '用例名称',
      dataIndex: 'case_name',
      render: (name: string | null, row) => name ?? `用例#${row.test_case_id}`,
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
    <Drawer title="管理套件用例" width={640} open={suiteId != null} onClose={onClose} destroyOnHidden>
      <div className="member-add-row">
        <Select
          className="member-add-row__select"
          showSearch
          filterOption={false}
          onSearch={(value) => { setKeyword(value); setCandidatePage(1); }}
          loading={allCasesQuery.isFetching}
          notFoundContent={allCasesQuery.isError ? '加载失败，请重试' : '没有匹配用例'}
          placeholder="搜索用例名称或编号"
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
      <Space style={{ margin: '8px 0' }}>
        <Button disabled={candidatePage === 1} onClick={() => setCandidatePage(candidatePage - 1)}>上一页候选</Button>
        <Typography.Text>第 {candidatePage} 页</Typography.Text>
        <Button disabled={allCases.length < 20} onClick={() => setCandidatePage(candidatePage + 1)}>下一页候选</Button>
        {allCasesQuery.isError && <Button onClick={() => void allCasesQuery.refetch()}>重试候选加载</Button>}
      </Space>
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
