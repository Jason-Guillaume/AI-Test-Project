// 数据池列表：单条删除、当前页多选和批量删除都进入回收站。
import { useState } from 'react';
import { Alert, App, Button, Form, Input, InputNumber, Modal, Select, Space, Table } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import { testDataApi } from '@/features/test-data/api/testData';
import { getErrorMessage } from '@/shared/api/client';
import { collectPages } from '@/shared/api/pagination';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import type { DataPool, DataPoolCreate } from '@/features/test-data/contracts';

const KEY_PATTERN = /^[A-Z][A-Z0-9_]{0,99}$/;

/**
 * 数据池与条目管理。删除只移入回收站，占用中的条目由后端拒绝。
 */
export function PoolTab({ projectId }: { projectId: number }) {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<DataPoolCreate>();
  const [open, setOpen] = useState(false);
  const [selectedPoolIds, setSelectedPoolIds] = useState<number[]>([]);
  const [activePool, setActivePool] = useState<DataPool | null>(null);
  const [selectedItemIds, setSelectedItemIds] = useState<number[]>([]);

  const poolsQuery = useQuery({
    queryKey: ['test-data', 'pools', projectId],
    queryFn: () => collectPages((page) => testDataApi.listPools(projectId, { page, page_size: 200 })),
  });
  const itemsQuery = useQuery({
    queryKey: ['test-data', 'pool-items', activePool?.id],
    queryFn: () => collectPages((page) => testDataApi.listPoolItems(activePool!.id, { page, page_size: 200 })),
    enabled: activePool != null,
  });

  const createMutation = useMutation({
    mutationFn: (body: DataPoolCreate) => testDataApi.createPool(projectId, body),
    onSuccess: async () => {
      message.success('数据池已创建');
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ['test-data', 'pools'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '创建数据池失败')),
  });

  const removeMany = (resourceType: 'data_pool' | 'data_pool_item', ids: number[], clear: () => void) => {
    if (!ids.length) return;
    if (ids.length > 100) {
      void message.warning('每批最多删除 100 条，请分批操作');
      return;
    }
    modal.confirm({
      title: `将选中的 ${ids.length} 条记录移入回收站？`,
      content: '仍有条目、活跃租约或父池已删除时会逐条失败，其它记录不受影响。',
      okText: '移入回收站',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        const receipt = await dataLifecycleApi.deleteMany(resourceType, projectId, ids);
        clear();
        await queryClient.invalidateQueries({ queryKey: ['test-data', 'pools'] });
        await queryClient.invalidateQueries({ queryKey: ['test-data', 'pool-items'] });
        await queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
        const failures = receipt.items.filter((item) => !item.succeeded);
        modal.info({
          title: `删除完成：成功 ${receipt.succeeded} 条，失败 ${receipt.failed} 条`,
          content: failures.length ? (
            <Space direction="vertical">
              {failures.map((item) => <Alert key={item.id} type="error" showIcon message={`#${item.id}`} description={item.error ?? '删除失败'} />)}
            </Space>
          ) : '成功项已进入回收站。',
          okText: '查看回收站',
          onOk: () => navigate('/console/recycle-bin'),
        });
      },
    });
  };

  if (poolsQuery.isPending) return <LoadingState />;
  if (poolsQuery.isError) return <ErrorState error={poolsQuery.error} onRetry={poolsQuery.refetch} />;
  const pools = poolsQuery.data?.items ?? [];
  const poolItems = itemsQuery.data?.items ?? [];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Space wrap>
        <Button type="primary" onClick={() => { form.resetFields(); form.setFieldsValue({ scope: 'PROJECT', status: 'ACTIVE', max_concurrency: 1, lease_ttl_seconds: 1800 }); setOpen(true); }}>新增数据池</Button>
        <Button danger disabled={!selectedPoolIds.length} onClick={() => removeMany('data_pool', selectedPoolIds, () => setSelectedPoolIds([]))}>批量删除（{selectedPoolIds.length}）</Button>
        <Button disabled={!selectedPoolIds.length} onClick={() => setSelectedPoolIds([])}>取消选择</Button>
        <Button onClick={() => navigate('/console/recycle-bin')}>回收站</Button>
      </Space>
      <Table<DataPool>
        rowKey="id"
        dataSource={pools}
        pagination={false}
        rowSelection={{ selectedRowKeys: selectedPoolIds, onChange: (keys) => setSelectedPoolIds(keys.map(Number)) }}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '键', dataIndex: 'pool_key' },
          { title: '条目', dataIndex: 'item_count', width: 80 },
          { title: '状态', dataIndex: 'status', width: 100 },
          {
            title: '操作', width: 160,
            render: (_, row) => (
              <Space>
                <Button size="small" type="link" onClick={() => { setActivePool(row); setSelectedItemIds([]); }}>条目</Button>
                <Button size="small" type="link" danger onClick={() => removeMany('data_pool', [row.id], () => setSelectedPoolIds((ids) => ids.filter((id) => id !== row.id)))}>删除</Button>
              </Space>
            ),
          },
        ]}
      />
      {activePool && (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space>
            <span>池「{activePool.name}」的条目</span>
            <Button danger disabled={!selectedItemIds.length} onClick={() => removeMany('data_pool_item', selectedItemIds, () => setSelectedItemIds([]))}>批量删除条目（{selectedItemIds.length}）</Button>
          </Space>
          <Table
            rowKey="id"
            loading={itemsQuery.isFetching}
            dataSource={poolItems}
            pagination={false}
            rowSelection={{ selectedRowKeys: selectedItemIds, onChange: (keys) => setSelectedItemIds(keys.map(Number)) }}
            columns={[
              { title: 'ID', dataIndex: 'id', width: 80 },
              { title: '状态', dataIndex: 'status', width: 120 },
              { title: '占用次数', dataIndex: 'occupied_count', width: 100 },
              {
                title: '操作', width: 90,
                render: (_, row: { id: number }) => (
                  <Button size="small" type="link" danger onClick={() => removeMany('data_pool_item', [row.id], () => setSelectedItemIds((ids) => ids.filter((id) => id !== row.id)))}>删除</Button>
                ),
              },
            ]}
          />
        </Space>
      )}
      <Modal title="新增数据池" open={open} confirmLoading={createMutation.isPending} onCancel={() => setOpen(false)} onOk={() => form.submit()}>
        <Form form={form} layout="vertical" onFinish={(values) => createMutation.mutate(values)}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="pool_key" label="池键" rules={[{ required: true, pattern: KEY_PATTERN, message: '使用大写字母、数字和下划线' }]}><Input maxLength={100} /></Form.Item>
          <Form.Item name="scope" label="作用域"><Select options={['CASE', 'RUN', 'PROJECT', 'GLOBAL'].map((value) => ({ value, label: value }))} /></Form.Item>
          <Form.Item name="max_concurrency" label="最大并发"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="lease_ttl_seconds" label="租约秒数"><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="status" label="状态"><Select options={[{ value: 'ACTIVE', label: '启用' }, { value: 'DISABLED', label: '停用' }]} /></Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
