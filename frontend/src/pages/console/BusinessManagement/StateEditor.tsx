// 状态定义编辑器：管理单个步骤的业务状态变更定义（实体 + 前置状态 → 后置状态）。
// 用于描述步骤执行后业务实体的状态流转（如 task: CREATED → RUNNING）。
import { useState } from 'react';
import { App, Button, Empty, Form, Input, Modal, Popconfirm, Space, Table, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { businessApi } from '@/features/business/api/business';
import { getErrorMessage } from '@/shared/api/client';
import type { BusinessActionDetail, BusinessStateCreate, BusinessStateUpdate } from '@/features/business/contracts';


export function StateEditor({
  action,
  onChanged,
}: {
  action: BusinessActionDetail;
  onChanged: () => void;
}) {
  const { message } = App.useApp();
  const [addOpen, setAddOpen] = useState(false);
  const [editItem, setEditItem] = useState<{ id: number; values: BusinessStateUpdate } | null>(null);
  const [form] = Form.useForm<BusinessStateCreate>();

  const createMutation = useMutation({
    mutationFn: (body: BusinessStateCreate) => businessApi.createState(action.id, body),
    onSuccess: () => {
      message.success('状态定义已添加');
      setAddOpen(false);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: BusinessStateUpdate }) =>
      businessApi.updateState(id, values),
    onSuccess: () => {
      message.success('状态定义已更新');
      setEditItem(null);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => businessApi.removeState(id),
    onSuccess: () => {
      message.success('状态定义已删除');
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const columns = [
    {
      title: '实体',
      dataIndex: 'entity',
      width: 140,
      render: (v: string) => <Tag color="purple">{v}</Tag>,
    },
    {
      title: '前置状态',
      dataIndex: 'pre_state',
      width: 120,
      render: (v: string | null) => v ?? <span style={{ color: '#999' }}>—</span>,
    },
    { title: '→', key: 'arrow', width: 40, align: 'center' as const },
    {
      title: '后置状态',
      dataIndex: 'post_state',
      width: 120,
      render: (v: string | null) => v ?? <span style={{ color: '#999' }}>—</span>,
    },
    {
      title: '操作',
      key: 'op',
      width: 120,
      render: (_: unknown, r: { id: number; entity: string; pre_state: string | null; post_state: string | null }) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setEditItem({ id: r.id, values: { entity: r.entity, pre_state: r.pre_state ?? undefined, post_state: r.post_state ?? undefined } });
              form.setFieldsValue(r);
            }}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除？"
            onConfirm={(e) => { e?.stopPropagation(); deleteMutation.mutate(r.id); }}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Button
          size="small"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields();
            setAddOpen(true);
          }}
        >
          新增状态定义
        </Button>
        <span style={{ color: '#999', fontSize: 12 }}>
          描述步骤执行后的业务状态流转，如 task: CREATED → RUNNING
        </span>
      </Space>
      {action.states.length === 0 ? (
        <Empty description="暂无状态定义" />
      ) : (
        <Table rowKey="id" columns={columns} dataSource={action.states} pagination={false} size="small" />
      )}

      <StateFormModal
        open={addOpen || editItem != null}
        title={editItem ? '编辑状态定义' : '新增状态定义'}
        onClose={() => { setAddOpen(false); setEditItem(null); }}
        onSubmit={async () => {
          const values = await form.validateFields();
          if (editItem) {
            await updateMutation.mutateAsync({
              id: editItem.id,
              values: {
                entity: values.entity,
                pre_state: values.pre_state ?? null,
                post_state: values.post_state ?? null,
              },
            });
          } else {
            await createMutation.mutateAsync(values);
          }
        }}
        form={form}
        submitting={createMutation.isPending || updateMutation.isPending}
      />
    </div>
  );
}

function StateFormModal({
  open,
  title,
  onClose,
  onSubmit,
  form,
  submitting,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  onSubmit: () => Promise<void>;
  form: ReturnType<typeof Form.useForm<BusinessStateCreate>>[0];
  submitting: boolean;
}) {
  return (
    <Modal title={title} open={open} onCancel={onClose} onOk={onSubmit} confirmLoading={submitting} okText="保存" cancelText="取消" destroyOnClose width={480}>
      <Form<BusinessStateCreate> form={form} layout="vertical">
        <Form.Item name="entity" label="业务实体" rules={[{ required: true, message: '请输入业务实体名' }]}>
          <Input maxLength={100} placeholder="如 task、project、user" />
        </Form.Item>
        <Form.Item name="pre_state" label="前置状态">
          <Input maxLength={100} placeholder="如 CREATED（留空表示无前置状态要求）" />
        </Form.Item>
        <Form.Item name="post_state" label="后置状态">
          <Input maxLength={100} placeholder="如 RUNNING" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
