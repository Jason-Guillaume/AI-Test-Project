// 测试资产页：只管理测试策略和测试点。
// 用例已拆到 /console/test-cases，这里不再用树把三类资产叠在一起。
//
// 权限（服务端为准）：读 = 项目可见（viewer+）；写 = 项目成员（member+）。
// 列表接口返回裸数组。策略和测试点数量不大，一次取 100 条后在页面内搜索。
import { useState } from 'react';
import { Alert, App, Button, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tabs, Tag } from 'antd';
import type { TableColumnsType } from 'antd';
import { useNavigate } from 'react-router-dom';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { testManagementApi } from '@/features/test-management/api/testManagement';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, PageContainer } from '@/shared/ui/PageState';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { TEST_PRIORITY_OPTIONS, TEST_STATUS_OPTIONS, TEST_STRATEGY_CATEGORY_OPTIONS, TEST_TARGET_TYPE_OPTIONS } from './constants';
import type { TestPoint, TestPointCreate, TestPointUpdate, TestStrategy, TestStrategyCreate, TestStrategyUpdate } from '@/features/test-management/contracts';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';

interface StrategyFormValues {
  name: string;
  category: TestStrategyCreate['category'];
  enabled: boolean;
  description?: string;
}

interface PointFormValues {
  name: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  target_type: 'API' | 'WEB' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION';
  status: 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
  strategy_id?: number;
  description?: string;
}

/** 测试资产页。进入页面时拉取当前项目的策略和测试点。 */
export function TestAssetWorkspace() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { currentProjectId } = useConsoleScope();
  const [strategyForm] = Form.useForm<StrategyFormValues>();
  const [pointForm] = Form.useForm<PointFormValues>();
  const [strategyEditing, setStrategyEditing] = useState<TestStrategy | null>(null);
  const [strategyOpen, setStrategyOpen] = useState(false);
  const [pointEditing, setPointEditing] = useState<TestPoint | null>(null);
  const [pointOpen, setPointOpen] = useState(false);
  const [strategyKeyword, setStrategyKeyword] = useState('');
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<number[]>([]);
  const [selectedPointIds, setSelectedPointIds] = useState<number[]>([]);
  const [pointKeyword, setPointKeyword] = useState('');

  const strategiesQuery = useQuery({
    queryKey: ['test-strategies', currentProjectId],
    queryFn: () => testManagementApi.listStrategies(currentProjectId!, { page: 1, page_size: 100 }),
    enabled: currentProjectId != null,
  });
  const pointsQuery = useQuery({
    queryKey: ['test-points', currentProjectId],
    queryFn: () => testManagementApi.listPoints(currentProjectId!, { page: 1, page_size: 100 }),
    enabled: currentProjectId != null,
  });

  const saveStrategy = useMutation({
    mutationFn: async (values: StrategyFormValues) => {
      const body: TestStrategyCreate = {
        name: values.name,
        category: values.category,
        enabled: values.enabled,
        description: values.description || null,
      };
      if (strategyEditing) {
        const update: TestStrategyUpdate = body;
        return testManagementApi.updateStrategy(strategyEditing.id, update);
      }
      return testManagementApi.createStrategy(currentProjectId!, body);
    },
    onSuccess: () => {
      message.success(strategyEditing ? '测试策略已更新' : '测试策略已创建');
      queryClient.invalidateQueries({ queryKey: ['test-strategies'] });
      setStrategyOpen(false);
    },
    onError: (error) => message.error(getErrorMessage(error, '保存策略失败')),
  });
  const removeStrategy = useMutation({
    mutationFn: (id: number) => testManagementApi.removeStrategy(id),
    onSuccess: () => {
      message.success('测试策略已删除');
      queryClient.invalidateQueries({ queryKey: ['test-strategies'] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '删除策略失败')),
  });
  function batchDeleteStrategies() {
    if (!currentProjectId || !selectedStrategyIds.length) return;
    if (selectedStrategyIds.length > 100) { void message.warning('每批最多删除 100 个策略，请分批操作'); return; }
    const ids = [...selectedStrategyIds];
    modal.confirm({
      title: `确认删除选中的 ${ids.length} 个测试策略？`,
      content: '仍被测试点引用的策略会逐条拒绝删除；成功项可从项目回收站恢复。',
      okText: '删除并移入回收站',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        const receipt = await dataLifecycleApi.deleteMany('test_strategy', currentProjectId, ids);
        setSelectedStrategyIds([]);
        await queryClient.invalidateQueries({ queryKey: ['test-strategies', currentProjectId] });
        await queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
        const failures = receipt.items.filter(item => !item.succeeded);
        if (failures.length) {
          message.warning(`已删除 ${receipt.succeeded} 个策略，${receipt.failed} 个未删除`);
          modal.info({
            title: '批量删除结果',
            content: <Space direction="vertical" style={{ width: '100%' }}>
              {failures.map(item => <Alert key={item.id} type="error" showIcon message={`测试策略 #${item.id}`} description={item.error ?? '删除失败'} />)}
            </Space>,
          });
        } else {
          message.success(`已删除 ${receipt.succeeded} 个测试策略，可在回收站恢复`);
        }
      },
    });
  }
  const savePoint = useMutation({
    mutationFn: async (values: PointFormValues) => {
      const body: TestPointCreate = {
        name: values.name,
        priority: values.priority,
        target_type: values.target_type,
        status: values.status,
        strategy_id: values.strategy_id ?? null,
        description: values.description || null,
      };
      if (pointEditing) return testManagementApi.updatePoint(pointEditing.id, body satisfies TestPointUpdate);
      return testManagementApi.createPoint(currentProjectId!, body);
    },
    onSuccess: () => {
      message.success(pointEditing ? '测试点已更新' : '测试点已创建');
      queryClient.invalidateQueries({ queryKey: ['test-points'] });
      setPointOpen(false);
    },
    onError: (error) => message.error(getErrorMessage(error, '保存测试点失败')),
  });
  const removePoint = useMutation({
    mutationFn: (id: number) => testManagementApi.removePoint(id),
    onSuccess: () => {
      message.success('测试点已移入回收站');
      queryClient.invalidateQueries({ queryKey: ['test-points'] });
      queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '删除测试点失败')),
  });

  function batchDeletePoints() {
    if (!currentProjectId || !selectedPointIds.length) return;
    if (selectedPointIds.length > 100) { void message.warning('每批最多删除 100 个测试点，请分批操作'); return; }
    const ids = [...selectedPointIds];
    modal.confirm({
      title: `确认删除选中的 ${ids.length} 个测试点？`,
      content: '仍被测试用例引用的测试点会逐条拒绝；成功项进入当前项目回收站。',
      okText: '删除并移入回收站',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        const receipt = await dataLifecycleApi.deleteMany('test_point', currentProjectId, ids);
        setSelectedPointIds([]);
        await queryClient.invalidateQueries({ queryKey: ['test-points', currentProjectId] });
        await queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
        const failures = receipt.items.filter((item) => !item.succeeded);
        if (failures.length) {
          modal.info({
            title: `批量删除完成：成功 ${receipt.succeeded} 个，失败 ${receipt.failed} 个`,
            content: <Space direction="vertical" style={{ width: '100%' }}>
              {failures.map((item) => <Alert key={item.id} type="error" showIcon message={`测试点 #${item.id}`} description={item.error ?? '删除失败'} />)}
            </Space>,
          });
        } else {
          modal.success({
            title: `已将 ${receipt.succeeded} 个测试点移入回收站`,
            content: '原始 ID 和策略关联已保留。',
            okText: '查看回收站',
            onOk: () => navigate('/console/recycle-bin'),
          });
        }
      },
    });
  }

  if (currentProjectId == null) {
    return <PageContainer><EmptyState description="请先在顶部选择一个项目" /></PageContainer>;
  }

  const strategies = strategiesQuery.data ?? [];
  const points = pointsQuery.data ?? [];
  const strategyKeywordText = strategyKeyword.trim();
  const pointKeywordText = pointKeyword.trim();
  const visibleStrategies = strategyKeywordText
    ? strategies.filter((item) => `${item.name} ${item.description ?? ''}`.includes(strategyKeywordText))
    : strategies;
  const visiblePoints = pointKeywordText
    ? points.filter((item) => `${item.name} ${item.description ?? ''}`.includes(pointKeywordText))
    : points;
  const strategyName = new Map(strategies.map((item) => [item.id, item.name]));

  const openStrategy = (row?: TestStrategy) => {
    setStrategyEditing(row ?? null);
    strategyForm.setFieldsValue(row
      ? { name: row.name, category: row.category as StrategyFormValues['category'], enabled: row.enabled, description: row.description ?? undefined }
      : { name: '', category: 'FUNCTIONAL', enabled: true, description: undefined });
    setStrategyOpen(true);
  };
  const openPoint = (row?: TestPoint) => {
    setPointEditing(row ?? null);
    pointForm.setFieldsValue(row
      ? {
        name: row.name,
        priority: row.priority as PointFormValues['priority'],
        target_type: row.target_type as PointFormValues['target_type'],
        status: row.status as PointFormValues['status'],
        strategy_id: row.strategy_id ?? undefined,
        description: row.description ?? undefined,
      }
      : { name: '', priority: 'P1', target_type: 'API', status: 'DRAFT', description: undefined });
    setPointOpen(true);
  };

  const strategyColumns: TableColumnsType<TestStrategy> = [
    { title: '策略', dataIndex: 'name', ellipsis: true },
    { title: '类别', dataIndex: 'category', width: 160, render: (value: string) => <Tag>{value}</Tag> },
    { title: '启用', dataIndex: 'enabled', width: 80, render: (value: boolean) => value ? <Tag color="green">是</Tag> : <Tag>否</Tag> },
    { title: '说明', dataIndex: 'description', ellipsis: true, render: (value: string | null) => value || '-' },
    {
      title: '操作', width: 140,
      render: (_, row) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openStrategy(row)}>编辑</Button>
          <Popconfirm title="删除这个测试策略？" onConfirm={() => removeStrategy.mutate(row.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];
  const pointColumns: TableColumnsType<TestPoint> = [
    { title: '测试点', dataIndex: 'name', ellipsis: true },
    { title: '策略', width: 220, ellipsis: true, render: (_, row) => strategyName.get(row.strategy_id ?? -1) || '-' },
    { title: '优先级', dataIndex: 'priority', width: 90 },
    { title: '对象', dataIndex: 'target_type', width: 140 },
    { title: '状态', dataIndex: 'status', width: 110, render: (value: string) => <Tag>{value}</Tag> },
    {
      title: '操作', width: 140,
      render: (_, row) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openPoint(row)}>编辑</Button>
          <Popconfirm title="将这个测试点移入回收站？" description="仍被用例引用时会拒绝删除。" onConfirm={() => removePoint.mutate(row.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer>
      <Space style={{ marginBottom: 16 }} wrap>
        <span>策略和测试点在这里维护。用例请到独立的用例库查看和编辑。</span>
        <Button onClick={() => navigate('/console/test-cases')}>打开测试用例</Button>
      </Space>
      <Tabs
        items={[
          {
            key: 'strategies',
            label: `测试策略（${visibleStrategies.length}）`,
            children: (
              <>
                <Space style={{ marginBottom: 12 }} wrap>
                  <Input.Search allowClear placeholder="搜索策略" style={{ width: 240 }} onSearch={setStrategyKeyword} />
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => openStrategy()}>新建策略</Button>
                  <Button danger disabled={!selectedStrategyIds.length} onClick={batchDeleteStrategies}>批量删除已选（{selectedStrategyIds.length}）</Button>
                  <Button disabled={!selectedStrategyIds.length} onClick={() => navigate('/console/recycle-bin')}>查看回收站</Button>
                </Space>
                <Table rowKey="id" rowSelection={{ selectedRowKeys: selectedStrategyIds, onChange: keys => setSelectedStrategyIds(keys.map(Number)) }} columns={strategyColumns} dataSource={visibleStrategies} loading={strategiesQuery.isFetching} pagination={false} locale={{ emptyText: strategiesQuery.isError ? '策略加载失败' : '还没有测试策略' }} />
              </>
            ),
          },
          {
            key: 'points',
            label: `测试点（${visiblePoints.length}）`,
            children: (
              <>
                <Space style={{ marginBottom: 12 }} wrap>
                  <Input.Search allowClear placeholder="搜索测试点" style={{ width: 240 }} onSearch={setPointKeyword} />
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => openPoint()}>新建测试点</Button>
                  <Button danger disabled={!selectedPointIds.length} onClick={batchDeletePoints}>批量删除已选（{selectedPointIds.length}）</Button>
                  <Button disabled={!selectedPointIds.length} onClick={() => navigate('/console/recycle-bin')}>查看回收站</Button>
                </Space>
                <Table rowKey="id" rowSelection={{ selectedRowKeys: selectedPointIds, onChange: keys => setSelectedPointIds(keys.map(Number)) }} columns={pointColumns} dataSource={visiblePoints} loading={pointsQuery.isFetching} pagination={false} locale={{ emptyText: pointsQuery.isError ? '测试点加载失败' : '还没有测试点' }} />
              </>
            ),
          },
        ]}
      />
      <Modal title={strategyEditing ? '编辑测试策略' : '新建测试策略'} open={strategyOpen} onCancel={() => setStrategyOpen(false)} onOk={() => strategyForm.submit()} confirmLoading={saveStrategy.isPending} destroyOnClose>
        <Form form={strategyForm} layout="vertical" onFinish={(values) => saveStrategy.mutate(values)}>
          <Form.Item name="name" label="策略名称" rules={[{ required: true, message: '请输入策略名称' }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="category" label="类别"><Select options={TEST_STRATEGY_CATEGORY_OPTIONS} /></Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} maxLength={1000} /></Form.Item>
        </Form>
      </Modal>
      <Modal title={pointEditing ? '编辑测试点' : '新建测试点'} open={pointOpen} onCancel={() => setPointOpen(false)} onOk={() => pointForm.submit()} confirmLoading={savePoint.isPending} destroyOnClose>
        <Form form={pointForm} layout="vertical" onFinish={(values) => savePoint.mutate(values)}>
          <Form.Item name="name" label="测试点名称" rules={[{ required: true, message: '请输入测试点名称' }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="strategy_id" label="所属策略"><Select allowClear options={strategies.map((item) => ({ value: item.id, label: item.name }))} /></Form.Item>
          <Form.Item name="priority" label="优先级"><Select options={TEST_PRIORITY_OPTIONS} /></Form.Item>
          <Form.Item name="target_type" label="被测对象"><Select options={TEST_TARGET_TYPE_OPTIONS} /></Form.Item>
          <Form.Item name="status" label="状态"><Select options={TEST_STATUS_OPTIONS} /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} maxLength={1000} /></Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
