// 前置条件编辑器：管理单个步骤的前置条件列表（可编辑、可删除）。
// 前置条件分四类（变量/状态/业务/文本），用于定义步骤执行前必须满足的条件。
import { useState } from 'react';
import { App, Button, Empty, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { businessApi } from '@/features/business/api/business';
import { getErrorMessage } from '@/shared/api/client';
import { PRECONDITION_OPERATOR_OPTIONS, PRECONDITION_TYPE_OPTIONS } from './constants';
import type { BusinessActionDetail, BusinessPrecondition, BusinessPreconditionCreate, BusinessPreconditionUpdate } from '@/features/business/contracts';


const PRECONDITION_TYPE_LABELS: Record<string, { color: string; text: string }> = {
  VARIABLE: { color: 'blue', text: '变量' },
  STATE: { color: 'green', text: '状态' },
  BUSINESS: { color: 'orange', text: '业务' },
  TEXT: { color: 'default', text: '文本' },
};

export function PreconditionEditor({
  action,
  onChanged,
}: {
  action: BusinessActionDetail;
  onChanged: () => void;
}) {
  const { message } = App.useApp();
  const [addOpen, setAddOpen] = useState(false);
  const [editItem, setEditItem] = useState<{ id: number; values: BusinessPreconditionUpdate } | null>(null);
  const [form] = Form.useForm<BusinessPreconditionCreate>();

  const createMutation = useMutation({
    mutationFn: (body: BusinessPreconditionCreate) => businessApi.createPrecondition(action.id, body),
    onSuccess: () => {
      message.success('前置条件已添加');
      setAddOpen(false);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: BusinessPreconditionUpdate }) =>
      businessApi.updatePrecondition(id, values),
    onSuccess: () => {
      message.success('前置条件已更新');
      setEditItem(null);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => businessApi.removePrecondition(id),
    onSuccess: () => {
      message.success('前置条件已删除');
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const items = [...action.preconditions].sort((a, b) => a.sort - b.sort);

  const columns = [
    { title: '#', dataIndex: 'sort', width: 40, render: (v: number) => v },
    {
      title: '类型',
      dataIndex: 'type',
      width: 80,
      render: (v: string) => {
        const info = PRECONDITION_TYPE_LABELS[v] ?? { color: 'default', text: v };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    { title: '目标', dataIndex: 'target', width: 160 },
    { title: '运算符', dataIndex: 'operator', width: 120 },
    { title: '期望值', dataIndex: 'expected_value', render: (v: string | null) => v ?? '—' },
    {
      title: '操作',
      key: 'op',
      width: 120,
      render: (_: unknown, r: BusinessPrecondition) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setEditItem({ id: r.id, values: { type: r.type, target: r.target, operator: r.operator, expected_value: r.expected_value ?? undefined, description: r.description ?? undefined, sort: r.sort } });
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
        <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => {
          form.resetFields();
          setAddOpen(true);
        }}>
          新增前置条件
        </Button>
      </Space>
      {items.length === 0 ? (
        <Empty description="暂无前置条件" />
      ) : (
        <Table rowKey="id" columns={columns} dataSource={items} pagination={false} size="small" />
      )}

      <PreconditionFormModal
        open={addOpen || editItem != null}
        title={editItem ? '编辑前置条件' : '新增前置条件'}
        onClose={() => { setAddOpen(false); setEditItem(null); }}
        onSubmit={async () => {
          const values = await form.validateFields();
          if (editItem) {
            await updateMutation.mutateAsync({
              id: editItem.id,
              values: {
                type: values.type,
                target: values.target,
                operator: values.operator,
                expected_value: values.expected_value ?? null,
                description: values.description ?? null,
                sort: values.sort,
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

function PreconditionFormModal({
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
  form: ReturnType<typeof Form.useForm<BusinessPreconditionCreate>>[0];
  submitting: boolean;
}) {
  return (
    <Modal title={title} open={open} onCancel={onClose} onOk={onSubmit} confirmLoading={submitting} okText="保存" cancelText="取消" destroyOnClose width={540}>
      <Form<BusinessPreconditionCreate> form={form} layout="vertical" initialValues={{ type: 'VARIABLE', operator: 'EQ' }}>
        <div className="form-field-row">
          <Form.Item name="type" label="类型" style={{ flex: 1, margin: 0 }}>
            <Select options={PRECONDITION_TYPE_OPTIONS} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="operator" label="运算符" style={{ flex: 1, margin: 0 }}>
            <Select options={PRECONDITION_OPERATOR_OPTIONS} style={{ width: '100%' }} />
          </Form.Item>
        </div>
        <Form.Item name="target" label="目标（变量名/状态/业务条件）" rules={[{ required: true, message: '请输入目标' }]}>
          <Input maxLength={200} placeholder="如 project_id、task.status" />
        </Form.Item>
        <Form.Item name="expected_value" label="期望值">
          <Input maxLength={500} />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={2} maxLength={1000} />
        </Form.Item>
        <Form.Item name="sort" label="排序值">
          <Input type="number" placeholder="数字越小越靠前" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
