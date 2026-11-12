// 被测库连接列表。删除进入回收站，密码不会出现在回收站详情里。
import { useState } from 'react';
import { Alert, App, Button, Form, Input, InputNumber, Modal, Select, Space, Switch, Table } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import { testDataApi } from '@/features/test-data/api/testData';
import type { Environment } from '@/features/environments/contracts';
import { getErrorMessage } from '@/shared/api/client';
import { collectPages } from '@/shared/api/pagination';
import { ErrorState, LoadingState } from '@/shared/ui/PageState';
import type { TargetDbConnection, TargetDbConnectionCreate } from '@/features/test-data/contracts';

/**
 * 被测库连接管理。创建和删除都要求平台管理员权限，失败原因由接口返回。
 */
export function ConnectionTab({ projectId, environments }: { projectId: number; environments: Environment[] }) {
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<TargetDbConnectionCreate>();
  const [open, setOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  const query = useQuery({
    queryKey: ['test-data', 'connections', projectId],
    queryFn: () => collectPages((page) => testDataApi.listConnections(projectId, { page, page_size: 200 })),
  });
  const createMutation = useMutation({
    mutationFn: (body: TargetDbConnectionCreate) => testDataApi.createConnection(projectId, body),
    onSuccess: async () => {
      message.success('连接已创建');
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ['test-data', 'connections'] });
    },
    onError: (error) => message.error(getErrorMessage(error, '创建连接失败')),
  });

  const removeMany = (ids: number[]) => {
    if (!ids.length) return;
    if (ids.length > 100) {
      void message.warning('每批最多删除 100 条，请分批操作');
      return;
    }
    modal.confirm({
      title: `将选中的 ${ids.length} 个数据库连接移入回收站？`,
      content: '仍被数据工厂引用的连接会逐条拒绝。密码密文保留，但回收站详情不会展示。',
      okText: '移入回收站',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        const receipt = await dataLifecycleApi.deleteMany('target_database_connection', projectId, ids);
        setSelectedIds([]);
        await queryClient.invalidateQueries({ queryKey: ['test-data', 'connections'] });
        await queryClient.invalidateQueries({ queryKey: ['recycle-bin'] });
        const failures = receipt.items.filter((item) => !item.succeeded);
        modal.info({
          title: `删除完成：成功 ${receipt.succeeded} 个，失败 ${receipt.failed} 个`,
          content: failures.length ? (
            <Space direction="vertical">
              {failures.map((item) => <Alert key={item.id} type="error" showIcon message={`连接 #${item.id}`} description={item.error ?? '删除失败'} />)}
            </Space>
          ) : '成功项已进入回收站。',
          okText: '查看回收站',
          onOk: () => navigate('/console/recycle-bin'),
        });
      },
    });
  };

  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;
  const connections = query.data?.items ?? [];

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Space wrap>
        <Button type="primary" onClick={() => { form.resetFields(); form.setFieldsValue({ port: 5432, enabled: true }); setOpen(true); }}>新增连接</Button>
        <Button danger disabled={!selectedIds.length} onClick={() => removeMany(selectedIds)}>批量删除（{selectedIds.length}）</Button>
        <Button disabled={!selectedIds.length} onClick={() => setSelectedIds([])}>取消选择</Button>
        <Button onClick={() => navigate('/console/recycle-bin')}>回收站</Button>
      </Space>
      <Table<TargetDbConnection>
        rowKey="id"
        dataSource={connections}
        pagination={false}
        rowSelection={{ selectedRowKeys: selectedIds, onChange: (keys) => setSelectedIds(keys.map(Number)) }}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '环境', dataIndex: 'environment_name' },
          { title: '主机', dataIndex: 'host' },
          { title: '库名', dataIndex: 'database_name' },
          { title: '引用', dataIndex: 'referenced_count', width: 80 },
          {
            title: '操作', width: 90,
            render: (_, row) => <Button size="small" type="link" danger onClick={() => removeMany([row.id])}>删除</Button>,
          },
        ]}
      />
      <Modal title="新增被测库连接" open={open} confirmLoading={createMutation.isPending} onCancel={() => setOpen(false)} onOk={() => form.submit()}>
        <Form form={form} layout="vertical" onFinish={(values) => createMutation.mutate(values)}>
          <Form.Item name="environment_id" label="环境" rules={[{ required: true, message: '请选择环境' }]}>
            <Select options={environments.filter((item) => item.id != null).map((item) => ({ value: item.id as number, label: item.display_name || item.name }))} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input maxLength={200} /></Form.Item>
          <Form.Item name="host" label="主机" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="port" label="端口"><InputNumber min={1} max={65535} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="database_name" label="数据库" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password /></Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
