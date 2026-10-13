// 变量引用面板：配置「动作 A 的输出变量 → 动作 B 的输入变量」的引用关系。
// 用于步骤之间的数据传递（如 创建项目.output.project_id → 创建任务.input.project_id）。
import { useState } from 'react';
import { App, Button, Empty, Form, Modal, Popconfirm, Select, Space, Table } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { businessApi } from '@/api/business';
import { getErrorMessage } from '@/api/client';
import type { BusinessActionDetail, BusinessVariableRefCreate } from '@/types';

export function VariableRefPanel({
  flowId,
  actions,
  refreshKey,
}: {
  flowId: number;
  actions: BusinessActionDetail[];
  refreshKey: number;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [form] = Form.useForm<BusinessVariableRefCreate>();

  const { data: refs, isPending } = useQuery({
    queryKey: ['business', flowId, 'variable-refs', refreshKey],
    queryFn: () => businessApi.listVariableRefs(flowId),
    enabled: flowId > 0,
  });

  const createMutation = useMutation({
    mutationFn: (body: BusinessVariableRefCreate) => businessApi.createVariableRef(flowId, body),
    onSuccess: () => {
      message.success('变量引用已添加');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setAddOpen(false);
      form.resetFields();
    },
    onError: (e) => message.error(getErrorMessage(e, '添加失败')),
  });

  const deleteMutation = useMutation({
    mutationFn: (refId: number) => businessApi.removeVariableRef(refId),
    onSuccess: () => {
      message.success('变量引用已删除');
      queryClient.invalidateQueries({ queryKey: ['business'] });
    },
    onError: (e) => message.error(getErrorMessage(e, '删除失败')),
  });

  const actionName = (actionId: number) => actions.find((a) => a.id === actionId)?.name ?? `#${actionId}`;

  const columns = [
    {
      title: '来源步骤（输出）',
      key: 'source',
      render: (_: unknown, r: { source_action_id: number; source_variable: string }) => (
        <Space>
          <span style={{ fontWeight: 500 }}>{actionName(r.source_action_id)}</span>
          <span style={{ color: '#999' }}>· {r.source_variable}</span>
        </Space>
      ),
    },
    { title: '→', key: 'arrow', width: 40, align: 'center' as const },
    {
      title: '目标步骤（输入）',
      key: 'target',
      render: (_: unknown, r: { target_action_id: number; target_variable: string }) => (
        <Space>
          <span style={{ fontWeight: 500 }}>{actionName(r.target_action_id)}</span>
          <span style={{ color: '#999' }}>· {r.target_variable}</span>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'op',
      width: 80,
      render: (_: unknown, r: { id: number }) => (
        <Popconfirm
          title="确认删除该引用？"
          onConfirm={() => deleteMutation.mutate(r.id)}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
        >
          <Button type="link" size="small" danger>
            删除
          </Button>
        </Popconfirm>
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
          新增引用
        </Button>
        <span style={{ color: '#999', fontSize: 12 }}>
          配置步骤之间的数据传递（如 创建项目.output.project_id → 创建任务.input.project_id）
        </span>
      </Space>
      {isPending ? (
        <Empty description="加载中" />
      ) : refs && refs.length > 0 ? (
        <Table rowKey="id" columns={columns} dataSource={refs} pagination={false} size="small" />
      ) : (
        <Empty description="暂无变量引用" />
      )}

      <AddRefModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onSubmit={async () => {
          const values = await form.validateFields();
          await createMutation.mutateAsync(values);
        }}
        form={form}
        actions={actions}
        submitting={createMutation.isPending}
      />
    </div>
  );
}

function AddRefModal({
  open,
  onClose,
  onSubmit,
  form,
  actions,
  submitting,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: () => Promise<void>;
  form: ReturnType<typeof Form.useForm<BusinessVariableRefCreate>>[0];
  actions: BusinessActionDetail[];
  submitting: boolean;
}) {
  // useWatch 订阅 form 值变化，确保变量下拉菜单在选择步骤后实时填充。
  const sourceActionId = Form.useWatch('source_action_id', form);
  const targetActionId = Form.useWatch('target_action_id', form);

  const sourceAction = actions.find((a) => a.id === sourceActionId);
  const targetAction = actions.find((a) => a.id === targetActionId);

  return (
    <Modal
      title="新增变量引用"
      open={open}
      onCancel={onClose}
      onOk={onSubmit}
      confirmLoading={submitting}
      okText="添加"
      cancelText="取消"
      destroyOnClose
      width={560}
    >
      <Form<BusinessVariableRefCreate> form={form} layout="vertical">
        <Form.Item
          name="source_action_id"
          label="来源步骤（输出方）"
          rules={[{ required: true, message: '请选择来源步骤' }]}
        >
          <Select
            options={actions.map((a) => ({ value: a.id, label: a.name }))}
            placeholder="选择输出方步骤"
            onChange={() => form.setFieldValue('source_variable', undefined)}
          />
        </Form.Item>
        <Form.Item
          name="source_variable"
          label="来源变量（输出）"
          rules={[{ required: true, message: '请选择输出变量' }]}
        >
          <Select
            placeholder="选择该步骤的输出变量"
            options={(sourceAction?.output_variables ?? []).map((v) => ({ value: v.name, label: v.name }))}
          />
        </Form.Item>
        <Form.Item
          name="target_action_id"
          label="目标步骤（输入方）"
          rules={[{ required: true, message: '请选择目标步骤' }]}
        >
          <Select
            options={actions.map((a) => ({ value: a.id, label: a.name }))}
            placeholder="选择输入方步骤"
            onChange={() => form.setFieldValue('target_variable', undefined)}
          />
        </Form.Item>
        <Form.Item
          name="target_variable"
          label="目标变量（输入）"
          rules={[{ required: true, message: '请选择输入变量' }]}
        >
          <Select
            placeholder="选择该步骤的输入变量"
            options={(targetAction?.input_variables ?? []).map((v) => ({ value: v.name, label: v.name }))}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
