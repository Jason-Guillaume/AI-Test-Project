// 变量编辑器：管理单个步骤的输入变量与输出变量。
// 输入变量 = 步骤执行前需要的参数；输出变量 = 步骤执行后产出的结果（可被其他步骤通过变量引用消费）。
import { useState } from 'react';
import { App, Button, Empty, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tabs, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { businessApi } from '@/api/business';
import { getErrorMessage } from '@/api/client';
import { VARIABLE_DATA_TYPE_OPTIONS } from './constants';
import type { BusinessActionDetail, BusinessVariable, BusinessVariableCreate, BusinessVariableUpdate } from '@/types';

export function VariableEditor({
  action,
  onChanged,
}: {
  action: BusinessActionDetail;
  onChanged: () => void;
}) {
  return (
    <Tabs
      items={[
        {
          key: 'INPUT',
          label: `输入变量（${action.input_variables.length}）`,
          children: <VariableList action={action} direction="INPUT" onChanged={onChanged} />,
        },
        {
          key: 'OUTPUT',
          label: `输出变量（${action.output_variables.length}）`,
          children: <VariableList action={action} direction="OUTPUT" onChanged={onChanged} />,
        },
      ]}
      size="small"
    />
  );
}

function VariableList({
  action,
  direction,
  onChanged,
}: {
  action: BusinessActionDetail;
  direction: 'INPUT' | 'OUTPUT';
  onChanged: () => void;
}) {
  const { message } = App.useApp();
  const [addOpen, setAddOpen] = useState(false);
  const [editItem, setEditItem] = useState<{ id: number; values: BusinessVariableUpdate } | null>(null);
  const [form] = Form.useForm<BusinessVariableCreate>();

  const items = [...(direction === 'INPUT' ? action.input_variables : action.output_variables)]
    .sort((a, b) => a.sort - b.sort);

  const createMutation = useMutation({
    mutationFn: (body: BusinessVariableCreate) => businessApi.createVariable(action.id, body),
    onSuccess: () => {
      message.success('变量已添加');
      setAddOpen(false);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: number; values: BusinessVariableUpdate }) =>
      businessApi.updateVariable(id, values),
    onSuccess: () => {
      message.success('变量已更新');
      setEditItem(null);
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => businessApi.removeVariable(id),
    onSuccess: () => {
      message.success('变量已删除');
      onChanged();
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const columns = [
    { title: '#', dataIndex: 'sort', width: 40 },
    {
      title: '变量名',
      dataIndex: 'name',
      width: 160,
      render: (v: string) => <span style={{ fontWeight: 500 }}>{v}</span>,
    },
    {
      title: '数据类型',
      dataIndex: 'data_type',
      width: 100,
      render: (v: string) => <Tag style={{ fontSize: 11 }}>{v}</Tag>,
    },
    {
      title: '必填',
      dataIndex: 'required',
      width: 60,
      render: (v: boolean) => (v ? <Tag color="red">是</Tag> : <Tag>否</Tag>),
    },
    { title: '描述', dataIndex: 'description', render: (v: string | null) => v ?? '—' },
    {
      title: '操作',
      key: 'op',
      width: 120,
      render: (_: unknown, r: BusinessVariable) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setEditItem({
                id: r.id,
                values: {
                  direction: r.direction,
                  name: r.name,
                  data_type: r.data_type,
                  required: r.required,
                  description: r.description ?? undefined,
                  sort: r.sort,
                },
              });
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
            form.setFieldsValue({ direction, data_type: 'STRING', required: false });
            setAddOpen(true);
          }}
        >
          新增{direction === 'INPUT' ? '输入' : '输出'}变量
        </Button>
      </Space>
      {items.length === 0 ? (
        <Empty description={`暂无${direction === 'INPUT' ? '输入' : '输出'}变量`} />
      ) : (
        <Table rowKey="id" columns={columns} dataSource={items} pagination={false} size="small" />
      )}

      <VariableFormModal
        open={addOpen || editItem != null}
        title={editItem ? '编辑变量' : `新增${direction === 'INPUT' ? '输入' : '输出'}变量`}
        onClose={() => { setAddOpen(false); setEditItem(null); }}
        onSubmit={async () => {
          const values = await form.validateFields();
          if (editItem) {
            await updateMutation.mutateAsync({
              id: editItem.id,
              values: {
                name: values.name,
                data_type: values.data_type,
                required: values.required,
                description: values.description ?? null,
                sort: values.sort,
              },
            });
          } else {
            await createMutation.mutateAsync({
              ...values,
              direction,
              data_type: values.data_type ?? 'STRING',
              required: values.required ?? false,
            });
          }
        }}
        form={form}
        submitting={createMutation.isPending || updateMutation.isPending}
      />
    </div>
  );
}

function VariableFormModal({
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
  form: ReturnType<typeof Form.useForm<BusinessVariableCreate>>[0];
  submitting: boolean;
}) {
  return (
    <Modal title={title} open={open} onCancel={onClose} onOk={onSubmit} confirmLoading={submitting} okText="保存" cancelText="取消" destroyOnClose width={520}>
      <Form<BusinessVariableCreate> form={form} layout="vertical">
        <Form.Item name="name" label="变量名" rules={[{ required: true, message: '请输入变量名' }]}>
          <Input maxLength={100} placeholder="如 project_id" />
        </Form.Item>
        <Space size="middle" style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="data_type" label="数据类型" style={{ flex: 1, margin: 0 }}>
            <Select options={VARIABLE_DATA_TYPE_OPTIONS} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="required" label="必填" valuePropName="checked" style={{ flex: 0, margin: 0 }}>
            <Switch />
          </Form.Item>
        </Space>
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
